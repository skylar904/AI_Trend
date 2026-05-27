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
    tool = {"type": "web_search"}
    if allowed_domains:
        tool["filters"] = {"allowed_domains": allowed_domains}

    response = get_client().responses.create(
        model=WEB_SEARCH_MODEL,
        tools=[tool],
        include=["web_search_call.action.sources"],
        input=(
            "請搜尋以下主題，整理可用於 AI/軟體專案規劃的背景資料。"
            "請優先找官方文件、GitHub、論文、產品頁或可信技術文章。"
            f"\n\n主題：{query}"
        ),
    )

    sources = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", "") != "web_search_call":
            continue
        action = getattr(item, "action", None)
        for source in getattr(action, "sources", []) or []:
            sources.append(
                {
                    "title": getattr(source, "title", "") or getattr(source, "url", ""),
                    "url": getattr(source, "url", ""),
                }
            )

    return {
        "summary": response.output_text,
        "sources": sources,
    }
