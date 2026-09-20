import json
import io
import html
import os
import re
from urllib.parse import quote, urlencode, urlparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from dotenv import load_dotenv
from openai import OpenAI
from pypdf import PdfReader

from summarizer import MODEL, extract_json
from web_research import web_research


load_dotenv()

REQUEST_TIMEOUT = 25
GEMINI_TIMEOUT = int(os.getenv("GEMINI_TIMEOUT", "45"))
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_SERVICE_UNAVAILABLE_MESSAGE = "API token不足，服務無法使用"
MAX_AGENT_ROUNDS = 10
MAX_TOOL_RESULTS = 15
MAX_FINAL_RESULTS = 6
README_LIMIT = 6000
FILE_CONTENT_LIMIT = 10000
PAPER_CONTENT_LIMIT = 24000
client = None


AGENT_INSTRUCTIONS = """
你是一個技術資源研究 Agent。你的第一責任是完整保留使用者原句中的目標、資源類型、功能與限制，再依需求即時上網研究。

允許的最終資源只有三類：
1. GitHub repository 或 repository 中的 Skill、程式碼與套件。
2. Hugging Face model 或 dataset。
3. 真正的學術論文；不限期刊、會議、預印本或發表網站。

必要規則：
- 不得推薦課程、教學網站、產品頁、一般部落格或其他類型的資源。
- 使用者明確說 Skill、模型、資料集、論文、專案或套件時，按字面資源類型理解。除非使用者明確說「學習、課程、教學」，否則 Skill 絕不能解讀成學習技能。
- 使用者明確指定資源類型時，最終結果必須是該類型：Skill 只能以 GitHub Skill 為結果；模型必須是 Hugging Face model 或可直接使用的 GitHub 模型實作；資料集必須是 Hugging Face dataset 或 GitHub dataset；論文必須是真正論文。其他類型只能作為研究背景，不能替代使用者要找的東西。
- GitHub、Hugging Face 與論文搜尋通常使用精準英文技術詞；不要只把中文原句原封不動送進英文技術平台。
- 不向使用者追問。資訊不足時採最合理的技術方向繼續研究，但最終回答不要另外列出「採用假設」。
- 搜尋只是找候選，不能只看標題、摘要片段、stars、downloads 或 citations 就推薦。
- GitHub 候選必須先呼叫 inspect_github_repository；需要確認功能時，再讀取關鍵程式碼。Skill 必須實際讀到 SKILL.md 或等價的完整 Skill 定義。
- Hugging Face 候選必須先呼叫 inspect_huggingface_resource，讀取 Card、設定與檔案清單。
- 論文候選必須先呼叫 inspect_paper。能取得 PDF 時讀取重要頁面；只能取得摘要時必須在 evidence_basis 與 limitations 清楚標示。
- 最終只能引用已完成 inspect 的有效 source_id，不得自行創造名稱、網址、數據或 source_id。
- 按需求符合程度選出最相關的 3 至 6 個結果。找不到合格結果就直接說沒有找到，不得湊數。
- answer 最多兩句。每個項目清楚說明它是什麼、怎麼運作、為什麼符合、限制與實際查閱依據。
- 不在可見文字中輸出 source_id，不重複列資料來源，不用「如果你告訴我」或問句結尾。
- 使用繁體中文，不展示內部分類、搜尋策略或工具流程。
""".strip()


PLANNER_INSTRUCTIONS = """
你是一個技術資源需求理解器。你的任務是把使用者自然語言需求轉成可執行的搜尋計畫。

請判斷使用者真正想解決什麼問題，以及最可能需要哪幾種技術資源。

可選資源類型：
- github：GitHub repository、Codex Skill、plugin、SDK、library、framework、可直接參考或安裝的開源專案。
- huggingface_model：Hugging Face model，適合模型、辨識、生成、embedding、分類、推論等需求。
- huggingface_dataset：Hugging Face dataset，適合資料集、訓練資料、benchmark data 等需求。
- paper：學術論文，適合研究方法、演算法、benchmark、實驗設計、文獻探討等需求。

規則：
- 使用者明確指定 skill、plugin、Codex、coding agent、前端開發、UI/UX 或設計流程時，通常優先考慮 github。
- 使用者只描述專題或問題、沒有指定資源類型時，選 1 到 3 種最有幫助的資源類型，不要全部都選。
- search_queries 要使用適合 GitHub、Hugging Face 或論文搜尋的英文技術詞，不要只原封不動翻譯中文。
- 如果使用者提到 Codex Skill，GitHub 搜尋 query 應該包含 SKILL.md 或 Codex skill。
- 不要編造具體不存在的 repo、model、dataset 或論文名稱；只規劃搜尋方向。
- 輸出 JSON，不要 Markdown。
""".strip()


