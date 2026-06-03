import os
import sqlite3
from datetime import datetime
import json

from dotenv import load_dotenv

from entities import parse_aliases, serialize_aliases


load_dotenv()

DB_TYPE = os.getenv("DB_TYPE", "sqlite").strip().lower()
USE_MYSQL = DB_TYPE == "mysql"
SQLITE_DB_NAME = os.getenv("SQLITE_DB_NAME", "articles.db")
DB_NAME = os.getenv("DB_NAME", "ai_trend") if USE_MYSQL else SQLITE_DB_NAME

if USE_MYSQL:
    import pymysql

    DB_INTEGRITY_ERROR = pymysql.err.IntegrityError
else:
    DB_INTEGRITY_ERROR = sqlite3.IntegrityError


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

WEEKLY_EMERGING_TOPIC_COLUMNS = {
    "analysis_summary": "TEXT",
    "generated_queries": "TEXT",
}


def db_label():
    if USE_MYSQL:
        return f"mysql://{os.getenv('DB_HOST', '127.0.0.1')}:{os.getenv('DB_PORT', '3306')}/{DB_NAME}"
    return DB_NAME


def convert_placeholders(sql):
    if not USE_MYSQL:
        return sql

    converted = []
    in_single = False
    in_double = False
    index = 0
    while index < len(sql):
        char = sql[index]
        if char == "'" and not in_double:
            converted.append(char)
            if in_single and index + 1 < len(sql) and sql[index + 1] == "'":
                converted.append(sql[index + 1])
                index += 2
                continue
            in_single = not in_single
        elif char == '"' and not in_single:
            converted.append(char)
            in_double = not in_double
        elif char == "?" and not in_single and not in_double:
            converted.append("%s")
        else:
            converted.append(char)
        index += 1
    return "".join(converted)


class RowAdapter(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def adapt_row(row):
    if USE_MYSQL and isinstance(row, dict):
        return RowAdapter(row)
    return row


class CursorAdapter:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, sql, params=None):
        self.cursor.execute(convert_placeholders(sql), params or ())
        return self

    def fetchone(self):
        row = self.cursor.fetchone()
        return adapt_row(row) if row is not None else None

    def fetchall(self):
        return [adapt_row(row) for row in self.cursor.fetchall()]

    @property
    def lastrowid(self):
        return self.cursor.lastrowid

    def __iter__(self):
        return iter(self.cursor)


class ConnectionAdapter:
    def __init__(self, conn):
        self.conn = conn

    def cursor(self):
        return CursorAdapter(self.conn.cursor())

    def execute(self, sql, params=None):
        cursor = self.cursor()
        return cursor.execute(sql, params)

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        self.close()


