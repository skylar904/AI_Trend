import sqlite3
import sys

from database import DB_NAME, init_db


def safe_text(value):
    text = str(value or "")
    encoding = sys.stdout.encoding or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def fetch_all(cursor, sql, values=()):
    return cursor.execute(sql, values).fetchall()


def main():
    init_db()

    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        total = cursor.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        latest = cursor.execute("SELECT MAX(created_at) FROM articles").fetchone()[0]

        categories = fetch_all(
            cursor,
            """
            SELECT COALESCE(ai_category, category, '未分類') AS category, COUNT(*) AS count
            FROM articles
            GROUP BY COALESCE(ai_category, category, '未分類')
            ORDER BY count DESC, category
            """,
        )

        sources = fetch_all(
            cursor,
            """
            SELECT source, COUNT(*) AS count
            FROM articles
            GROUP BY source
            ORDER BY count DESC, source
            """,
        )

        source_groups = fetch_all(
            cursor,
            """
            SELECT COALESCE(source_group_label, '未分類來源') AS source_group_label,
                   COUNT(*) AS count
            FROM articles
            GROUP BY COALESCE(source_group_label, '未分類來源')
            ORDER BY count DESC, source_group_label
            """,
        )

        top_trends = fetch_all(
            cursor,
            """
            SELECT title, source, COALESCE(ai_category, category, '') AS category,
                   relevance_score, importance_score, trend_score, trend_reason, created_at
            FROM articles
            ORDER BY trend_score DESC, created_at DESC
            LIMIT 10
            """,
        )

        top_entities = fetch_all(
            cursor,
            """
            SELECT canonical_name, entity_type, mention_count, trend_score, last_seen_at
            FROM entities
            ORDER BY trend_score DESC, mention_count DESC, canonical_name
            LIMIT 10
            """,
        )

        weekly_topics = fetch_all(
            cursor,
            """
            SELECT COALESCE(ai_category, category, '未分類') AS name,
                   COUNT(id) AS article_count,
                   COUNT(DISTINCT source) AS source_count,
                   ROUND(
                       COALESCE(SUM(trend_score), 0)
                       + COUNT(id) * 8
                       + COUNT(DISTINCT source) * 12,
                       2
                   ) AS discussion_score,
                   GROUP_CONCAT(DISTINCT source) AS sources
            FROM articles
            WHERE date(created_at) >= date('now', '-7 days')
            GROUP BY COALESCE(ai_category, category, '未分類')
            ORDER BY discussion_score DESC, article_count DESC, name
            LIMIT 5
            """,
        )

    print(f"資料庫：{DB_NAME}")
    print(f"文章總數：{total}")
    print(f"最新收錄：{latest or '尚無資料'}")

    print("\n分類分布：")
    if categories:
        for row in categories:
            print(f"- {row['category']}: {row['count']}")
    else:
        print("- 尚無資料")

    print("\n來源分布：")
    if sources:
        for row in sources:
            print(f"- {row['source']}: {row['count']}")
    else:
        print("- 尚無資料")

    print("\n來源類型分布：")
    if source_groups:
        for row in source_groups:
            print(f"- {row['source_group_label']}: {row['count']}")
    else:
        print("- 尚無資料")

    print("\n趨勢分數 Top 10：")
    if top_trends:
        for index, row in enumerate(top_trends, start=1):
            print(
                f"{index}. [{row['trend_score']}] {safe_text(row['title'])} "
                f"({safe_text(row['source'])} / {safe_text(row['category'])} / "
                f"相關 {row['relevance_score']} / 重要 {row['importance_score']})"
            )
            if row["trend_reason"]:
                print(f"   - {safe_text(row['trend_reason'])}")
    else:
        print("- 尚無資料")

    print("\n熱門實體 Top 10：")
    if top_entities:
        for index, row in enumerate(top_entities, start=1):
            print(
                f"{index}. [{row['trend_score']}] {safe_text(row['canonical_name'])} "
                f"({safe_text(row['entity_type'])} / 提及 {row['mention_count']} / "
                f"最新 {row['last_seen_at']})"
            )
    else:
        print("- 尚無資料")

    print("\n本週討論度 Top 5：")
    if weekly_topics:
        for index, row in enumerate(weekly_topics, start=1):
            print(
                f"{index}. [{row['discussion_score']}] {safe_text(row['name'])} "
                f"(文章 {row['article_count']} / 來源 {row['source_count']} / "
                f"{safe_text(row['sources'])})"
            )
    else:
        print("- 尚無資料")


if __name__ == "__main__":
    main()
