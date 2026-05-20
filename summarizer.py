import os
import json
import re
from openai import OpenAI
from dotenv import load_dotenv

from cleaning import is_probably_ai_related
from entities import normalize_extracted_entities
from trend_config import CATEGORIES, ENTITY_TYPES

load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-nano")
client = None


def get_client():
    global client

    if client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        client = OpenAI(api_key=api_key)

    return client


def extract_json(text):
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()

    match = re.search(r"\{.*\}", raw, flags=re.S)
    if match:
        raw = match.group(0)

    return json.loads(raw)


def clamp_score(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, number))


def fallback_analysis(article, error=None):
    related = is_probably_ai_related(article)
    summary = article.get("summary") or "暫時使用 RSS 原始摘要，待下一次巡邏重新產生 AI 摘要。"
    reason = "OpenAI 分析失敗，已使用關鍵字規則保守判斷。"
    if error:
        reason = f"{reason} 錯誤：{error}"

    return {
        "should_include": related,
        "category": article.get("category") or "其他AI趨勢",
        "relevance_score": 70 if related else 20,
        "importance_score": 45 if related else 10,
        "reason": reason,
        "summary": summary,
        "entities": [],
    }


def analyze_article(article):
    """
    Analyze one article for the trend pipeline.
    Returns JSON-like metadata plus a Traditional Chinese summary.
    """

    title = article.get("title", "")
    source = article.get("source", "")
    category = article.get("category", "")
    summary = article.get("summary", "")
    link = article.get("link", "")
    categories = "、".join(CATEGORIES)
    entity_types = "、".join(ENTITY_TYPES)

    prompt = f"""
你是一個 AI 科技趨勢情報系統的資料分析器。

請根據文章資訊判斷它是否值得收錄到「AI 科技趨勢 / AI 工具」資料庫。
只輸出 JSON，不要 Markdown，不要解釋 JSON 以外的內容。

可用分類：
{categories}

判斷標準：
- relevance_score：0~100，文章和 AI 科技趨勢、AI 工具、模型、研究、AI 基礎設施、AI 產業的相關程度。
- importance_score：0~100，對學生、工程師、研究所推甄作品、AI 工具觀察的值得追蹤程度。
- should_include：只有 relevance_score >= 60 且不是純廣告/低品質內容才是 true。
- category：必須從可用分類中選一個。
- reason：用一句繁體中文說明為什麼收錄或略過。
- summary：若 should_include 為 true，請輸出下列四段 Markdown；若 false，仍用 1 句話說明略過原因。
- entities：抽出文章提到的 AI 工具、公司、模型、框架、產品。若沒有明確提到，回傳空陣列。

entity type 只能使用：
{entity_types}

entity 抽取規則：
- name：文章中的原始名稱。
- canonical_name：合併後的標準名稱，例如「Google Gemini」「Gemini Flash」可標準化成「Gemini」。
- type：tool / company / model / framework / product / other 其中之一。
- confidence：0~1，越高代表越確定。
- evidence：文章中支持這個 entity 的短句或原因。
- 不要把「AI」「machine learning」「tool」這種泛稱當作 entity。

summary 格式：
### 中文摘要
2~4 句話說明文章重點。

### 為什麼重要
2~3 句話說明趨勢意義。

### 適合誰關注
列出適合關注的人。

### 對使用者的建議
用白話說明需不需要追，建議先看什麼。

文章標題：
{title}

來源：
{source}

原始分類：
{category}

RSS 原始摘要：
{summary}

連結：
{link}

請輸出 JSON schema：
{{
  "should_include": true,
  "category": "AI工具",
  "relevance_score": 80,
  "importance_score": 70,
  "reason": "一句話原因",
  "summary": "Markdown 摘要",
  "entities": [
    {{
      "name": "Cursor AI",
      "canonical_name": "Cursor",
      "type": "tool",
      "confidence": 0.9,
      "evidence": "文章標題或摘要提到 Cursor AI"
    }}
  ]
}}
"""

    try:
        response = get_client().responses.create(
            model=MODEL,
            input=prompt,
        )
        data = extract_json(response.output_text)
    except Exception as error:
        return fallback_analysis(article, error)

    category_value = data.get("category") or "其他AI趨勢"
    if category_value not in CATEGORIES:
        category_value = "其他AI趨勢"

    return {
        "should_include": bool(data.get("should_include")),
        "category": category_value,
        "relevance_score": clamp_score(data.get("relevance_score")),
        "importance_score": clamp_score(data.get("importance_score")),
        "reason": str(data.get("reason") or "").strip(),
        "summary": str(data.get("summary") or "").strip(),
        "entities": normalize_extracted_entities(data.get("entities", [])),
    }


def summarize_article(article):
    """
    將單篇文章整理成中文科技情報摘要。
    """

    title = article.get("title", "")
    source = article.get("source", "")
    category = article.get("category", "")
    summary = article.get("summary", "")
    link = article.get("link", "")

    prompt = f"""
你是一個給資工/電子相關學生看的 AI 科技情報整理員。

請根據下面文章資訊，用繁體中文整理成簡潔但有用的情報。

文章標題：
{title}

來源：
{source}

分類：
{category}

RSS 原始摘要：
{summary}

連結：
{link}

請輸出格式如下：

### 中文摘要
用 2~4 句話說明這篇文章/工具/消息在講什麼。

### 為什麼重要
用 2~3 句話說明它可能代表什麼趨勢，或為什麼值得注意。

### 適合誰關注
列出適合關注的人，例如 AI 工具使用者、軟體工程師、研究生、資工學生、創業者等。

### 對鴨妤的建議
請用很白話的方式說明：
這個東西需不需要追？
如果值得追，建議先看什麼？
如果不重要，也請直接說可以略過。
"""

    response = get_client().responses.create(
        model=MODEL,
        input=prompt
    )

    return response.output_text
