import json
import os
import re
from datetime import datetime

from database import (
    get_daily_topics,
    get_topic_stats,
    rebuild_topic_stats,
    save_daily_topics,
)
from summarizer import extract_json, get_client


TOPIC_MODEL = os.getenv("TOPIC_MODEL", os.getenv("OPENAI_MODEL", "gpt-5.4-nano"))
TOPIC_BATCH_SIZE = int(os.getenv("TOPIC_BATCH_SIZE", os.getenv("MAX_TOPIC_INPUT_ARTICLES", "120")))
BATCH_TOPIC_CANDIDATES = int(os.getenv("BATCH_TOPIC_CANDIDATES", "10"))
FINAL_TOPIC_LIMIT = int(os.getenv("FINAL_TOPIC_LIMIT", "5"))
DISPLAY_EVIDENCE_ARTICLES = int(os.getenv("DISPLAY_EVIDENCE_ARTICLES", "10"))
MAX_TOPIC_SUMMARY_CHARS = int(os.getenv("MAX_TOPIC_SUMMARY_CHARS", "520"))


def normalize_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def clamp_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, number)


def clamp_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, number)


def truncate_text(value, limit):
    text = normalize_text(value)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def topic_date_today():
    return datetime.now().strftime("%Y-%m-%d")


def article_packet(article):
    return {
        "id": article.get("id"),
        "title": truncate_text(article.get("title", ""), 180),
        "source": article.get("source", ""),
        "category": article.get("category", ""),
        "summary": truncate_text(
            article.get("ai_summary") or article.get("summary") or "",
            MAX_TOPIC_SUMMARY_CHARS,
        ),
        "trend_score": clamp_float(article.get("trend_score", 0)),
    }


def build_topic_prompt(articles, topic_limit=BATCH_TOPIC_CANDIDATES):
    payload = [article_packet(article) for article in articles]
    return f"""
你是一個 AI 趨勢情報系統的每日話題編輯器。

請根據這批今天新增文章，找出最多 {topic_limit} 個「本日話題候選」。

重要規則：
- 只能根據下面文章中實際出現的資訊判斷，不要創造文章中沒有的話題。
- 優先選具體話題：模型、產品、功能、事件、研究方法、開源專案、工具、政策或產業事件。
- 大品牌或泛稱可以作為脈絡，但不要只輸出 OpenAI、Google、ChatGPT、AI、LLM 這種沒有細節的詞，除非今天文章真的沒有更具體主題。
- 可以合併同義詞或大小寫變體，例如 GPT6 Astra / GPT-6 Astra 可合併。
- 不要輸出 mention_count、article_count、source_count，這些統計數字會由 Python 根據 evidence_articles 計算。
- evidence_articles 的 id 必須來自「這批今天新增文章」中的 id，不要使用不存在的文章 id。
- reason 用一句繁體中文說明為什麼這個話題今天值得注意。
- evidence_articles 放入支持這個話題的文章，最多 5 篇。

請只輸出 JSON，不要 Markdown，不要解釋 JSON 以外的內容。

JSON schema：
{{
  "topics": [
    {{
      "term": "具體話題名稱",
      "reason": "一句繁體中文原因",
      "evidence_articles": [
        {{
          "id": 123,
          "evidence": "為什麼這篇文章支持該話題"
        }}
      ]
    }}
  ]
}}

這批今天新增文章：
{json.dumps(payload, ensure_ascii=False)}
""".strip()


def topic_variants(term):
    normalized = normalize_text(term).lower()
    variants = {normalized}
    if "-" in normalized:
        variants.add(normalized.replace("-", " "))
        variants.add(normalized.replace("-", ""))
    if " " in normalized:
        variants.add(normalized.replace(" ", "-"))
        variants.add(normalized.replace(" ", ""))
    variants.update({variant.replace("-", "").replace(" ", "") for variant in list(variants)})
    return [variant for variant in variants if len(variant) >= 3]


def topic_key(term):
    normalized = normalize_text(term).lower()
    normalized = re.sub(r"[_\-]+", " ", normalized)
    normalized = re.sub(r"[^\w\s\u4e00-\u9fff]", "", normalized)
    return normalize_text(normalized).replace(" ", "")


