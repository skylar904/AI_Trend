import base64
import json
import os
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from api_sources import API_RSS_REPLACEMENTS, API_SOURCES
from cleaning import clean_article, dedupe_articles
from trend_config import DEFAULT_SOURCE_WEIGHT


REQUEST_TIMEOUT = 25


def request_json(url, params=None, headers=None, method="GET", body=None):
    query = urlencode(params or {})
    request_url = f"{url}?{query}" if query and method == "GET" else url
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "AI-Trend-Dashboard",
        **(headers or {}),
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    request = Request(request_url, data=data, headers=request_headers, method=method)
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def request_text(url, params=None, headers=None):
    query = urlencode(params or {})
    request_url = f"{url}?{query}" if query else url
    request = Request(
        request_url,
        headers={
            "Accept": "application/xml, text/xml, application/json",
            "User-Agent": "AI-Trend-Dashboard",
            **(headers or {}),
        },
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return response.read().decode("utf-8")


def has_required_env(source):
    return all(os.getenv(name) for name in source.get("requires_env", []))


def base_article(source, title, link, summary, published=""):
    return clean_article(
        {
            "source": source["name"],
            "category": source["category"],
            "title": title,
            "link": link,
            "published": published,
            "summary": summary,
            "source_weight": source.get("weight", DEFAULT_SOURCE_WEIGHT),
            "source_group": source.get("source_group", ""),
            "source_group_label": source.get("source_group_label", ""),
        }
    )


def collect_github_search(source):
    token = os.getenv("GITHUB_TOKEN", "")
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    per_query = max(1, source["max_entries"] // len(source["queries"]))
    articles = []
    seen = set()

    for query in source["queries"]:
        data = request_json(
            "https://api.github.com/search/repositories",
            params={
                "q": query,
                "sort": "updated",
                "order": "desc",
                "per_page": per_query,
            },
            headers=headers,
        )
        for repo in data.get("items", []):
            full_name = repo.get("full_name") or repo.get("name", "")
            if not full_name or full_name in seen:
                continue
            seen.add(full_name)
            topics = ", ".join(repo.get("topics") or [])
            summary = (
                f"{repo.get('description') or ''}\n"
                f"Stars: {repo.get('stargazers_count', 0)}. "
                f"Forks: {repo.get('forks_count', 0)}. "
                f"Language: {repo.get('language') or 'unknown'}. "
                f"Topics: {topics}."
            )
            articles.append(
                base_article(
                    source,
                    f"GitHub repo: {full_name}",
                    repo.get("html_url", ""),
                    summary,
                    repo.get("updated_at", ""),
                )
            )
    return articles[: source["max_entries"]]


def collect_huggingface_models(source):
    token = os.getenv("HF_TOKEN", "")
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    per_search = max(1, source["max_entries"] // len(source["searches"]))
    articles = []
    seen = set()

    for search in source["searches"]:
        data = request_json(
            "https://huggingface.co/api/models",
            params={
                "search": search,
                "sort": "lastModified",
                "direction": "-1",
                "limit": per_search,
                "full": "true",
            },
            headers=headers,
        )
        for model in data:
            model_id = model.get("modelId") or model.get("id", "")
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            tags = ", ".join((model.get("tags") or [])[:12])
            summary = (
                f"Hugging Face model for {model.get('pipeline_tag') or 'AI tasks'}. "
                f"Downloads: {model.get('downloads', 0)}. "
                f"Likes: {model.get('likes', 0)}. "
                f"Tags: {tags}."
            )
            articles.append(
                base_article(
                    source,
                    f"Hugging Face model: {model_id}",
                    f"https://huggingface.co/{model_id}",
                    summary,
                    model.get("lastModified", ""),
                )
            )
    return articles[: source["max_entries"]]


def collect_arxiv(source):
    xml = request_text(
        "https://export.arxiv.org/api/query",
        params={
            "search_query": source["query"],
            "sortBy": "lastUpdatedDate",
            "sortOrder": "descending",
            "max_results": source["max_entries"],
        },
    )
    root = ElementTree.fromstring(xml)
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    articles = []
    for entry in root.findall("atom:entry", namespace):
        title = entry.findtext("atom:title", default="", namespaces=namespace)
        summary = entry.findtext("atom:summary", default="", namespaces=namespace)
        published = entry.findtext("atom:updated", default="", namespaces=namespace)
        link = entry.findtext("atom:id", default="", namespaces=namespace)
        for link_node in entry.findall("atom:link", namespace):
            if link_node.attrib.get("rel") == "alternate":
                link = link_node.attrib.get("href", link)
                break
        articles.append(base_article(source, title, link, summary, published))
    return articles


def collect_semantic_scholar(source):
    headers = {}
    semantic_scholar_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    if semantic_scholar_key:
        headers["x-api-key"] = semantic_scholar_key

    data = request_json(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params={
            "query": source["query"],
            "limit": source["max_entries"],
            "fields": "title,abstract,url,year,venue,publicationDate,citationCount,authors",
        },
        headers=headers,
    )
    articles = []
    for paper in data.get("data", []):
        authors = ", ".join(author.get("name", "") for author in paper.get("authors", [])[:4])
        summary = (
            f"{paper.get('abstract') or ''}\n"
            f"Venue: {paper.get('venue') or 'unknown'}. "
            f"Year: {paper.get('year') or 'unknown'}. "
            f"Citations: {paper.get('citationCount', 0)}. "
            f"Authors: {authors}."
        )
        articles.append(
            base_article(
                source,
                paper.get("title", ""),
                paper.get("url", ""),
                summary,
                paper.get("publicationDate", ""),
            )
        )
    return articles


def openalex_abstract(inverted_index):
    if not inverted_index:
        return ""
    words = []
    for word, positions in inverted_index.items():
        for position in positions:
            words.append((position, word))
    return " ".join(word for _, word in sorted(words))


def collect_openalex(source):
    data = request_json(
        "https://api.openalex.org/works",
        params={
            "search": source["query"],
            "sort": "publication_date:desc",
            "per-page": source["max_entries"],
        },
    )
    articles = []
    for work in data.get("results", []):
        title = work.get("display_name", "")
        link = work.get("doi") or work.get("id", "")
        summary = (
            f"{openalex_abstract(work.get('abstract_inverted_index'))}\n"
            f"Citations: {work.get('cited_by_count', 0)}. "
            f"Publication year: {work.get('publication_year') or 'unknown'}."
        )
        articles.append(
            base_article(
                source,
                title,
                link,
                summary,
                work.get("publication_date", ""),
            )
        )
    return articles


def collect_hacker_news(source):
    ids = request_json("https://hacker-news.firebaseio.com/v0/topstories.json")
    articles = []
    for story_id in ids[: source["max_entries"]]:
        item = request_json(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
        if not item or item.get("type") != "story":
            continue
        summary = (
            f"Hacker News story. Score: {item.get('score', 0)}. "
            f"Comments: {item.get('descendants', 0)}."
        )
        articles.append(
            base_article(
                source,
                item.get("title", ""),
                item.get("url") or f"https://news.ycombinator.com/item?id={story_id}",
                summary,
                datetime.fromtimestamp(item.get("time", 0)).strftime("%Y-%m-%d %H:%M:%S")
                if item.get("time")
                else "",
            )
        )
    return articles


def collect_product_hunt(source):
    token = os.getenv("PRODUCT_HUNT_TOKEN", "")
    query = """
    query TodayPosts($first: Int!) {
      posts(first: $first, order: VOTES) {
        edges {
          node {
            id
            name
            tagline
            url
            votesCount
            commentsCount
            createdAt
            topics { edges { node { name } } }
          }
        }
      }
    }
    """
    data = request_json(
        "https://api.producthunt.com/v2/api/graphql",
        headers={"Authorization": f"Bearer {token}"},
        method="POST",
        body={"query": query, "variables": {"first": source["max_entries"]}},
    )
    articles = []
    for edge in data.get("data", {}).get("posts", {}).get("edges", []):
        post = edge.get("node", {})
        topics = [
            topic_edge.get("node", {}).get("name", "")
            for topic_edge in post.get("topics", {}).get("edges", [])
        ]
        summary = (
            f"{post.get('tagline') or ''}\n"
            f"Votes: {post.get('votesCount', 0)}. "
            f"Comments: {post.get('commentsCount', 0)}. "
            f"Topics: {', '.join(topic for topic in topics if topic)}."
        )
        articles.append(
            base_article(
                source,
                f"Product Hunt: {post.get('name', '')}",
                post.get("url", ""),
                summary,
                post.get("createdAt", ""),
            )
        )
    return articles


def reddit_access_token():
    client_id = os.getenv("REDDIT_CLIENT_ID", "")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    request = Request(
        "https://www.reddit.com/api/v1/access_token",
        data=urlencode({"grant_type": "client_credentials"}).encode("utf-8"),
        headers={
            "Authorization": f"Basic {credentials}",
            "User-Agent": "AI-Trend-Dashboard",
        },
        method="POST",
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))["access_token"]


def collect_reddit(source):
    token = reddit_access_token()
    subreddit_path = "+".join(source.get("subreddits", []))
    data = request_json(
        f"https://oauth.reddit.com/r/{subreddit_path}/hot",
        params={"limit": source["max_entries"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    articles = []
    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        summary = (
            f"{post.get('selftext') or ''}\n"
            f"Score: {post.get('score', 0)}. "
            f"Comments: {post.get('num_comments', 0)}. "
            f"Subreddit: r/{post.get('subreddit', '')}."
        )
        articles.append(
            base_article(
                source,
                post.get("title", ""),
                f"https://www.reddit.com{post.get('permalink', '')}",
                summary,
                datetime.fromtimestamp(post.get("created_utc", 0)).strftime("%Y-%m-%d %H:%M:%S")
                if post.get("created_utc")
                else "",
            )
        )
    return articles


COLLECTORS = {
    "github_search": collect_github_search,
    "huggingface_models": collect_huggingface_models,
    "arxiv": collect_arxiv,
    "semantic_scholar": collect_semantic_scholar,
    "openalex": collect_openalex,
    "hacker_news": collect_hacker_news,
    "product_hunt": collect_product_hunt,
    "reddit": collect_reddit,
}


def collect_api_candidates():
    candidates = []
    successful_sources = set()

    for source in API_SOURCES:
        if not has_required_env(source):
            required = ", ".join(source.get("requires_env", []))
            print(f"API 憑證未設定，略過 {source['name']}：{required}")
            continue

        print(f"正在巡邏 API 來源：{source['name']}")
        try:
            articles = COLLECTORS[source["api_type"]](source)
        except Exception as error:
            print(f"API 來源讀取失敗，略過 {source['name']}：{error}")
            continue

        candidates.extend(articles)
        successful_sources.add(source["key"])

    return dedupe_articles(candidates), successful_sources


def rss_replacements_for(successful_api_sources):
    replacements = set()
    for source_key in successful_api_sources:
        replacements.update(API_RSS_REPLACEMENTS.get(source_key, set()))
    return replacements
