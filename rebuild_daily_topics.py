import argparse
import re
from datetime import datetime

from database import get_articles_by_date, init_db
from topic_rankings import update_topic_rankings


def valid_date(value):
    article_date = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", article_date):
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD, for example 2026-09-16")
    try:
        datetime.strptime(article_date, "%Y-%m-%d")
    except ValueError as error:
        raise argparse.ArgumentTypeError("date must be a real calendar date") from error
    return article_date


def parse_args():
    parser = argparse.ArgumentParser(
        description="Rebuild daily topic rankings from articles already saved in the database."
    )
    parser.add_argument("--date", type=valid_date, required=True, help="Article date to rebuild.")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum saved articles to send into topic ranking. 0 means all articles for the date.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview topics without writing.")
    return parser.parse_args()


def main():
    args = parse_args()
    init_db()

    articles = get_articles_by_date(args.date, limit=args.limit)
    print(f"{args.date} 已存文章數：{len(articles)}")
    if not articles:
        print("沒有可重建的文章。")
        return

    topics = update_topic_rankings(articles, topic_date=args.date, dry_run=args.dry_run)
    if args.dry_run:
        print("Dry run 模式：未寫入 daily_topics / topic_stats。")
    print(f"{args.date} 話題 Top {len(topics)} 已重建。")


if __name__ == "__main__":
    main()
