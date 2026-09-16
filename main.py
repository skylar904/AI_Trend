import argparse
import json
import feedparser
from datetime import datetime

from api_collectors import collect_api_candidates, rss_replacements_for
from cleaning import clean_article, dedupe_articles, is_probably_ai_related
from rss_sources import RSS_FEEDS
from database import (
    init_db,
    is_article_exists_by_identity,
    save_pending_article,
    save_article,
    save_platform_items,
)
from Github_Huggingface_analyzer import analyze_platform_item
from Github_Huggingface_collector import collect_platform_top
from summarizer import OpenAIAnalysisRetryableError, analyze_article
from trend_config import (
    DEFAULT_SOURCE_WEIGHT,
    MAX_DAILY_ARTICLES,
    MIN_RELEVANCE_SCORE,
    TREND_SCORE_WEIGHTS,
)
from topic_rankings import update_topic_rankings


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
            "source_group": feed.get("source_group", ""),
            "source_group_label": feed.get("source_group_label", ""),
        }
        articles.append(clean_article(article))

    return articles


def calculate_trend_components(article, analysis):
    source_weight = float(article.get("source_weight", DEFAULT_SOURCE_WEIGHT))
    relevance_score = int(analysis.get("relevance_score", 0))
    importance_score = int(analysis.get("importance_score", 0))

    components = {
        "relevance": round(relevance_score * TREND_SCORE_WEIGHTS["relevance"], 2),
        "importance": round(importance_score * TREND_SCORE_WEIGHTS["importance"], 2),
        "source": round(source_weight * TREND_SCORE_WEIGHTS["source"], 2),
        "recency": TREND_SCORE_WEIGHTS["recency"],
    }
    return components


def calculate_trend_score(components):
    return round(sum(float(value) for value in components.values()), 2)


def build_trend_reason(article, analysis, components):
    reasons = [
        f"AI 相關性 {analysis.get('relevance_score', 0)} 分",
        f"重要性 {analysis.get('importance_score', 0)} 分",
        f"來源權重貢獻 {components['source']} 分",
        f"近期性貢獻 {components['recency']} 分",
    ]
    return "；".join(reasons) + "。"


def collect_candidates():
    candidates = []
    api_candidates, successful_api_sources = collect_api_candidates()
    candidates.extend(api_candidates)
    rss_replacements = rss_replacements_for(successful_api_sources)

    for feed in RSS_FEEDS:
        if feed["name"] in rss_replacements:
            print(f"API 已處理，略過 RSS fallback：{feed['name']}")
            continue

        print(f"正在巡邏來源：{feed['name']}")
        try:
            rss_articles = fetch_feed(feed)
            candidates.extend(rss_articles)
        except Exception as error:
            print(f"來源讀取失敗，略過 {feed['name']}：{error}")

    deduped = dedupe_articles(candidates)
    deduped.sort(
        key=lambda article: float(article.get("source_weight", DEFAULT_SOURCE_WEIGHT)),
        reverse=True,
    )
    return deduped


def parse_args():
    parser = argparse.ArgumentParser(description="Run the local AI trend patrol pipeline.")
    parser.add_argument(
        "--limit",
        type=int,
        default=MAX_DAILY_ARTICLES,
        help="Optional global cap for new articles to analyze and save. 0 means no global cap.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze candidates without writing to the database.",
    )
    parser.add_argument(
        "--skip-platform",
        action="store_true",
        help="Skip GitHub and Hugging Face platform top 10 collection.",
    )
    parser.add_argument(
        "--platform-only",
        action="store_true",
        help="Only update GitHub and Hugging Face platform rankings, then exit.",
    )
    return parser.parse_args()


def update_platform_rankings(dry_run=False):
    print("\n更新平台熱門排行榜：GitHub / Hugging Face")
    try:
        rankings = collect_platform_top(limit=10)
    except Exception as error:
        print(f"平台排行榜讀取失敗，略過：{error}")
        return

    for platform, items in rankings.items():
        print(f"{platform} Top {len(items)}")
        if dry_run:
            continue
        analyzed_items = []
        for item in items:
            print(f"分析排行項目：{item['name']}")
            item.update(analyze_platform_item(item))
            analyzed_items.append(item)
        save_platform_items(platform, analyzed_items)


def main():
    args = parse_args()
    init_db()

    if not args.skip_platform:
        update_platform_rankings(args.dry_run)
        if args.platform_only:
            return

    candidates = collect_candidates()
    print(f"\n候選文章數量：{len(candidates)}")
    if args.limit > 0:
        print(f"本次全站收錄上限：{args.limit}")
    else:
        print("本次不使用全站收錄上限，改由各來源 max_entries 控制。")
    if args.dry_run:
        print("Dry run 模式：只分析，不寫入資料庫。")

    all_new_articles = []
    pending_count = 0

    for article in candidates:
        if args.limit > 0 and len(all_new_articles) >= args.limit:
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
        try:
            analysis = analyze_article(article)
        except OpenAIAnalysisRetryableError as error:
            print(f"OpenAI 分析暫時失敗，加入待補：{article['title']} / {error}")
            pending_count += 1
            if not args.dry_run:
                save_pending_article(article, error)
            continue

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
        trend_components = calculate_trend_components(article, analysis)
        article["trend_score"] = calculate_trend_score(trend_components)
        article["reason"] = analysis["reason"]
        article["ai_summary"] = analysis["summary"]
        article["trend_components"] = json.dumps(trend_components, ensure_ascii=False)
        article["trend_reason"] = build_trend_reason(article, analysis, trend_components)
        article["collected_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        article_id = None
        if not args.dry_run:
            article_id = save_article(article)
            if article_id:
                article["id"] = article_id
            else:
                print(f"資料庫已存在或寫入失敗，略過話題統計：{article['title']}")
                continue

        all_new_articles.append(article)
        print(
            "已收錄："
            f"{article['title']} "
            f"(相關 {article['relevance_score']} / 重要 {article['importance_score']} / 趨勢 {article['trend_score']})"
        )

    if not all_new_articles:
        if pending_count:
            print(f"\n今天沒有成功上架新文章，但有 {pending_count} 篇已加入待補。")
            print("補好 OpenAI token/quota 後，執行：.venv/bin/python retry_pending_articles.py")
            return
        print("\n今天沒有新的文章。")
        return

    print(f"\n新文章數量：{len(all_new_articles)}")
    if pending_count:
        print(f"另有 {pending_count} 篇因 OpenAI 暫時失敗加入待補。")
    if args.dry_run:
        print("Dry run 完成，未寫入資料庫。")

    topic_date = datetime.now().strftime("%Y-%m-%d")
    try:
        topics = update_topic_rankings(all_new_articles, topic_date=topic_date, dry_run=args.dry_run)
    except Exception as error:
        print(f"本日話題更新失敗，但文章已保留在資料庫：{error}")
        print(
            "補好 OpenAI token/quota 後，執行："
            f".venv/bin/python rebuild_daily_topics.py --date {topic_date}"
        )
        raise
    print(f"本日話題 Top {len(topics)} 已更新，近期焦點已累積重建。")


if __name__ == "__main__":
    main()
