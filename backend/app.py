import json
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from database import connect_db, init_db, table_exists
from project_advisor import advise_project
from topic_rankings import get_topic_rankings


app = FastAPI(title="AI Trend API")
init_db()

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


def row_to_dict(row):
    return dict(row)


def parse_json(value, fallback=None):
    if fallback is None:
        fallback = {}
    try:
        return json.loads(value) if value else fallback
    except json.JSONDecodeError:
        return fallback


def attach_article_metadata(conn, articles):
    for article in articles:
        article["trend_components"] = parse_json(article.get("trend_components"), {})
        article["trend_components"].pop("entity", None)

    return articles


def get_platform_items(platform, limit):
    with connect_db() as conn:
        if not table_exists(conn, "platform_items"):
            return []

        rows = conn.execute(
            """
            SELECT id, platform, item_id, name, url, description, `rank`, score,
                   primary_metric_name, primary_metric_value,
                   secondary_metric_name, secondary_metric_value,
                   category, tags, metrics, ai_summary, usage_guide, target_users,
                   popularity_reason, quickstart, ai_analysis, analyzed_at, fetched_at
            FROM platform_items
            WHERE platform = ?
            ORDER BY `rank` ASC, score DESC
            LIMIT ?
            """,
            (platform, limit),
        ).fetchall()

    items = [row_to_dict(row) for row in rows]
    for item in items:
        item["tags"] = parse_json(item.get("tags"), [])
        item["metrics"] = parse_json(item.get("metrics"), {})
        item["ai_analysis"] = parse_json(item.get("ai_analysis"), {})
    return items


def article_date_expression():
    return "substr(created_at, 1, 10)"


def append_article_filters(where, values, source=None, category=None, q=None):
    if source:
        where.append("source = ?")
        values.append(source)

    if category:
        where.append("category = ?")
        values.append(category)

    if q:
        where.append("(title LIKE ? OR summary LIKE ? OR ai_summary LIKE ?)")
        values.extend([f"%{q}%", f"%{q}%", f"%{q}%"])


def latest_article_date(conn, where, values):
    sql = f"SELECT MAX({article_date_expression()}) AS article_date FROM articles"
    if where:
        sql += " WHERE " + " AND ".join(where)
    row = conn.execute(sql, values).fetchone()
    return row["article_date"] if row and row["article_date"] else ""


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
    date: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
):
    where = []
    values = []

    with connect_db() as conn:
        append_article_filters(where, values, source, category, q)
        selected_date = date or latest_article_date(conn, where, values)
        if not selected_date:
            return []

        where.append(f"{article_date_expression()} = ?")
        values.append(selected_date)

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

        rows = conn.execute(sql, values).fetchall()
        articles = [row_to_dict(row) for row in rows]
        articles = attach_article_metadata(conn, articles)

    return articles


@app.get("/api/articles/dates")
def get_article_dates():
    with connect_db() as conn:
        rows = conn.execute(
            f"""
            SELECT {article_date_expression()} AS date, COUNT(*) AS count
            FROM articles
            WHERE created_at IS NOT NULL AND created_at != ''
            GROUP BY {article_date_expression()}
            ORDER BY date DESC
            """
        ).fetchall()

    return [row_to_dict(row) for row in rows if row["date"]]


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


@app.get("/api/dashboard/weekly-topics")
def get_weekly_topics(limit: Annotated[int, Query(ge=1, le=10)] = 5):
    return get_topic_rankings(scope="recent", limit=limit, days=7)


@app.get("/api/dashboard/topic-rankings")
def get_dashboard_topic_rankings(
    scope: Annotated[str, Query()] = "all",
    limit: Annotated[int, Query(ge=1, le=10)] = 5,
):
    if scope not in {"all", "today", "recent"}:
        raise HTTPException(status_code=400, detail="scope must be all, today, or recent")
    return get_topic_rankings(scope=scope, limit=limit, days=7)


@app.get("/api/platform/github/top")
def get_github_top(limit: Annotated[int, Query(ge=1, le=25)] = 10):
    return get_platform_items("github", limit)


@app.get("/api/platform/huggingface/top")
def get_huggingface_top(limit: Annotated[int, Query(ge=1, le=25)] = 10):
    return get_platform_items("huggingface", limit)


@app.get("/api/project-advisor")
def get_project_advice(q: Annotated[str, Query(min_length=2, max_length=300)]):
    try:
        return advise_project(q)
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
