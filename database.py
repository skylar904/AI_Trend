import sqlite3
from datetime import datetime


DB_NAME = "articles.db"


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            link TEXT NOT NULL UNIQUE,
            source TEXT,
            category TEXT,
            published TEXT,
            summary TEXT,
            ai_summary TEXT,
            created_at TEXT
        )
    """)

    # 如果你之前已經建立過 articles.db，這裡會自動補 ai_summary 欄位
    cursor.execute("PRAGMA table_info(articles)")
    columns = [column[1] for column in cursor.fetchall()]

    if "ai_summary" not in columns:
        cursor.execute("ALTER TABLE articles ADD COLUMN ai_summary TEXT")

    conn.commit()
    conn.close()


def is_article_exists(link):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id FROM articles WHERE link = ?",
        (link,)
    )

    result = cursor.fetchone()
    conn.close()

    return result is not None


def save_article(article):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO articles (
                title, link, source, category, published, summary, ai_summary, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            article["title"],
            article["link"],
            article["source"],
            article["category"],
            article["published"],
            article["summary"],
            article.get("ai_summary", ""),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

        conn.commit()

    except sqlite3.IntegrityError:
        pass

    conn.close()