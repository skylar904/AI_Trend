import os


MAX_DAILY_ARTICLES = int(os.getenv("MAX_DAILY_ARTICLES", "30"))
MAX_ENTRIES_PER_SOURCE = int(os.getenv("MAX_ENTRIES_PER_SOURCE", "10"))
MIN_RELEVANCE_SCORE = int(os.getenv("MIN_RELEVANCE_SCORE", "60"))

CATEGORIES = [
    "AI工具",
    "模型發布",
    "研究論文",
    "開源專案",
    "產業動態",
    "投資併購",
    "政策法規",
    "AI基礎設施",
    "教學資源",
    "其他AI趨勢",
]

AI_KEYWORDS = [
    "ai",
    "artificial intelligence",
    "agent",
    "agents",
    "chatgpt",
    "claude",
    "gemini",
    "llm",
    "large language model",
    "openai",
    "anthropic",
    "deepmind",
    "hugging face",
    "machine learning",
    "ml",
    "neural",
    "model",
    "inference",
    "rag",
    "vector database",
    "copilot",
    "cursor",
    "生成式",
    "人工智慧",
    "機器學習",
    "模型",
    "推論",
]

DEFAULT_SOURCE_WEIGHT = 1.0
