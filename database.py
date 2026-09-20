import os
import sqlite3
from datetime import datetime
import json

from dotenv import load_dotenv

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

PENDING_ARTICLE_COLUMNS = {
    "source": "TEXT",
    "category": "TEXT",
    "published": "TEXT",
    "summary": "TEXT",
    "fingerprint": "TEXT",
    "source_weight": "REAL DEFAULT 1",
    "source_group": "TEXT",
    "source_group_label": "TEXT",
    "raw_payload": "TEXT",
    "status": "TEXT",
    "failure_reason": "TEXT",
    "attempt_count": "INTEGER DEFAULT 0",
    "last_attempt_at": "TEXT",
    "completed_article_id": "INTEGER DEFAULT 0",
    "created_at": "TEXT",
    "updated_at": "TEXT",
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
        "platform": "VARCHAR(64)",
        "item_id": "VARCHAR(255)",
        "name": "VARCHAR(255)",
        "url": "VARCHAR(512)",
        "primary_metric_name": "VARCHAR(64)",
        "secondary_metric_name": "VARCHAR(64)",
        "week_start": "VARCHAR(32)",
        "week_end": "VARCHAR(32)",
        "term": "VARCHAR(191)",
        "topic_date": "VARCHAR(32)",
        "query": "VARCHAR(512)",
        "created_at": "VARCHAR(32)",
        "updated_at": "VARCHAR(32)",
        "fetched_at": "VARCHAR(32)",
        "analyzed_at": "VARCHAR(32)",
        "first_seen_at": "VARCHAR(32)",
        "last_seen_at": "VARCHAR(32)",
        "collected_at": "VARCHAR(32)",
        "published": "VARCHAR(128)",
        "status": "VARCHAR(32)",
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
        CREATE TABLE IF NOT EXISTS daily_topics (
            id {integer_pk_type()},
            topic_date {text_type("topic_date")} NOT NULL,
            term {text_type("term")} NOT NULL,
            mention_count INTEGER DEFAULT 0,
            source_count INTEGER DEFAULT 0,
            article_count INTEGER DEFAULT 0,
            trend_score_sum REAL DEFAULT 0,
            topic_score REAL DEFAULT 0,
            reason {text_type("reason")},
            evidence_articles {text_type("evidence_articles")},
            created_at {text_type("created_at")},
            updated_at {text_type("updated_at")},
            UNIQUE(topic_date, term)
        )
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS topic_stats (
            id {integer_pk_type()},
            term {text_type("term")} NOT NULL UNIQUE,
            total_mentions INTEGER DEFAULT 0,
            total_article_count INTEGER DEFAULT 0,
            total_source_count INTEGER DEFAULT 0,
            active_days INTEGER DEFAULT 0,
            trend_score_sum REAL DEFAULT 0,
            topic_score REAL DEFAULT 0,
            first_seen_at {text_type("first_seen_at")},
            last_seen_at {text_type("last_seen_at")},
            evidence_articles {text_type("evidence_articles")},
            created_at {text_type("created_at")},
            updated_at {text_type("updated_at")}
        )
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS pending_articles (
            id {integer_pk_type()},
            title {text_type("title")} NOT NULL,
            link {text_type("link")} NOT NULL UNIQUE,
            source {text_type("source")},
            category {text_type("category")},
            published {text_type("published")},
            summary {text_type("summary")},
            fingerprint {text_type("fingerprint")},
            source_weight REAL DEFAULT 1,
            source_group {text_type("source_group")},
            source_group_label {text_type("source_group_label")},
            raw_payload {text_type("raw_payload")},
            status {text_type("status")} DEFAULT 'pending',
            failure_reason {text_type("failure_reason")},
            attempt_count INTEGER DEFAULT 0,
            last_attempt_at {text_type("last_attempt_at")},
            completed_article_id INTEGER DEFAULT 0,
            created_at {text_type("created_at")},
            updated_at {text_type("updated_at")}
        )
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS processed_candidates (
            id {integer_pk_type()},
            fingerprint {text_type("fingerprint")} NOT NULL UNIQUE,
            link {text_type("link")},
            title {text_type("title")},
            status {text_type("status")} NOT NULL,
            reason {text_type("reason")},
            article_id INTEGER DEFAULT 0,
            first_processed_at {text_type("first_processed_at")},
            last_processed_at {text_type("last_processed_at")}
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

    pending_article_columns = get_table_columns(conn, "pending_articles")
    for column, column_type in PENDING_ARTICLE_COLUMNS.items():
        if column not in pending_article_columns:
            cursor.execute(f"ALTER TABLE pending_articles ADD COLUMN {column} {db_column_type(column, column_type)}")

    create_index_if_not_exists(conn, "idx_articles_fingerprint", "articles", "fingerprint")
    create_index_if_not_exists(conn, "idx_articles_trend_score", "articles", "trend_score")
    create_index_if_not_exists(
        conn,
        "idx_platform_items_platform_rank",
        "platform_items",
        "platform, `rank`",
    )
    create_index_if_not_exists(conn, "idx_platform_items_fetched_at", "platform_items", "fetched_at")
    create_index_if_not_exists(
        conn,
        "idx_daily_topics_date_score",
        "daily_topics",
        "topic_date, topic_score",
    )
    create_index_if_not_exists(conn, "idx_topic_stats_score", "topic_stats", "topic_score")
    create_index_if_not_exists(
        conn,
        "idx_pending_articles_status",
        "pending_articles",
        "status, updated_at",
    )
    create_index_if_not_exists(
        conn,
        "idx_processed_candidates_status",
        "processed_candidates",
        "status",
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


def get_candidate_processing_status(link, fingerprint):
    if not link and not fingerprint:
        return None

    conn = connect_db()
    cursor = conn.cursor()
    identity_params = (link or "", fingerprint or "", fingerprint or "")

    article = cursor.execute(
        """
        SELECT id FROM articles
        WHERE link = ? OR (? <> '' AND fingerprint = ?)
        LIMIT 1
        """,
        identity_params,
    ).fetchone()
    if article:
        conn.close()
        return "accepted"

    processed = cursor.execute(
        """
        SELECT status FROM processed_candidates
        WHERE fingerprint = ? OR (? <> '' AND link = ?)
        LIMIT 1
        """,
        (fingerprint or "", link or "", link or ""),
    ).fetchone()
    if processed:
        conn.close()
        return processed["status"] or "processed"

    pending = cursor.execute(
        """
        SELECT status FROM pending_articles
        WHERE link = ? OR (? <> '' AND fingerprint = ?)
        LIMIT 1
        """,
        identity_params,
    ).fetchone()
    conn.close()
    if pending:
        return pending["status"] or "pending"
    return None


def record_candidate_processing(article, status, reason="", article_id=0):
    fingerprint = str(article.get("fingerprint") or "").strip()
    if not fingerprint:
        return None

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    values = (
        fingerprint,
        article.get("link", ""),
        article.get("title", ""),
        str(status or "processed"),
        str(reason or ""),
        int(article_id or 0),
        now,
        now,
    )
    conn = connect_db()
    cursor = conn.cursor()

    if USE_MYSQL:
        sql = """
            INSERT INTO processed_candidates (
                fingerprint, link, title, status, reason, article_id,
                first_processed_at, last_processed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON DUPLICATE KEY UPDATE
                link = VALUES(link),
                title = VALUES(title),
                status = VALUES(status),
                reason = VALUES(reason),
                article_id = VALUES(article_id),
                last_processed_at = VALUES(last_processed_at)
        """
    else:
        sql = """
            INSERT INTO processed_candidates (
                fingerprint, link, title, status, reason, article_id,
                first_processed_at, last_processed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fingerprint) DO UPDATE SET
                link = excluded.link,
                title = excluded.title,
                status = excluded.status,
                reason = excluded.reason,
                article_id = excluded.article_id,
                last_processed_at = excluded.last_processed_at
        """

    cursor.execute(sql, values)
    conn.commit()
    processed_id = cursor.lastrowid
    conn.close()
    return processed_id


def save_article(article):
    conn = connect_db()
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    created_at = article.get("created_at") or now
    collected_at = article.get("collected_at") or created_at

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
            collected_at,
            article.get("trend_reason", ""),
            article.get("trend_components", ""),
            article.get("source_group", ""),
            article.get("source_group_label", ""),
            created_at
        ))

        conn.commit()
        article_id = cursor.lastrowid

    except DB_INTEGRITY_ERROR:
        article_id = None

    conn.close()
    return article_id


def normalize_article_row(row):
    article = dict(row)
    article["trend_score"] = float(article.get("trend_score") or 0)
    article["relevance_score"] = int(article.get("relevance_score") or 0)
    article["importance_score"] = int(article.get("importance_score") or 0)
    return article


def get_article_by_id(article_id):
    conn = connect_db()
    cursor = conn.cursor()
    row = cursor.execute(
        """
        SELECT id, title, link, source, category, published, summary, ai_summary,
               fingerprint, relevance_score, importance_score, trend_score,
               ai_category, reason, collected_at, trend_reason, trend_components,
               source_group, source_group_label, created_at
        FROM articles
        WHERE id = ?
        """,
        (article_id,),
    ).fetchone()
    conn.close()
    return normalize_article_row(row) if row else None


def get_articles_by_date(article_date, limit=None):
    conn = connect_db()
    cursor = conn.cursor()
    sql = """
        SELECT id, title, link, source, category, published, summary, ai_summary,
               fingerprint, relevance_score, importance_score, trend_score,
               ai_category, reason, collected_at, trend_reason, trend_components,
               source_group, source_group_label, created_at
        FROM articles
        WHERE substr(created_at, 1, 10) = ?
        ORDER BY trend_score DESC, id DESC
    """
    params = [article_date]
    if limit and int(limit) > 0:
        sql += " LIMIT ?"
        params.append(int(limit))
    rows = cursor.execute(sql, params).fetchall()
    conn.close()
    return [normalize_article_row(row) for row in rows]


def pending_article_values(article, failure_reason, status="pending"):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        article.get("title", ""),
        article.get("link", ""),
        article.get("source", ""),
        article.get("category", ""),
        article.get("published", ""),
        article.get("summary", ""),
        article.get("fingerprint", ""),
        float(article.get("source_weight", 1) or 1),
        article.get("source_group", ""),
        article.get("source_group_label", ""),
        json.dumps(article, ensure_ascii=False),
        status,
        str(failure_reason or ""),
        now,
        now,
    )


