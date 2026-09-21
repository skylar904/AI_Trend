import json
import os
import re
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from summarizer import extract_json


load_dotenv()

GEMINI_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "45"))
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_SERVICE_UNAVAILABLE_MESSAGE = "API token不足，服務無法使用"
MIN_FINAL_RESULTS = 6
MAX_FINAL_RESULTS = 10


def gemini_error_response():
    return {"answer": GEMINI_SERVICE_UNAVAILABLE_MESSAGE, "sections": []}


def gemini_api_key():
    return str(os.getenv("GEMINI_API_KEY") or "").strip()


def gemini_model():
    return "gemini-3.1-flash-lite"


def gemini_consultant_prompt(query):
    return f"""
你是一位務實的 AI 專案技術顧問，請針對使用者需求即時搜尋網路並整理建議。

使用者需求：
{query}

重要規則：
- 請使用 Google Search 查資料，不要只靠模型記憶。
- 不要限制資料來源只能是 GitHub、Hugging Face 或論文。
- 可以納入論文、GitHub、Hugging Face、商業 API、技術文章、官方文件、模型架構、資料集與實作方法。
- 請像技術顧問一樣先理解問題，再拆解可行技術路線。
- 不要追問使用者；資訊不足時採用最合理的技術假設。
- 不要編造來源、模型名稱、數據或網址。
- 找不到現成模型時，請明確說明可行替代做法，例如資料收集、偵測、分割、embedding、metric learning、比對流程。
- 使用繁體中文。

請輸出嚴格 JSON，不要 Markdown code block，不要額外說明。格式如下：
{{
  "answer": "用 2 到 5 句總結整體建議。",
  "sections": [
    {{
      "title": "段落標題",
      "summary": "這段的簡短摘要",
      "items": [
        {{
          "title": "資源或方案名稱",
          "description": "它是什麼。",
          "how_it_works": "它怎麼運作或怎麼用在這個專案。",
          "why_relevant": "為什麼和使用者需求相關。",
          "limitations": "限制、風險或需要注意的地方。",
          "evidence_basis": "你根據什麼來源或查到的內容判斷。",
          "url": "可查證來源網址",
          "source_type": "web"
        }}
      ]
    }}
  ]
}}

source_type 可使用：github、huggingface_model、huggingface_dataset、paper、web。
請盡量提供 {MIN_FINAL_RESULTS} 到 {MAX_FINAL_RESULTS} 個互不重複且可查證的結果；只有確實找不到足夠合格來源時，才可少於 {MIN_FINAL_RESULTS} 個。
最多 4 個 sections，每個 section 最多 4 個 items。
""".strip()


def extract_gemini_text(response_data):
    texts = []
    for candidate in response_data.get("candidates", []) or []:
        content = candidate.get("content") or {}
        for part in content.get("parts", []) or []:
            text = part.get("text")
            if text:
                texts.append(text)
    return "\n".join(texts).strip()


def source_type_from_url(url):
    parsed = urlparse(str(url or ""))
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if "github.com" in host:
        return "github"
    if "huggingface.co" in host:
        if "/datasets/" in path:
            return "huggingface_dataset"
        return "huggingface_model"
    if any(domain in host for domain in ("arxiv.org", "doi.org", "ieee.org", "sciencedirect.com")):
        return "paper"
    return "web"


