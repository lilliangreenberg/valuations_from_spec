"""News article repository for database CRUD operations."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from src.services.database import Database

logger = structlog.get_logger(__name__)


class NewsArticleRepository:
    """Repository for news article data access."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def store_news_article(self, data: dict[str, Any]) -> int:
        """Store a news article. Returns article ID."""
        try:
            cursor = self.db.execute(
                """INSERT INTO news_articles
                   (company_id, title, content_url, source, published_at,
                    discovered_at, match_confidence, match_evidence,
                    logo_similarity, company_match_snippet, keyword_match_snippet,
                    significance_classification, significance_sentiment,
                    significance_confidence, matched_keywords, matched_categories,
                    significance_notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data["company_id"],
                    data["title"],
                    data["content_url"],
                    data["source"],
                    data["published_at"],
                    data["discovered_at"],
                    data["match_confidence"],
                    json.dumps(data.get("match_evidence", [])),
                    data.get("logo_similarity"),
                    data.get("company_match_snippet"),
                    data.get("keyword_match_snippet"),
                    data.get("significance_classification"),
                    data.get("significance_sentiment"),
                    data.get("significance_confidence"),
                    json.dumps(data.get("matched_keywords", [])),
                    json.dumps(data.get("matched_categories", [])),
                    data.get("significance_notes"),
                ),
            )
            self.db.connection.commit()
            return cursor.lastrowid or 0
        except Exception as exc:
            if "UNIQUE constraint" in str(exc):
                logger.debug("duplicate_news_article_skipped", url=data.get("content_url"))
                return 0
            raise

    def check_duplicate_news_url(self, content_url: str) -> bool:
        """Check if a news article URL already exists."""
        row = self.db.fetchone(
            "SELECT id FROM news_articles WHERE content_url = ?",
            (content_url,),
        )
        return row is not None

    def get_news_articles(
        self,
        company_id: int,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get news articles for a company."""
        rows = self.db.fetchall(
            """SELECT * FROM news_articles
               WHERE company_id = ?
               ORDER BY published_at DESC
               LIMIT ?""",
            (company_id, limit),
        )
        return [self._deserialize_row(row) for row in rows]

    def get_news_for_date_range(
        self,
        company_id: int,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """Get news articles within a date range."""
        rows = self.db.fetchall(
            """SELECT * FROM news_articles
               WHERE company_id = ?
               AND published_at >= ? AND published_at <= ?
               ORDER BY published_at DESC""",
            (company_id, start_date, end_date),
        )
        return [self._deserialize_row(row) for row in rows]

    def get_significant_news(
        self,
        days: int = 90,
        sentiment: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get significant news articles."""
        sql = """SELECT na.*, c.name as company_name
                 FROM news_articles na
                 JOIN companies c ON na.company_id = c.id
                 WHERE na.significance_classification = 'significant'
                 AND na.published_at >= datetime('now', ?)"""
        params: list[Any] = [f"-{days} days"]

        if sentiment:
            sql += " AND na.significance_sentiment = ?"
            params.append(sentiment)

        sql += " ORDER BY na.published_at DESC"
        rows = self.db.fetchall(sql, tuple(params))
        return [self._deserialize_row(row) for row in rows]

    def _deserialize_row(self, row: Any) -> dict[str, Any]:
        """Deserialize JSON fields."""
        data = dict(row)
        for field in ("match_evidence", "matched_keywords", "matched_categories"):
            if data.get(field):
                try:
                    data[field] = json.loads(data[field])
                except (json.JSONDecodeError, TypeError):
                    data[field] = []
            else:
                data[field] = []
        return data
