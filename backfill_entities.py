import argparse
import json

from database import (
    connect_db,
    init_db,
    link_article_entity,
    update_article_trend_metadata,
    upsert_entity,
)
from main import (
    build_trend_reason,
    calculate_trend_components,
    calculate_trend_score,
)
from summarizer import analyze_article


def parse_args():
    parser = argparse.ArgumentParser(
        description="Backfill entities and explainable trend scores for existing articles."
    )
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_articles(limit):
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.title, a.link, a.source, a.category, a.published,
                   a.summary, a.ai_summary, a.relevance_score, a.importance_score,
                   a.trend_score
            FROM articles a
            LEFT JOIN article_entities ae ON ae.article_id = a.id
            WHERE ae.article_id IS NULL
            ORDER BY a.trend_score DESC, a.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def main():
    args = parse_args()
    init_db()

    articles = load_articles(args.limit)
    print(f"待補實體文章數：{len(articles)}")
    if args.dry_run:
        print("Dry run 模式：只分析，不寫入資料庫。")

    for article in articles:
        print(f"\n補抽實體：{article['title']}")
        analysis = analyze_article(article)
        if not analysis.get("should_include"):
            print(f"略過：{analysis.get('reason', 'AI 判斷不收錄')}")
            continue

        trend_components = calculate_trend_components(article, analysis)
        article["category"] = analysis["category"]
        article["ai_category"] = analysis["category"]
        article["relevance_score"] = analysis["relevance_score"]
        article["importance_score"] = analysis["importance_score"]
        article["trend_score"] = calculate_trend_score(trend_components)
        article["reason"] = analysis["reason"]
        article["trend_components"] = json.dumps(trend_components, ensure_ascii=False)
        article["trend_reason"] = build_trend_reason(article, analysis, trend_components)

        entity_names = [entity["canonical_name"] for entity in analysis.get("entities", [])]
        print(f"實體：{'、'.join(entity_names) if entity_names else '無'}")

        if args.dry_run:
            continue

        update_article_trend_metadata(article["id"], article)
        for entity in analysis.get("entities", []):
            entity_id = upsert_entity(entity, article["trend_score"])
            link_article_entity(
                article["id"],
                entity_id,
                entity.get("confidence", 0),
                entity.get("evidence", ""),
            )


if __name__ == "__main__":
    main()