def save_pending_article(article, failure_reason, status="pending"):
    if not article.get("link"):
        return None

    conn = connect_db()
    cursor = conn.cursor()
    values = pending_article_values(article, failure_reason, status)

    if USE_MYSQL:
        sql = """
            INSERT INTO pending_articles (
                title, link, source, category, published, summary, fingerprint,
                source_weight, source_group, source_group_label, raw_payload,
                status, failure_reason, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON DUPLICATE KEY UPDATE
                title = VALUES(title),
                source = VALUES(source),
                category = VALUES(category),
                published = VALUES(published),
                summary = VALUES(summary),
                fingerprint = VALUES(fingerprint),
                source_weight = VALUES(source_weight),
                source_group = VALUES(source_group),
                source_group_label = VALUES(source_group_label),
                raw_payload = VALUES(raw_payload),
                status = VALUES(status),
                failure_reason = VALUES(failure_reason),
                updated_at = VALUES(updated_at)
        """
    else:
        sql = """
            INSERT INTO pending_articles (
                title, link, source, category, published, summary, fingerprint,
                source_weight, source_group, source_group_label, raw_payload,
                status, failure_reason, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(link) DO UPDATE SET
                title = excluded.title,
                source = excluded.source,
                category = excluded.category,
                published = excluded.published,
                summary = excluded.summary,
                fingerprint = excluded.fingerprint,
                source_weight = excluded.source_weight,
                source_group = excluded.source_group,
                source_group_label = excluded.source_group_label,
                raw_payload = excluded.raw_payload,
                status = excluded.status,
                failure_reason = excluded.failure_reason,
                updated_at = excluded.updated_at
        """

    cursor.execute(sql, values)
    conn.commit()
    pending_id = cursor.lastrowid
    conn.close()
    return pending_id


