import argparse
import re
from datetime import datetime, timedelta

from database import connect_db, init_db, rebuild_topic_stats, table_exists


ARTICLE_MONTH_SQL = "substr(created_at, 1, 7)"


def previous_month(today=None):
    today = today or datetime.now()
    first_day_this_month = today.replace(day=1)
    last_day_previous_month = first_day_this_month - timedelta(days=1)
    return last_day_previous_month.strftime("%Y-%m")


def valid_month(value):
    month = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise argparse.ArgumentTypeError("month must use YYYY-MM, for example 2026-08")
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError as error:
        raise argparse.ArgumentTypeError("month must be a real calendar month") from error
    return month


def parse_args():
    parser = argparse.ArgumentParser(description="Delete one month of article history and rebuild topic stats.")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--month", type=valid_month, help="Month to delete, formatted as YYYY-MM.")
    target.add_argument("--previous-month", action="store_true", help="Delete the calendar month before today.")
    parser.add_argument("--dry-run", action="store_true", help="Preview counts without deleting data.")
    return parser.parse_args()


def monthly_cleanup_preview(month):
    conn = connect_db()
    cursor = conn.cursor()

    article_count = cursor.execute(
        f"SELECT COUNT(*) AS count FROM articles WHERE {ARTICLE_MONTH_SQL} = ?",
        (month,),
    ).fetchone()["count"]
    daily_topic_count = cursor.execute(
        "SELECT COUNT(*) AS count FROM daily_topics WHERE substr(topic_date, 1, 7) = ?",
        (month,),
    ).fetchone()["count"]
    processed_reference_count = 0
    if table_exists(conn, "processed_candidates"):
        processed_reference_count = cursor.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM processed_candidates
            WHERE article_id IN (
                SELECT id FROM articles WHERE {ARTICLE_MONTH_SQL} = ?
            )
            """,
            (month,),
        ).fetchone()["count"]
    pending_reference_count = 0
    if table_exists(conn, "pending_articles"):
        pending_reference_count = cursor.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM pending_articles
            WHERE completed_article_id IN (
                SELECT id FROM articles WHERE {ARTICLE_MONTH_SQL} = ?
            )
            """,
            (month,),
        ).fetchone()["count"]

    conn.close()
    return {
        "month": month,
        "articles": int(article_count or 0),
        "daily_topics": int(daily_topic_count or 0),
        "processed_references": int(processed_reference_count or 0),
        "pending_references": int(pending_reference_count or 0),
    }


def cleanup_month(month):
    preview = monthly_cleanup_preview(month)
    with connect_db() as conn:
        cursor = conn.cursor()

        # Keep the deduplication history, but remove IDs that are about to
        # point at deleted article rows.
        if table_exists(conn, "processed_candidates"):
            cursor.execute(
                f"""
                UPDATE processed_candidates
                SET article_id = 0
                WHERE article_id IN (
                    SELECT id FROM articles WHERE {ARTICLE_MONTH_SQL} = ?
                )
                """,
                (month,),
            )
        if table_exists(conn, "pending_articles"):
            cursor.execute(
                f"""
                UPDATE pending_articles
                SET completed_article_id = 0
                WHERE completed_article_id IN (
                    SELECT id FROM articles WHERE {ARTICLE_MONTH_SQL} = ?
                )
                """,
                (month,),
            )

        if table_exists(conn, "article_entities"):
            cursor.execute(
                f"""
                DELETE FROM article_entities
                WHERE article_id IN (
                    SELECT id FROM articles WHERE {ARTICLE_MONTH_SQL} = ?
                )
                """,
                (month,),
            )

        cursor.execute(
            f"DELETE FROM articles WHERE {ARTICLE_MONTH_SQL} = ?",
            (month,),
        )
        cursor.execute(
            "DELETE FROM daily_topics WHERE substr(topic_date, 1, 7) = ?",
            (month,),
        )

    rebuild_topic_stats()
    return {**preview, "deleted": True}


def main():
    args = parse_args()
    init_db()

    month = previous_month() if args.previous_month else args.month
    preview = monthly_cleanup_preview(month)
    print(f"目標月份：{month}")
    print(f"將刪除文章：{preview['articles']} 篇")
    print(f"將刪除本日話題紀錄：{preview['daily_topics']} 筆")
    print(f"將清除 processed_candidates 舊文章 ID：{preview['processed_references']} 筆")
    print(f"將清除 pending_articles 舊文章 ID：{preview['pending_references']} 筆")

    if args.dry_run:
        print("Dry run 模式：未刪除任何資料。")
        return

    result = cleanup_month(month)
    print(f"已刪除 {result['articles']} 篇文章與 {result['daily_topics']} 筆本日話題紀錄。")
    print("已重建近期焦點 topic_stats。")


if __name__ == "__main__":
    main()
