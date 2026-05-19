import feedparser
from feeds import RSS_FEEDS
from report import generate_markdown_report, save_report
from database import init_db, is_article_exists, save_article
from summarizer import summarize_article


def fetch_feed(feed):
    parsed = feedparser.parse(feed["url"])

    articles = []

    for entry in parsed.entries[:5]:
        article = {
            "source": feed["name"],
            "category": feed["category"],
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "published": entry.get("published", ""),
            "summary": entry.get("summary", "")
        }
        articles.append(article)

    return articles


def main():
    init_db()

    all_new_articles = []

    for feed in RSS_FEEDS:
        print(f"正在讀取：{feed['name']}")
        articles = fetch_feed(feed)

        for article in articles:
            link = article["link"]

            if not link:
                continue

            if is_article_exists(link):
                print(f"已存在，跳過：{article['title']}")
                continue

            print(f"新文章：{article['title']}")

            print("正在產生 AI 中文摘要...")
            try:
                ai_summary = summarize_article(article)
            except Exception as e:
                print(f"AI 摘要失敗：{e}")
                ai_summary = "AI 摘要產生失敗，暫時保留原始 RSS 摘要。"

            article["ai_summary"] = ai_summary

            save_article(article)
            all_new_articles.append(article)

    if not all_new_articles:
        print("\n今天沒有新的文章。")
        return

    markdown_text = generate_markdown_report(all_new_articles)
    file_path = save_report(markdown_text)

    print(f"\n新文章數量：{len(all_new_articles)}")
    print(f"報告已產生：{file_path}")


if __name__ == "__main__":
    main()