def extract_gemini_grounding_sources(response_data):
    sources = []
    seen_urls = set()
    for candidate in response_data.get("candidates", []) or []:
        metadata = candidate.get("groundingMetadata") or candidate.get("grounding_metadata") or {}
        chunks = metadata.get("groundingChunks") or metadata.get("grounding_chunks") or []
        for chunk in chunks:
            web = chunk.get("web") or {}
            url = str(web.get("uri") or web.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            sources.append(
                {
                    "title": str(web.get("title") or url).strip(),
                    "description": "Gemini Google Search grounding 取得的參考來源。",
                    "how_it_works": "作為本次顧問建議的查證背景來源。",
                    "why_relevant": "此來源與使用者提出的技術需求或可行方案相關。",
                    "limitations": "此項目是參考來源，不代表它本身一定是可直接使用的模型或套件。",
                    "evidence_basis": "Gemini grounding metadata",
                    "url": url,
                    "source_type": source_type_from_url(url),
                }
            )
    return sources[:MAX_FINAL_RESULTS]


def visible_advice_text(value, limit=1800):
    text = str(value or "").strip()
    text = re.sub(r"```(?:json)?", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def normalize_gemini_advice(raw_data, fallback_text="", grounding_sources=None):
    data = raw_data if isinstance(raw_data, dict) else {}
    grounding_sources = grounding_sources or []
    answer = visible_advice_text(data.get("answer") or fallback_text, 1800)
    sections = []
    total_items = 0
    seen_urls = set()

    for raw_section in data.get("sections", [])[:4]:
        if not isinstance(raw_section, dict):
            continue
        items = []
        for raw_item in raw_section.get("items", [])[:4]:
            if not isinstance(raw_item, dict) or total_items >= MAX_FINAL_RESULTS:
                continue
            url = str(raw_item.get("url") or "").strip()
            normalized_url = url.rstrip("/")
            if normalized_url and normalized_url in seen_urls:
                continue
            source_type = str(raw_item.get("source_type") or "").strip()
            if not source_type:
                source_type = source_type_from_url(url)
            if source_type not in {"github", "huggingface_model", "huggingface_dataset", "paper", "web"}:
                source_type = "web"
            items.append(
                {
                    "title": visible_advice_text(raw_item.get("title") or url or "參考資源", 160),
                    "description": visible_advice_text(raw_item.get("description"), 700),
                    "how_it_works": visible_advice_text(raw_item.get("how_it_works"), 1000),
                    "why_relevant": visible_advice_text(raw_item.get("why_relevant"), 700),
                    "limitations": visible_advice_text(raw_item.get("limitations"), 700),
                    "evidence_basis": visible_advice_text(raw_item.get("evidence_basis"), 300),
                    "url": url,
                    "source_type": source_type,
                }
            )
            if normalized_url:
                seen_urls.add(normalized_url)
            total_items += 1
        if items:
            sections.append(
                {
                    "title": visible_advice_text(raw_section.get("title") or "顧問建議", 80),
                    "summary": visible_advice_text(raw_section.get("summary"), 400),
                    "items": items,
                }
            )

    supplemental_sources = []
    for source in grounding_sources:
        if total_items >= MAX_FINAL_RESULTS:
            break
        url = str(source.get("url") or "").strip()
        normalized_url = url.rstrip("/")
        if not normalized_url or normalized_url in seen_urls:
            continue
        supplemental_sources.append(source)
        seen_urls.add(normalized_url)
        total_items += 1

    if supplemental_sources:
        sections.append(
            {
                "title": "搜尋查證來源",
                "summary": "以下是 Gemini Google Search grounding 回傳、且未與上述推薦重複的補充來源。這些來源用於查證，不一定都是可直接使用的模型、套件或 Skill。",
                "items": supplemental_sources,
            }
        )

    return {"answer": answer or GEMINI_SERVICE_UNAVAILABLE_MESSAGE, "sections": sections}


def call_gemini_grounded_advisor(query):
    api_key = gemini_api_key()
    if not api_key:
        return gemini_error_response()

    url = GEMINI_API_URL.format(model=quote(gemini_model(), safe=""))
    payload = {
        "contents": [{"role": "user", "parts": [{"text": gemini_consultant_prompt(query)}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.2, "topP": 0.9},
    }
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )

    try:
        with urlopen(request, timeout=GEMINI_TIMEOUT) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return gemini_error_response()

    text = extract_gemini_text(response_data)
    if not text:
        return gemini_error_response()

    grounding_sources = extract_gemini_grounding_sources(response_data)
    try:
        parsed = extract_json(text)
    except Exception:
        parsed = {}
    return normalize_gemini_advice(parsed, fallback_text=text, grounding_sources=grounding_sources)


def advise_project(user_query):
    query = str(user_query or "").strip()
    if not query:
        raise ValueError("query is required")
    return call_gemini_grounded_advisor(query)
