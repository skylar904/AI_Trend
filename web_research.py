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


SEARCH_GUIDES = {
    "github": (
        ["github.com"],
        "只尋找 GitHub repository、repository 內的檔案或 GitHub Skill。不要回傳課程、文章或產品網站。",
    ),
    "huggingface": (
        ["huggingface.co"],
        "只尋找 Hugging Face model 或 dataset 頁面。不要回傳 Spaces、文章、課程或一般產品頁。",
    ),
    "paper": (
        None,
        "只尋找真正的學術論文、會議論文、期刊論文或預印本。優先找 DOI、正式論文頁或可下載 PDF；不要回傳新聞、部落格、課程或一般產品頁。",
    ),
}


def web_research(query, source_kind):
    query = str(query or "").strip()
    if not query:
        raise ValueError("query is required")
    if source_kind not in SEARCH_GUIDES:
        raise ValueError("source_kind must be github, huggingface or paper")

    allowed_domains, guide = SEARCH_GUIDES[source_kind]
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
            "你是技術資源候選發現工具。請即時搜尋網路，但嚴格遵守資源範圍。"
            f"{guide} 搜尋結果只是候選，後續程式還會深入驗證；不要臆測不存在的名稱或網址。"
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
        "source_kind": source_kind,
        "sources": sources,
    }