def count_topic_mentions(term, evidence_articles):
    variants = topic_variants(term)
    if not variants:
        return len(evidence_articles)

    total = 0
    for article in evidence_articles:
        text = normalize_text(
            " ".join(
                [
                    article.get("title", ""),
                    article.get("summary", ""),
                    article.get("evidence", ""),
                ]
            )
        ).lower()
        hits = sum(text.count(variant) for variant in variants)
        total += hits or 1
    return total


def calculate_topic_score(term, evidence_articles):
    article_count = len(evidence_articles)
    source_count = len(
        {article.get("source") for article in evidence_articles if article.get("source")}
    )
    mention_count = count_topic_mentions(term, evidence_articles)
    trend_score_sum = sum(clamp_float(article.get("trend_score")) for article in evidence_articles)
    topic_score = round(
        mention_count * 10 + article_count * 4 + source_count * 3 + trend_score_sum * 0.1,
        2,
    )
    return mention_count, article_count, source_count, round(trend_score_sum, 2), topic_score


def normalize_evidence_articles(topic, article_lookup=None, limit=5):
    article_lookup = article_lookup or {}
    articles = topic.get("evidence_articles") or topic.get("articles") or []
    normalized = []
    seen = set()
    for article in articles:
        if not isinstance(article, dict):
            continue
        article_id = article.get("id")
        lookup_key = str(article_id)
        if article_lookup and lookup_key not in article_lookup:
            continue
        if lookup_key in seen:
            continue
        seen.add(lookup_key)
        source_article = article_lookup.get(str(article_id), {})
        normalized.append(
            {
                "id": article_id,
                "title": normalize_text(article.get("title") or source_article.get("title", "")),
                "source": normalize_text(article.get("source") or source_article.get("source", "")),
                "evidence": normalize_text(article.get("evidence", "")),
                "summary": normalize_text(source_article.get("summary", "")),
                "trend_score": clamp_float(
                    article.get("trend_score", source_article.get("trend_score", 0))
                ),
            }
        )
    return normalized[:limit]


def normalize_ai_topics(data, article_lookup=None, limit=FINAL_TOPIC_LIMIT):
    topics = data.get("topics", []) if isinstance(data, dict) else []
    normalized = []
    seen = set()

    for topic in topics:
        if not isinstance(topic, dict):
            continue

        term = normalize_text(topic.get("term", "")).strip(".,:;!?()[]{}\"'")
        key = term.lower()
        if not term or key in seen:
            continue
        seen.add(key)

        evidence_articles = normalize_evidence_articles(topic, article_lookup)
        mention_count, article_count, source_count, trend_score_sum, topic_score = calculate_topic_score(
            term,
            evidence_articles,
        )
        normalized.append(
            {
                "term": term,
                "name": term,
                "mention_count": mention_count,
                "article_count": article_count,
                "source_count": source_count,
                "trend_score_sum": trend_score_sum,
                "topic_score": topic_score,
                "weekly_signal_score": topic_score,
                "reason": normalize_text(topic.get("reason", "")),
                "articles": evidence_articles,
                "sources": sorted(
                    {article["source"] for article in evidence_articles if article.get("source")}
                ),
            }
        )

    normalized.sort(
        key=lambda item: (
            item["topic_score"],
            item["mention_count"],
            item["article_count"],
            item["source_count"],
        ),
        reverse=True,
    )
    return normalized[:limit]


def attach_share(topics):
    max_score = max([float(topic.get("topic_score") or 0) for topic in topics] or [1])
    if max_score <= 0:
        max_score = 1
    for topic in topics:
        topic["share"] = round(float(topic.get("topic_score") or 0) / max_score * 100, 2)
    return topics


def prepare_articles(articles):
    prepared_articles = []
    for index, article in enumerate(articles, start=1):
        prepared = dict(article)
        if prepared.get("id") is None:
            prepared["id"] = f"candidate-{index}"
        prepared_articles.append(prepared)
    return prepared_articles


def chunk_articles(articles, chunk_size):
    chunk_size = max(1, int(chunk_size or 1))
    for index in range(0, len(articles), chunk_size):
        yield articles[index : index + chunk_size]


def generate_batch_topics(batch_articles, article_lookup):
    prompt = build_topic_prompt(batch_articles)
    response = get_client().responses.create(
        model=TOPIC_MODEL,
        input=prompt,
    )
    return normalize_ai_topics(
        extract_json(response.output_text),
        article_lookup,
        limit=BATCH_TOPIC_CANDIDATES,
    )


