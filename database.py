import sqlite3
from datetime import datetime

from entities import parse_aliases, serialize_aliases


DB_NAME = "articles.db"


ARTICLE_COLUMNS = {
    "fingerprint": "TEXT",
    "relevance_score": "INTEGER DEFAULT 0",
    "importance_score": "INTEGER DEFAULT 0",
    "trend_score": "REAL DEFAULT 0",
    "ai_category": "TEXT",
    "reason": "TEXT",
    "collected_at": "TEXT",
    "trend_reason": "TEXT",
    "trend_components": "TEXT",
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
            trend_reason TEXT,
            trend_components TEXT,
            created_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_name TEXT NOT NULL UNIQUE,
            entity_type TEXT,
            aliases TEXT,
            mention_count INTEGER DEFAULT 0,
            trend_score REAL DEFAULT 0,
            first_seen_at TEXT,
            last_seen_at TEXT,
            created_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS article_entities (
            article_id INTEGER NOT NULL,
            entity_id INTEGER NOT NULL,
            confidence REAL DEFAULT 0,
            evidence TEXT,
            created_at TEXT,
            PRIMARY KEY (article_id, entity_id)
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
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_entities_trend_score ON entities(trend_score)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_article_entities_entity ON article_entities(entity_id)"
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
                ai_category, reason, collected_at, trend_reason, trend_components, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            article.get("trend_reason", ""),
            article.get("trend_components", ""),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))

        conn.commit()
        article_id = cursor.lastrowid

    except sqlite3.IntegrityError:
        article_id = None

    conn.close()
    return article_id


def upsert_entity(entity, article_trend_score=0):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    canonical_name = entity["canonical_name"]
    entity_type = entity.get("entity_type", "other")
    aliases = [canonical_name, entity.get("name", "")]

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    row = cursor.execute(
        "SELECT * FROM entities WHERE canonical_name = ?",
        (canonical_name,),
    ).fetchone()

    if row:
        merged_aliases = parse_aliases(row["aliases"]) + aliases
        cursor.execute(
            """
            UPDATE entities
            SET entity_type = COALESCE(NULLIF(?, ''), entity_type),
                aliases = ?,
                mention_count = mention_count + 1,
                trend_score = trend_score + ?,
                last_seen_at = ?
            WHERE id = ?
            """,
            (
                entity_type,
                serialize_aliases(merged_aliases),
                float(article_trend_score or 0),
                now,
                row["id"],
            ),
        )
        entity_id = row["id"]
    else:
        cursor.execute(
            """
            INSERT INTO entities (
                canonical_name, entity_type, aliases, mention_count,
                trend_score, first_seen_at, last_seen_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                canonical_name,
                entity_type,
                serialize_aliases(aliases),
                1,
                float(article_trend_score or 0),
                now,
                now,
                now,
            ),
        )
        entity_id = cursor.lastrowid

    conn.commit()
    conn.close()
    return entity_id


def link_article_entity(article_id, entity_id, confidence=0, evidence=""):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT OR REPLACE INTO article_entities (
            article_id, entity_id, confidence, evidence, created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            article_id,
            entity_id,
            float(confidence or 0),
            str(evidence or ""),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )

    conn.commit()
    conn.close()


def update_article_trend_metadata(article_id, article):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE articles
        SET relevance_score = ?,
            importance_score = ?,
            trend_score = ?,
            ai_category = ?,
            category = ?,
            reason = ?,
            trend_reason = ?,
            trend_components = ?
        WHERE id = ?
        """,
        (
            article.get("relevance_score", 0),
            article.get("importance_score", 0),
            article.get("trend_score", 0),
            article.get("ai_category", article.get("category", "")),
            article.get("category", ""),
            article.get("reason", ""),
            article.get("trend_reason", ""),
            article.get("trend_components", ""),
            article_id,
        ),
    )

    conn.commit()
    conn.close()