def get_pending_articles(limit=50, statuses=None):
    statuses = statuses or ["pending", "failed"]
    placeholders = ",".join(["?"] * len(statuses))
    conn = connect_db()
    cursor = conn.cursor()
    rows = cursor.execute(
        f"""
        SELECT id, title, link, source, category, published, summary, fingerprint,
               source_weight, source_group, source_group_label, raw_payload,
               status, failure_reason, attempt_count, last_attempt_at,
               completed_article_id, created_at, updated_at
        FROM pending_articles
        WHERE status IN ({placeholders})
        ORDER BY updated_at ASC, id ASC
        LIMIT ?
        """,
        [*statuses, limit],
    ).fetchall()
    conn.close()

    results = []
    for row in rows:
        item = dict(row)
        try:
            payload = json.loads(item.get("raw_payload") or "{}")
        except (TypeError, json.JSONDecodeError):
            payload = {}
        item["article"] = payload if isinstance(payload, dict) else {}
        results.append(item)
    return results


def update_pending_article_status(pending_id, status, failure_reason="", completed_article_id=0):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE pending_articles
        SET status = ?,
            failure_reason = ?,
            completed_article_id = ?,
            last_attempt_at = ?,
            updated_at = ?,
            attempt_count = attempt_count + 1
        WHERE id = ?
        """,
        (
            status,
            str(failure_reason or ""),
            int(completed_article_id or 0),
            now,
            now,
            pending_id,
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


def topic_share(rows, score_key="topic_score"):
    max_score = max([float(row.get(score_key) or 0) for row in rows] or [1])
    if max_score <= 0:
        max_score = 1
    for row in rows:
        row["share"] = round(float(row.get(score_key) or 0) / max_score * 100, 2)
    return rows


def normalize_topic_row(row):
    topic = dict(row)
    topic["mention_count"] = int(topic.get("mention_count") or topic.get("total_mentions") or 0)
    topic["article_count"] = int(topic.get("article_count") or topic.get("total_article_count") or 0)
    topic["source_count"] = int(topic.get("source_count") or topic.get("total_source_count") or 0)
    topic["trend_score_sum"] = float(topic.get("trend_score_sum") or 0)
    topic["topic_score"] = float(topic.get("topic_score") or 0)
    topic["weekly_signal_score"] = topic["topic_score"]
    topic["articles"] = parse_json_array(topic.get("evidence_articles"))
    topic["sources"] = sorted(
        {
            str(article.get("source")).strip()
            for article in topic["articles"]
            if isinstance(article, dict) and str(article.get("source") or "").strip()
        }
    )
    return topic


def parse_json_array(value):
    if not value:
        return []
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def save_daily_topics(topic_date, topics):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = connect_db()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM daily_topics WHERE topic_date = ?", (topic_date,))

    for topic in topics:
        term = str(topic.get("term") or "").strip()
        if not term:
            continue
        cursor.execute(
            """
            INSERT INTO daily_topics (
                topic_date, term, mention_count, source_count, article_count,
                trend_score_sum, topic_score, reason, evidence_articles,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                topic_date,
                term,
                int(topic.get("mention_count", 0)),
                int(topic.get("source_count", 0)),
                int(topic.get("article_count", 0)),
                float(topic.get("trend_score_sum", 0)),
                float(topic.get("topic_score", 0)),
                topic.get("reason", ""),
                json.dumps(topic.get("articles", []), ensure_ascii=False),
                now,
                now,
            ),
        )

    conn.commit()
    conn.close()


