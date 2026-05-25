import json
from datetime import datetime

from summarizer import MODEL, extract_json, get_client


def fallback_platform_analysis(item, error=None):
    description = item.get("description") or "這個項目目前沒有足夠的 README 或 model card 可供分析。"
    reason = "AI 分析失敗，暫時使用平台原始描述。"
    if error:
        reason = f"{reason} 錯誤：{error}"

    return {
        "ai_summary": description,
        "usage_guide": "請先開啟原始連結查看 README、文件或 model card。",
        "target_users": "想快速理解熱門開源專案或模型的讀者。",
        "popularity_reason": reason,
        "quickstart": "開啟連結後，優先查看安裝方式、範例程式與使用限制。",
        "ai_analysis": {
            "what_it_is": description,
            "main_uses": [],
            "target_users": ["一般讀者"],
            "how_to_start": ["開啟原始連結查看文件"],
            "why_popular": reason,
            "caveats": [],
        },
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
你是一個 AI/開源工具排行榜的產品分析員。

請根據 GitHub README 或 Hugging Face model card，幫一般讀者快速理解這個熱門項目。
只輸出 JSON，不要 Markdown，不要 JSON 以外的文字。

請用繁體中文，保持具體、短句、可操作。

平台：{platform}
名稱：{name}
連結：{url}
平台描述：{description}
分類/任務：{category}
標籤：{tags}
平台指標：{metrics}

README 或 model card 內容：
{source_text}

請輸出 JSON schema：
{{
  "what_it_is": "用 2~3 句說明這是什麼",
  "main_uses": ["主要用途 1", "主要用途 2", "主要用途 3"],
  "target_users": ["適合使用者 1", "適合使用者 2"],
  "how_to_start": ["第一步", "第二步", "第三步"],
  "why_popular": "用 1~2 句說明為什麼它會上熱門",
  "caveats": ["使用限制或注意事項 1", "使用限制或注意事項 2"]
}}
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
        "what_it_is": str(data.get("what_it_is") or "").strip(),
        "main_uses": [str(value).strip() for value in data.get("main_uses", []) if value],
        "target_users": [str(value).strip() for value in data.get("target_users", []) if value],
        "how_to_start": [str(value).strip() for value in data.get("how_to_start", []) if value],
        "why_popular": str(data.get("why_popular") or "").strip(),
        "caveats": [str(value).strip() for value in data.get("caveats", []) if value],
    }

    return {
        "ai_summary": analysis["what_it_is"],
        "usage_guide": "\n".join(analysis["how_to_start"]),
        "target_users": "、".join(analysis["target_users"]),
        "popularity_reason": analysis["why_popular"],
        "quickstart": analysis["how_to_start"][0] if analysis["how_to_start"] else "",
        "ai_analysis": analysis,
        "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
