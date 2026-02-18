"""News monitoring orchestration service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

from src.domains.monitoring.core.significance_analysis import (
    analyze_content_significance,
)
from src.domains.news.core.verification_logic import (
    build_evidence_list,
    calculate_weighted_confidence,
    check_domain_in_content,
    check_domain_match,
    check_name_in_context,
    extract_domain_from_url,
    is_article_verified,
)

if TYPE_CHECKING:
    from src.domains.discovery.repositories.social_media_link_repository import (
        SocialMediaLinkRepository,
    )
    from src.domains.discovery.services.logo_service import LogoService
    from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository
    from src.domains.news.repositories.news_article_repository import (
        NewsArticleRepository,
    )
    from src.domains.news.services.kagi_client import KagiClient
    from src.repositories.company_repository import CompanyRepository

logger = structlog.get_logger(__name__)


class NewsMonitorManager:
    """Orchestrates news search, verification, and storage."""

    def __init__(
        self,
        kagi_client: KagiClient,
        news_repo: NewsArticleRepository,
        company_repo: CompanyRepository,
        snapshot_repo: SnapshotRepository,
        llm_client: Any | None = None,
        logo_service: LogoService | None = None,
        logo_repo: SocialMediaLinkRepository | None = None,
    ) -> None:
        self.kagi = kagi_client
        self.news_repo = news_repo
        self.company_repo = company_repo
        self.snapshot_repo = snapshot_repo
        self.llm_client = llm_client
        self.logo_service = logo_service
        self.logo_repo = logo_repo

    def search_company_news(
        self,
        company_id: int | None = None,
        company_name: str | None = None,
    ) -> dict[str, Any]:
        """Search and store news for a single company.

        Returns summary dict.
        """
        # Resolve company
        if company_id is not None:
            company = self.company_repo.get_company_by_id(company_id)
        elif company_name is not None:
            company = self.company_repo.get_company_by_name(company_name)
        else:
            return {"error": "Either company_id or company_name required"}

        if not company:
            return {"error": "Company not found"}

        company_id = company["id"]
        name = company["name"]
        homepage_url = company.get("homepage_url", "")

        # Calculate date range
        after_date, before_date = self._calculate_date_range(company_id)

        # Search Kagi
        articles = self.kagi.search(
            query=name,
            after_date=after_date,
            before_date=before_date,
        )

        found = len(articles)
        verified = 0
        stored = 0

        company_domain = extract_domain_from_url(homepage_url) if homepage_url else ""
        now = datetime.now(UTC).isoformat()

        for article in articles:
            # Check for duplicate
            if self.news_repo.check_duplicate_news_url(article["url"]):
                continue

            # Verify company match
            signals: dict[str, float] = {}

            # Logo match (perceptual hash comparison)
            logo_match: tuple[bool, float] | None = None
            logo_similarity_score: float | None = None
            logo_match = self._check_logo_match(
                company_id, article.get("snippet", ""), homepage_url
            )
            if logo_match is not None:
                signals["logo"] = 1.0 if logo_match[0] else 0.0
                logo_similarity_score = logo_match[1]

            # Domain match
            domain_matched = check_domain_match(article["url"], company_domain)
            if not domain_matched:
                domain_matched = check_domain_in_content(article.get("snippet", ""), company_domain)
            signals["domain"] = 1.0 if domain_matched else 0.0

            # Name in context
            context_matched = check_name_in_context(article.get("snippet", ""), name)
            signals["context"] = 1.0 if context_matched else 0.0

            # LLM verification (optional)
            llm_match: tuple[bool, str] | None = None
            if self.llm_client:
                try:
                    is_match, reasoning = self.llm_client.verify_company_identity(
                        company_name=name,
                        company_url=homepage_url or "",
                        article_title=article.get("title", ""),
                        article_source=article.get("source", ""),
                        article_snippet=article.get("snippet", ""),
                    )
                    signals["llm"] = 1.0 if is_match else 0.0
                    llm_match = (is_match, reasoning)
                except Exception as exc:
                    logger.warning("llm_verification_failed", error=str(exc))

            confidence = calculate_weighted_confidence(signals)

            if not is_article_verified(confidence):
                continue

            verified += 1

            # Build evidence list
            evidence = build_evidence_list(
                logo_match=logo_match,
                domain_match=domain_matched,
                domain_name=company_domain,
                context_match=context_matched,
                company_name=name,
                llm_match=llm_match,
            )

            # Analyze significance
            sig_result = analyze_content_significance(
                article.get("snippet", "") + " " + article.get("title", ""),
            )

            # Store article
            self.news_repo.store_news_article(
                {
                    "company_id": company_id,
                    "title": article.get("title", ""),
                    "content_url": article["url"],
                    "source": article.get("source", ""),
                    "published_at": article.get("published", now),
                    "discovered_at": now,
                    "match_confidence": confidence,
                    "match_evidence": evidence,
                    "logo_similarity": logo_similarity_score,
                    "company_match_snippet": article.get("snippet", "")[:500],
                    "keyword_match_snippet": None,
                    "significance_classification": sig_result.classification,
                    "significance_sentiment": sig_result.sentiment,
                    "significance_confidence": sig_result.confidence,
                    "matched_keywords": sig_result.matched_keywords,
                    "matched_categories": sig_result.matched_categories,
                    "significance_notes": sig_result.notes,
                }
            )
            stored += 1

        return {
            "company_id": company_id,
            "company_name": name,
            "articles_found": found,
            "articles_verified": verified,
            "articles_stored": stored,
        }

    def search_all_companies(
        self,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Search news for all companies.

        Returns aggregate summary.
        """
        companies = self.company_repo.get_all_companies()
        if limit is not None:
            companies = companies[:limit]

        total_found = 0
        total_verified = 0
        total_stored = 0
        errors: list[str] = []

        for company in companies:
            try:
                result = self.search_company_news(company_id=company["id"])
                if result.get("error"):
                    errors.append(f"{company['name']}: {result['error']}")
                else:
                    total_found += result.get("articles_found", 0)
                    total_verified += result.get("articles_verified", 0)
                    total_stored += result.get("articles_stored", 0)
            except Exception as exc:
                logger.error(
                    "news_search_failed",
                    company=company["name"],
                    error=str(exc),
                )
                errors.append(f"{company['name']}: {exc}")

        return {
            "companies_processed": len(companies),
            "total_found": total_found,
            "total_verified": total_verified,
            "total_stored": total_stored,
            "errors": errors,
        }

    def _check_logo_match(
        self,
        company_id: int,
        article_html_or_snippet: str,
        company_url: str,
    ) -> tuple[bool, float] | None:
        """Compare stored company logo with article image via perceptual hash.

        Returns (is_similar, similarity_score) or None if comparison not possible.
        """
        if not self.logo_service or not self.logo_repo:
            return None

        # Get stored company logo
        stored_logo = self.logo_repo.get_company_logo(company_id)
        if not stored_logo or not stored_logo.get("perceptual_hash"):
            return None

        # Try to extract logo from article content
        article_logo = self.logo_service.extract_logo_from_html(
            article_html_or_snippet, company_url
        )
        if not article_logo or not article_logo.get("source_url"):
            return None

        # If we can only extract the URL but not compute the hash at this
        # stage (no image download in pure verification), we report the
        # extraction succeeded but similarity is 0.0. A full implementation
        # would download the image, compute its perceptual hash, then compare.
        # For now, we use the logo_comparison pure function if both hashes are
        # available.
        from src.domains.discovery.core.logo_comparison import compute_hash_similarity

        article_hash = article_logo.get("perceptual_hash")
        if not article_hash:
            # Cannot compare without a hash -- signal that logo extraction
            # was attempted but inconclusive.
            return None

        stored_hash = stored_logo["perceptual_hash"]
        similarity = float(compute_hash_similarity(stored_hash, article_hash))
        is_similar = similarity >= 0.85
        return (is_similar, similarity)

    def _calculate_date_range(self, company_id: int) -> tuple[str, str]:
        """Calculate search date range based on snapshot history.

        With 2+ snapshots: oldest snapshot to now.
        Without: 90 days ago to now.
        """
        oldest = self.snapshot_repo.get_oldest_snapshot_date(company_id)
        now = datetime.now(UTC)
        before_date = now.strftime("%Y-%m-%d")

        after_date = oldest[:10] if oldest else (now - timedelta(days=90)).strftime("%Y-%m-%d")

        return after_date, before_date