def article_matches_topic(term, article):
    variants = topic_variants(term)
    if not variants:
        return False
    text = normalize_text(
        " ".join(
            [
                article.get("title", ""),
                article.get("summary", ""),
                article.get("evidence", ""),
            ]
        )
    ).lower()
    compact_text = text.replace("-", "").replace(" ", "")
    return any(variant in text or variant in compact_text for variant in variants)


def merge_seed_articles(existing, seed_articles):
    merged = {str(article.get("id")): article for article in existing if article.get("id") is not None}
    for article in seed_articles:
        article_id = article.get("id")
        if article_id is None:
            continue
        merged.setdefault(str(article_id), article)
    return list(merged.values())


def build_topic_from_candidates(term, reason, seed_articles, article_lookup):
    matched_articles = [
        article for article in article_lookup.values() if article_matches_topic(term, article)
    ]
    matched_articles = merge_seed_articles(matched_articles, seed_articles)
    matched_articles.sort(key=lambda item: clamp_float(item.get("trend_score")), reverse=True)

    mention_count, article_count, source_count, trend_score_sum, topic_score = calculate_topic_score(
        term,
        matched_articles,
    )

    display_articles = []
    for article in matched_articles[:DISPLAY_EVIDENCE_ARTICLES]:
        display_articles.append(
            {
                **article,
                "evidence": article.get("evidence") or f"文章標題或摘要提到 {term}",
            }
        )

    return {
        "term": term,
        "name": term,
        "mention_count": mention_count,
        "article_count": article_count,
        "source_count": source_count,
        "trend_score_sum": trend_score_sum,
        "topic_score": topic_score,
        "weekly_signal_score": topic_score,
        "reason": reason,
        "articles": display_articles,
        "sources": sorted(
            {article["source"] for article in matched_articles if article.get("source")}
        ),
    }


def merge_topic_candidates(candidates, article_lookup):
    grouped = {}
    for topic in candidates:
        term = normalize_text(topic.get("term", ""))
        key = topic_key(term)
        if not term or not key:
            continue

        group = grouped.setdefault(
            key,
            {
                "term": term,
                "reason": normalize_text(topic.get("reason", "")),
                "seed_articles": [],
                "best_score": 0.0,
            },
        )
        score = clamp_float(topic.get("topic_score"))
        if score > group["best_score"]:
            group["term"] = term
            group["reason"] = normalize_text(topic.get("reason", "")) or group["reason"]
            group["best_score"] = score
        group["seed_articles"] = merge_seed_articles(
            group["seed_articles"],
            topic.get("articles", []),
        )

    merged = []
    for group in grouped.values():
        topic = build_topic_from_candidates(
            group["term"],
            group["reason"],
            group["seed_articles"],
            article_lookup,
        )
        if topic["article_count"] > 0:
            merged.append(topic)
    merged.sort(
        key=lambda item: (
            item["topic_score"],
            item["mention_count"],
            item["article_count"],
            item["source_count"],
        ),
        reverse=True,
    )
    return attach_share(merged[:FINAL_TOPIC_LIMIT])


def generate_daily_topics(articles):
    if not articles:
        return []

    prepared_articles = prepare_articles(articles)
    article_lookup = {
        str(article.get("id")): article_packet(article)
        for article in prepared_articles
        if article.get("id") is not None
    }

    candidates = []
    for batch in chunk_articles(prepared_articles, TOPIC_BATCH_SIZE):
        candidates.extend(generate_batch_topics(batch, article_lookup))

    return merge_topic_candidates(candidates, article_lookup)


def update_topic_rankings(articles, topic_date=None, dry_run=False):
    topic_date = topic_date or topic_date_today()
    topics = generate_daily_topics(articles)

    if dry_run:
        return topics

    save_daily_topics(topic_date, topics)
    rebuild_topic_stats()
    return topics


def refresh_topic_stats():
    return rebuild_topic_stats()


def get_topic_rankings(scope="all", limit=5, days=7):
    if scope == "today":
        return get_daily_topics(topic_date_today(), limit)
    if scope == "recent":
        return get_daily_topics(None, limit)
    return get_topic_stats(limit)