def connect_db():
    if USE_MYSQL:
        conn = pymysql.connect(
            host=os.getenv("DB_HOST", "127.0.0.1"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
            database=DB_NAME,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
        return ConnectionAdapter(conn)

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return ConnectionAdapter(conn)


def table_exists(conn, table_name):
    if USE_MYSQL:
        return conn.execute("SHOW TABLES LIKE ?", (table_name,)).fetchone() is not None

    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def get_table_columns(conn, table_name):
    if USE_MYSQL:
        if not table_name.replace("_", "").isalnum():
            raise ValueError(f"Invalid table name: {table_name}")
        rows = conn.execute(f"SHOW COLUMNS FROM `{table_name}`").fetchall()
        return [row["Field"] for row in rows]

    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [row[1] for row in rows]


def create_index_if_not_exists(conn, index_name, table_name, columns):
    if USE_MYSQL:
        exists = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM information_schema.statistics
            WHERE table_schema = DATABASE() AND index_name = ?
            """,
            (index_name,),
        ).fetchone()
        if int(exists["count"] or 0) > 0:
            return
        conn.execute(f"CREATE INDEX {index_name} ON {table_name}({columns})")
        return

    conn.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name}({columns})")


def text_type(column):
    if not USE_MYSQL:
        return "TEXT"

    varchar_columns = {
        "link": "VARCHAR(512)",
        "source": "VARCHAR(191)",
        "category": "VARCHAR(191)",
        "fingerprint": "VARCHAR(255)",
        "ai_category": "VARCHAR(191)",
        "source_group": "VARCHAR(64)",
        "source_group_label": "VARCHAR(191)",
        "canonical_name": "VARCHAR(191)",
        "entity_type": "VARCHAR(64)",
        "platform": "VARCHAR(64)",
        "item_id": "VARCHAR(255)",
        "name": "VARCHAR(255)",
        "url": "VARCHAR(512)",
        "primary_metric_name": "VARCHAR(64)",
        "secondary_metric_name": "VARCHAR(64)",
        "week_start": "VARCHAR(32)",
        "week_end": "VARCHAR(32)",
        "term": "VARCHAR(191)",
        "query": "VARCHAR(512)",
        "created_at": "VARCHAR(32)",
        "updated_at": "VARCHAR(32)",
        "fetched_at": "VARCHAR(32)",
        "analyzed_at": "VARCHAR(32)",
        "first_seen_at": "VARCHAR(32)",
        "last_seen_at": "VARCHAR(32)",
        "collected_at": "VARCHAR(32)",
        "published": "VARCHAR(128)",
    }
    return varchar_columns.get(column, "TEXT")


def integer_pk_type():
    return "INT AUTO_INCREMENT PRIMARY KEY" if USE_MYSQL else "INTEGER PRIMARY KEY AUTOINCREMENT"


def db_column_type(column, default_type):
    if not USE_MYSQL:
        return default_type
    if default_type.startswith("TEXT"):
        return text_type(column)
    if default_type.startswith("INTEGER"):
        return default_type.replace("INTEGER", "INT")
    if default_type.startswith("REAL"):
        return default_type.replace("REAL", "DOUBLE")
    return default_type


def init_db():
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS articles (
            id {integer_pk_type()},
            title {text_type("title")} NOT NULL,
            link {text_type("link")} NOT NULL UNIQUE,
            source {text_type("source")},
            category {text_type("category")},
            published {text_type("published")},
            summary {text_type("summary")},
            ai_summary {text_type("ai_summary")},
            fingerprint {text_type("fingerprint")},
            relevance_score INTEGER DEFAULT 0,
            importance_score INTEGER DEFAULT 0,
            trend_score REAL DEFAULT 0,
            ai_category {text_type("ai_category")},
            reason {text_type("reason")},
            collected_at {text_type("collected_at")},
            trend_reason {text_type("trend_reason")},
            trend_components {text_type("trend_components")},
            source_group {text_type("source_group")},
            source_group_label {text_type("source_group_label")},
            created_at {text_type("created_at")}
        )
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS entities (
            id {integer_pk_type()},
            canonical_name {text_type("canonical_name")} NOT NULL UNIQUE,
            entity_type {text_type("entity_type")},
            aliases {text_type("aliases")},
            mention_count INTEGER DEFAULT 0,
            trend_score REAL DEFAULT 0,
            first_seen_at {text_type("first_seen_at")},
            last_seen_at {text_type("last_seen_at")},
            created_at {text_type("created_at")}
        )
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS article_entities (
            article_id INTEGER NOT NULL,
            entity_id INTEGER NOT NULL,
            confidence REAL DEFAULT 0,
            evidence {text_type("evidence")},
            created_at {text_type("created_at")},
            PRIMARY KEY (article_id, entity_id)
        )
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS platform_items (
            id {integer_pk_type()},
            platform {text_type("platform")} NOT NULL,
            item_id {text_type("item_id")} NOT NULL,
            name {text_type("name")} NOT NULL,
            url {text_type("url")},
            description {text_type("description")},
            `rank` INTEGER,
            score REAL DEFAULT 0,
            primary_metric_name {text_type("primary_metric_name")},
            primary_metric_value REAL DEFAULT 0,
            secondary_metric_name {text_type("secondary_metric_name")},
            secondary_metric_value REAL DEFAULT 0,
            category {text_type("category")},
            tags {text_type("tags")},
            metrics {text_type("metrics")},
            ai_summary {text_type("ai_summary")},
            usage_guide {text_type("usage_guide")},
            target_users {text_type("target_users")},
            popularity_reason {text_type("popularity_reason")},
            quickstart {text_type("quickstart")},
            ai_analysis {text_type("ai_analysis")},
            analyzed_at {text_type("analyzed_at")},
            fetched_at {text_type("fetched_at")},
            created_at {text_type("created_at")},
            updated_at {text_type("updated_at")},
            UNIQUE(platform, item_id)
        )
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS weekly_emerging_topics (
            id {integer_pk_type()},
            week_start {text_type("week_start")} NOT NULL,
            week_end {text_type("week_end")} NOT NULL,
            term {text_type("term")} NOT NULL,
            mention_count INTEGER DEFAULT 0,
            source_count INTEGER DEFAULT 0,
            article_count INTEGER DEFAULT 0,
            trend_score_sum REAL DEFAULT 0,
            weekly_signal_score REAL DEFAULT 0,
            analysis_summary {text_type("analysis_summary")},
            generated_queries {text_type("generated_queries")},
            created_at {text_type("created_at")},
            updated_at {text_type("updated_at")},
            UNIQUE(week_start, term)
        )
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS weekly_emerging_topic_articles (
            topic_id INTEGER NOT NULL,
            article_id INTEGER NOT NULL,
            evidence {text_type("evidence")},
            created_at {text_type("created_at")},
            PRIMARY KEY (topic_id, article_id)
        )
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS generated_search_queries (
            id {integer_pk_type()},
            term {text_type("term")} NOT NULL,
            platform {text_type("platform")} NOT NULL,
            query {text_type("query")} NOT NULL,
            reason {text_type("reason")},
            active INTEGER DEFAULT 1,
            created_at {text_type("created_at")},
            updated_at {text_type("updated_at")},
            UNIQUE(term, platform, query)
        )
    """)

    # Keep older local databases compatible as the project evolves.
    columns = get_table_columns(conn, "articles")

    if "ai_summary" not in columns:
        cursor.execute(f"ALTER TABLE articles ADD COLUMN ai_summary {text_type('ai_summary')}")

    for column, column_type in ARTICLE_COLUMNS.items():
        if column not in columns:
            cursor.execute(f"ALTER TABLE articles ADD COLUMN {column} {db_column_type(column, column_type)}")

    platform_columns = get_table_columns(conn, "platform_items")
    for column, column_type in PLATFORM_ITEM_COLUMNS.items():
        if column not in platform_columns:
            cursor.execute(f"ALTER TABLE platform_items ADD COLUMN {column} {db_column_type(column, column_type)}")

    weekly_topic_columns = get_table_columns(conn, "weekly_emerging_topics")
    for column, column_type in WEEKLY_EMERGING_TOPIC_COLUMNS.items():
        if column not in weekly_topic_columns:
            cursor.execute(f"ALTER TABLE weekly_emerging_topics ADD COLUMN {column} {db_column_type(column, column_type)}")

    create_index_if_not_exists(conn, "idx_articles_fingerprint", "articles", "fingerprint")
    create_index_if_not_exists(conn, "idx_articles_trend_score", "articles", "trend_score")
    create_index_if_not_exists(conn, "idx_entities_trend_score", "entities", "trend_score")
    create_index_if_not_exists(conn, "idx_article_entities_entity", "article_entities", "entity_id")
    create_index_if_not_exists(
        conn,
        "idx_platform_items_platform_rank",
        "platform_items",
        "platform, `rank`",
    )
    create_index_if_not_exists(conn, "idx_platform_items_fetched_at", "platform_items", "fetched_at")
    create_index_if_not_exists(
        conn,
        "idx_weekly_emerging_topics_score",
        "weekly_emerging_topics",
        "week_start, weekly_signal_score",
    )
    create_index_if_not_exists(
        conn,
        "idx_generated_search_queries_platform",
        "generated_search_queries",
        "platform, active",
    )

    conn.commit()
    conn.close()


def is_article_exists(link):
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id FROM articles WHERE link = ?",
        (link,)
    )

    result = cursor.fetchone()
    conn.close()

    return result is not None


