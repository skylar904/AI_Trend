import os
import tempfile
import unittest
from unittest.mock import patch


TEST_DB = tempfile.NamedTemporaryFile(prefix="ai_trend_test_", suffix=".db", delete=False)
TEST_DB.close()
os.environ["DB_TYPE"] = "sqlite"
os.environ["SQLITE_DB_NAME"] = TEST_DB.name

import api_collectors
from article_content import extract_article_text
from cleaning import is_probably_ai_related, normalize_topic_key
from cleanup_month import cleanup_month
from database import (
    connect_db,
    get_topic_stats,
    init_db,
    rebuild_topic_stats,
    record_candidate_processing,
    save_article,
    save_daily_topics,
)
from topic_rankings import article_matches_topic, calculate_topic_score


class PipelineLogicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(TEST_DB.name)
        except FileNotFoundError:
            pass

    def test_short_ai_keywords_use_word_boundaries(self):
        for title in ("email newsletter", "detail report", "railway maintenance"):
            self.assertFalse(is_probably_ai_related({"title": title}))
        self.assertTrue(is_probably_ai_related({"title": "New AI agent release"}))
        self.assertTrue(is_probably_ai_related({"title": "Machine learning model"}))

    def test_empty_api_response_keeps_rss_fallback(self):
        source = {
            "key": "example",
            "name": "Example API",
            "api_type": "example",
            "requires_env": [],
        }
        with patch.object(api_collectors, "API_SOURCES", [source]), patch.dict(
            api_collectors.COLLECTORS,
            {"example": lambda _: []},
            clear=True,
        ):
            articles, successful = api_collectors.collect_api_candidates()
        self.assertEqual(articles, [])
        self.assertEqual(successful, set())

    def test_topic_keys_and_matching_are_strict(self):
        self.assertEqual(normalize_topic_key("GPT-6"), normalize_topic_key("gpt 6"))
        self.assertTrue(article_matches_topic("GPT-6", {"title": "GPT 6 model released"}))
        self.assertFalse(article_matches_topic("agent", {"title": "Agentic systems"}))
        self.assertFalse(article_matches_topic("RAG", {"title": "Storage update"}))

    def test_mention_count_is_distinct_article_count(self):
        result = calculate_topic_score(
            "GPT-6",
            [
                {"id": 1, "source": "Source A", "trend_score": 80},
                {"id": 2, "source": "Source A", "trend_score": 70},
            ],
        )
        self.assertEqual(result[0], 2)
        self.assertEqual(result[1], 2)
        self.assertEqual(result[2], 1)

    def test_article_html_extraction_ignores_navigation(self):
        text = extract_article_text(
            "<html><nav>menu</nav><article><h1>Title</h1><p>Useful body.</p></article></html>"
        )
        self.assertEqual(text, "Title\nUseful body.")

    def test_cross_day_topics_merge_and_sources_are_distinct(self):
        save_daily_topics(
            "2099-01-01",
            [
                {
                    "term": "GPT-6",
                    "mention_count": 1,
                    "article_count": 1,
                    "source_count": 1,
                    "trend_score_sum": 80,
                    "topic_score": 24,
                    "articles": [{"id": 1, "source": "Source A"}],
                    "sources": ["Source A"],
                }
            ],
        )
        save_daily_topics(
            "2099-01-02",
            [
                {
                    "term": "gpt 6",
                    "mention_count": 2,
                    "article_count": 2,
                    "source_count": 2,
                    "trend_score_sum": 140,
                    "topic_score": 47,
                    "articles": [
                        {"id": 2, "source": "Source A"},
                        {"id": 3, "source": "Source B"},
                    ],
                    "sources": ["Source A", "Source B"],
                }
            ],
        )
        rebuild_topic_stats()
        rows = get_topic_stats(10)
        merged = [row for row in rows if normalize_topic_key(row["term"]) == "gpt6"]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["source_count"], 2)
        self.assertEqual(merged[0]["mention_count"], 3)
        self.assertEqual(merged[0]["active_days"], 2)

    def test_month_cleanup_clears_stale_article_ids(self):
        article = {
            "title": "Old test article",
            "link": "https://example.com/old-test-article",
            "source": "Example",
            "category": "AI 模型與研究",
            "published": "2098-12-01",
            "summary": "summary",
            "fingerprint": "old-test-fingerprint",
            "created_at": "2098-12-01 10:00:00",
        }
        article_id = save_article(article)
        record_candidate_processing(article, "accepted", article_id=article_id)
        conn = connect_db()
        conn.execute(
            """
            INSERT INTO pending_articles (
                title, link, status, completed_article_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                article["title"],
                article["link"] + "/pending",
                "completed",
                article_id,
                article["created_at"],
                article["created_at"],
            ),
        )
        conn.commit()
        conn.close()

        cleanup_month("2098-12")
        conn = connect_db()
        processed = conn.execute(
            "SELECT article_id FROM processed_candidates WHERE fingerprint = ?",
            (article["fingerprint"],),
        ).fetchone()
        pending = conn.execute(
            "SELECT completed_article_id FROM pending_articles WHERE link = ?",
            (article["link"] + "/pending",),
        ).fetchone()
        article_count = conn.execute(
            "SELECT COUNT(*) AS count FROM articles WHERE id = ?",
            (article_id,),
        ).fetchone()["count"]
        conn.close()

        self.assertEqual(processed["article_id"], 0)
        self.assertEqual(pending["completed_article_id"], 0)
        self.assertEqual(article_count, 0)


if __name__ == "__main__":
    unittest.main()
