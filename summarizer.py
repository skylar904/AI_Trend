import os
import json
import re
from openai import OpenAI
from dotenv import load_dotenv

from cleaning import is_probably_ai_related
from trend_config import CATEGORIES

load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-nano")
client = None


class OpenAIAnalysisRetryableError(RuntimeError):
    pass


CATEGORY_GUIDE = """
AI 工具與應用：
AI 產品、應用程式、使用方法、工具比較、工作流程、自動化應用、一般使用者或知識工作者可以直接採用的 AI 工具與功能。

AI Agent 與開發：
AI Agent 架構、multi-agent、tool calling、function calling、RAG、workflow、agent framework、開發者工具、部署、監控、evals、prompt engineering、AI coding assistant、軟體工程 agent。

AI 模型與研究：
新模型發布、模型架構、訓練方法、推論能力、多模態模型、embedding、benchmark、leaderboard、開放權重模型、模型效能比較、模型能力分析。

AI 產業與治理：
AI 公司策略、商業採用、投資併購、法規政策、AI Act、安全風險、資安、模型治理、對齊、安全評估、倫理、版權、資料隱私、政府或產業監管。

開源專案：
GitHub repo、開源 library、framework、SDK、developer repo、CLI 工具、可安裝或可 fork 的開源實作。若主要重點是某個開源專案本身，優先選這類。

研究論文：
arXiv、Semantic Scholar、OpenAlex、Papers with Code、學術會議、期刊、預印本、論文方法、實驗結果、citation、paper benchmark。若內容主要是一篇或多篇論文，優先選這類。

產業新聞：
科技媒體報導、產品市場動態、公司新聞、合作案、商業發布、人物訪談、使用者採用、非技術深度的新聞事件。若不是明確屬於治理、研究、開源或工具教學，才選這類。

其他AI趨勢：
與 AI 有關，但不適合放入以上分類，或資訊不足以明確判斷的內容。
""".strip()


CATEGORY_PRIORITY_RULES = """
分類優先原則：
- 如果主要內容是一篇論文、學術方法或實驗結果，選「研究論文」。
- 如果主要內容是模型發布、模型能力、benchmark、leaderboard 或模型比較，選「AI 模型與研究」。
- 如果主要內容是 Agent、RAG、tool calling、workflow、evals、AI coding 或開發框架，選「AI Agent 與開發」。
- 如果主要內容是 GitHub repo、開源 SDK、library 或可安裝工具，選「開源專案」。
- 如果主要內容是法規、安全、治理、政策、商業策略、投資或風險，選「AI 產業與治理」。
- 如果主要內容是一般使用者工具、AI 產品功能、工具比較或實際應用教學，選「AI 工具與應用」。
- 如果只是一般科技媒體新聞，且沒有更精準分類，選「產業新聞」。
- 如果仍無法判斷，選「其他AI趨勢」。
""".strip()


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


def is_retryable_openai_error(error):
    error_name = error.__class__.__name__.lower()
    message = str(error).lower()
    retryable_names = {
        "authenticationerror",
        "permissiondeniederror",
        "ratelimiterror",
        "apierror",
        "apiconnectionerror",
        "apitimestouterror",
    }
    retryable_terms = [
        "openai_api_key",
        "api key",
        "authentication",
        "permission",
        "quota",
        "billing",
        "credit",
        "rate limit",
        "rate_limit",
        "429",
        "401",
        "403",
        "timeout",
        "connection",
    ]
    return error_name in retryable_names or any(term in message for term in retryable_terms)


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

    prompt = f"""
你是一個 AI 科技趨勢情報系統的資料分析器。

請根據文章資訊判斷它是否值得收錄到「AI 科技趨勢 / AI 工具」資料庫。
只輸出 JSON，不要 Markdown，不要解釋 JSON 以外的內容。

可用分類：
{categories}

分類定義：
{CATEGORY_GUIDE}

{CATEGORY_PRIORITY_RULES}

判斷標準：
- relevance_score：0~100，文章和 AI 科技趨勢、AI 工具、模型、研究、AI 基礎設施、AI 產業的相關程度。
- importance_score：0~100，對學生、工程師、研究所推甄作品、AI 工具觀察的值得追蹤程度。
- should_include：只有 relevance_score >= 60 且不是純廣告/低品質內容才是 true。
- category：必須從可用分類中選一個。
- reason：用一句繁體中文說明為什麼收錄或略過。
- summary：若 should_include 為 true，請輸出下列四段 Markdown；若 false，仍用 1 句話說明略過原因。

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
  "category": "AI 工具與應用",
  "relevance_score": 80,
  "importance_score": 70,
  "reason": "一句話原因",
  "summary": "Markdown 摘要"
}}
"""

    try:
        response = get_client().responses.create(
            model=MODEL,
            input=prompt,
        )
        data = extract_json(response.output_text)
    except Exception as error:
        if is_retryable_openai_error(error):
            raise OpenAIAnalysisRetryableError(str(error)) from error
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

### 對使用者的建議
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
