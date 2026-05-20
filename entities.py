import json
import re

from trend_config import ENTITY_TYPES


ENTITY_ALIASES = {
    "anthropic claude": "Claude",
    "claude opus": "Claude",
    "claude sonnet": "Claude",
    "claude": "Claude",
    "chat gpt": "ChatGPT",
    "chatgpt app": "ChatGPT",
    "chatgpt": "ChatGPT",
    "cursor ai": "Cursor",
    "anysphere cursor": "Cursor",
    "cursor": "Cursor",
    "gemini 3 5 flash": "Gemini",
    "gemini 3.5 flash": "Gemini",
    "gemini flash": "Gemini",
    "google gemini": "Gemini",
    "gemini": "Gemini",
    "gpt 5": "GPT",
    "gpt-5": "GPT",
    "gpt 4": "GPT",
    "gpt-4": "GPT",
    "huggingface": "Hugging Face",
    "hugging face": "Hugging Face",
    "open ai": "OpenAI",
    "openai": "OpenAI",
    "perplexity ai": "Perplexity",
    "perplexity": "Perplexity",
}


def normalize_entity_key(name):
    text = str(name or "").strip().lower()
    text = re.sub(r"[^\w\s.\-]", " ", text)
    text = re.sub(r"[-_]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def title_case_entity(name):
    raw = str(name or "").strip()
    if not raw:
        return ""

    known_upper = {"ai", "api", "gpt", "llm", "rag", "gpu", "tpu", "ml"}
    words = []
    for word in re.split(r"\s+", raw):
        if word.lower() in known_upper:
            words.append(word.upper())
        elif word.isupper() and len(word) <= 5:
            words.append(word)
        else:
            words.append(word[:1].upper() + word[1:])
    return " ".join(words)


def canonicalize_entity_name(name):
    key = normalize_entity_key(name)
    if not key:
        return ""
    return ENTITY_ALIASES.get(key, title_case_entity(key))


def normalize_entity_type(entity_type):
    value = str(entity_type or "other").strip().lower()
    return value if value in ENTITY_TYPES else "other"


def parse_aliases(value):
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return parse_aliases(data)


def serialize_aliases(aliases):
    unique = []
    seen = set()
    for alias in aliases:
        clean = str(alias or "").strip()
        key = normalize_entity_key(clean)
        if clean and key not in seen:
            seen.add(key)
            unique.append(clean)
    return json.dumps(unique, ensure_ascii=False)


def normalize_extracted_entities(entities):
    normalized = []
    seen = set()

    for entity in entities or []:
        if not isinstance(entity, dict):
            continue

        name = str(entity.get("name") or entity.get("canonical_name") or "").strip()
        canonical = canonicalize_entity_name(entity.get("canonical_name") or name)
        if not canonical:
            continue

        key = normalize_entity_key(canonical)
        if key in seen:
            continue
        seen.add(key)

        try:
            confidence = float(entity.get("confidence", 0.75))
        except (TypeError, ValueError):
            confidence = 0.75

        normalized.append(
            {
                "name": name or canonical,
                "canonical_name": canonical,
                "entity_type": normalize_entity_type(entity.get("type") or entity.get("entity_type")),
                "confidence": max(0, min(1, confidence)),
                "evidence": str(entity.get("evidence") or "").strip(),
            }
        )

    return normalized
