import os
import json
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen


REQUEST_TIMEOUT = 20
GITHUB_API_URL = "https://api.github.com/search/repositories"
HUGGING_FACE_API_URL = "https://huggingface.co/api/models"


def request_json(url, params=None, token=None, token_type="Bearer"):
    headers = {
        "Accept": "application/json",
        "User-Agent": "AI-Trend-Dashboard",
    }
    if token:
        headers["Authorization"] = f"{token_type} {token}"

    query = urlencode(params or {})
    request_url = f"{url}?{query}" if query else url
    request = Request(request_url, headers=headers)

    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def collect_github_top(limit=10):
    token = os.getenv("GITHUB_TOKEN", "")
    data = request_json(
        GITHUB_API_URL,
        params={
            "q": "stars:>1",
            "sort": "stars",
            "order": "desc",
            "per_page": limit,
        },
        token=token,
        token_type="Bearer",
    )

    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    items = []
    for index, repo in enumerate(data.get("items", [])[:limit], start=1):
        stars = int(repo.get("stargazers_count") or 0)
        forks = int(repo.get("forks_count") or 0)
        items.append(
            {
                "platform": "github",
                "item_id": str(repo.get("full_name") or repo.get("id")),
                "name": repo.get("full_name") or repo.get("name", ""),
                "url": repo.get("html_url", ""),
                "description": repo.get("description") or "",
                "rank": index,
                "score": stars,
                "primary_metric_name": "stars",
                "primary_metric_value": stars,
                "secondary_metric_name": "forks",
                "secondary_metric_value": forks,
                "category": repo.get("language") or "",
                "tags": repo.get("topics") or [],
                "metrics": {
                    "stars": stars,
                    "forks": forks,
                    "watchers": int(repo.get("watchers_count") or 0),
                    "open_issues": int(repo.get("open_issues_count") or 0),
                    "language": repo.get("language") or "",
                    "updated_at": repo.get("updated_at") or "",
                },
                "fetched_at": fetched_at,
            }
        )
    return items


def collect_huggingface_top(limit=10):
    token = os.getenv("HF_TOKEN", "")
    data = request_json(
        HUGGING_FACE_API_URL,
        params={
            "sort": "downloads",
            "direction": "-1",
            "limit": limit,
            "full": "true",
        },
        token=token,
        token_type="Bearer",
    )

    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    items = []
    for index, model in enumerate(data[:limit], start=1):
        model_id = model.get("modelId") or model.get("id", "")
        downloads = int(model.get("downloads") or 0)
        likes = int(model.get("likes") or 0)
        tags = model.get("tags") or []
        items.append(
            {
                "platform": "huggingface",
                "item_id": str(model_id),
                "name": model_id,
                "url": f"https://huggingface.co/{model_id}" if model_id else "",
                "description": model.get("cardData", {}).get("summary") or "",
                "rank": index,
                "score": downloads,
                "primary_metric_name": "downloads",
                "primary_metric_value": downloads,
                "secondary_metric_name": "likes",
                "secondary_metric_value": likes,
                "category": model.get("pipeline_tag") or "",
                "tags": tags[:10],
                "metrics": {
                    "downloads": downloads,
                    "likes": likes,
                    "pipeline_tag": model.get("pipeline_tag") or "",
                    "last_modified": model.get("lastModified") or "",
                    "library_name": model.get("library_name") or "",
                },
                "fetched_at": fetched_at,
            }
        )
    return items


def collect_platform_top(limit=10):
    return {
        "github": collect_github_top(limit),
        "huggingface": collect_huggingface_top(limit),
    }
