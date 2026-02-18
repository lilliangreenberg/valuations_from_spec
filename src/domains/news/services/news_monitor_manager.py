"""News monitoring orchestration service."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
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
from src.utils.progress import ProgressTracker

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

        articles = self._fetch_news_for_company(company)
        if articles is None:
            return {"error": "Search failed"}

        result = self._verify_and_store_articles(
            company_id=company_id,
            company_name=name,
            homepage_url=homepage_url,
            articles=articles,
        )

        return {
            "company_id": company_id,
            "company_name": name,
            **result,
        }

    def search_all_companies(
        self,
        limit: int | None = None,
        max_workers: int = 5,
    ) -> dict[str, Any]:
        """Search news for all companies with parallel Kagi API calls.

        Parallelizes the Kagi search phase across companies, then processes
        results sequentially for SQLite-safe DB writes.

        Args:
            limit: Process only the first N companies.
            max_workers: Number of parallel workers for Kagi API calls.

        Returns aggregate summary.
        """
        companies = self.company_repo.get_all_companies()
        if limit is not None:
            companies = companies[:limit]

        tracker = ProgressTracker(total=len(companies))
        total_found = 0
        total_verified = 0
        total_stored = 0

        # Phase 1: Parallel Kagi search
        search_results: dict[int, tuple[dict[str, Any], list[dict[str, Any]]]] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self._fetch_news_for_company, company): company
                for company in companies
            }

            for future in as_completed(futures):
                company = futures[future]
                try:
                    result = future.result()
                    if result is not None:
                        search_results[company["id"]] = (company, result)
                except Exception as exc:
                    logger.error(
                        "news_search_failed",
                        company=company["name"],
                        error=str(exc),
                    )
                    tracker.record_failure(f"{company['name']}: {exc}")

        # Phase 2: Sequential verification + DB writes
        for company_id, (company, articles) in search_results.items():
            try:
                store_result = self._verify_and_store_articles(
                    company_id=company_id,
                    company_name=company["name"],
                    homepage_url=company.get("homepage_url", ""),
                    articles=articles,
                )
                total_found += store_result["articles_found"]
                total_verified += store_result["articles_verified"]
                total_stored += store_result["articles_stored"]
                tracker.record_success()
            except Exception as exc:
                logger.error(
                    "news_processing_failed",
                    company=company["name"],
                    error=str(exc),
                )
                tracker.record_failure(f"{company['name']}: {exc}")

            tracker.log_progress(every_n=10)

        # Mark companies with no search results
        companies_with_results = set(search_results.keys())
        for company in companies:
            if company["id"] not in companies_with_results and not any(
                company["name"] in e for e in tracker.errors
            ):
                tracker.record_success()

        summary = tracker.summary()
        summary["total_found"] = total_found
        summary["total_verified"] = total_verified
        summary["total_stored"] = total_stored
        return summary

    def _fetch_news_for_company(
        self,
        company: dict[str, Any],
    ) -> list[dict[str, Any]] | None:
        """Fetch news articles from Kagi for a single company (thread-safe).

        Returns list of raw article dicts, or None on error.
        """
        company_id = company["id"]
        name = company["name"]

        after_date, before_date = self._calculate_date_range(company_id)

        articles = self.kagi.search(
            query=name,
            after_date=after_date,
            before_date=before_date,
        )

        logger.debug(
            "kagi_search_fetched",
            company=name,
            articles=len(articles),
        )
        return articles

    def _verify_and_store_articles(
        self,
        company_id: int,
        company_name: str,
        homepage_url: str,
        articles: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Verify and store articles for a company (must run on main thread for SQLite).

        Returns dict with articles_found, articles_verified, articles_stored.
        """
        found = len(articles)
        verified = 0
        stored = 0

        company_domain = extract_domain_from_url(homepage_url) if homepage_url else ""
        now = datetime.now(UTC).isoformat()

        for article in articles:
            if self.news_repo.check_duplicate_news_url(article["url"]):
                continue

            signals: dict[str, float] = {}

            logo_match: tuple[bool, float] | None = None
            logo_similarity_score: float | None = None
            logo_match = self._check_logo_match(
                company_id, article.get("snippet", ""), homepage_url
            )
            if logo_match is not None:
                signals["logo"] = 1.0 if logo_match[0] else 0.0
                logo_similarity_score = logo_match[1]

            domain_matched = check_domain_match(article["url"], company_domain)
            if not domain_matched:
                domain_matched = check_domain_in_content(article.get("snippet", ""), company_domain)
            signals["domain"] = 1.0 if domain_matched else 0.0

            context_matched = check_name_in_context(article.get("snippet", ""), company_name)
            signals["context"] = 1.0 if context_matched else 0.0

            llm_match: tuple[bool, str] | None = None
            if self.llm_client:
                try:
                    is_match, reasoning = self.llm_client.verify_company_identity(
                        company_name=company_name,
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

            evidence = build_evidence_list(
                logo_match=logo_match,
                domain_match=domain_matched,
                domain_name=company_domain,
                context_match=context_matched,
                company_name=company_name,
                llm_match=llm_match,
            )

            sig_result = analyze_content_significance(
                article.get("snippet", "") + " " + article.get("title", ""),
            )

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
            "articles_found": found,
            "articles_verified": verified,
            "articles_stored": stored,
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
