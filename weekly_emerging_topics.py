import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta

from database import (
    DB_NAME,
    save_generated_search_queries,
    save_weekly_emerging_topics,
)
from summarizer import MODEL, extract_json, get_client


MAX_ARTICLES_FOR_EXTRACTION = 80
MAX_TERMS = 80
GENERIC_TERMS = {
    "ai",
    "artificial intelligence",
    "llm",
    "large language model",
    "model",
    "models",
    "tool",
    "tools",
    "agent",
    "agents",
    "research",
    "paper",
    "startup",
    "technology",
    "machine learning",
    "deep learning",
    "open source",
}
QUERY_PLATFORMS = {
    "github",
    "huggingface",
    "openalex",
    "semantic_scholar",
    "arxiv",
    "reddit",
}


def compact_text(value, limit=900):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def normalize_term(term):
    value = re.sub(r"\s+", " ", str(term or "")).strip()
    value = value.strip(".,:;!?()[]{}\"'")
    return value


def is_good_term(term):
    value = normalize_term(term)
    lowered = value.lower()
    if not value or lowered in GENERIC_TERMS:
        return False
    if len(value) < 3 or len(value) > 80:
        return False
    if len(value.split()) > 6:
        return False
    return bool(re.search(r"[A-Za-z0-9\u4e00-\u9fff]", value))


def load_recent_articles(days=7):
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, title, source, category, summary, ai_summary,
               trend_score, created_at
        FROM articles
        WHERE created_at >= ?
        ORDER BY trend_score DESC, created_at DESC
        LIMIT ?
        """,
        (since, MAX_ARTICLES_FOR_EXTRACTION),
    ).fetchall()

    article_ids = [row["id"] for row in rows]
    entity_map = defaultdict(list)
    if article_ids:
        placeholders = ",".join(["?"] * len(article_ids))
        entity_rows = conn.execute(
            f"""
            SELECT ae.article_id, e.canonical_name
            FROM article_entities ae
            JOIN entities e ON e.id = ae.entity_id
            WHERE ae.article_id IN ({placeholders})
            """,
            article_ids,
        ).fetchall()
        for row in entity_rows:
            entity_map[row["article_id"]].append(row["canonical_name"])

    conn.close()

    articles = []
    for row in rows:
        article = dict(row)
        article["entities"] = entity_map.get(row["id"], [])
        articles.append(article)
    return articles


def article_text(article):
    return " ".join(
        [
            article.get("title", ""),
            article.get("summary", ""),
            article.get("ai_summary", ""),
            " ".join(article.get("entities", [])),
        ]
    )


def fallback_terms(articles):
    terms = []
    seen = set()
    for article in articles:
        for entity in article.get("entities", []):
            term = normalize_term(entity)
            key = term.lower()
            if is_good_term(term) and key not in seen:
                seen.add(key)
                terms.append({"term": term, "signal_type": "entity"})
        for match in re.findall(r"\b[A-Z][A-Za-z0-9.+-]*(?:\s+[A-Z][A-Za-z0-9.+-]*){0,3}\b", article.get("title", "")):
            term = normalize_term(match)
            key = term.lower()
            if is_good_term(term) and key not in seen:
                seen.add(key)
                terms.append({"term": term, "signal_type": "unknown"})
    return terms[:MAX_TERMS]


def extract_candidate_terms(articles):
    if not articles:
        return []

    corpus = []
    for article in articles:
        corpus.append(
            {
                "id": article["id"],
                "title": article["title"],
                "source": article["source"],
                "category": article["category"],
                "trend_score": article["trend_score"],
                "entities": article.get("entities", []),
                "text": compact_text(article.get("ai_summary") or article.get("summary")),
            }
        )

    prompt = f"""
你是一個 AI 科技趨勢資料分析系統的候選議題抽取器。

任務：從近 7 天文章中抽出「可重複搜尋、可被統計的具名議題」。
不要判斷熱門程度，不要生成 query，只抽候選名詞。

可以抽的類型很廣：
人物、公司、產品、模型、工具、框架、開源專案、硬體、研究方向、技術概念、政策事件、社群流行詞、未知但看起來可追蹤的專有名詞。

不要抽太泛的詞：
AI、LLM、model、tool、agent、research、startup、technology、machine learning。

只輸出 JSON，不要 Markdown。

文章資料：
{json.dumps(corpus, ensure_ascii=False)}