FINAL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["answer", "sections"],
    "properties": {
        "answer": {"type": "string"},
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
                            "required": [
                                "source_id",
                                "title",
                                "description",
                                "how_it_works",
                                "why_relevant",
                                "limitations",
                                "evidence_basis",
                            ],
                            "properties": {
                                "source_id": {"type": "string"},
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "how_it_works": {"type": "string"},
                                "why_relevant": {"type": "string"},
                                "limitations": {"type": "string"},
                                "evidence_basis": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
    },
}


RESEARCH_PLAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intent_summary", "resource_types", "search_queries", "priority_terms"],
    "properties": {
        "intent_summary": {"type": "string"},
        "resource_types": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["github", "huggingface_model", "huggingface_dataset", "paper"],
            },
        },
        "search_queries": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source_kind", "query"],
                "properties": {
                    "source_kind": {
                        "type": "string",
                        "enum": ["github", "huggingface", "paper"],
                    },
                    "query": {"type": "string"},
                },
            },
        },
        "priority_terms": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}


AGENT_TOOLS = [
    {
        "type": "function",
        "name": "discover_online",
        "description": "即時上網發現 GitHub、Hugging Face 或論文候選。搜尋到的頁面只是候選，仍必須使用對應 inspect 工具驗證後才能推薦。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string"},
                "source_kind": {
                    "type": "string",
                    "enum": ["github", "huggingface", "paper"],
                },
            },
            "required": ["query", "source_kind"],
        },
        "strict": False,
    },
    {
        "type": "function",
        "name": "search_github",
        "description": "透過 GitHub API 即時搜尋 repository 候選。這一步只找候選，推薦前必須 inspect。",
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
        "name": "search_github_code",
        "description": "在 GitHub 程式碼中搜尋檔案或內容；尋找 Agent Skill 時優先使用 filename:SKILL.md。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
        },
        "strict": False,
    },
    {
        "type": "function",
        "name": "search_huggingface_models",
        "description": "透過 Hugging Face API 即時搜尋模型候選。推薦前必須 inspect。",
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
        "description": "透過 Hugging Face API 即時搜尋資料集候選。推薦前必須 inspect。",
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
        "description": "透過學術索引即時搜尋論文候選；論文不限平台。推薦前必須 inspect。",
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
        "name": "inspect_github_repository",
        "description": "深入查閱 GitHub repository 的 README、目錄、manifest、Skill 定義、授權與維護狀態。",
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
    {
        "type": "function",
        "name": "read_github_file",
        "description": "讀取已知 GitHub repository 中與需求相關的關鍵程式碼或設定檔。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repository": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["repository", "path"],
        },
        "strict": False,
    },
    {
        "type": "function",
        "name": "inspect_huggingface_resource",
        "description": "深入查閱 Hugging Face model 或 dataset 的 Card、設定、檔案清單、輸入輸出與限制。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "resource_id": {"type": "string"},
                "resource_type": {"type": "string", "enum": ["model", "dataset"]},
            },
            "required": ["resource_id", "resource_type"],
        },
        "strict": False,
    },
    {
        "type": "function",
        "name": "inspect_paper",
        "description": "深入查閱已搜尋到的論文。使用 source_id 取得摘要及公開 PDF，並標明實際分析依據。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"source_id": {"type": "string"}},
            "required": ["source_id"],
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


def request_bytes(url, headers=None, max_bytes=40 * 1024 * 1024):
    request = Request(
        str(url),
        headers={"User-Agent": "AI-Trend-Dashboard", **(headers or {})},
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        content_length = int(response.headers.get("Content-Length") or 0)
        if content_length and content_length > max_bytes:
            raise ValueError("remote file is too large")
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("remote file is too large")
    return data


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


def github_request_json(url, params=None):
    try:
        return request_json(url, params=params, headers=github_headers())
    except HTTPError as error:
        if error.code not in {401, 403} or not os.getenv("GITHUB_TOKEN"):
            raise
        return request_json(
            url,
            params=params,
            headers={"Accept": "application/vnd.github+json"},
        )


def github_request_text(url):
    try:
        return request_text(url, headers=github_headers(raw=True))
    except HTTPError as error:
        if error.code not in {401, 403} or not os.getenv("GITHUB_TOKEN"):
            raise
        return request_text(url, headers={"Accept": "application/vnd.github.raw+json"})


def validate_repository(repository):
    repository = str(repository or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("repository must use owner/name format")
    return repository


def read_github_file(repository, path):
    repository = validate_repository(repository)
    path = str(path or "").strip().lstrip("/")
    if not path or ".." in path.split("/"):
        raise ValueError("invalid repository path")
    return github_request_text(
        f"https://api.github.com/repos/{repository}/contents/{quote(path, safe='/')}"
    )[:FILE_CONTENT_LIMIT]


def inspect_github_repository(repository):
    repository = validate_repository(repository)

    repo = github_request_json(f"https://api.github.com/repos/{repository}")
    readme = ""
    try:
        readme = github_request_text(f"https://api.github.com/repos/{repository}/readme")
    except Exception:
        pass

    tree_paths = []
    try:
        default_branch = repo.get("default_branch") or "main"
        tree = github_request_json(
            f"https://api.github.com/repos/{repository}/git/trees/{quote(default_branch, safe='')}",
            params={"recursive": "1"},
        )
        tree_paths = [
            item.get("path", "")
            for item in tree.get("tree", [])
            if item.get("type") == "blob" and item.get("path")
        ][:300]
    except Exception:
        pass

    priority_names = {
        "skill.md",
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "setup.py",
        "cargo.toml",
        "go.mod",
        "dockerfile",
        "compose.yml",
        "docker-compose.yml",
    }
    priority_paths = sorted(
        tree_paths,
        key=lambda path: (
            0 if path.lower().endswith("skill.md") else 1,
            0 if path.rsplit("/", 1)[-1].lower() in priority_names else 1,
            path.count("/"),
            len(path),
        ),
    )
    key_files = []
    for path in priority_paths:
        filename = path.rsplit("/", 1)[-1].lower()
        if not (path.lower().endswith("skill.md") or filename in priority_names):
            continue
        try:
            key_files.append({"path": path, "content": read_github_file(repository, path)})
        except Exception:
            continue
        if len(key_files) >= 8:
            break

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
        "tree_paths": tree_paths,
        "key_files": key_files,
        "analysis_basis": "README, repository tree, manifests and Skill definitions",
        "inspected": True,
    }


def github_search(query, limit=8):
    limit = clamp_limit(limit)
    data = github_request_json(
        "https://api.github.com/search/repositories",
        params={"q": str(query).strip(), "per_page": limit},
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
            "inspected": False,
        }
        results.append(result)
    return results[:limit]


def github_code_search(query, limit=8):
    limit = min(10, clamp_limit(limit))
    try:
        data = github_request_json(
            "https://api.github.com/search/code",
            params={"q": str(query).strip(), "per_page": limit},
        )
    except HTTPError:
        discovery = web_research(f"{query} GitHub", "github")
        data = {
            "items": [
                {
                    "repository": {
                        "full_name": github_repository_from_url(item.get("url")),
                        "html_url": item.get("url"),
                    },
                    "path": "",
                    "html_url": item.get("url"),
                }
                for item in discovery.get("sources", [])
            ]
        }
    results = []
    seen = set()
    for item in data.get("items", []):
        repo = item.get("repository") or {}
        full_name = repo.get("full_name") or ""
        if not full_name or full_name in seen:
            continue
        seen.add(full_name)
        results.append(
            {
                "name": full_name,
                "url": repo.get("html_url") or f"https://github.com/{full_name}",
                "description": repo.get("description") or "",
                "matched_path": item.get("path") or "",
                "match_url": item.get("html_url") or "",
                "inspected": False,
            }
        )
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
                "inspected": False,
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
                "inspected": False,
            }
        )
    return results


