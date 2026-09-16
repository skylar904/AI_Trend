import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from dotenv import load_dotenv
from openai import OpenAI

from summarizer import MODEL, extract_json
from web_research import web_research


load_dotenv()

REQUEST_TIMEOUT = 25
client = None


def get_client():
    global client
    if client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        client = OpenAI(api_key=api_key)
    return client


def request_json(url, params=None, headers=None):
    query = urlencode(params or {})
    request_url = f"{url}?{query}" if query else url
    request = Request(
        request_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "AI-Trend-Dashboard",
            **(headers or {}),
        },
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def request_text(url, params=None):
    query = urlencode(params or {})
    request_url = f"{url}?{query}" if query else url
    request = Request(
        request_url,
        headers={
            "Accept": "application/xml, text/xml",
            "User-Agent": "AI-Trend-Dashboard",
        },
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return response.read().decode("utf-8")


def analyze_request(user_query):
    prompt = f"""
你是一個 AI 專案顧問的搜尋策略產生器。
請判斷使用者輸入是專案描述，還是未知名詞。
然後產生用於 GitHub、Hugging Face、研究資料庫的搜尋 query。

只輸出 JSON，不要 Markdown。

使用者輸入：
{user_query}

輸出 schema：
{{
  "input_type": "project_description",
  "normalized_goal": "一句話整理使用者想做什麼",
  "github_queries": ["query1", "query2", "query3"],
  "huggingface_queries": ["query1", "query2", "query3"],
  "research_queries": ["query1", "query2", "query3"],
  "should_use_exact_search_first": false
}}
"""
    response = get_client().responses.create(model=MODEL, input=prompt)
    data = extract_json(response.output_text)

    input_type = data.get("input_type")
    if input_type not in {"project_description", "unknown_term"}:
        input_type = "project_description"

    exact_first = bool(data.get("should_use_exact_search_first")) or input_type == "unknown_term"
    exact_query = f'"{user_query.strip()}"'

    return {
        "input_type": input_type,
        "normalized_goal": str(data.get("normalized_goal") or user_query).strip(),
        "github_queries": [str(q).strip() for q in data.get("github_queries", []) if q],
        "huggingface_queries": [str(q).strip() for q in data.get("huggingface_queries", []) if q],
        "research_queries": [str(q).strip() for q in data.get("research_queries", []) if q],
        "should_use_exact_search_first": exact_first,
        "exact_query": exact_query,
    }


def github_search(queries, limit=5):
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    results = []
    seen = set()
    per_query = max(1, limit // max(len(queries), 1))

    for query in queries:
        try:
            data = request_json(
                "https://api.github.com/search/repositories",
                params={
                    "q": query,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": per_query,
                },
                headers=headers,
            )
        except Exception:
            continue

        for repo in data.get("items", []):
            full_name = repo.get("full_name", "")
            if not full_name or full_name in seen:
                continue
            seen.add(full_name)
            results.append(
                {
                    "name": full_name,
                    "url": repo.get("html_url", ""),
                    "description": repo.get("description") or "",
                    "stars": int(repo.get("stargazers_count") or 0),
                    "language": repo.get("language") or "",
                    "topics": repo.get("topics") or [],
                }
            )
    return results[:limit]


def huggingface_search(queries, limit=5):
    token = os.getenv("HF_TOKEN", "")
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    results = []
    seen = set()
    per_query = max(1, limit // max(len(queries), 1))

    for query in queries:
        try:
            data = request_json(
                "https://huggingface.co/api/models",
                params={
                    "search": query,
                    "sort": "downloads",
                    "direction": "-1",
                    "limit": per_query,
                    "full": "true",
                },
                headers=headers,
            )
        except Exception:
            continue

        for model in data:
            model_id = model.get("modelId") or model.get("id", "")
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            results.append(
                {
                    "name": model_id,
                    "url": f"https://huggingface.co/{model_id}",
                    "task": model.get("pipeline_tag") or "",
                    "downloads": int(model.get("downloads") or 0),
                    "likes": int(model.get("likes") or 0),
                    "tags": (model.get("tags") or [])[:8],
                }
            )
    return results[:limit]


def openalex_search(queries, limit=4):
    results = []
    seen = set()
    per_query = max(1, limit // max(len(queries), 1))

    for query in queries:
        try:
            data = request_json(
                "https://api.openalex.org/works",
                params={
                    "search": query,
                    "sort": "publication_date:desc",
                    "per-page": per_query,
                },
            )
        except Exception:
            continue

        for work in data.get("results", []):
            title = work.get("display_name", "")
            url = work.get("doi") or work.get("id", "")
            if not title or title in seen:
                continue
            seen.add(title)
            results.append(
                {
                    "title": title,
                    "url": url,
                    "year": work.get("publication_year"),
                    "citations": int(work.get("cited_by_count") or 0),
                }
            )
    return results[:limit]


def arxiv_search(queries, limit=3):
    results = []
    seen = set()
    per_query = max(1, limit // max(len(queries), 1))
    namespace = {"atom": "http://www.w3.org/2005/Atom"}

    for query in queries:
        try:
            xml = request_text(
                "https://export.arxiv.org/api/query",
                params={
                    "search_query": f'all:"{query}"',
                    "sortBy": "lastUpdatedDate",
                    "sortOrder": "descending",
                    "max_results": per_query,
                },
            )
            root = ElementTree.fromstring(xml)
        except Exception:
            continue

        for entry in root.findall("atom:entry", namespace):
            title = " ".join((entry.findtext("atom:title", default="", namespaces=namespace) or "").split())
            url = entry.findtext("atom:id", default="", namespaces=namespace)
            if not title or title in seen:
                continue
            seen.add(title)
            results.append(
                {
                    "title": title,
                    "url": url,
                    "year": (entry.findtext("atom:published", default="", namespaces=namespace) or "")[:4],
                    "citations": None,
                }
            )
    return results[:limit]


def summarize_advice(user_query, strategy, github_results, hf_results, research_results, web_result):
    prompt = f"""
你是一個 AI 專案顧問。請根據搜尋結果，整理使用者的專案建議。
只輸出 JSON，不要 Markdown。

只輸出五個區塊：
1. 專案本質
2. GitHub 參考專案
3. Hugging Face 可用模型
4. 相關研究方向
5. 資料來源

使用者輸入：
{user_query}

搜尋策略：
{json.dumps(strategy, ensure_ascii=False)}

GitHub 結果：
{json.dumps(github_results, ensure_ascii=False)}

Hugging Face 結果：
{json.dumps(hf_results, ensure_ascii=False)}

研究結果：
{json.dumps(research_results, ensure_ascii=False)}

Web Search 補充：
{json.dumps(web_result, ensure_ascii=False)}

輸出 schema：
{{
  "project_nature": "用繁體中文說明這個專案本質",
  "github_projects": [
    {{"name": "repo", "url": "url", "why_relevant": "為什麼相關", "stars": 0, "language": "Python"}}
  ],
  "huggingface_models": [
    {{"name": "model", "url": "url", "why_relevant": "可用在哪裡", "downloads": 0, "task": "image-classification"}}
  ],
  "research_directions": [
    {{"title": "方向或論文", "url": "url", "why_relevant": "為什麼值得看"}}
  ],
  "sources": [
    {{"title": "source title", "url": "url", "source_type": "github"}}
  ]
}}
"""
    response = get_client().responses.create(model=MODEL, input=prompt)
    data = extract_json(response.output_text)
    return {
        "project_nature": str(data.get("project_nature") or "").strip(),
        "github_projects": data.get("github_projects", [])[:5],
        "huggingface_models": data.get("huggingface_models", [])[:5],
        "research_directions": data.get("research_directions", [])[:6],
        "sources": data.get("sources", [])[:12],
    }


def advise_project(user_query):
    query = str(user_query or "").strip()
    if not query:
        raise ValueError("query is required")

    strategy = analyze_request(query)
    if strategy["should_use_exact_search_first"]:
        github_queries = [strategy["exact_query"]] + strategy["github_queries"][:2]
        hf_queries = [strategy["exact_query"]] + strategy["huggingface_queries"][:2]
        research_queries = [strategy["exact_query"]] + strategy["research_queries"][:2]
    else:
        github_queries = strategy["github_queries"][:5]
        hf_queries = strategy["huggingface_queries"][:5]
        research_queries = strategy["research_queries"][:5]

    github_results = github_search(github_queries)
    hf_results = huggingface_search(hf_queries)
    research_results = openalex_search(research_queries) + arxiv_search(research_queries)

    web_result = {"summary": "", "sources": []}
    try:
        web_result = web_research(query)
    except Exception as error:
        web_result = {
            "summary": f"Web search failed: {error}",
            "sources": [],
        }

    advice = summarize_advice(
        query,
        strategy,
        github_results,
        hf_results,
        research_results,
        web_result,
    )
    advice["input_type"] = strategy["input_type"]
    advice["normalized_goal"] = strategy["normalized_goal"]
    return advice
