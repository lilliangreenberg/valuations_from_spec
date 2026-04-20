"""Leadership extraction orchestrator.

Uses CDP + Chrome Extension as the primary extraction method,
with Kagi search as a fallback. Includes employment verification
via personal profile visits and Claude Vision analysis.
Detects leadership changes and flags critical departures.
"""

from __future__ import annotations

import base64
import json
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
from src.domains.leadership.core.vision_prompts import build_people_tab_prompt
from src.domains.leadership.core.vision_result_parser import (
    merge_dom_and_vision_results,
    parse_people_tab_result,
)
from src.domains.leadership.services.cdp_browser import CDPBlockedError
from src.utils.progress import ProgressTracker

if TYPE_CHECKING:
    from src.domains.discovery.repositories.social_media_link_repository import (
        SocialMediaLinkRepository,
    )
    from src.domains.leadership.repositories.leadership_change_repository import (
        LeadershipChangeRepository,
    )
    from src.domains.leadership.repositories.leadership_repository import (
        LeadershipRepository,
    )
    from src.domains.leadership.repositories.linkedin_snapshot_repository import (
        LinkedInSnapshotRepository,
    )
    from src.domains.leadership.services.cdp_browser import CDPBrowser
    from src.domains.leadership.services.employment_verifier import EmploymentVerifier
    from src.domains.leadership.services.leadership_search import LeadershipSearch
    from src.repositories.company_repository import CompanyRepository
    from src.services.llm_client import LLMClient

logger = structlog.get_logger(__name__)


