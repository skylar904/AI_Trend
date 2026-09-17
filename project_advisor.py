import json
import os
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from dotenv import load_dotenv
from openai import OpenAI

from summarizer import MODEL, extract_json
from web_research import web_research


load_dotenv()

REQUEST_TIMEOUT = 25
MAX_AGENT_ROUNDS = 6
MAX_TOOL_RESULTS = 12
README_LIMIT = 2400
client = None


AGENT_INSTRUCTIONS = """
你是一個通用的技術研究與資源探索 Agent。使用者可能提出產品構想、軟體專案、遊戲、Skill、模型、資料集、論文、工具、學習方向，或任何尚未預先列舉的需求。

工作原則：
- 先理解使用者真正想完成的目標，再自行選擇適合的工具與搜尋詞。
- 每次查詢至少使用一個搜尋工具。不要固定呼叫所有工具，只使用對目前目標有價值的工具。
- 當某個專門工具能直接取得所需資源時，優先使用專門工具；Web Search 用於探索未知主題、近期資訊與補足脈絡。
- 資訊不完整時不要向使用者追問；採用合理假設，並在 assumptions 中簡短說明。
- 若有多種主要解讀，涵蓋最有幫助的方向，不要因為模糊而停止。
- 第一次結果不足時，調整關鍵字、換來源或讀取重要 repository，再繼續搜尋。
- 比較候選的實際用途、相容性、文件、維護狀態、授權與限制，不要只按照 stars、downloads 或 citations 排名。
- 只能推薦工具結果中實際存在的資源。所有推薦項目必須引用有效的 source_id，不得自行創造名稱、網址、數據或 source_id。
- 回答使用繁體中文，直接解決需求，不展示內部推理、工具呼叫流程或分類 JSON。
- 最終輸出必須符合指定 JSON schema。沒有來源支撐的純建議可以寫在 answer 或 section summary，但不能偽裝成具體資源。
""".strip()


FINAL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "assumptions", "sections", "source_ids"],
    "properties": {
        "answer": {"type": "string"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "summary", "items"],
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["source_id", "title", "description", "details"],
                            "properties": {
                                "source_id": {"type": "string"},
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "details": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                    },
                },
            },
        },
        "source_ids": {"type": "array", "items": {"type": "string"}},
    },
}


AGENT_TOOLS = [
    {
        "type": "function",
        "name": "search_web",
        "description": "搜尋一般網路、官方文件、產品頁、技術文章或未知主題。適合先探索廣泛或近期資訊。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "description": "具體、可直接搜尋的查詢"},
                "allowed_domains": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "可選的網域限制，例如 github.com；通常留空即可",
                },
            },
            "required": ["query"],
        },
        "strict": False,
    },
    {
        "type": "function",
        "name": "search_github",
        "description": "搜尋可執行、可參考或可重用的 GitHub repository，並取得 README、維護狀態、授權和 Demo 等資訊。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_TOOL_RESULTS},
            },
            "required": ["query"],
        },
        "strict": False,
    },
    {
        "type": "function",
        "name": "search_huggingface_models",
        "description": "搜尋 Hugging Face 模型。只有在需求需要預訓練模型、模型權重或推論能力時使用。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_TOOL_RESULTS},
            },
            "required": ["query"],
        },
        "strict": False,
    },
    {
        "type": "function",
        "name": "search_huggingface_datasets",
        "description": "搜尋 Hugging Face 資料集。只有在需求需要訓練、評估或範例資料時使用。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_TOOL_RESULTS},
            },
            "required": ["query"],
        },
        "strict": False,
    },
    {
        "type": "function",
        "name": "search_papers",
        "description": "搜尋 Semantic Scholar、OpenAlex 與 arXiv 的研究論文。適合研究方法、技術比較、近期論文或學術背景。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_TOOL_RESULTS},
            },
            "required": ["query"],
        },
        "strict": False,
    },
    {
        "type": "function",
        "name": "read_github_repository",
        "description": "深入讀取某個已知 GitHub repository 的 README、授權、更新狀態與基本資訊。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repository": {
                    "type": "string",
                    "description": "owner/repository 格式，例如 vuejs/core",
                }
            },
            "required": ["repository"],
        },
        "strict": False,
    },
]


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