請輸出：
{{
  "terms": [
    {{
      "term": "Claude Code",
      "signal_type": "product"
    }}
  ]
}}
"""

    try:
        response = get_client().responses.create(model=MODEL, input=prompt)
        data = extract_json(response.output_text)
        raw_terms = data.get("terms", [])
    except Exception:
        raw_terms = fallback_terms(articles)

    terms = []
    seen = set()
    for raw in raw_terms:
        term = normalize_term(raw.get("term", ""))
        key = term.lower()
        if not is_good_term(term) or key in seen:
            continue
        seen.add(key)
        terms.append(
            {
                "term": term,
                "signal_type": raw.get("signal_type", "unknown"),
            }
        )
    return terms[:MAX_TERMS]


def evidence_for(article, term):
    text = compact_text(article_text(article), 1600)
    lowered = text.lower()
    index = lowered.find(term.lower())
    if index < 0:
        return compact_text(article.get("title", ""), 220)
    start = max(0, index - 90)
    end = min(len(text), index + len(term) + 160)
    return text[start:end].strip()


def count_mentions(text, term):
    if not term:
        return 0
    return len(re.findall(re.escape(term), text, flags=re.I))


def rank_terms(articles, terms):
    ranked = []
    for item in terms:
        term = item["term"]
        articles_for_term = []
        mention_count = 0
        sources = set()
        trend_score_sum = 0.0

        for article in articles:
            text = article_text(article)
            mentions = count_mentions(text, term)
            if mentions <= 0:
                continue

            mention_count += mentions
            sources.add(article.get("source", ""))
            trend_score_sum += float(article.get("trend_score") or 0)
            articles_for_term.append(
                {
                    "id": article["id"],
                    "title": article.get("title", ""),
                    "source": article.get("source", ""),
                    "trend_score": float(article.get("trend_score") or 0),
                    "evidence": evidence_for(article, term),
                }
            )

        article_count = len(articles_for_term)
        source_count = len([source for source in sources if source])
        if article_count == 0:
            continue

        weekly_signal_score = round(
            mention_count * 2 + source_count * 8 + article_count * 5 + trend_score_sum,
            2,
        )
        ranked.append(
            {
                "term": term,
                "signal_type": item.get("signal_type", "unknown"),
                "mention_count": mention_count,
                "source_count": source_count,
                "article_count": article_count,
                "trend_score_sum": round(trend_score_sum, 2),
                "weekly_signal_score": weekly_signal_score,
                "articles": articles_for_term[:8],
            }
        )

    ranked.sort(key=lambda value: value["weekly_signal_score"], reverse=True)
    return ranked[:5]


def analyze_top_topic(topic):
    context = json.dumps(
        {
            "term": topic["term"],
            "metrics": {
                "mention_count": topic["mention_count"],
                "source_count": topic["source_count"],
                "article_count": topic["article_count"],
                "trend_score_sum": topic["trend_score_sum"],
            },
            "articles": topic.get("articles", []),
        },
        ensure_ascii=False,
    )

    prompt = f"""
你是一個 AI 科技趨勢分析器。

請根據這個 Top 5 議題的相關文章上下文，理解它是什麼，並產生下週應該加入 API 搜尋的 query。
只輸出 JSON，不要 Markdown。

限制：
- 不要為 RSS 產生 query，RSS 只會做命中加權。
- platform 只能是：github, huggingface, openalex, semantic_scholar, arxiv, reddit。
- query 不能太廣，不能只輸出 AI、LLM、agent、model。
- query 應該保留原始 term 或明確同義詞。

資料：
{context}

請輸出：
{{
  "analysis_summary": "用 1~2 句說明這個議題為什麼本週被關注",
  "queries": [
    {{
      "platform": "github",
      "query": "\\"Claude Code\\"",
      "reason": "追蹤相關開源專案"
    }}
  ]
}}
"""

    try:
        response = get_client().responses.create(model=MODEL, input=prompt)
        data = extract_json(response.output_text)
    except Exception:
        data = {
            "analysis_summary": "AI 深度分析暫時失敗，已保留本週統計結果。",
            "queries": [],
        }

    queries = []
    seen = set()
    for query in data.get("queries", []):
        platform = str(query.get("platform", "")).strip()
        query_text = str(query.get("query", "")).strip()
        key = (platform, query_text.lower())
        if platform not in QUERY_PLATFORMS or not query_text or key in seen:
            continue
        seen.add(key)
        queries.append(
            {
                "platform": platform,
                "query": query_text,
                "reason": str(query.get("reason", "")).strip(),
            }
        )

    return {
        "analysis_summary": str(data.get("analysis_summary", "")).strip(),
        "generated_queries": queries[:15],
    }


def update_weekly_emerging_topics(days=7, dry_run=False):
    articles = load_recent_articles(days)
    if not articles:
        print("近 7 天沒有文章，略過本週新興議題。")
        return []

    week_end = datetime.now().strftime("%Y-%m-%d")
    week_start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    terms = extract_candidate_terms(articles)
    top_topics = rank_terms(articles, terms)

    for topic in top_topics:
        analysis = analyze_top_topic(topic)
        topic.update(analysis)

    if dry_run:
        return top_topics

    save_weekly_emerging_topics(week_start, week_end, top_topics)
    for topic in top_topics:
        save_generated_search_queries(topic["term"], topic.get("generated_queries", []))

    return top_topics
