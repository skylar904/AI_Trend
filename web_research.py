import os

from openai import OpenAI
from dotenv import load_dotenv


load_dotenv()

WEB_SEARCH_MODEL = os.getenv("WEB_SEARCH_MODEL", os.getenv("OPENAI_MODEL", "gpt-5.4-nano"))
client = None


def get_client():
    global client
    if client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        client = OpenAI(api_key=api_key)
    return client


def web_research(query, allowed_domains=None):
    query = str(query or "").strip()
    if not query:
        raise ValueError("query is required")

    tool = {"type": "web_search"}
    if allowed_domains:
        domains = [str(domain).strip() for domain in allowed_domains if str(domain).strip()]
        if domains:
            tool["filters"] = {"allowed_domains": domains[:20]}

    response = get_client().responses.create(
        model=WEB_SEARCH_MODEL,
        tools=[tool],
        include=["web_search_call.action.sources"],
        input=(
            "你是技術研究 Agent 的網路搜尋工具。請直接搜尋指定查詢，整理具體事實、"
            "可用資源、限制與重要差異。優先採用官方文件、原始專案、論文、產品頁或"
            "可信技術資料；不要臆測不存在的名稱、功能或網址。"
            f"\n\n搜尋查詢：{query}"
        ),
    )

    sources = []
    seen_urls = set()
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", "") != "web_search_call":
            continue
        action = getattr(item, "action", None)
        for source in getattr(action, "sources", []) or []:
            url = getattr(source, "url", "")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            sources.append(
                {
                    "title": getattr(source, "title", "") or url,
                    "url": url,
                }
            )

    return {
        "summary": response.output_text,
        "sources": sources,
    }
