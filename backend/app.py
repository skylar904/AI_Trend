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
               substr(COALESCE(ai_summary, summary, ''), 1, 280) AS preview
        FROM articles
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC, id DESC"

    with connect_db() as conn:
        rows = conn.execute(sql, values).fetchall()

    return [row_to_dict(row) for row in rows]


@app.get("/api/articles/{article_id}")
def get_article(article_id: int):
    with connect_db() as conn:
        row = conn.execute(
            """
            SELECT id, title, link, source, category, published, created_at,
                   summary, ai_summary
            FROM articles
            WHERE id = ?
            """,
            (article_id,),
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Article not found")

    return row_to_dict(row)


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
