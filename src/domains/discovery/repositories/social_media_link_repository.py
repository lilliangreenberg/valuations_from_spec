"""Social media link repository for database CRUD operations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from src.services.database import Database

logger = structlog.get_logger(__name__)


class SocialMediaLinkRepository:
    """Repository for social media link data access."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def store_social_link(self, data: dict[str, Any]) -> int:
        """Store a social media link. Handles UNIQUE constraint via upsert."""
        try:
            cursor = self.db.execute(
                """INSERT INTO social_media_links
                   (company_id, platform, profile_url, discovery_method,
                    verification_status, similarity_score, discovered_at,
                    last_verified_at, html_location, account_type,
                    account_confidence, rejection_reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data["company_id"],
                    data["platform"],
                    data["profile_url"],
                    data["discovery_method"],
                    data.get("verification_status", "unverified"),
                    data.get("similarity_score"),
                    data["discovered_at"],
                    data.get("last_verified_at"),
                    data.get("html_location"),
                    data.get("account_type"),
                    data.get("account_confidence"),
                    data.get("rejection_reason"),
                ),
            )
            self.db.connection.commit()
            return cursor.lastrowid or 0
        except Exception as exc:
            if "UNIQUE constraint" in str(exc):
                logger.debug("duplicate_social_link_skipped", url=data.get("profile_url"))
                return 0
            raise

    def get_links_for_company(self, company_id: int) -> list[dict[str, Any]]:
        """Get all social media links for a company."""
        rows = self.db.fetchall(
            "SELECT * FROM social_media_links WHERE company_id = ? ORDER BY platform",
            (company_id,),
        )
        return [dict(row) for row in rows]

    def get_links_by_platform(self, platform: str) -> list[dict[str, Any]]:
        """Get all links for a specific platform."""
        rows = self.db.fetchall(
            "SELECT * FROM social_media_links WHERE platform = ?",
            (platform,),
        )
        return [dict(row) for row in rows]

    def link_exists(self, company_id: int, profile_url: str) -> bool:
        """Check if a link already exists for this company."""
        row = self.db.fetchone(
            "SELECT id FROM social_media_links WHERE company_id = ? AND profile_url = ?",
            (company_id, profile_url),
        )
        return row is not None

    def store_blog_link(self, data: dict[str, Any]) -> int:
        """Store a blog link. Handles UNIQUE constraint."""
        try:
            cursor = self.db.execute(
                """INSERT INTO blog_links
                   (company_id, blog_type, blog_url, discovery_method,
                    is_active, discovered_at, last_checked_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    data["company_id"],
                    data["blog_type"],
                    data["blog_url"],
                    data["discovery_method"],
                    1 if data.get("is_active", True) else 0,
                    data["discovered_at"],
                    data.get("last_checked_at"),
                ),
            )
            self.db.connection.commit()
            return cursor.lastrowid or 0
        except Exception as exc:
            if "UNIQUE constraint" in str(exc):
                logger.debug("duplicate_blog_link_skipped", url=data.get("blog_url"))
                return 0
            raise

    def store_company_logo(self, data: dict[str, Any]) -> int:
        """Store a company logo. Handles UNIQUE constraint."""
        try:
            cursor = self.db.execute(
                """INSERT INTO company_logos
                   (company_id, image_data, image_format, perceptual_hash,
                    source_url, extraction_location, width, height, extracted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data["company_id"],
                    data["image_data"],
                    data["image_format"],
                    data["perceptual_hash"],
                    data["source_url"],
                    data["extraction_location"],
                    data.get("width"),
                    data.get("height"),
                    data["extracted_at"],
                ),
            )
            self.db.connection.commit()
            return cursor.lastrowid or 0
        except Exception as exc:
            if "UNIQUE constraint" in str(exc):
                logger.debug("duplicate_logo_skipped", company_id=data.get("company_id"))
                return 0
            raise

    def get_company_logo(self, company_id: int) -> dict[str, Any] | None:
        """Get the latest logo for a company."""
        row = self.db.fetchone(
            "SELECT * FROM company_logos WHERE company_id = ? ORDER BY extracted_at DESC LIMIT 1",
            (company_id,),
        )
        return dict(row) if row else None

    def get_company_ids_with_logos(self) -> set[int]:
        """Get the set of company IDs that have at least one stored logo."""
        rows = self.db.fetchall("SELECT DISTINCT company_id FROM company_logos")
        return {row["company_id"] for row in rows}