def get_daily_topics(topic_date=None, limit=5):
    conn = connect_db()
    cursor = conn.cursor()

    if topic_date is None:
        latest = cursor.execute("SELECT MAX(topic_date) AS topic_date FROM daily_topics").fetchone()
        topic_date = latest["topic_date"] if latest else None

    if not topic_date:
        conn.close()
        return []

    rows = cursor.execute(
        """
        SELECT id, topic_date, term, mention_count, source_count, article_count,
               trend_score_sum, topic_score, reason, evidence_articles,
               created_at, updated_at
        FROM daily_topics
        WHERE topic_date = ?
        ORDER BY topic_score DESC, source_count DESC, article_count DESC, term
        LIMIT ?
        """,
        (topic_date, limit),
    ).fetchall()
    conn.close()

    return topic_share([normalize_topic_row(row) for row in rows])


def get_topic_stats(limit=5):
    conn = connect_db()
    cursor = conn.cursor()
    rows = cursor.execute(
        """
        SELECT id, term, total_mentions, total_article_count, total_source_count,
               active_days, trend_score_sum, topic_score, first_seen_at,
               last_seen_at, evidence_articles, created_at, updated_at
        FROM topic_stats
        ORDER BY topic_score DESC, total_source_count DESC, total_article_count DESC, active_days DESC, term
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()

    return topic_share([normalize_topic_row(row) for row in rows])


def rebuild_topic_stats():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = connect_db()
    cursor = conn.cursor()

    rows = cursor.execute(
        """
        SELECT topic_date, term, mention_count, source_count, article_count,
               trend_score_sum, topic_score, evidence_articles
        FROM daily_topics
        ORDER BY topic_date ASC, topic_score DESC
        """
    ).fetchall()

    stats = {}
    for row in rows:
        term = row["term"]
        stat = stats.setdefault(
            term,
            {
                "term": term,
                "total_mentions": 0,
                "total_article_count": 0,
                "total_source_count": 0,
                "active_days": 0,
                "trend_score_sum": 0.0,
                "topic_score": 0.0,
                "first_seen_at": row["topic_date"],
                "last_seen_at": row["topic_date"],
                "articles": [],
            },
        )
        stat["total_mentions"] += int(row["mention_count"] or 0)
        stat["total_article_count"] += int(row["article_count"] or 0)
        stat["total_source_count"] += int(row["source_count"] or 0)
        stat["active_days"] += 1
        stat["trend_score_sum"] += float(row["trend_score_sum"] or 0)
        stat["topic_score"] += float(row["topic_score"] or 0)
        stat["first_seen_at"] = min(stat["first_seen_at"], row["topic_date"])
        stat["last_seen_at"] = max(stat["last_seen_at"], row["topic_date"])
        stat["articles"].extend(parse_json_array(row["evidence_articles"])[:3])

    cursor.execute("DELETE FROM topic_stats")
    for stat in stats.values():
        cursor.execute(
            """
            INSERT INTO topic_stats (
                term, total_mentions, total_article_count, total_source_count,
                active_days, trend_score_sum, topic_score, first_seen_at,
                last_seen_at, evidence_articles, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stat["term"],
                stat["total_mentions"],
                stat["total_article_count"],
                stat["total_source_count"],
                stat["active_days"],
                round(stat["trend_score_sum"], 2),
                round(stat["topic_score"], 2),
                stat["first_seen_at"],
                stat["last_seen_at"],
                json.dumps(stat["articles"][:8], ensure_ascii=False),
                now,
                now,
            ),
        )

    conn.commit()
    conn.close()
    return len(stats)
