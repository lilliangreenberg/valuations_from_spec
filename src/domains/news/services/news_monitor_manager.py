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
    COMPETING_DOMAIN_PENALTY,
    build_evidence_list,
    calculate_weighted_confidence,
    check_domain_in_content,
    check_domain_match,
    check_name_in_context,
    detect_competing_domain,
    extract_company_description,
    extract_domain_from_url,
    is_article_verified,
)
from src.utils.progress import ProgressTracker

if TYPE_CHECKING:
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
    ) -> None:
        self.kagi = kagi_client
        self.news_repo = news_repo
        self.company_repo = company_repo
        self.snapshot_repo = snapshot_repo
        self.llm_client = llm_client

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

        Returns aggregate summary with report_details for report generation.
        """
        companies = self.company_repo.get_all_companies()
        if limit is not None:
            companies = companies[:limit]

        tracker = ProgressTracker(total=len(companies))
        total_found = 0
        total_verified = 0
        total_stored = 0

        with_news_details: list[dict[str, Any]] = []
        failed_details: list[dict[str, Any]] = []
        skipped_details: list[dict[str, Any]] = []

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
                    failed_details.append({
                        "company_id": company["id"],
                        "name": company.get("name", ""),
                        "error": f"{company['name']}: {exc}",
                    })

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

                # Collect stored article detail for report
                if store_result["articles_stored"] > 0:
                    with_news_details.append({
                        "company_id": company_id,
                        "name": company["name"],
                        "homepage_url": company.get("homepage_url", ""),
                        "articles_found": store_result["articles_found"],
                        "articles_verified": store_result["articles_verified"],
                        "articles_stored": store_result["articles_stored"],
                        "articles": store_result.get("article_details", []),
                    })
            except Exception as exc:
                logger.error(
                    "news_processing_failed",
                    company=company["name"],
                    error=str(exc),
                )
                tracker.record_failure(f"{company['name']}: {exc}")
                failed_details.append({
                    "company_id": company["id"],
                    "name": company.get("name", ""),
                    "error": f"{company['name']}: {exc}",
                })

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
        summary["report_details"] = {
            "with_news": with_news_details,
            "failed": failed_details,
            "skipped": skipped_details,
        }
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
    ) -> dict[str, Any]:
        """Verify and store articles for a company (must run on main thread for SQLite).

        Returns dict with articles_found, articles_verified, articles_stored,
        and article_details for report generation.
        """
        found = len(articles)
        verified = 0
        stored = 0
        article_details: list[dict[str, Any]] = []

        company_domain = extract_domain_from_url(homepage_url) if homepage_url else ""
        now = datetime.now(UTC).isoformat()

        # Fetch company description from latest snapshot for LLM context
        company_description = ""
        snapshots = self.snapshot_repo.get_latest_snapshots(company_id, limit=1)
        if snapshots:
            company_description = extract_company_description(snapshots[0].get("content_markdown"))

        for article in articles:
            if self.news_repo.check_duplicate_news_url(article["url"]):
                continue

            signals: dict[str, float] = {}

            domain_matched = check_domain_match(article["url"], company_domain)
            if not domain_matched:
                domain_matched = check_domain_in_content(article.get("snippet", ""), company_domain)

            if domain_matched:
                signals["domain"] = 1.0
            elif detect_competing_domain(article["url"], company_domain):
                signals["domain"] = COMPETING_DOMAIN_PENALTY
            else:
                signals["domain"] = 0.0

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
                        company_description=company_description,
                    )
                    signals["llm"] = 1.0 if is_match else 0.0
                    llm_match = (is_match, reasoning)
                except Exception as exc:
                    logger.warning("llm_verification_failed", error=str(exc))

            confidence = calculate_weighted_confidence(signals)

            if not is_article_verified(confidence):
                logger.debug(
                    "article_rejected",
                    title=article.get("title", "")[:80],
                    signals=signals,
                    confidence=confidence,
                )
                continue

            verified += 1

            evidence = build_evidence_list(
                domain_match=domain_matched,
                domain_name=company_domain,
                context_match=context_matched,
                company_name=company_name,
                llm_match=llm_match,
            )

            combined_text = article.get("snippet", "") + " " + article.get("title", "")
            sig_result = analyze_content_significance(combined_text)

            # LLM as primary classifier -- keywords passed as hints
            if self.llm_client:
                try:
                    llm_result = self.llm_client.classify_news_significance(
                        title=article.get("title", ""),
                        source=article.get("source", ""),
                        content=article.get("snippet", ""),
                        keywords=sig_result.matched_keywords,
                        company_name=company_name,
                    )
                    if not llm_result.get("error"):
                        sig_result.classification = llm_result.get(
                            "classification", sig_result.classification
                        )
                        sig_result.sentiment = llm_result.get("sentiment", sig_result.sentiment)
                        sig_result.confidence = llm_result.get("confidence", sig_result.confidence)
                        if llm_result.get("reasoning"):
                            sig_result.notes = llm_result["reasoning"]
                except Exception as exc:
                    logger.warning(
                        "llm_news_classification_failed",
                        article_url=article.get("url", ""),
                        error=str(exc),
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
                    "logo_similarity": None,
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
            article_details.append({
                "title": article.get("title", ""),
                "content_url": article["url"],
                "source": article.get("source", ""),
                "published_at": article.get("published", now),
                "match_confidence": confidence,
                "significance": sig_result.classification,
                "sentiment": sig_result.sentiment,
                "matched_keywords": sig_result.matched_keywords,
                "matched_categories": sig_result.matched_categories,
            })

        return {
            "articles_found": found,
            "articles_verified": verified,
            "articles_stored": stored,
            "article_details": article_details,
        }

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
