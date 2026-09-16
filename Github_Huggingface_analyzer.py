import json
from datetime import datetime

from summarizer import MODEL, extract_json, get_client


def fallback_platform_analysis(item, error=None):
    description = item.get("description") or "No README or model card content was available."
    note = "AI analysis was not available."
    if error:
        note = f"{note} Error: {error}"

    analysis = {
        "what_it_does": description,
        "best_for": "Readers who want a quick overview of this repository or model.",
        "analysis_note": note,
    }

    return {
        "ai_summary": analysis["what_it_does"],
        "usage_guide": "",
        "target_users": analysis["best_for"],
        "popularity_reason": "",
        "quickstart": "",
        "ai_analysis": analysis,
        "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def analyze_platform_item(item):
    platform = item.get("platform", "")
    name = item.get("name", "")
    url = item.get("url", "")
    description = item.get("description", "")
    category = item.get("category", "")
    tags = ", ".join(item.get("tags", [])[:12])
    metrics = json.dumps(item.get("metrics", {}), ensure_ascii=False)
    source_text = item.get("analysis_source", "")

    prompt = f"""
You are analyzing a popular GitHub repository or Hugging Face model for an AI trend dashboard.
Return only valid JSON. Do not use Markdown.
Write all user-facing values in Traditional Chinese.
Keep every answer concise.

Repository/model metadata:
- platform: {platform}
- name: {name}
- url: {url}
- description: {description}
- category/language/task: {category}
- tags: {tags}
- metrics: {metrics}

README or model card excerpt:
{source_text}

Required JSON schema:
{{
  "what_it_does": "1 to 2 short sentences explaining what this project/model does.",
  "best_for": "1 short sentence explaining who should care about it."
}}

Rules:
- Do not include installation steps.
- Do not explain why it is popular.
"""

    try:
        response = get_client().responses.create(
            model=MODEL,
            input=prompt,
        )
        data = extract_json(response.output_text)
    except Exception as error:
        return fallback_platform_analysis(item, error)

    analysis = {
        "what_it_does": str(data.get("what_it_does") or "").strip(),
        "best_for": str(data.get("best_for") or "").strip(),
    }

    if not analysis["what_it_does"]:
        analysis["what_it_does"] = description
    if not analysis["best_for"]:
        analysis["best_for"] = "想快速理解這個熱門專案或模型的讀者。"

    return {
        "ai_summary": analysis["what_it_does"],
        "usage_guide": "",
        "target_users": analysis["best_for"],
        "popularity_reason": "",
        "quickstart": "",
        "ai_analysis": analysis,
        "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