def request_text(url, params=None, headers=None):
    query = urlencode(params or {})
    request_url = f"{url}?{query}" if query else url
    request = Request(
        request_url,
        headers={
            "Accept": "text/plain, text/markdown, application/xml, text/xml",
            "User-Agent": "AI-Trend-Dashboard",
            **(headers or {}),
        },
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return response.read().decode("utf-8", errors="replace")


def clamp_limit(value, default=8):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return max(1, min(MAX_TOOL_RESULTS, value))


def short_text(value, limit=README_LIMIT):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def github_headers(raw=False):
    headers = {}
    token = os.getenv("GITHUB_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    headers["Accept"] = "application/vnd.github.raw+json" if raw else "application/vnd.github+json"
    return headers


def read_github_repository(repository):
    repository = str(repository or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("repository must use owner/name format")

    repo = request_json(f"https://api.github.com/repos/{repository}", headers=github_headers())
    readme = ""
    try:
        readme = request_text(
            f"https://api.github.com/repos/{repository}/readme",
            headers=github_headers(raw=True),
        )
    except Exception:
        pass

    license_data = repo.get("license") or {}
    return {
        "name": repo.get("full_name") or repository,
        "url": repo.get("html_url") or f"https://github.com/{repository}",
        "description": repo.get("description") or "",
        "stars": int(repo.get("stargazers_count") or 0),
        "language": repo.get("language") or "",
        "topics": repo.get("topics") or [],
        "updated_at": repo.get("pushed_at") or repo.get("updated_at") or "",
        "archived": bool(repo.get("archived")),
        "license": license_data.get("spdx_id") or license_data.get("name") or "",
        "homepage": repo.get("homepage") or "",
        "readme_excerpt": short_text(readme),
    }


def github_search(query, limit=8):
    limit = clamp_limit(limit)
    data = request_json(
        "https://api.github.com/search/repositories",
        params={"q": str(query).strip(), "per_page": limit},
        headers=github_headers(),
    )

    results = []
    for repo in data.get("items", []):
        full_name = repo.get("full_name", "")
        if not full_name or repo.get("archived"):
            continue
        result = {
            "name": full_name,
            "url": repo.get("html_url", ""),
            "description": repo.get("description") or "",
            "stars": int(repo.get("stargazers_count") or 0),
            "language": repo.get("language") or "",
            "topics": repo.get("topics") or [],
            "updated_at": repo.get("pushed_at") or repo.get("updated_at") or "",
            "archived": False,
            "license": (repo.get("license") or {}).get("spdx_id") or "",
            "homepage": repo.get("homepage") or "",
            "readme_excerpt": "",
        }
        if len(results) < 4:
            try:
                result.update(read_github_repository(full_name))
            except Exception:
                pass
        results.append(result)
    return results[:limit]


def _huggingface_license(item):
    card_data = item.get("cardData") or {}
    if card_data.get("license"):
        return str(card_data["license"])
    for tag in item.get("tags") or []:
        if str(tag).startswith("license:"):
            return str(tag).split(":", 1)[1]
    return ""


def huggingface_model_search(query, limit=8):
    limit = clamp_limit(limit)
    headers = {}
    token = os.getenv("HF_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = request_json(
        "https://huggingface.co/api/models",
        params={
            "search": str(query).strip(),
            "sort": "downloads",
            "direction": "-1",
            "limit": limit,
            "full": "true",
        },
        headers=headers,
    )
    results = []
    for model in data:
        model_id = model.get("modelId") or model.get("id", "")
        if not model_id:
            continue
        results.append(
            {
                "name": model_id,
                "url": f"https://huggingface.co/{model_id}",
                "description": short_text((model.get("cardData") or {}).get("description"), 600),
                "task": model.get("pipeline_tag") or "",
                "downloads": int(model.get("downloads") or 0),
                "likes": int(model.get("likes") or 0),
                "tags": (model.get("tags") or [])[:12],
                "license": _huggingface_license(model),
                "updated_at": model.get("lastModified") or "",
            }
        )
    return results


def huggingface_dataset_search(query, limit=8):
    limit = clamp_limit(limit)
    headers = {}
    token = os.getenv("HF_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = request_json(
        "https://huggingface.co/api/datasets",
        params={
            "search": str(query).strip(),
            "sort": "downloads",
            "direction": "-1",
            "limit": limit,
            "full": "true",
        },
        headers=headers,
    )
    results = []
    for dataset in data:
        dataset_id = dataset.get("id") or dataset.get("datasetId", "")
        if not dataset_id:
            continue
        results.append(
            {
                "name": dataset_id,
                "url": f"https://huggingface.co/datasets/{dataset_id}",
                "description": short_text((dataset.get("cardData") or {}).get("description"), 600),
                "downloads": int(dataset.get("downloads") or 0),
                "likes": int(dataset.get("likes") or 0),
                "tags": (dataset.get("tags") or [])[:12],
                "license": _huggingface_license(dataset),
                "updated_at": dataset.get("lastModified") or "",
            }
        )
    return results


def openalex_abstract(inverted_index):
    if not inverted_index:
        return ""
    words = []
    for word, positions in inverted_index.items():
        for position in positions:
            words.append((position, word))
    return " ".join(word for _, word in sorted(words))


def semantic_scholar_search(query, limit=6):
    headers = {}
    api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    if api_key:
        headers["x-api-key"] = api_key
    data = request_json(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params={
            "query": str(query).strip(),
            "limit": clamp_limit(limit),
            "fields": "title,abstract,url,year,venue,publicationDate,citationCount,authors",
        },
        headers=headers,
    )
    results = []
    for paper in data.get("data", []):
        title = paper.get("title") or ""
        if not title:
            continue
        results.append(
            {
                "title": title,
                "url": paper.get("url") or "",
                "abstract": short_text(paper.get("abstract"), 1200),
                "year": paper.get("year"),
                "venue": paper.get("venue") or "",
                "citations": int(paper.get("citationCount") or 0),
                "authors": [author.get("name", "") for author in (paper.get("authors") or [])[:5]],
                "provider": "Semantic Scholar",
            }
        )
    return results


def openalex_search(query, limit=6):
    data = request_json(
        "https://api.openalex.org/works",
        params={
            "search": str(query).strip(),
            "sort": "relevance_score:desc",
            "per-page": clamp_limit(limit),
        },
    )
    results = []
    for work in data.get("results", []):
        title = work.get("display_name", "")
        if not title:
            continue
        results.append(
            {
                "title": title,
                "url": work.get("doi") or (work.get("primary_location") or {}).get("landing_page_url") or work.get("id", ""),
                "abstract": short_text(openalex_abstract(work.get("abstract_inverted_index")), 1200),
                "year": work.get("publication_year"),
                "venue": ((work.get("primary_location") or {}).get("source") or {}).get("display_name") or "",
                "citations": int(work.get("cited_by_count") or 0),
                "authors": [
                    ((entry.get("author") or {}).get("display_name") or "")
                    for entry in (work.get("authorships") or [])[:5]
                ],
                "provider": "OpenAlex",
            }
        )
    return results


def arxiv_search(query, limit=6):
    xml = request_text(
        "https://export.arxiv.org/api/query",
        params={
            "search_query": f'all:"{str(query).strip()}"',
            "sortBy": "relevance",
            "sortOrder": "descending",
            "max_results": clamp_limit(limit),
        },
        headers={"Accept": "application/atom+xml, application/xml"},
    )
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    root = ElementTree.fromstring(xml)
    results = []
    for entry in root.findall("atom:entry", namespace):
        title = " ".join((entry.findtext("atom:title", default="", namespaces=namespace) or "").split())
        if not title:
            continue
        results.append(
            {
                "title": title,
                "url": entry.findtext("atom:id", default="", namespaces=namespace),
                "abstract": short_text(entry.findtext("atom:summary", default="", namespaces=namespace), 1200),
                "year": (entry.findtext("atom:published", default="", namespaces=namespace) or "")[:4],
                "venue": "arXiv",
                "citations": None,
                "authors": [
                    author.findtext("atom:name", default="", namespaces=namespace)
                    for author in entry.findall("atom:author", namespace)[:5]
                ],
                "provider": "arXiv",
            }
        )
    return results


def paper_search(query, limit=8):
    limit = clamp_limit(limit)
    results = []
    seen = set()
    providers = (semantic_scholar_search, openalex_search, arxiv_search)
    per_provider = max(2, min(limit, (limit + len(providers) - 1) // len(providers) + 1))

    for provider in providers:
        try:
            provider_results = provider(query, per_provider)
        except Exception:
            continue
        for paper in provider_results:
            key = re.sub(r"\W+", "", paper.get("title", "").lower())
            if not key or key in seen:
                continue
            seen.add(key)
            results.append(paper)
            if len(results) >= limit:
                return results
    return results


class SourceRegistry:
    def __init__(self):
        self._sources = []
        self._by_url = {}

    def add(self, source_type, title, url, description="", metadata=None):
        url = str(url or "").strip()
        if not url.startswith(("http://", "https://")):
            return None
        if url in self._by_url:
            return self._by_url[url]

        source = {
            "source_id": f"source_{len(self._sources) + 1}",
            "source_type": str(source_type or "web"),
            "title": str(title or url).strip(),
            "url": url,
            "description": short_text(description, 1200),
            "metadata": metadata or {},
        }
        self._sources.append(source)
        self._by_url[url] = source
        return source

    def get(self, source_id):
        for source in self._sources:
            if source["source_id"] == source_id:
                return source
        return None


def source_for_result(registry, source_type, result):
    title = result.get("name") or result.get("title") or result.get("url")
    description = result.get("description") or result.get("abstract") or result.get("readme_excerpt") or ""
    metadata = {
        key: value
        for key, value in result.items()
        if key not in {"name", "title", "url", "description", "abstract", "readme_excerpt"}
        and value not in (None, "", [], {})
    }
    source = registry.add(source_type, title, result.get("url"), description, metadata)
    if not source:
        return None
    return {
        "source_id": source["source_id"],
        "title": source["title"],
        "url": source["url"],
        "description": source["description"],
        "metadata": source["metadata"],
    }


def execute_tool(name, arguments, registry):
    query = str(arguments.get("query") or "").strip()
    limit = clamp_limit(arguments.get("limit"), 8)

    if name == "search_web":
        domains = arguments.get("allowed_domains") or None
        result = web_research(query, allowed_domains=domains)
        sources = []
        for item in result.get("sources", []):
            source = registry.add("web", item.get("title"), item.get("url"))
            if source:
                sources.append(
                    {
                        "source_id": source["source_id"],
                        "title": source["title"],
                        "url": source["url"],
                    }
                )
        return {"summary": result.get("summary", ""), "results": sources}

    if name == "search_github":
        results = github_search(query, limit)
        source_type = "github"
    elif name == "search_huggingface_models":
        results = huggingface_model_search(query, limit)
        source_type = "huggingface_model"
    elif name == "search_huggingface_datasets":
        results = huggingface_dataset_search(query, limit)
        source_type = "huggingface_dataset"
    elif name == "search_papers":
        results = paper_search(query, limit)
        source_type = "paper"
    elif name == "read_github_repository":
        results = [read_github_repository(arguments.get("repository"))]
        source_type = "github"
    else:
        raise ValueError(f"unknown tool: {name}")

    registered = []
    for result in results:
        source = source_for_result(registry, source_type, result)
        if source:
            registered.append(source)
    return {"results": registered}


def create_agent_response(**kwargs):
    return get_client().responses.create(
        model=MODEL,
        instructions=AGENT_INSTRUCTIONS,
        tools=AGENT_TOOLS,
        parallel_tool_calls=False,
        text={
            "format": {
                "type": "json_schema",
                "name": "technical_research_answer",
                "strict": True,
                "schema": FINAL_SCHEMA,
            }
        },
        **kwargs,
    )


def normalize_advice(data, registry):
    assumptions = [str(item).strip() for item in data.get("assumptions", []) if str(item).strip()]
    sections = []
    used_source_ids = []

    for raw_section in data.get("sections", []):
        title = str(raw_section.get("title") or "").strip()
        summary = str(raw_section.get("summary") or "").strip()
        items = []
        for raw_item in raw_section.get("items", []):
            source_id = str(raw_item.get("source_id") or "").strip()
            source = registry.get(source_id)
            if not source:
                continue
            used_source_ids.append(source_id)
            items.append(
                {
                    "source_id": source_id,
                    "title": str(raw_item.get("title") or source["title"]).strip(),
                    "description": str(raw_item.get("description") or "").strip(),
                    "details": [
                        str(detail).strip()
                        for detail in raw_item.get("details", [])
                        if str(detail).strip()
                    ],
                    "url": source["url"],
                    "source_type": source["source_type"],
                    "metadata": source["metadata"],
                }
            )
        if title or summary or items:
            sections.append({"title": title or "相關資源", "summary": summary, "items": items})

    requested_ids = [str(item) for item in data.get("source_ids", [])]
    ordered_ids = []
    for source_id in used_source_ids + requested_ids:
        if registry.get(source_id) and source_id not in ordered_ids:
            ordered_ids.append(source_id)

    return {
        "answer": str(data.get("answer") or "").strip(),
        "assumptions": assumptions,
        "sections": sections,
        "sources": [registry.get(source_id) for source_id in ordered_ids],
    }


def advise_project(user_query):
    query = str(user_query or "").strip()
    if not query:
        raise ValueError("query is required")

    registry = SourceRegistry()
    response = create_agent_response(input=query)

    for _ in range(MAX_AGENT_ROUNDS):
        calls = [item for item in (response.output or []) if getattr(item, "type", "") == "function_call"]
        if not calls:
            break

        tool_outputs = []
        for call in calls:
            try:
                arguments = json.loads(call.arguments or "{}")
                result = execute_tool(call.name, arguments, registry)
            except Exception as error:
                result = {"error": str(error)[:600], "results": []}
            tool_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(result, ensure_ascii=False),
                }
            )

        response = create_agent_response(previous_response_id=response.id, input=tool_outputs)
    else:
        response = create_agent_response(
            previous_response_id=response.id,
            input="請停止呼叫工具，根據目前已取得並驗證的來源直接輸出最終 JSON。",
            tool_choice="none",
        )

    if not response.output_text:
        raise RuntimeError("research agent returned no final answer")

    data = extract_json(response.output_text)
    return normalize_advice(data, registry)
