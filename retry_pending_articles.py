import argparse
import json
from datetime import datetime

from cleaning import is_probably_ai_related
from database import (
    get_article_by_id,
    get_pending_articles,
    init_db,
    is_article_exists_by_identity,
    save_article,
    update_pending_article_status,
)
from main import build_trend_reason, calculate_trend_components, calculate_trend_score
from summarizer import OpenAIAnalysisRetryableError, analyze_article
from topic_rankings import update_topic_rankings
from trend_config import MIN_RELEVANCE_SCORE


def parse_args():
    parser = argparse.ArgumentParser(description="Retry articles left pending by an OpenAI outage/quota issue.")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def article_from_pending(pending):
    article = dict(pending.get("article") or {})
    for key in [
        "title",
        "link",
        "source",
        "category",
        "published",
        "summary",
        "fingerprint",
        "source_weight",
        "source_group",
        "source_group_label",
    ]:
        if not article.get(key):
            article[key] = pending.get(key, "")
    if not article.get("created_at"):
        article["created_at"] = pending.get("created_at", "")
    if not article.get("collected_at"):
        article["collected_at"] = pending.get("created_at", "")
    return article


def analyze_and_save(article, dry_run=False):
    if not article.get("link"):
        return None

    if is_article_exists_by_identity(article["link"], article.get("fingerprint", "")):
        return None

    if not is_probably_ai_related(article):
        return None

    analysis = analyze_article(article)
    if (
        not analysis.get("should_include")
        or analysis.get("relevance_score", 0) < MIN_RELEVANCE_SCORE
    ):
        return None

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
    article["collected_at"] = article.get("collected_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if dry_run:
        return article

    article_id = save_article(article)
    if not article_id:
        return None

    article["id"] = article_id
    return article


def main():
    args = parse_args()
    init_db()

    pending_items = get_pending_articles(limit=args.limit)
    print(f"待補文章數：{len(pending_items)}")
    if args.dry_run:
        print("Dry run 模式：只分析，不寫入資料庫。")

    completed_articles = []
    for pending in pending_items:
        article = article_from_pending(pending)
        print(f"\n重新分析：{article.get('title', '')}")

        if int(pending.get("completed_article_id") or 0) > 0:
            saved_article = get_article_by_id(pending["completed_article_id"])
            if saved_article:
                completed_articles.append(
                    {"pending": pending, "article": saved_article, "already_saved": True}
                )
                print("文章已存在，將補跑話題統計。")
                continue

        try:
            saved_article = analyze_and_save(article, args.dry_run)
        except OpenAIAnalysisRetryableError as error:
            print(f"OpenAI 仍暫時失敗，保留待補：{error}")
            if not args.dry_run:
                update_pending_article_status(pending["id"], "failed", error)
            continue

        if not saved_article:
            print("略過：已存在、低相關，或 AI 判斷不收錄。")
            if not args.dry_run:
                update_pending_article_status(pending["id"], "completed", "Skipped or already saved.")
            continue

        completed_articles.append({"pending": pending, "article": saved_article, "already_saved": False})
        print(f"已補上架：{saved_article['title']}")

    if completed_articles:
        articles_by_date = {}
        for item in completed_articles:
            article = item["article"]
            topic_date = str(article.get("created_at") or "")[:10] or None
            articles_by_date.setdefault(topic_date, []).append(article)

        try:
            for topic_date, articles in articles_by_date.items():
                topics = update_topic_rankings(articles, topic_date=topic_date, dry_run=args.dry_run)
                label = topic_date or "今天"
                print(f"\n已更新 {label} 話題 Top {len(topics)}，近期焦點已重建。")
        except Exception as error:
            print(f"話題統計補跑失敗，文章會保留在待補清單：{error}")
            for item in completed_articles:
                article = item["article"]
                if not args.dry_run:
                    update_pending_article_status(
                        item["pending"]["id"],
                        "failed",
                        f"Topic ranking failed: {error}",
                        article.get("id", 0),
                    )
            print("補好 OpenAI token/quota 後，再執行：.venv/bin/python retry_pending_articles.py")
            raise

        if not args.dry_run:
            for item in completed_articles:
                article = item["article"]
                update_pending_article_status(
                    item["pending"]["id"],
                    "completed",
                    "",
                    article.get("id", 0),
                )
    else:
        print("\n沒有新增待補文章。")


if __name__ == "__main__":
    main()
