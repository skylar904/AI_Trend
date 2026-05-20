import argparse
import feedparser
from datetime import datetime

from cleaning import clean_article, dedupe_articles, is_probably_ai_related
from feeds import RSS_FEEDS
from report import generate_markdown_report, save_report
from database import init_db, is_article_exists_by_identity, save_article
from summarizer import analyze_article
from trend_config import DEFAULT_SOURCE_WEIGHT, MAX_DAILY_ARTICLES, MIN_RELEVANCE_SCORE


def fetch_feed(feed):
    parsed = feedparser.parse(feed["url"])

    articles = []

    for entry in parsed.entries[:feed.get("max_entries", 10)]:
        article = {
            "source": feed["name"],
            "category": feed["category"],
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "published": entry.get("published", ""),
            "summary": entry.get("summary", entry.get("description", "")),
            "source_weight": feed.get("weight", DEFAULT_SOURCE_WEIGHT),
        }
        articles.append(clean_article(article))

    return articles


def calculate_trend_score(article, analysis):
    source_weight = float(article.get("source_weight", DEFAULT_SOURCE_WEIGHT))
    relevance_score = int(analysis.get("relevance_score", 0))
    importance_score = int(analysis.get("importance_score", 0))

    return round(
        relevance_score * 0.38
        + importance_score * 0.42
        + source_weight * 10
        + (8 if article.get("link") else 0),
        2,
    )


def collect_candidates():
    candidates = []

    for feed in RSS_FEEDS:
        print(f"正在巡邏來源：{feed['name']}")
        try:
            candidates.extend(fetch_feed(feed))
        except Exception as error:
            print(f"來源讀取失敗，略過 {feed['name']}：{error}")

    return dedupe_articles(candidates)


def parse_args():
    parser = argparse.ArgumentParser(description="Run the local AI trend patrol pipeline.")
    parser.add_argument(
        "--limit",
        type=int,
        default=MAX_DAILY_ARTICLES,
        help="Maximum number of new articles to analyze and save.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze candidates without writing to articles.db or reports/.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    init_db()

    candidates = collect_candidates()
    print(f"\n候選文章數量：{len(candidates)}")
    print(f"本次收錄上限：{args.limit}")
    if args.dry_run:
        print("Dry run 模式：只分析，不寫入資料庫與報告。")

    all_new_articles = []

    for article in candidates:
        if len(all_new_articles) >= args.limit:
            break

        link = article["link"]
        fingerprint = article.get("fingerprint", "")

        if not link:
            continue

        if is_article_exists_by_identity(link, fingerprint):
            print(f"已存在，跳過：{article['title']}")
            continue

        if not is_probably_ai_related(article):
            print(f"低相關候選，略過：{article['title']}")
            continue

        print(f"\n分析新文章：{article['title']}")
        analysis = analyze_article(article)

        if (
            not analysis.get("should_include")
            or analysis.get("relevance_score", 0) < MIN_RELEVANCE_SCORE
        ):
            print(f"AI 判斷略過：{analysis.get('reason', article['title'])}")
            continue

        article["category"] = analysis["category"]
        article["ai_category"] = analysis["category"]
        article["relevance_score"] = analysis["relevance_score"]
        article["importance_score"] = analysis["importance_score"]
        article["trend_score"] = calculate_trend_score(article, analysis)
        article["reason"] = analysis["reason"]
        article["ai_summary"] = analysis["summary"]
        article["collected_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not args.dry_run:
            save_article(article)
        all_new_articles.append(article)
        print(
            "已收錄："
            f"{article['title']} "
            f"(相關 {article['relevance_score']} / 重要 {article['importance_score']} / 趨勢 {article['trend_score']})"
        )

    if not all_new_articles:
        print("\n今天沒有新的文章。")
        return

    markdown_text = generate_markdown_report(all_new_articles)

    print(f"\n新文章數量：{len(all_new_articles)}")
    if args.dry_run:
        print("Dry run 完成，未產生報告檔。")
    else:
        file_path = save_report(markdown_text)
        print(f"報告已產生：{file_path}")


if __name__ == "__main__":
    main()
