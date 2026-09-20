import sys
from datetime import datetime, timedelta

from database import connect_db, db_label, init_db
from topic_rankings import get_topic_rankings


def safe_text(value):
    text = str(value or "")
    encoding = sys.stdout.encoding or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def fetch_all(cursor, sql, values=()):
    return cursor.execute(sql, values).fetchall()


def main():
    init_db()
    since = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

    with connect_db() as conn:
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

    recent_focus_topics = get_topic_rankings(scope="all", limit=5)
    today_topics = get_topic_rankings(scope="today", limit=5)

    print(f"資料庫：{db_label()}")
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

    print("\n近期焦點 Top 5：")
    if recent_focus_topics:
        for index, row in enumerate(recent_focus_topics, start=1):
            print(
                f"{index}. [{row['topic_score']}] {safe_text(row['term'])} "
                f"(來源 {row['source_count']} / 文章 {row['article_count']})"
            )
    else:
        print("- 尚無資料")

    print("\n本日話題 Top 5：")
    if today_topics:
        for index, row in enumerate(today_topics, start=1):
            print(
                f"{index}. [{row['topic_score']}] {safe_text(row['term'])} "
                f"(來源 {row['source_count']} / 文章 {row['article_count']})"
            )
    else:
        print("- 尚無資料")


if __name__ == "__main__":
    main()
