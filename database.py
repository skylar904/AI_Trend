import sqlite3
from datetime import datetime
import json

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
    "source_group": "TEXT",
    "source_group_label": "TEXT",
}

PLATFORM_ITEM_COLUMNS = {
    "ai_summary": "TEXT",
    "usage_guide": "TEXT",
    "target_users": "TEXT",
    "popularity_reason": "TEXT",
    "quickstart": "TEXT",
    "ai_analysis": "TEXT",
    "analyzed_at": "TEXT",
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
            source_group TEXT,
            source_group_label TEXT,
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

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS platform_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            item_id TEXT NOT NULL,
            name TEXT NOT NULL,
            url TEXT,
            description TEXT,
            rank INTEGER,
            score REAL DEFAULT 0,
            primary_metric_name TEXT,
            primary_metric_value REAL DEFAULT 0,
            secondary_metric_name TEXT,
            secondary_metric_value REAL DEFAULT 0,
            category TEXT,
            tags TEXT,
            metrics TEXT,
            ai_summary TEXT,
            usage_guide TEXT,
            target_users TEXT,
            popularity_reason TEXT,
            quickstart TEXT,
            ai_analysis TEXT,
            analyzed_at TEXT,
            fetched_at TEXT,
            created_at TEXT,
            updated_at TEXT,
            UNIQUE(platform, item_id)
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

    cursor.execute("PRAGMA table_info(platform_items)")
    platform_columns = [column[1] for column in cursor.fetchall()]
    for column, column_type in PLATFORM_ITEM_COLUMNS.items():
        if column not in platform_columns:
            cursor.execute(f"ALTER TABLE platform_items ADD COLUMN {column} {column_type}")

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
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_platform_items_platform_rank ON platform_items(platform, rank)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_platform_items_fetched_at ON platform_items(fetched_at)"
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
                ai_category, reason, collected_at, trend_reason, trend_components,
                source_group, source_group_label, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            article.get("source_group", ""),
            article.get("source_group_label", ""),
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


def save_platform_items(platform, items):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM platform_items WHERE platform = ?", (platform,))

    for item in items:
        cursor.execute(
            """
            INSERT INTO platform_items (
                platform, item_id, name, url, description, rank, score,
                primary_metric_name, primary_metric_value,
                secondary_metric_name, secondary_metric_value,
                category, tags, metrics, ai_summary, usage_guide, target_users,
                popularity_reason, quickstart, ai_analysis, analyzed_at,
                fetched_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                platform,
                item.get("item_id", ""),
                item.get("name", ""),
                item.get("url", ""),
                item.get("description", ""),
                item.get("rank", 0),
                item.get("score", 0),
                item.get("primary_metric_name", ""),
                item.get("primary_metric_value", 0),
                item.get("secondary_metric_name", ""),
                item.get("secondary_metric_value", 0),
                item.get("category", ""),
                json.dumps(item.get("tags", []), ensure_ascii=False),
                json.dumps(item.get("metrics", {}), ensure_ascii=False),
                item.get("ai_summary", ""),
                item.get("usage_guide", ""),
                item.get("target_users", ""),
                item.get("popularity_reason", ""),
                item.get("quickstart", ""),
                json.dumps(item.get("ai_analysis", {}), ensure_ascii=False),
                item.get("analyzed_at", ""),
                item.get("fetched_at", now),
                now,
                now,
            ),
        )

    conn.commit()
    conn.close()
