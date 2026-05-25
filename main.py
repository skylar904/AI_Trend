import argparse
import json
import feedparser
from datetime import datetime

from api_collectors import collect_api_candidates, rss_replacements_for
from cleaning import clean_article, dedupe_articles, is_probably_ai_related
from rss_sources import RSS_FEEDS
from report import generate_markdown_report, save_report
from database import (
    init_db,
    is_article_exists_by_identity,
    link_article_entity,
    save_article,
    save_platform_items,
    upsert_entity,
)
from platform_collectors import collect_platform_top
from summarizer import analyze_article
from trend_config import (
    DEFAULT_SOURCE_WEIGHT,
    MAX_DAILY_ARTICLES,
    MIN_RELEVANCE_SCORE,
    TREND_SCORE_WEIGHTS,
)


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
    entities = analysis.get("entities", [])
    entity_count = min(len(entities), 4)

    components = {
        "relevance": round(relevance_score * TREND_SCORE_WEIGHTS["relevance"], 2),
        "importance": round(importance_score * TREND_SCORE_WEIGHTS["importance"], 2),
        "source": round(source_weight * TREND_SCORE_WEIGHTS["source"], 2),
        "entity": round(entity_count * TREND_SCORE_WEIGHTS["entity"], 2),
        "recency": TREND_SCORE_WEIGHTS["recency"],
    }
    return components


def calculate_trend_score(components):
    return round(sum(float(value) for value in components.values()), 2)


def build_trend_reason(article, analysis, components):
    entities = analysis.get("entities", [])
    entity_names = [entity["canonical_name"] for entity in entities[:3]]
    reasons = [
        f"AI 相關性 {analysis.get('relevance_score', 0)} 分",
        f"重要性 {analysis.get('importance_score', 0)} 分",
        f"來源權重貢獻 {components['source']} 分",
    ]
    if entity_names:
        reasons.append(f"提到 {'、'.join(entity_names)} 等實體")
    else:
        reasons.append("未抽出明確工具/模型實體")
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
    parser.add_argument(
        "--skip-platform",
        action="store_true",
        help="Skip GitHub and Hugging Face platform top 10 collection.",
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
        save_platform_items(platform, items)


def main():
    args = parse_args()
    init_db()

    if not args.skip_platform:
        update_platform_rankings(args.dry_run)

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
                for entity in analysis.get("entities", []):
                    entity_id = upsert_entity(entity, article["trend_score"])
                    link_article_entity(
                        article_id,
                        entity_id,
                        entity.get("confidence", 0),
                        entity.get("evidence", ""),
                    )

        all_new_articles.append(article)
        entity_names = [
            entity["canonical_name"] for entity in analysis.get("entities", [])
        ]
        print(
            "已收錄："
            f"{article['title']} "
            f"(相關 {article['relevance_score']} / 重要 {article['importance_score']} / 趨勢 {article['trend_score']})"
        )
        if entity_names:
            print(f"關聯實體：{'、'.join(entity_names)}")

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
