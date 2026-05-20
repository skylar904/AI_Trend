from trend_config import MAX_ENTRIES_PER_SOURCE


RSS_FEEDS = [
    {
        "name": "Hacker News",
        "url": "https://news.ycombinator.com/rss",
        "category": "工程 / 科技討論",
        "max_entries": MAX_ENTRIES_PER_SOURCE,
        "weight": 0.8,
    },
    {
        "name": "TechCrunch AI",
        "url": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "category": "AI 新聞",
        "max_entries": MAX_ENTRIES_PER_SOURCE,
        "weight": 1.1,
    },
    {
        "name": "OpenAI Blog",
        "url": "https://openai.com/news/rss.xml",
        "category": "官方消息",
        "max_entries": MAX_ENTRIES_PER_SOURCE,
        "weight": 1.35,
    },
    {
        "name": "Google DeepMind Blog",
        "url": "https://deepmind.google/blog/rss.xml",
        "category": "官方消息",
        "max_entries": MAX_ENTRIES_PER_SOURCE,
        "weight": 1.3,
    },
    {
        "name": "Hugging Face Blog",
        "url": "https://huggingface.co/blog/feed.xml",
        "category": "AI / 開源模型",
        "max_entries": MAX_ENTRIES_PER_SOURCE,
        "weight": 1.2,
    },
    {
        "name": "The Verge AI",
        "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
        "category": "AI 產品 / 產業",
        "max_entries": MAX_ENTRIES_PER_SOURCE,
        "weight": 1.0,
    },
    {
        "name": "InfoQ AI ML",
        "url": "https://feed.infoq.com/ai-ml-data-eng",
        "category": "AI 工程 / MLOps",
        "max_entries": MAX_ENTRIES_PER_SOURCE,
        "weight": 1.05,
    },
    {
        "name": "arXiv cs.AI",
        "url": "https://export.arxiv.org/rss/cs.AI",
        "category": "研究論文",
        "max_entries": MAX_ENTRIES_PER_SOURCE,
        "weight": 1.0,
    },
    {
        "name": "arXiv cs.CL",
        "url": "https://export.arxiv.org/rss/cs.CL",
        "category": "研究論文",
        "max_entries": MAX_ENTRIES_PER_SOURCE,
        "weight": 1.0,
    },
]
