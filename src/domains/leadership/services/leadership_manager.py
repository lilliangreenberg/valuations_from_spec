"""Leadership extraction orchestrator.

Tries Playwright first, falls back to Kagi search.
Detects leadership changes and flags critical departures.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from src.domains.discovery.core.url_normalization import normalize_social_url
from src.domains.leadership.core.change_detection import (
    build_leadership_change_summary,
    compare_leadership,
)
from src.domains.leadership.core.profile_parsing import filter_leadership_results
from src.domains.leadership.services.linkedin_browser import LinkedInBlockedError
from src.utils.progress import ProgressTracker

if TYPE_CHECKING:
    from src.domains.discovery.repositories.social_media_link_repository import (
        SocialMediaLinkRepository,
    )
    from src.domains.leadership.repositories.leadership_repository import (
        LeadershipRepository,
    )
    from src.domains.leadership.services.leadership_search import LeadershipSearch
    from src.domains.leadership.services.linkedin_browser import LinkedInBrowser
    from src.repositories.company_repository import CompanyRepository

logger = structlog.get_logger(__name__)


class LeadershipManager:
    """Orchestrates leadership extraction with Playwright + Kagi fallback."""

    def __init__(
        self,
        linkedin_browser: LinkedInBrowser,
        leadership_search: LeadershipSearch,
        leadership_repo: LeadershipRepository,
        social_link_repo: SocialMediaLinkRepository,
        company_repo: CompanyRepository,
    ) -> None:
        self.browser = linkedin_browser
        self.search = leadership_search
        self.leadership_repo = leadership_repo
        self.social_link_repo = social_link_repo
        self.company_repo = company_repo

    def extract_company_leadership(
        self,
        company_id: int,
    ) -> dict[str, Any]:
        """Extract leadership for a single company.

        1. Look up LinkedIn company URL from social_media_links
        2. Try Playwright first -> Kagi fallback on failure
        3. Detect leadership changes vs stored records
        4. Store results

        Returns summary dict with: company_id, company_name, leaders_found,
        method_used, leadership_changes, errors
        """
        company = self.company_repo.get_company_by_id(company_id)
        if not company:
            return {"error": f"Company {company_id} not found"}

        company_name = company["name"]
        linkedin_company_url = self._find_linkedin_company_url(company_id)

        people: list[dict[str, str]] = []
        method_used = "kagi_search"
        errors: list[str] = []

        # Try Playwright first (if we have a LinkedIn company URL)
        if linkedin_company_url:
            try:
                raw_people = self.browser.extract_people(linkedin_company_url)
                # Filter to leadership titles only
                people = filter_leadership_results(raw_people)
                method_used = "playwright_scrape"
                logger.info(
                    "playwright_extraction_succeeded",
                    company=company_name,
                    raw_count=len(raw_people),
                    leaders=len(people),
                )
            except LinkedInBlockedError as exc:
                logger.warning(
                    "playwright_blocked_falling_back_to_kagi",
                    company=company_name,
                    reason=str(exc),
                )
                errors.append(f"Playwright blocked: {exc}")
            except Exception as exc:
                logger.warning(
                    "playwright_failed_falling_back_to_kagi",
                    company=company_name,
                    error=str(exc),
                )
                errors.append(f"Playwright error: {exc}")

        # Fallback to Kagi search if Playwright didn't produce results
        if not people:
            try:
                people = self.search.search_leadership(company_name)
                method_used = "kagi_search"
            except Exception as exc:
                logger.error(
                    "kagi_search_failed",
                    company=company_name,
                    error=str(exc),
                )
                errors.append(f"Kagi search error: {exc}")

        # Get previous leadership for change detection
        previous_leadership = self.leadership_repo.get_current_leadership(company_id)

        # Store results
        now = datetime.now(UTC).isoformat()
        confidence = 0.8 if method_used == "playwright_scrape" else 0.6
        stored_count = 0

        for person in people:
            profile_url = normalize_social_url(person.get("profile_url", ""))
            if not profile_url:
                continue

            self.leadership_repo.store_leadership(
                {
                    "company_id": company_id,
                    "person_name": person.get("name", "Unknown"),
                    "title": person.get("title", ""),
                    "linkedin_profile_url": profile_url,
                    "discovery_method": method_used,
                    "confidence": confidence,
                    "is_current": True,
                    "discovered_at": now,
                    "last_verified_at": now,
                    "source_company_linkedin_url": linkedin_company_url,
                }
            )
            stored_count += 1

        # Detect leadership changes
        current_as_dicts = [
            {
                "person_name": p.get("name", ""),
                "title": p.get("title", ""),
                "linkedin_profile_url": normalize_social_url(p.get("profile_url", "")),
            }
            for p in people
        ]
        changes = compare_leadership(previous_leadership, current_as_dicts)
        change_summary = build_leadership_change_summary(changes)

        # Mark departed leaders
        for change in changes:
            change_type = str(change.get("change_type", ""))
            if change_type.endswith("_departure"):
                profile_url = str(change.get("profile_url", ""))
                if profile_url:
                    self.leadership_repo.mark_not_current(company_id, profile_url)

        # Log critical changes prominently
        critical_changes = [c for c in changes if c.get("severity") == "critical"]
        if critical_changes:
            for change in critical_changes:
                logger.warning(
                    "critical_leadership_change",
                    company=company_name,
                    change_type=str(change.get("change_type", "")),
                    person=str(change.get("person_name", "")),
                    title=str(change.get("title", "")),
                )

        return {
            "company_id": company_id,
            "company_name": company_name,
            "leaders_found": stored_count,
            "method_used": method_used,
            "leadership_changes": [
                {
                    "change_type": str(c.get("change_type", "")),
                    "person_name": str(c.get("person_name", "")),
                    "title": str(c.get("title", "")),
                    "severity": str(c.get("severity", "")),
                }
                for c in changes
            ],
            "change_significance": change_summary.classification,
            "errors": errors,
        }

    def extract_all_leadership(
        self,
        limit: int | None = None,
        max_workers: int = 1,
    ) -> dict[str, Any]:
        """Extract leadership for all companies.

        Args:
            limit: Process only the first N companies.
            max_workers: Number of parallel workers. Default 1 because
                Playwright browser is single-threaded. Use higher values
                only when using Kagi-only mode (no browser).

        Returns aggregate summary.
        """
        companies = self.company_repo.get_all_companies()
        if limit is not None:
            companies = companies[:limit]

        tracker = ProgressTracker(total=len(companies))
        total_leaders = 0
        all_critical_changes: list[dict[str, Any]] = []

        if max_workers <= 1:
            # Sequential mode (default, safe for Playwright)
            for company in companies:
                leaders_found = self._process_company_leadership(
                    company,
                    tracker,
                    all_critical_changes,
                )
                total_leaders += leaders_found
                tracker.log_progress(every_n=1)
        else:
            # Parallel mode (for Kagi-only workflows)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(self.extract_company_leadership, company["id"]): company
                    for company in companies
                }

                for future in as_completed(futures):
                    company = futures[future]
                    try:
                        result = future.result()
                        if result.get("error"):
                            tracker.record_failure(result["error"])
                        else:
                            total_leaders += result.get("leaders_found", 0)
                            for change in result.get("leadership_changes", []):
                                if change.get("severity") == "critical":
                                    all_critical_changes.append(
                                        {**change, "company_name": company["name"]}
                                    )
                            tracker.record_success()
                    except Exception as exc:
                        logger.error(
                            "leadership_extraction_failed",
                            company=company["name"],
                            error=str(exc),
                        )
                        tracker.record_failure(str(exc))

                    tracker.log_progress(every_n=1)

        raw_summary = tracker.summary()
        aggregate: dict[str, Any] = {**raw_summary}
        aggregate["total_leaders_found"] = total_leaders
        aggregate["critical_changes"] = all_critical_changes
        return aggregate

    def _process_company_leadership(
        self,
        company: dict[str, Any],
        tracker: ProgressTracker,
        all_critical_changes: list[dict[str, Any]],
    ) -> int:
        """Process a single company's leadership extraction (sequential mode helper).

        Returns number of leaders found.
        """
        try:
            result = self.extract_company_leadership(company["id"])
            if result.get("error"):
                tracker.record_failure(result["error"])
                return 0
            for change in result.get("leadership_changes", []):
                if change.get("severity") == "critical":
                    all_critical_changes.append({**change, "company_name": company["name"]})
            tracker.record_success()
            return int(result.get("leaders_found", 0))
        except Exception as exc:
            logger.error(
                "leadership_extraction_failed",
                company=company["name"],
                error=str(exc),
            )
            tracker.record_failure(str(exc))
            return 0

    def _find_linkedin_company_url(self, company_id: int) -> str | None:
        """Find the LinkedIn company URL from social_media_links."""
        links = self.social_link_repo.get_links_for_company(company_id)
        for link in links:
            if link.get("platform") == "linkedin" and "linkedin.com/company/" in link.get(
                "profile_url", ""
            ):
                return str(link["profile_url"])
        return None