class LeadershipManager:
    """Orchestrates leadership extraction with CDP + Kagi fallback."""

    def __init__(
        self,
        cdp_browser: CDPBrowser,
        leadership_search: LeadershipSearch,
        leadership_repo: LeadershipRepository,
        social_link_repo: SocialMediaLinkRepository,
        company_repo: CompanyRepository,
        llm_client: LLMClient | None = None,
        snapshot_repo: LinkedInSnapshotRepository | None = None,
        employment_verifier: EmploymentVerifier | None = None,
        leadership_change_repo: LeadershipChangeRepository | None = None,
    ) -> None:
        self.browser = cdp_browser
        self.search = leadership_search
        self.leadership_repo = leadership_repo
        self.social_link_repo = social_link_repo
        self.company_repo = company_repo
        self.llm = llm_client
        self.snapshot_repo = snapshot_repo
        self.verifier = employment_verifier
        self.leadership_change_repo = leadership_change_repo

    def extract_company_leadership(
        self,
        company_id: int,
    ) -> dict[str, Any]:
        """Extract leadership for a single company.

        1. Look up LinkedIn company URL from social_media_links
        2. Try CDP extraction first -> Kagi fallback on failure
        3. For CDP: DOM extraction + Vision analysis, merged
        4. Detect leadership changes vs stored records
        5. Verify existing leaders not seen in new scrape
        6. Store results

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

        # Try CDP extraction first (if we have a LinkedIn company URL)
        if linkedin_company_url:
            try:
                people, method_used = self._extract_via_cdp(
                    company_id, company_name, linkedin_company_url
                )
            except CDPBlockedError as exc:
                logger.warning(
                    "cdp_blocked_falling_back_to_kagi",
                    company=company_name,
                    reason=str(exc),
                )
                errors.append(f"CDP blocked: {exc}")
            except Exception as exc:
                logger.warning(
                    "cdp_failed_falling_back_to_kagi",
                    company=company_name,
                    error=str(exc),
                    exc_info=True,
                )
                errors.append(f"CDP error: {exc}")

        # Fallback to Kagi search if CDP didn't produce results
        if not people:
            try:
                people = self.search.search_leadership(company_name)
                method_used = "kagi_search"
                logger.info(
                    "kagi_fallback_used",
                    company=company_name,
                    leaders_found=len(people),
                )
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
        confidence = 0.8 if method_used == "cdp_scrape" else 0.6
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

        # Persist detected changes to the append-only event log. Only write
        # when there was at least one previously-known leader, so bootstrap
        # runs (first-ever extraction for a company) don't generate a flood
        # of phantom "NEW_LEADERSHIP" events for every current employee.
        if self.leadership_change_repo is not None and previous_leadership and changes:
            events = [
                {
                    "company_id": company_id,
                    "change_type": str(change.get("change_type", "")),
                    "person_name": str(change.get("person_name", "")) or "Unknown",
                    "title": str(change.get("title", "")) or None,
                    "linkedin_profile_url": str(change.get("profile_url", "")) or None,
                    "severity": str(change.get("severity", "minor")),
                    "detected_at": now,
                    "confidence": confidence,
                    "discovery_method": method_used,
                }
                for change in changes
            ]
            try:
                inserted = self.leadership_change_repo.store_changes(events)
                logger.info(
                    "leadership_changes_recorded",
                    company_id=company_id,
                    count=inserted,
                )
            except Exception as exc:
                logger.error(
                    "leadership_changes_persist_failed",
                    company_id=company_id,
                    error=str(exc),
                )

        # Mark departed leaders
        for change in changes:
            change_type = str(change.get("change_type", ""))
            if change_type.endswith("_departure"):
                profile_url = str(change.get("profile_url", ""))
                if profile_url:
                    self.leadership_repo.mark_not_current(company_id, profile_url)

        # Verify leaders who were previously known but not in current People tab
        verification_results: list[dict[str, Any]] = []
        if self.verifier and method_used == "cdp_scrape":
            verification_results = self._verify_missing_leaders(
                company_id, company_name, previous_leadership, current_as_dicts
            )

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

        # Build leader detail list for report
        leader_details: list[dict[str, Any]] = []
        for person in people:
            profile_url = normalize_social_url(person.get("profile_url", ""))
            if profile_url:
                leader_details.append(
                    {
                        "person_name": person.get("name", "Unknown"),
                        "title": person.get("title", ""),
                        "linkedin_profile_url": profile_url,
                        "confidence": confidence,
                    }
                )

        return {
            "company_id": company_id,
            "company_name": company_name,
            "leaders_found": stored_count,
            "method_used": method_used,
            "leaders": leader_details,
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
            "verification_results": verification_results,
            "errors": errors,
        }

    def _extract_via_cdp(
        self,
        company_id: int,
        company_name: str,
        linkedin_company_url: str,
    ) -> tuple[list[dict[str, str]], str]:
        """Extract leadership via CDP + Vision (dual strategy).

        Returns (people_list, method_used).
        """
        now = datetime.now(UTC).isoformat()

        # Step 1: DOM extraction via CDP
        raw_people = self.browser.extract_people(linkedin_company_url)
        dom_leaders = filter_leadership_results(raw_people)

        logger.info(
            "cdp_dom_extraction_complete",
            company=company_name,
            raw_count=len(raw_people),
            leaders=len(dom_leaders),
        )

        # Step 2: Capture screenshots and run Vision analysis
        vision_leaders: list[dict[str, str]] = []
        screenshot_paths: list[str] = []

        if self.llm:
            try:
                screenshot_paths = self.browser.capture_people_screenshots(
                    linkedin_company_url, company_id
                )

                for path in screenshot_paths:
                    with open(path, "rb") as f:
                        screenshot_b64 = base64.b64encode(f.read()).decode("utf-8")

                    prompt = build_people_tab_prompt()
                    raw_vision = self.llm.analyze_screenshot(screenshot_b64, prompt)

                    if not raw_vision.get("error"):
                        batch_people = parse_people_tab_result(raw_vision)
                        vision_leaders.extend(batch_people)

                logger.info(
                    "cdp_vision_extraction_complete",
                    company=company_name,
                    vision_people=len(vision_leaders),
                    screenshots=len(screenshot_paths),
                )
            except Exception as exc:
                logger.warning(
                    "cdp_vision_analysis_failed",
                    company=company_name,
                    error=str(exc),
                )

        # Step 3: Merge DOM + Vision results
        if vision_leaders:
            merged = merge_dom_and_vision_results(dom_leaders, vision_leaders)
            # Re-filter merged results for leadership titles
            people = filter_leadership_results(merged)
        else:
            people = dom_leaders

        # Step 4: Store LinkedIn snapshot
        if self.snapshot_repo:
            page_html = self.browser.get_page_html()
            self.snapshot_repo.store_snapshot(
                {
                    "company_id": company_id,
                    "linkedin_url": linkedin_company_url,
                    "url_type": "company",
                    "person_name": None,
                    "content_html": page_html,
                    "content_json": json.dumps({"employees": raw_people}),
                    "vision_data_json": json.dumps({"vision_leaders": vision_leaders}),
                    "screenshot_path": screenshot_paths[0] if screenshot_paths else None,
                    "captured_at": now,
                }
            )

        logger.info(
            "cdp_extraction_merged",
            company=company_name,
            dom_count=len(dom_leaders),
            vision_count=len(vision_leaders),
            merged_count=len(people),
        )

        return people, "cdp_scrape"

    def _verify_missing_leaders(
        self,
        company_id: int,
        company_name: str,
        previous: list[dict[str, str]],
        current: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        """Verify leaders who were previously known but not seen in current scrape.

        Uses personal profile visits to confirm departures vs People tab omissions.
        """
        if not self.verifier:
            return []

        curr_urls = {p.get("linkedin_profile_url", "") for p in current}
        missing = [p for p in previous if p.get("linkedin_profile_url", "") not in curr_urls]

        if not missing:
            return []

        logger.info(
            "verifying_missing_leaders",
            company=company_name,
            missing_count=len(missing),
        )

        results: list[dict[str, Any]] = []
        for leader in missing:
            result = self.verifier.verify_leader(company_id, company_name, leader)
            results.append(result)
            self.browser.delay_between_pages()

        return results

    def extract_all_leadership(
        self,
        limit: int | None = None,
        max_workers: int = 1,
        exclude_company_ids: set[int] | None = None,
    ) -> dict[str, Any]:
        """Extract leadership for all companies.

        Args:
            limit: Process only the first N companies.
            max_workers: Number of parallel workers. Default 1 because
                CDP browser is single-threaded. Use higher values
                only when using Kagi-only mode (no browser).
            exclude_company_ids: Company IDs to exclude (e.g. manually closed).

        Returns aggregate summary with report_details for report generation.
        """
        companies = self.company_repo.get_all_companies()
        if exclude_company_ids:
            pre = len(companies)
            companies = [c for c in companies if c["id"] not in exclude_company_ids]
            excluded = pre - len(companies)
            if excluded:
                logger.info(
                    "excluded_manually_closed",
                    total=pre,
                    excluded=excluded,
                    remaining=len(companies),
                )
        if limit is not None:
            companies = companies[:limit]

        tracker = ProgressTracker(total=len(companies))
        total_leaders = 0
        all_critical_changes: list[dict[str, Any]] = []

        extracted_details: list[dict[str, Any]] = []
        failed_details: list[dict[str, Any]] = []
        skipped_details: list[dict[str, Any]] = []

        if max_workers <= 1:
            # Sequential mode (default, safe for CDP browser)
            for company in companies:
                leaders_found = self._process_company_leadership(
                    company,
                    tracker,
                    all_critical_changes,
                    extracted_details,
                    failed_details,
                    skipped_details,
                )
                total_leaders += leaders_found
                tracker.log_progress(every_n=1)
                # Delay between companies
                self.browser.delay_between_pages()
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
                            failed_details.append(
                                {
                                    "company_id": company["id"],
                                    "name": company.get("name", ""),
                                    "error": result["error"],
                                }
                            )
                        else:
                            total_leaders += result.get("leaders_found", 0)
                            for change in result.get("leadership_changes", []):
                                if change.get("severity") == "critical":
                                    all_critical_changes.append(
                                        {**change, "company_name": company["name"]}
                                    )
                            tracker.record_success()
                            extracted_details.append(
                                {
                                    "company_id": result["company_id"],
                                    "name": result["company_name"],
                                    "method_used": result["method_used"],
                                    "leaders_found": result["leaders_found"],
                                    "leaders": result.get("leaders", []),
                                    "leadership_changes": result.get("leadership_changes", []),
                                }
                            )
                    except Exception as exc:
                        logger.error(
                            "leadership_extraction_failed",
                            company=company["name"],
                            error=str(exc),
                        )
                        tracker.record_failure(str(exc))
                        failed_details.append(
                            {
                                "company_id": company["id"],
                                "name": company.get("name", ""),
                                "error": str(exc),
                            }
                        )

                    tracker.log_progress(every_n=1)

        raw_summary = tracker.summary()
        aggregate: dict[str, Any] = {**raw_summary}
        aggregate["total_leaders_found"] = total_leaders
        aggregate["critical_changes"] = all_critical_changes
        aggregate["report_details"] = {
            "extracted": extracted_details,
            "failed": failed_details,
            "skipped": skipped_details,
        }
        return aggregate

    def _process_company_leadership(
        self,
        company: dict[str, Any],
        tracker: ProgressTracker,
        all_critical_changes: list[dict[str, Any]],
        extracted_details: list[dict[str, Any]],
        failed_details: list[dict[str, Any]],
        skipped_details: list[dict[str, Any]],
    ) -> int:
        """Process a single company's leadership extraction (sequential mode helper).

        Returns number of leaders found.
        """
        try:
            result = self.extract_company_leadership(company["id"])
            if result.get("error"):
                tracker.record_failure(result["error"])
                failed_details.append(
                    {
                        "company_id": company["id"],
                        "name": company.get("name", ""),
                        "error": result["error"],
                    }
                )
                return 0
            for change in result.get("leadership_changes", []):
                if change.get("severity") == "critical":
                    all_critical_changes.append({**change, "company_name": company["name"]})
            tracker.record_success()
            extracted_details.append(
                {
                    "company_id": result["company_id"],
                    "name": result["company_name"],
                    "method_used": result["method_used"],
                    "leaders_found": result["leaders_found"],
                    "leaders": result.get("leaders", []),
                    "leadership_changes": result.get("leadership_changes", []),
                }
            )
            return int(result.get("leaders_found", 0))
        except Exception as exc:
            logger.error(
                "leadership_extraction_failed",
                company=company["name"],
                error=str(exc),
            )
            tracker.record_failure(str(exc))
            failed_details.append(
                {
                    "company_id": company["id"],
                    "name": company.get("name", ""),
                    "error": str(exc),
                }
            )
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
