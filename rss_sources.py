from trend_config import MAX_ENTRIES_PER_SOURCE


SOURCE_GROUPS = {
    "official": "官方公告",
    "research": "研究論文",
    "industry": "產業新聞",
    "community": "社群 / 趨勢",
}


def feed(name, url, category, source_group, weight, max_entries=None):
    return {
        "name": name,
        "url": url,
        "category": category,
        "source_group": source_group,
        "source_group_label": SOURCE_GROUPS[source_group],
        "max_entries": max_entries or MAX_ENTRIES_PER_SOURCE,
        "weight": weight,
    }


RSS_FEEDS = [
    # 1. 官方公告
    feed("OpenAI Blog", "https://openai.com/news/rss.xml", "官方公告", "official", 1.4),
    feed("Anthropic News", "https://www.anthropic.com/news/rss.xml", "官方公告", "official", 1.35),
    feed("Google DeepMind Blog", "https://deepmind.google/blog/rss.xml", "官方公告", "official", 1.35),
    feed(
        "Google AI Developers",
        "https://developers.googleblog.com/feeds/posts/default/-/AI",
        "官方公告",
        "official",
        1.25,
    ),
    feed("Microsoft AI Blog", "https://blogs.microsoft.com/ai/feed/", "官方公告", "official", 1.25),
    feed(
        "Microsoft Research",
        "https://www.microsoft.com/en-us/research/feed/",
        "官方公告",
        "official",
        1.15,
    ),
    feed(
        "Microsoft Agent Framework",
        "https://devblogs.microsoft.com/semantic-kernel/feed/",
        "AI Agent / Agentic Workflow",
        "official",
        1.2,
    ),
    feed(
        "NVIDIA AI Developer Blog",
        "https://developer.nvidia.com/blog/category/artificial-intelligence/feed/",
        "官方公告",
        "official",
        1.25,
    ),
    feed("NVIDIA Newsroom", "https://nvidianews.nvidia.com/rss", "官方公告", "official", 1.1),
    feed("Hugging Face Blog", "https://huggingface.co/blog/feed.xml", "官方公告", "official", 1.2),
    feed(
        "AWS Machine Learning Blog",
        "https://aws.amazon.com/blogs/machine-learning/feed/",
        "官方公告",
        "official",
        1.15,
    ),

    # 2. 研究論文
    feed("arXiv cs.AI", "https://export.arxiv.org/rss/cs.AI", "研究論文", "research", 1.0, 5),
    feed("arXiv cs.CL", "https://export.arxiv.org/rss/cs.CL", "研究論文", "research", 1.0, 5),
    feed("arXiv cs.LG", "https://export.arxiv.org/rss/cs.LG", "研究論文", "research", 1.0, 5),
    feed("arXiv stat.ML", "https://export.arxiv.org/rss/stat.ML", "研究論文", "research", 0.95, 5),
    feed("Papers with Code", "https://paperswithcode.com/rss", "研究論文", "research", 0.95, 5),
    feed("Hugging Face Papers", "https://huggingface.co/papers/rss", "研究論文", "research", 1.0, 5),

    # 3. 產業新聞
    feed(
        "TechCrunch AI",
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "產業新聞",
        "industry",
        1.1,
    ),
    feed(
        "The Verge AI",
        "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        "產業新聞",
        "industry",
        1.0,
    ),
    feed("VentureBeat AI", "https://venturebeat.com/category/ai/feed/", "產業新聞", "industry", 1.05),
    feed(
        "MIT Technology Review AI",
        "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
        "產業新聞",
        "industry",
        1.05,
    ),
    feed("InfoQ AI ML", "https://feed.infoq.com/ai-ml-data-eng", "產業新聞", "industry", 1.05),
    feed("The Decoder", "https://the-decoder.com/feed/", "產業新聞", "industry", 1.0),

    # 4. 社群 / 趨勢
    feed("Hacker News", "https://news.ycombinator.com/rss", "社群 / 趨勢", "community", 0.8),
    feed("Product Hunt", "https://www.producthunt.com/feed", "社群 / 趨勢", "community", 0.85),
    feed(
        "Reddit MachineLearning",
        "https://www.reddit.com/r/MachineLearning/.rss",
        "社群 / 趨勢",
        "community",
        0.8,
        5,
    ),
    feed(
        "Reddit LocalLLaMA",
        "https://www.reddit.com/r/LocalLLaMA/.rss",
        "社群 / 趨勢",
        "community",
        0.85,
        5,
    ),
    feed("Lobsters AI", "https://lobste.rs/t/ai.rss", "社群 / 趨勢", "community", 0.75, 5),
    feed(
        "Lobsters Machine Learning",
        "https://lobste.rs/t/machine_learning.rss",
        "社群 / 趨勢",
        "community",
        0.75,
        5,
    ),
    feed(
        "LangChain Blog",
        "https://blog.langchain.com/rss/",
        "AI Agent / Agentic Workflow",
        "community",
        1.15,
        8,
    ),
]


PLANNED_CUSTOM_SOURCES = [
    {
        "name": "CrewAI Blog",
        "url": "https://crewai.com/blog",
        "category": "AI Agent / Agentic Workflow",
        "source_group": "community",
        "source_group_label": SOURCE_GROUPS["community"],
        "reason": "CrewAI blog 目前沒有明確公開 RSS，適合用自訂爬蟲解析文章列表。",
    },
    {
        "name": "Vercel AI SDK / Agentic Infrastructure",
        "url": "https://vercel.com/blog",
        "category": "AI Agent / Agentic Workflow",
        "source_group": "industry",
        "source_group_label": SOURCE_GROUPS["industry"],
        "reason": "Vercel blog 有大量 AI SDK、agent、workflow 內容，但 RSS 入口不穩定，適合之後改用自訂爬蟲或官方 API。",
    },
    {
        "name": "LlamaIndex Blog",
        "url": "https://www.llamaindex.ai/blog",
        "category": "AI Agent / Agentic Workflow",
        "source_group": "community",
        "source_group_label": SOURCE_GROUPS["community"],
        "reason": "LlamaIndex agent 內容重要，但需確認穩定 feed 或自訂爬蟲。",
    },
    {
        "name": "OpenAI Agents SDK",
        "url": "https://openai.github.io/openai-agents-python/",
        "category": "AI Agent / Agentic Workflow",
        "source_group": "official",
        "source_group_label": SOURCE_GROUPS["official"],
        "reason": "文件型來源不是 RSS，之後可做 docs crawler 或版本更新監控。",
    },
]