def inspect_huggingface_resource(resource_id, resource_type):
    resource_id = str(resource_id or "").strip()
    resource_type = str(resource_type or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", resource_id):
        raise ValueError("resource_id must use owner/name format")
    if resource_type not in {"model", "dataset"}:
        raise ValueError("resource_type must be model or dataset")

    token = os.getenv("HF_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    api_kind = "models" if resource_type == "model" else "datasets"
    page_prefix = "" if resource_type == "model" else "datasets/"
    data = request_json(
        f"https://huggingface.co/api/{api_kind}/{quote(resource_id, safe='/')}",
        params={"full": "true"},
        headers=headers,
    )

    card = ""
    try:
        card = request_text(
            f"https://huggingface.co/{page_prefix}{resource_id}/raw/main/README.md",
            headers=headers,
        )[:README_LIMIT]
    except Exception:
        pass

    config = ""
    if resource_type == "model":
        try:
            config = request_text(
                f"https://huggingface.co/{resource_id}/raw/main/config.json",
                headers=headers,
            )[:FILE_CONTENT_LIMIT]
        except Exception:
            pass

    siblings = [
        item.get("rfilename", "")
        for item in (data.get("siblings") or [])
        if item.get("rfilename")
    ][:200]
    item_id = data.get("modelId") or data.get("id") or resource_id
    basis_parts = []
    if card:
        basis_parts.append("Model Card" if resource_type == "model" else "Dataset Card")
    if config:
        basis_parts.append("config")
    if siblings:
        basis_parts.append("repository file list")
    return {
        "name": item_id,
        "url": f"https://huggingface.co/{page_prefix}{item_id}",
        "description": short_text((data.get("cardData") or {}).get("description"), 1000),
        "task": data.get("pipeline_tag") or "",
        "downloads": int(data.get("downloads") or 0),
        "likes": int(data.get("likes") or 0),
        "tags": (data.get("tags") or [])[:20],
        "license": _huggingface_license(data),
        "updated_at": data.get("lastModified") or "",
        "card_excerpt": card,
        "config_excerpt": config,
        "files": siblings,
        "analysis_basis": ", ".join(basis_parts) or "Hugging Face API metadata",
        "inspected": True,
    }


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
            "fields": "title,abstract,url,year,venue,publicationDate,citationCount,authors,openAccessPdf,externalIds",
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
                "pdf_url": (paper.get("openAccessPdf") or {}).get("url") or "",
                "doi": (paper.get("externalIds") or {}).get("DOI") or "",
                "provider": "Semantic Scholar",
                "inspected": False,
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
                "pdf_url": (work.get("best_oa_location") or {}).get("pdf_url")
                or (work.get("primary_location") or {}).get("pdf_url")
                or "",
                "doi": work.get("doi") or "",
                "provider": "OpenAlex",
                "inspected": False,
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
                "pdf_url": (entry.findtext("atom:id", default="", namespaces=namespace) or "")
                .replace("http://arxiv.org/abs/", "https://arxiv.org/pdf/")
                .replace("https://arxiv.org/abs/", "https://arxiv.org/pdf/"),
                "provider": "arXiv",
                "inspected": False,
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


def extract_pdf_evidence(pdf_data):
    reader = PdfReader(io.BytesIO(pdf_data))
    pages = []
    for index, page in enumerate(reader.pages[:80]):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:
            text = ""
        if text:
            pages.append((index + 1, text))

    if not pages:
        raise ValueError("PDF contains no extractable text")

    keywords = (
        "method",
        "methodology",
        "approach",
        "architecture",
        "experiment",
        "evaluation",
        "result",
        "discussion",
        "conclusion",
        "limitation",
        "方法",
        "實驗",
        "結果",
        "結論",
        "限制",
    )
    selected = {number for number, _ in pages[:2]}
    selected.add(pages[-1][0])
    for number, text in pages:
        lowered = text.lower()
        if any(keyword in lowered for keyword in keywords):
            selected.add(number)
        if len(selected) >= 10:
            break

    chunks = []
    for number, text in pages:
        if number in selected:
            chunks.append(f"[Page {number}]\n{text}")
    evidence = "\n\n".join(chunks)
    return evidence[:PAPER_CONTENT_LIMIT], len(reader.pages), sorted(selected)


def html_to_text(raw_html):
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", str(raw_html or ""))
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return short_text(html.unescape(text), PAPER_CONTENT_LIMIT)


def inspect_paper_source(source):
    metadata = source.get("metadata") or {}
    abstract = source.get("description") or ""
    pdf_url = str(metadata.get("pdf_url") or "").strip()
    paper_text = ""
    page_count = 0
    selected_pages = []
    analysis_basis = ""
    full_text_available = False

    candidate_pdf_urls = []
    for url in (pdf_url, source.get("url")):
        if not url:
            continue
        if "arxiv.org/pdf/" in url and not url.endswith(".pdf"):
            candidate_pdf_urls.append(f"{url}.pdf")
        candidate_pdf_urls.append(url)
    for url in candidate_pdf_urls:
        try:
            pdf_data = request_bytes(url)
            if not pdf_data.startswith(b"%PDF"):
                continue
            paper_text, page_count, selected_pages = extract_pdf_evidence(pdf_data)
            analysis_basis = "公開 PDF 全文的重要頁面"
            pdf_url = url
            full_text_available = True
            break
        except Exception:
            continue

    arxiv_match = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?", " ".join(candidate_pdf_urls))
    if not paper_text and arxiv_match:
        try:
            ar5iv_text = html_to_text(
                request_text(f"https://ar5iv.labs.arxiv.org/html/{arxiv_match.group(1)}")
            )
        except Exception:
            ar5iv_text = ""
        if ar5iv_text:
            paper_text = ar5iv_text
            analysis_basis = "公開論文全文的 HTML 版本"
            full_text_available = True

    if not paper_text:
        try:
            landing_text = html_to_text(request_text(source.get("url")))
        except Exception:
            landing_text = ""
        if landing_text and any(
            marker in landing_text.lower()
            for marker in ("abstract", "authors", "doi", "journal", "conference", "proceedings")
        ):
            paper_text = landing_text
            analysis_basis = "論文頁面可讀文字"

    if not paper_text and abstract:
        paper_text = abstract
        analysis_basis = "摘要與書目資料（未取得可解析全文）"

    if not paper_text:
        raise ValueError("unable to verify paper content")

    return {
        "paper_text": paper_text,
        "pdf_url": pdf_url,
        "page_count": page_count,
        "selected_pages": selected_pages,
        "analysis_basis": analysis_basis,
        "full_text_available": full_text_available,
        "inspected": True,
    }


class SourceRegistry:
    def __init__(self):
        self._sources = []
        self._by_url = {}

    def add(self, source_type, title, url, description="", metadata=None):
        url = str(url or "").strip()
        if not url.startswith(("http://", "https://")):
            return None
        if url in self._by_url:
            source = self._by_url[url]
            new_description = short_text(description, 2000)
            if len(new_description) > len(source["description"]):
                source["description"] = new_description
            if title and source["title"] == source["url"]:
                source["title"] = str(title).strip()
            if metadata:
                source["metadata"].update(metadata)
            if source["source_type"].endswith("_candidate") or not str(source_type).endswith("_candidate"):
                source["source_type"] = str(source_type)
            return source

        source = {
            "source_id": f"source_{len(self._sources) + 1}",
            "source_type": str(source_type or "web"),
            "title": str(title or url).strip(),
            "url": url,
            "description": short_text(description, 2000),
            "metadata": {"inspected": False, **(metadata or {})},
        }
        self._sources.append(source)
        self._by_url[url] = source
        return source

    def get(self, source_id):
        for source in self._sources:
            if source["source_id"] == source_id:
                return source
        return None

    def all(self):
        return list(self._sources)

    def update(self, source_id, source_type=None, description=None, metadata=None):
        source = self.get(source_id)
        if not source:
            return None
        if source_type:
            source["source_type"] = str(source_type)
        if description and len(str(description)) > len(source["description"]):
            source["description"] = short_text(description, 2000)
        if metadata:
            source["metadata"].update(metadata)
        return source


def source_for_result(registry, source_type, result):
    title = result.get("name") or result.get("title") or result.get("url")
    description = result.get("description") or result.get("abstract") or result.get("readme_excerpt") or ""
    evidence_keys = {
        "readme_excerpt",
        "tree_paths",
        "key_files",
        "card_excerpt",
        "config_excerpt",
        "files",
        "paper_text",
    }
    metadata = {
        key: value
        for key, value in result.items()
        if key not in {"name", "title", "url", "description", "abstract"} | evidence_keys
        and value not in (None, "", [], {})
    }
    source = registry.add(source_type, title, result.get("url"), description, metadata)
    if not source:
        return None
    payload = {
        "source_id": source["source_id"],
        "title": source["title"],
        "url": source["url"],
        "description": source["description"],
        "metadata": source["metadata"],
    }
    evidence = {key: result.get(key) for key in evidence_keys if result.get(key)}
    if evidence:
        payload["evidence"] = evidence
    return payload


def github_repository_from_url(url):
    parsed = urlparse(str(url or ""))
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return ""
    repository = f"{parts[0]}/{parts[1].removesuffix('.git')}"
    try:
        return validate_repository(repository)
    except ValueError:
        return ""


def huggingface_resource_from_url(url):
    parsed = urlparse(str(url or ""))
    if parsed.netloc.lower() not in {"huggingface.co", "www.huggingface.co"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 3 and parts[0] == "datasets":
        return {"resource_type": "dataset", "resource_id": f"{parts[1]}/{parts[2]}"}
    if len(parts) >= 2 and parts[0] not in {"spaces", "blog", "docs", "datasets"}:
        return {"resource_type": "model", "resource_id": f"{parts[0]}/{parts[1]}"}
    return None


def register_results(registry, source_type, results):
    registered = []
    for result in results:
        source = source_for_result(registry, source_type, result)
        if source:
            registered.append(source)
    return registered


def execute_tool(name, arguments, registry):
    query = str(arguments.get("query") or "").strip()
    limit = clamp_limit(arguments.get("limit"), 8)

    if name == "discover_online":
        source_kind = str(arguments.get("source_kind") or "").strip()
        result = web_research(query, source_kind)
        registered = []
        for item in result.get("sources", []):
            url = item.get("url") or ""
            metadata = {
                "inspected": False,
                "discovered_online": True,
                "discovery_summary": short_text(result.get("summary"), 1800),
            }
            if source_kind == "github":
                repository = github_repository_from_url(url)
                if not repository:
                    continue
                url = f"https://github.com/{repository}"
                metadata["repository"] = repository
                candidate_type = "github_candidate"
            elif source_kind == "huggingface":
                resource = huggingface_resource_from_url(url)
                if not resource:
                    continue
                prefix = "datasets/" if resource["resource_type"] == "dataset" else ""
                url = f"https://huggingface.co/{prefix}{resource['resource_id']}"
                metadata.update(resource)
                candidate_type = "huggingface_candidate"
            elif source_kind == "paper":
                candidate_type = "paper_candidate"
            else:
                continue
            source = registry.add(candidate_type, item.get("title"), url, metadata=metadata)
            if source:
                registered.append(
                    {
                        "source_id": source["source_id"],
                        "title": source["title"],
                        "url": source["url"],
                        "metadata": source["metadata"],
                    }
                )
        return {"summary": result.get("summary", ""), "results": registered}

    if name == "search_github":
        return {"results": register_results(registry, "github", github_search(query, limit))}

    if name == "search_github_code":
        return {"results": register_results(registry, "github", github_code_search(query, limit))}

    if name == "inspect_github_repository":
        result = inspect_github_repository(arguments.get("repository"))
        return {"results": register_results(registry, "github", [result])}

    if name == "read_github_file":
        repository = validate_repository(arguments.get("repository"))
        path = str(arguments.get("path") or "").strip()
        content = read_github_file(repository, path)
        source = registry.add(
            "github",
            repository,
            f"https://github.com/{repository}",
        )
        return {
            "source_id": source["source_id"] if source else "",
            "repository": repository,
            "path": path,
            "content": content,
        }

    if name == "search_huggingface_models":
        return {
            "results": register_results(
                registry,
                "huggingface_model",
                huggingface_model_search(query, limit),
            )
        }

    if name == "search_huggingface_datasets":
        return {
            "results": register_results(
                registry,
                "huggingface_dataset",
                huggingface_dataset_search(query, limit),
            )
        }

    if name == "inspect_huggingface_resource":
        resource_type = str(arguments.get("resource_type") or "")
        result = inspect_huggingface_resource(arguments.get("resource_id"), resource_type)
        source_type = "huggingface_model" if resource_type == "model" else "huggingface_dataset"
        return {"results": register_results(registry, source_type, [result])}

    if name == "search_papers":
        return {"results": register_results(registry, "paper", paper_search(query, limit))}

    if name == "inspect_paper":
        source_id = str(arguments.get("source_id") or "").strip()
        source = registry.get(source_id)
        if not source or source["source_type"] not in {"paper", "paper_candidate"}:
            raise ValueError("source_id is not a paper candidate")
        inspection = inspect_paper_source(source)
        source = registry.update(source_id, source_type="paper", metadata=inspection)
        return {
            "source_id": source_id,
            "title": source["title"],
            "url": source["url"],
            "description": source["description"],
            "metadata": source["metadata"],
            "evidence": {"paper_text": inspection["paper_text"]},
        }

    raise ValueError(f"unknown tool: {name}")


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


def normalize_research_plan(data):
    allowed_types = {"github", "huggingface_model", "huggingface_dataset", "paper"}
    allowed_source_kinds = {"github", "huggingface", "paper"}
    raw = data if isinstance(data, dict) else {}

    resource_types = []
    for resource_type in raw.get("resource_types", []):
        resource_type = str(resource_type or "").strip()
        if resource_type in allowed_types and resource_type not in resource_types:
            resource_types.append(resource_type)

    search_queries = []
    seen_queries = set()
    for item in raw.get("search_queries", []):
        if not isinstance(item, dict):
            continue
        source_kind = str(item.get("source_kind") or "").strip()
        query = normalize_text_for_plan(item.get("query"))
        key = (source_kind, query.lower())
        if source_kind not in allowed_source_kinds or not query or key in seen_queries:
            continue
        seen_queries.add(key)
        search_queries.append({"source_kind": source_kind, "query": query})
        if len(search_queries) >= 8:
            break

    priority_terms = []
    for term in raw.get("priority_terms", []):
        term = normalize_text_for_plan(term)
        if term and term not in priority_terms:
            priority_terms.append(term)
        if len(priority_terms) >= 12:
            break

    return {
        "intent_summary": normalize_text_for_plan(raw.get("intent_summary", "")),
        "resource_types": resource_types,
        "search_queries": search_queries,
        "priority_terms": priority_terms,
    }


def normalize_text_for_plan(value, limit=500):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def fallback_research_plan(query, required_types=None):
    required_types = list(required_types or [])
    search_queries = []
    if not required_types or "github" in required_types:
        search_queries.append({"source_kind": "github", "query": f"{query} GitHub"})
    if "huggingface_model" in required_types or "huggingface_dataset" in required_types:
        search_queries.append({"source_kind": "huggingface", "query": str(query)})
    if "paper" in required_types:
        search_queries.append({"source_kind": "paper", "query": str(query)})
    return {
        "intent_summary": normalize_text_for_plan(query),
        "resource_types": required_types,
        "search_queries": search_queries[:4],
        "priority_terms": [],
    }


def plan_research_query(query, explicit_types=None):
    try:
        response = get_client().responses.create(
            model=MODEL,
            instructions=PLANNER_INSTRUCTIONS,
            input=query,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "research_intent_plan",
                    "strict": True,
                    "schema": RESEARCH_PLAN_SCHEMA,
                }
            },
        )
        return normalize_research_plan(extract_json(response.output_text))
    except Exception:
        return fallback_research_plan(query, explicit_types)


def build_agent_input(query, plan):
    return (
        "原始使用者需求：\n"
        f"{query}\n\n"
        "需求理解器已先把自然語言整理成搜尋計畫。請優先依照這份計畫搜尋與 inspect，"
        "但如果搜尋結果不足，可以根據原始需求補充合理查詢。最終仍只能推薦已完成 inspect 的有效來源。\n\n"
        f"{json.dumps(plan, ensure_ascii=False)}"
    )


def explicit_required_types(query):
    lowered = str(query or "").lower()
    if "skill" in lowered:
        return {"github"}
    if "資料集" in lowered or "dataset" in lowered:
        return {"huggingface_dataset", "github"}
    if "模型" in lowered or re.search(r"\bmodels?\b", lowered):
        return {"huggingface_model", "github"}
    if "論文" in lowered or re.search(r"\b(papers?|research paper)\b", lowered):
        return {"paper"}
    return set()


def ensure_required_inspections(registry, required_types, target_count=3):
    if not required_types:
        return []

    def matches(source):
        source_type = source["source_type"]
        if source_type in required_types:
            return True
        if source_type == "github_candidate" and "github" in required_types:
            return True
        if source_type == "huggingface_candidate":
            resource_type = source["metadata"].get("resource_type")
            return (
                resource_type == "model" and "huggingface_model" in required_types
            ) or (
                resource_type == "dataset" and "huggingface_dataset" in required_types
            )
        return source_type == "paper_candidate" and "paper" in required_types

    inspected_count = sum(
        1
        for source in registry.all()
        if matches(source) and source["metadata"].get("inspected")
    )
    supplements = []
    for source in registry.all():
        if inspected_count >= target_count:
            break
        if not matches(source) or source["metadata"].get("inspected"):
            continue
        try:
            source_type = source["source_type"]
            if source_type in {"github", "github_candidate"}:
                repository = source["metadata"].get("repository") or github_repository_from_url(source["url"])
                result = inspect_github_repository(repository)
                supplements.extend(register_results(registry, "github", [result]))
            elif source_type in {"huggingface_model", "huggingface_dataset", "huggingface_candidate"}:
                resource = huggingface_resource_from_url(source["url"])
                if not resource:
                    continue
                result = inspect_huggingface_resource(resource["resource_id"], resource["resource_type"])
                final_type = "huggingface_model" if resource["resource_type"] == "model" else "huggingface_dataset"
                supplements.extend(register_results(registry, final_type, [result]))
            elif source_type in {"paper", "paper_candidate"}:
                inspection = inspect_paper_source(source)
                registry.update(source["source_id"], source_type="paper", metadata=inspection)
                supplements.append(
                    {
                        "source_id": source["source_id"],
                        "title": source["title"],
                        "url": source["url"],
                        "description": source["description"],
                        "metadata": source["metadata"],
                        "evidence": {"paper_text": inspection["paper_text"]},
                    }
                )
            inspected_count += 1
        except Exception:
            continue
    return supplements


def normalize_advice(data, registry, required_types=None):
    def visible_text(value, limit=1600):
        text = str(value or "").strip()
        text = re.sub(r"(?i)\bsource_id\s*:?\s*source_\d+\b", "", text)
        text = re.sub(r"\bsource_\d+\b", "", text)
        return re.sub(r"\s+", " ", text).strip()[:limit]

    allowed_types = {"github", "huggingface_model", "huggingface_dataset", "paper"}
    sections = []
    total_items = 0
    seen_source_ids = set()

    for raw_section in data.get("sections", [])[:4]:
        title = visible_text(raw_section.get("title"), 80)
        summary = visible_text(raw_section.get("summary"), 400)
        items = []
        for raw_item in raw_section.get("items", []):
            if total_items >= MAX_FINAL_RESULTS:
                break
            source_id = str(raw_item.get("source_id") or "").strip()
            source = registry.get(source_id)
            if (
                not source
                or source_id in seen_source_ids
                or source["source_type"] not in allowed_types
                or (required_types and source["source_type"] not in required_types)
                or not source["metadata"].get("inspected")
            ):
                continue
            limitations = visible_text(raw_item.get("limitations"), 700)
            if source["source_type"] == "paper" and not source["metadata"].get("full_text_available"):
                abstract_notice = "未取得可解析全文，本項分析以摘要與書目資料為主。"
                if abstract_notice not in limitations:
                    limitations = f"{limitations} {abstract_notice}".strip()
            items.append(
                {
                    "title": visible_text(raw_item.get("title") or source["title"], 160),
                    "description": visible_text(raw_item.get("description"), 700),
                    "how_it_works": visible_text(raw_item.get("how_it_works"), 1000),
                    "why_relevant": visible_text(raw_item.get("why_relevant"), 700),
                    "limitations": limitations,
                    "evidence_basis": visible_text(
                        source["metadata"].get("analysis_basis")
                        or raw_item.get("evidence_basis"),
                        300,
                    ),
                    "url": source["url"],
                    "source_type": source["source_type"],
                }
            )
            seen_source_ids.add(source_id)
            total_items += 1
        if items:
            sections.append({"title": title or "相關資源", "summary": summary, "items": items})

    return {
        "answer": visible_text(data.get("answer"), 500),
        "sections": sections,
    }


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
    return sources[:8]


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
    if "arxiv.org" in host or "doi.org" in host or "ieee.org" in host or "sciencedirect.com" in host:
        return "paper"
    return "web"


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

    for raw_section in data.get("sections", [])[:4]:
        if not isinstance(raw_section, dict):
            continue
        items = []
        for raw_item in raw_section.get("items", [])[:4]:
            if not isinstance(raw_item, dict) or total_items >= MAX_FINAL_RESULTS:
                continue
            url = str(raw_item.get("url") or "").strip()
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
            total_items += 1
        if items:
            sections.append(
                {
                    "title": visible_advice_text(raw_section.get("title") or "顧問建議", 80),
                    "summary": visible_advice_text(raw_section.get("summary"), 400),
                    "items": items,
                }
            )

    if not sections and grounding_sources:
        sections.append(
            {
                "title": "參考來源",
                "summary": "以下是 Gemini Google Search grounding 回傳的查證來源。",
                "items": grounding_sources[:MAX_FINAL_RESULTS],
            }
        )

    return {"answer": answer or GEMINI_SERVICE_UNAVAILABLE_MESSAGE, "sections": sections}


def call_gemini_grounded_advisor(query):
    api_key = gemini_api_key()
    if not api_key:
        return gemini_error_response()

    url = GEMINI_API_URL.format(model=quote(gemini_model(), safe=""))
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": gemini_consultant_prompt(query)}],
            }
        ],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "temperature": 0.2,
            "topP": 0.9,
        },
    }
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
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
