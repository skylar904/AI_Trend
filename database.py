import sqlite3
from datetime import datetime


DB_NAME = "articles.db"


ARTICLE_COLUMNS = {
    "fingerprint": "TEXT",
    "relevance_score": "INTEGER DEFAULT 0",
    "importance_score": "INTEGER DEFAULT 0",
    "trend_score": "REAL DEFAULT 0",
    "ai_category": "TEXT",
    "reason": "TEXT",
    "collected_at": "TEXT",
}


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
            fingerprint TEXT,
            relevance_score INTEGER DEFAULT 0,
            importance_score INTEGER DEFAULT 0,
            trend_score REAL DEFAULT 0,
            ai_category TEXT,
            reason TEXT,
            collected_at TEXT,
            created_at TEXT
        )
    """)

    # Keep older local databases compatible as the project evolves.
    cursor.execute("PRAGMA table_info(articles)")
    columns = [column[1] for column in cursor.fetchall()]

    if "ai_summary" not in columns:
        cursor.execute("ALTER TABLE articles ADD COLUMN ai_summary TEXT")

    for column, column_type in ARTICLE_COLUMNS.items():
        if column not in columns:
            cursor.execute(f"ALTER TABLE articles ADD COLUMN {column} {column_type}")

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_articles_fingerprint ON articles(fingerprint)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_articles_trend_score ON articles(trend_score)"
    )

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


def is_article_exists_by_identity(link, fingerprint):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT id FROM articles
        WHERE link = ? OR (fingerprint IS NOT NULL AND fingerprint = ?)
        """,
        (link, fingerprint),
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
                title, link, source, category, published, summary, ai_summary,
                fingerprint, relevance_score, importance_score, trend_score,
                ai_category, reason, collected_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            article["title"],
            article["link"],
            article["source"],
            article["category"],
            article["published"],
            article["summary"],
            article.get("ai_summary", ""),
            article.get("fingerprint", ""),
            article.get("relevance_score", 0),
            article.get("importance_score", 0),
            article.get("trend_score", 0),
            article.get("ai_category", ""),
            article.get("reason", ""),
            article.get("collected_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

        conn.commit()

    except sqlite3.IntegrityError:
        pass

    conn.close()
