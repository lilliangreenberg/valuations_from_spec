"""CEO/founder LinkedIn discovery via Kagi search.

Discovers CEO/founder personal LinkedIn profiles by:
1. Extracting CEO names from the latest website snapshot (on-demand)
2. Checking if CEO LinkedIn already discovered (social_media_links or company_leadership)
3. Searching Kagi with targeted queries
4. Storing results in company_leadership and social_media_links tables
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from src.domains.discovery.core.url_normalization import normalize_social_url
from src.domains.leadership.core.name_extraction import extract_leadership_mentions
from src.utils.progress import ProgressTracker

if TYPE_CHECKING:
    from src.domains.discovery.repositories.social_media_link_repository import (
        SocialMediaLinkRepository,
    )
    from src.domains.leadership.repositories.leadership_mention_repository import (
        LeadershipMentionRepository,
    )
    from src.domains.leadership.repositories.leadership_repository import (
        LeadershipRepository,
    )
    from src.domains.leadership.services.leadership_search import LeadershipSearch
    from src.domains.monitoring.repositories.snapshot_repository import (
        SnapshotRepository,
    )
    from src.repositories.company_repository import CompanyRepository

logger = structlog.get_logger(__name__)


class CeoLinkedinDiscovery:
    """Discovers CEO/founder LinkedIn profiles via Kagi search."""

    def __init__(
        self,
        leadership_search: LeadershipSearch,
        leadership_repo: LeadershipRepository,
        leadership_mention_repo: LeadershipMentionRepository,
        snapshot_repo: SnapshotRepository,
        social_link_repo: SocialMediaLinkRepository,
        company_repo: CompanyRepository,
    ) -> None:
        self.search = leadership_search
        self.leadership_repo = leadership_repo
        self.mention_repo = leadership_mention_repo
        self.snapshot_repo = snapshot_repo
        self.social_link_repo = social_link_repo
        self.company_repo = company_repo

    def discover_for_company(
        self,
        company_id: int,
        ceo_name: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Discover CEO/founder LinkedIn for a single company.

        Args:
            company_id: Target company.
            ceo_name: Optional known CEO name for targeted search.
            dry_run: If True, show what would be done without writing to DB.

        Returns summary dict with: company_id, company_name, profiles_found,
        already_existed, reverified, ceo_name_used, queries_sent, errors
        """
        company = self.company_repo.get_company_by_id(company_id)
        if not company:
            return {"error": f"Company {company_id} not found"}

        company_name = company["name"]
        errors: list[str] = []

        # Step 1: Extract names from latest snapshot (self-contained)
        self._extract_mentions_from_snapshot(company_id, company_name, dry_run)

        # Step 2: Determine person_name for Kagi search
        person_name = ceo_name
        if not person_name:
            person_name = self._get_ceo_name_from_mentions(company_id)

        # Step 3: Search Kagi
        queries_sent = 0
        try:
            people = self.search.search_ceo_linkedin(company_name, person_name)
            # search_ceo_linkedin sends 2 queries internally (CEO + founder)
            queries_sent = 2
        except Exception as exc:
            logger.error(
                "ceo_linkedin_search_error",
                company=company_name,
                error=str(exc),
            )
            errors.append(f"Kagi search error: {exc}")
            people = []

        if not people:
            logger.info(
                "ceo_linkedin_not_found",
                company=company_name,
                person_name=person_name,
            )

        # Step 4: Store results
        now = datetime.now(UTC).isoformat()
        profiles_found = 0
        already_existed = 0
        reverified = 0

        for person in people:
            profile_url = normalize_social_url(person.get("profile_url", ""))
            if not profile_url or "linkedin.com/in/" not in profile_url:
                continue

            if dry_run:
                logger.info(
                    "dry_run_would_store",
                    company=company_name,
                    person_name=person.get("name", ""),
                    profile_url=profile_url,
                )
                profiles_found += 1
                continue

            # Store in company_leadership
            if self.leadership_repo.leadership_exists(company_id, profile_url):
                self.leadership_repo.update_verification_date(company_id, profile_url, now)
                reverified += 1
                logger.debug(
                    "ceo_linkedin_reverified",
                    company=company_name,
                    url=profile_url,
                )
            else:
                self.leadership_repo.store_leadership(
                    {
                        "company_id": company_id,
                        "person_name": person.get("name", "Unknown"),
                        "title": person.get("title", ""),
                        "linkedin_profile_url": profile_url,
                        "discovery_method": "kagi_ceo_search",
                        "confidence": 0.65,
                        "is_current": True,
                        "discovered_at": now,
                        "last_verified_at": now,
                    }
                )
                profiles_found += 1

            # Store in social_media_links (explicit check, no error-driven dedup)
            if not self.social_link_repo.link_exists(company_id, profile_url):
                self.social_link_repo.store_social_link(
                    {
                        "company_id": company_id,
                        "platform": "linkedin",
                        "profile_url": profile_url,
                        "discovery_method": "kagi_ceo_search",
                        "verification_status": "unverified",
                        "discovered_at": now,
                    }
                )
            else:
                already_existed += 1
                logger.debug(
                    "social_link_already_exists",
                    company=company_name,
                    url=profile_url,
                )

        return {
            "company_id": company_id,
            "company_name": company_name,
            "profiles_found": profiles_found,
            "already_existed": already_existed,
            "reverified": reverified,
            "ceo_name_used": person_name,
            "queries_sent": queries_sent,
            "errors": errors,
        }

    def discover_all(
        self,
        limit: int | None = None,
        max_workers: int = 5,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Discover CEO/founder LinkedIn for all companies in batch.

        Args:
            limit: Process first N companies.
            max_workers: Parallel Kagi search workers.
            dry_run: If True, show what would be done without writing to DB.

        Returns aggregate summary.
        """
        companies = self.company_repo.get_companies_with_homepage()
        if limit is not None:
            companies = companies[:limit]

        tracker = ProgressTracker(total=len(companies))
        total_profiles = 0
        total_reverified = 0
        total_already_existed = 0

        if max_workers <= 1:
            for company in companies:
                result = self._process_company(company, dry_run, tracker)
                total_profiles += result.get("profiles_found", 0)
                total_reverified += result.get("reverified", 0)
                total_already_existed += result.get("already_existed", 0)
                tracker.log_progress(every_n=10)
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        self.discover_for_company, company["id"], None, dry_run
                    ): company
                    for company in companies
                }
                for future in as_completed(futures):
                    company = futures[future]
                    try:
                        result = future.result()
                        if result.get("error"):
                            tracker.record_failure(result["error"])
                        else:
                            total_profiles += result.get("profiles_found", 0)
                            total_reverified += result.get("reverified", 0)
                            total_already_existed += result.get("already_existed", 0)
                            tracker.record_success()
                    except Exception as exc:
                        logger.error(
                            "ceo_discovery_failed",
                            company=company.get("name", ""),
                            error=str(exc),
                        )
                        tracker.record_failure(str(exc))
                    tracker.log_progress(every_n=10)

        summary = tracker.summary()
        summary["total_profiles_found"] = total_profiles
        summary["total_reverified"] = total_reverified
        summary["total_already_existed"] = total_already_existed
        summary["dry_run"] = dry_run
        return summary

    def _process_company(
        self,
        company: dict[str, Any],
        dry_run: bool,
        tracker: ProgressTracker,
    ) -> dict[str, Any]:
        """Process a single company in sequential mode."""
        try:
            result = self.discover_for_company(company["id"], dry_run=dry_run)
            if result.get("error"):
                tracker.record_failure(result["error"])
            else:
                tracker.record_success()
            return result
        except Exception as exc:
            logger.error(
                "ceo_discovery_failed",
                company=company.get("name", ""),
                error=str(exc),
            )
            tracker.record_failure(str(exc))
            return {"profiles_found": 0, "reverified": 0, "already_existed": 0}

    def _extract_mentions_from_snapshot(
        self,
        company_id: int,
        company_name: str,
        dry_run: bool,
    ) -> None:
        """Extract CEO/founder name mentions from latest snapshot.

        Reads the most recent snapshot from DB and extracts names.
        This keeps the leadership domain self-contained (no snapshot manager coupling).
        """
        snapshots = self.snapshot_repo.get_latest_snapshots(company_id, limit=1)
        if not snapshots:
            return

        snapshot = snapshots[0]
        markdown = snapshot.get("content_markdown", "")
        if not markdown:
            return

        mentions = extract_leadership_mentions(markdown, company_name)
        if not mentions:
            return

        if dry_run:
            for mention in mentions:
                logger.info(
                    "dry_run_mention_found",
                    company=company_name,
                    person_name=mention.person_name,
                    title_context=mention.title_context,
                    priority=mention.priority.name,
                )
            return

        now = datetime.now(UTC).isoformat()
        snapshot_id = snapshot.get("id")
        url = snapshot.get("url", "")

        for mention in mentions:
            self.mention_repo.store_mention(
                {
                    "company_id": company_id,
                    "person_name": mention.person_name,
                    "title_context": mention.title_context,
                    "source": "homepage_snapshot",
                    "source_url": url,
                    "confidence": 0.5,
                    "priority": mention.priority.value,
                    "extracted_at": now,
                    "snapshot_id": snapshot_id,
                }
            )

    def _get_ceo_name_from_mentions(self, company_id: int) -> str | None:
        """Look up the highest-priority CEO/founder name from leadership_mentions."""
        mentions = self.mention_repo.get_ceo_mentions(company_id)
        if mentions:
            return str(mentions[0]["person_name"])
        return None
