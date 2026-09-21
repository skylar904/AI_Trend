import hashlib
import html
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from trend_config import AI_KEYWORDS


TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
}


def strip_html(value):
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return normalize_whitespace(text)


def normalize_whitespace(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_url(url):
    raw_url = str(url or "").strip()
    if not raw_url:
        return ""

    parsed = urlparse(raw_url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
    ]
    normalized = parsed._replace(
        scheme=parsed.scheme.lower() or "https",
        netloc=parsed.netloc.lower(),
        query=urlencode(query),
        fragment="",
    )
    return urlunparse(normalized).rstrip("/")


def normalize_title(title):
    text = normalize_whitespace(title).lower()
    text = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", text)
    return normalize_whitespace(text)


def article_fingerprint(article):
    url = normalize_url(article.get("link", ""))
    if url:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    title = normalize_title(article.get("title", ""))
    source = normalize_whitespace(article.get("source", "")).lower()
    return hashlib.sha256(f"{source}:{title}".encode("utf-8")).hexdigest()


def clean_article(article):
    cleaned = dict(article)
    cleaned["title"] = normalize_whitespace(article.get("title", ""))
    cleaned["link"] = normalize_url(article.get("link", ""))
    cleaned["summary"] = strip_html(article.get("summary", ""))
    cleaned["published"] = normalize_whitespace(article.get("published", ""))
    cleaned["source"] = normalize_whitespace(article.get("source", ""))
    cleaned["category"] = normalize_whitespace(article.get("category", ""))
    cleaned["fingerprint"] = article_fingerprint(cleaned)
    return cleaned


def is_probably_ai_related(article):
    text = " ".join(
        [
            article.get("title", ""),
            article.get("summary", ""),
            article.get("source", ""),
            article.get("category", ""),
        ]
    ).lower()

    for keyword in AI_KEYWORDS:
        normalized_keyword = normalize_whitespace(keyword).lower()
        if not normalized_keyword:
            continue

        # Short Latin keywords such as "ai" and "ml" must be whole words.
        # A plain substring check would incorrectly accept email, detail,
        # railway, html, and many other unrelated words.
        if re.fullmatch(r"[a-z0-9][a-z0-9 ._+\-/]*", normalized_keyword):
            parts = [part for part in re.split(r"[\s_\-/]+", normalized_keyword) if part]
            pattern = r"[\s_\-/]+".join(re.escape(part) for part in parts)
            if re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", text):
                return True
            continue

        if normalized_keyword in text:
            return True

    return False


def normalize_topic_key(term):
    """Return a stable comparison key without changing the display label."""

    normalized = normalize_whitespace(term).casefold()
    normalized = re.sub(r"[\s_\-\u2010-\u2015]+", "", normalized)
    return normalized.strip(".,:;!?()[]{}\"'")


def dedupe_articles(articles):
    seen = set()
    unique = []

    for article in articles:
        cleaned = clean_article(article)
        key = cleaned["fingerprint"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(cleaned)

    return unique
