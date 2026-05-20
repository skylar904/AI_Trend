import json
import sqlite3
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse


BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "articles.db"
PUBLIC_DIR = BASE_DIR / "public"
INDEX_PATH = PUBLIC_DIR / "index.html"

app = FastAPI(title="AI Trend API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row):
    return {key: row[key] for key in row.keys()}


def parse_json(value, fallback=None):
    if fallback is None:
        fallback = {}
    try:
        return json.loads(value) if value else fallback
    except json.JSONDecodeError:
        return fallback


def table_exists(conn, table_name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def get_article_entities(conn, article_ids):
    if not article_ids or not table_exists(conn, "entities"):
        return {article_id: [] for article_id in article_ids}

    placeholders = ",".join(["?"] * len(article_ids))
    rows = conn.execute(
        f"""
        SELECT ae.article_id, e.id, e.canonical_name, e.entity_type,
               ae.confidence, ae.evidence
        FROM article_entities ae
        JOIN entities e ON e.id = ae.entity_id
        WHERE ae.article_id IN ({placeholders})
        ORDER BY ae.confidence DESC, e.canonical_name
        """,
        article_ids,
    ).fetchall()

    grouped = {article_id: [] for article_id in article_ids}
    for row in rows:
        grouped[row["article_id"]].append(row_to_dict(row))
    return grouped


def attach_article_metadata(conn, articles):
    article_ids = [article["id"] for article in articles]
    entity_map = get_article_entities(conn, article_ids)

    for article in articles:
        article["entities"] = entity_map.get(article["id"], [])
        article["trend_components"] = parse_json(article.get("trend_components"), {})

    return articles


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/stats")
def get_stats():
    with connect_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        sources = conn.execute(
            "SELECT source, COUNT(*) AS count FROM articles GROUP BY source ORDER BY source"
        ).fetchall()
        categories = conn.execute(
            "SELECT category, COUNT(*) AS count FROM articles GROUP BY category ORDER BY category"
        ).fetchall()
        latest = conn.execute("SELECT MAX(created_at) AS latest_created FROM articles").fetchone()

    return {
        "total": total,
        "sources": [row_to_dict(row) for row in sources],
        "categories": [row_to_dict(row) for row in categories],
        "latest_created": latest["latest_created"],
    }


@app.get("/api/articles")
def get_articles(
    source: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
):
    where = []
    values = []

    if source:
        where.append("source = ?")
        values.append(source)

    if category:
        where.append("category = ?")
        values.append(category)

    if q:
        where.append("(title LIKE ? OR summary LIKE ? OR ai_summary LIKE ?)")
        values.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

    sql = """
        SELECT id, title, link, source, category, published, created_at,
               relevance_score, importance_score, trend_score,
               trend_reason, trend_components,
               substr(COALESCE(ai_summary, summary, ''), 1, 280) AS preview
        FROM articles
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC, id DESC"

    with connect_db() as conn:
        rows = conn.execute(sql, values).fetchall()
        articles = [row_to_dict(row) for row in rows]
        articles = attach_article_metadata(conn, articles)

    return articles


@app.get("/api/articles/{article_id}")
def get_article(article_id: int):
    with connect_db() as conn:
        row = conn.execute(
            """
            SELECT id, title, link, source, category, published, created_at,
                   summary, ai_summary, relevance_score, importance_score,
                   trend_score, trend_reason, trend_components
            FROM articles
            WHERE id = ?
            """,
            (article_id,),
        ).fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail="Article not found")

        article = row_to_dict(row)
        article = attach_article_metadata(conn, [article])[0]

    return article


@app.get("/api/entities")
def get_entities():
    with connect_db() as conn:
        if not table_exists(conn, "entities"):
            return []
        rows = conn.execute(
            """
            SELECT id, canonical_name, entity_type, aliases, mention_count,
                   trend_score, first_seen_at, last_seen_at
            FROM entities
            ORDER BY trend_score DESC, mention_count DESC, canonical_name
            LIMIT 50
            """
        ).fetchall()

    entities = []
    for row in rows:
        entity = row_to_dict(row)
        entity["aliases"] = parse_json(entity.get("aliases"), [])
        entities.append(entity)
    return entities


@app.get("/api/entities/{entity_id}")
def get_entity(entity_id: int):
    with connect_db() as conn:
        if not table_exists(conn, "entities"):
            raise HTTPException(status_code=404, detail="Entity not found")

        entity_row = conn.execute(
            """
            SELECT id, canonical_name, entity_type, aliases, mention_count,
                   trend_score, first_seen_at, last_seen_at
            FROM entities
            WHERE id = ?
            """,
            (entity_id,),
        ).fetchone()
        if entity_row is None:
            raise HTTPException(status_code=404, detail="Entity not found")

        article_rows = conn.execute(
            """
            SELECT a.id, a.title, a.link, a.source, a.category, a.published,
                   a.created_at, a.trend_score, ae.confidence, ae.evidence
            FROM article_entities ae
            JOIN articles a ON a.id = ae.article_id
            WHERE ae.entity_id = ?
            ORDER BY a.trend_score DESC, a.created_at DESC
            LIMIT 20
            """,
            (entity_id,),
        ).fetchall()

    entity = row_to_dict(entity_row)
    entity["aliases"] = parse_json(entity.get("aliases"), [])
    entity["articles"] = [row_to_dict(row) for row in article_rows]
    return entity


@app.get("/api/trends/top")
def get_top_trends(limit: Annotated[int, Query(ge=1, le=50)] = 10):
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT id, title, link, source, category, published, created_at,
                   relevance_score, importance_score, trend_score,
                   trend_reason, trend_components,
                   substr(COALESCE(ai_summary, summary, ''), 1, 220) AS preview
            FROM articles
            ORDER BY trend_score DESC, created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        articles = [row_to_dict(row) for row in rows]
        articles = attach_article_metadata(conn, articles)

    return articles


@app.get("/", include_in_schema=False)
def serve_index():
    if INDEX_PATH.is_file():
        return FileResponse(INDEX_PATH)
    raise HTTPException(status_code=404, detail="Frontend build not found")


@app.get("/{path:path}", include_in_schema=False)
def serve_spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")

    static_file = PUBLIC_DIR / path
    if static_file.is_file():
        return FileResponse(static_file)

    if INDEX_PATH.is_file():
        return FileResponse(INDEX_PATH)

    raise HTTPException(status_code=404, detail="Frontend build not found")