def is_article_exists_by_identity(link, fingerprint):
    conn = connect_db()
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
    conn = connect_db()
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

    except DB_INTEGRITY_ERROR:
        article_id = None

    conn.close()
    return article_id


def upsert_entity(entity, article_trend_score=0):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    canonical_name = entity["canonical_name"]
    entity_type = entity.get("entity_type", "other")
    aliases = [canonical_name, entity.get("name", "")]

    conn = connect_db()
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
    conn = connect_db()
    cursor = conn.cursor()

    if USE_MYSQL:
        sql = """
            INSERT INTO article_entities (
                article_id, entity_id, confidence, evidence, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON DUPLICATE KEY UPDATE
                confidence = VALUES(confidence),
                evidence = VALUES(evidence),
                created_at = VALUES(created_at)
        """
    else:
        sql = """
            INSERT OR REPLACE INTO article_entities (
                article_id, entity_id, confidence, evidence, created_at
            )
            VALUES (?, ?, ?, ?, ?)
        """

    cursor.execute(
        sql,
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
    conn = connect_db()
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
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM platform_items WHERE platform = ?", (platform,))

    for item in items:
        cursor.execute(
            """
            INSERT INTO platform_items (
                platform, item_id, name, url, description, `rank`, score,
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


def save_weekly_emerging_topics(week_start, week_end, topics):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = connect_db()
    cursor = conn.cursor()

    old_topic_ids = [
        row[0]
        for row in cursor.execute(
            "SELECT id FROM weekly_emerging_topics WHERE week_start = ?",
            (week_start,),
        ).fetchall()
    ]
    if old_topic_ids:
        placeholders = ",".join(["?"] * len(old_topic_ids))
        cursor.execute(
            f"DELETE FROM weekly_emerging_topic_articles WHERE topic_id IN ({placeholders})",
            old_topic_ids,
        )
    cursor.execute("DELETE FROM weekly_emerging_topics WHERE week_start = ?", (week_start,))

    for topic in topics:
        cursor.execute(
            """
            INSERT INTO weekly_emerging_topics (
                week_start, week_end, term, mention_count, source_count,
                article_count, trend_score_sum, weekly_signal_score,
                analysis_summary, generated_queries, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                week_start,
                week_end,
                topic.get("term", ""),
                int(topic.get("mention_count", 0)),
                int(topic.get("source_count", 0)),
                int(topic.get("article_count", 0)),
                float(topic.get("trend_score_sum", 0)),
                float(topic.get("weekly_signal_score", 0)),
                topic.get("analysis_summary", ""),
                json.dumps(topic.get("generated_queries", []), ensure_ascii=False),
                now,
                now,
            ),
        )
        topic_id = cursor.lastrowid
        for article in topic.get("articles", []):
            if USE_MYSQL:
                sql = """
                    INSERT INTO weekly_emerging_topic_articles (
                        topic_id, article_id, evidence, created_at
                    )
                    VALUES (?, ?, ?, ?)
                    ON DUPLICATE KEY UPDATE
                        evidence = VALUES(evidence),
                        created_at = VALUES(created_at)
                """
            else:
                sql = """
                    INSERT OR REPLACE INTO weekly_emerging_topic_articles (
                        topic_id, article_id, evidence, created_at
                    )
                    VALUES (?, ?, ?, ?)
                """
            cursor.execute(
                sql,
                (
                    topic_id,
                    int(article.get("id")),
                    article.get("evidence", ""),
                    now,
                ),
            )

    conn.commit()
    conn.close()


def save_generated_search_queries(term, queries):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = connect_db()
    cursor = conn.cursor()

    for query in queries:
        platform = str(query.get("platform", "")).strip()
        query_text = str(query.get("query", "")).strip()
        if not platform or not query_text:
            continue
        if USE_MYSQL:
            sql = """
                INSERT INTO generated_search_queries (
                    term, platform, query, reason, active, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 1, ?, ?)
                ON DUPLICATE KEY UPDATE
                    reason = VALUES(reason),
                    active = 1,
                    updated_at = VALUES(updated_at)
            """
        else:
            sql = """
                INSERT INTO generated_search_queries (
                    term, platform, query, reason, active, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(term, platform, query) DO UPDATE SET
                    reason = excluded.reason,
                    active = 1,
                    updated_at = excluded.updated_at
            """
        cursor.execute(
            sql,
            (
                term,
                platform,
                query_text,
                query.get("reason", ""),
                now,
                now,
            ),
        )

    conn.commit()
    conn.close()


def get_active_generated_queries(platform=None):
    conn = connect_db()
    cursor = conn.cursor()

    if platform:
        rows = cursor.execute(
            """
            SELECT term, platform, query, reason
            FROM generated_search_queries
            WHERE active = 1 AND platform = ?
            ORDER BY updated_at DESC, id DESC
            """,
            (platform,),
        ).fetchall()
    else:
        rows = cursor.execute(
            """
            SELECT term, platform, query, reason
            FROM generated_search_queries
            WHERE active = 1
            ORDER BY updated_at DESC, id DESC
            """
        ).fetchall()

    result = [dict(row) for row in rows]
    conn.close()
    return result
