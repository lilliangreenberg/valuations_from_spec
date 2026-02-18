"""Company extraction orchestrator."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from src.core.transformers import normalize_company_name
from src.domains.discovery.core.blog_detection import BlogType, detect_blog_url, normalize_blog_url
from src.domains.discovery.core.platform_detection import detect_platform
from src.domains.discovery.core.url_normalization import normalize_social_url

if TYPE_CHECKING:
    from src.domains.discovery.repositories.social_media_link_repository import (
        SocialMediaLinkRepository,
    )
    from src.repositories.company_repository import CompanyRepository
    from src.services.airtable_client import AirtableClient

logger = structlog.get_logger(__name__)

# Airtable Resource types that map to social media platforms
_RESOURCE_TO_PLATFORM: dict[str, str] = {
    "linkedin - corporate": "linkedin",
    "linkedin - person": "linkedin",
    "twitter": "twitter",
    "instagram": "instagram",
    "facebook": "facebook",
    "youtube": "youtube",
    "github": "github",
    "tiktok": "tiktok",
    "bluesky": "bluesky",
}

# Airtable Resource types that are blog links
_BLOG_RESOURCES: set[str] = {"blog"}

# Resource types to skip (not social media or blogs)
_SKIP_RESOURCES: set[str] = {
    "homepage",
    "crunchbase",
    "ycombinator",
    "bloomberg",
    "wikipedia",
    "reddit",
    "edgar",
    "other",
    "no/little info / unsure",
    "kagi query",
}


class CompanyExtractor:
    """Orchestrates extracting companies from Airtable and storing locally."""

    def __init__(
        self,
        airtable_client: AirtableClient,
        company_repo: CompanyRepository,
    ) -> None:
        self.airtable = airtable_client
        self.company_repo = company_repo

    def extract_companies(self) -> dict[str, int]:
        """Extract all companies from Airtable and store in database.

        Bulk-fetches company names in a single API call instead of
        resolving each linked record individually.

        Returns summary dict with: processed, stored, skipped, errors.
        """
        records = self.airtable.fetch_online_presence_records()
        name_lookup = self.airtable.build_company_name_lookup()

        processed = 0
        stored = 0
        skipped = 0
        errors = 0

        for record in records:
            processed += 1
            fields = record.get("fields", {})

            # Filter for homepage records
            # Airtable field is "Resource" (singular, capitalized), value is a string
            resource = fields.get("Resource") or fields.get("resources", "")
            if isinstance(resource, list):
                resource_values = [r.lower() if isinstance(r, str) else "" for r in resource]
            elif isinstance(resource, str):
                resource_values = [resource.lower()]
            else:
                resource_values = []

            if "homepage" not in resource_values:
                skipped += 1
                continue

            # Get company name from linked record
            company_name_field = fields.get("company_name", [])
            if not company_name_field:
                logger.debug("record_missing_company_name", record_id=record.get("id"))
                skipped += 1
                continue

            # company_name is a linked record -- resolve via bulk lookup
            if isinstance(company_name_field, list) and company_name_field:
                record_id = company_name_field[0]
                company_name = name_lookup.get(record_id)
            elif isinstance(company_name_field, str):
                company_name = company_name_field
            else:
                skipped += 1
                continue

            if not company_name:
                skipped += 1
                continue

            company_name = normalize_company_name(company_name)
            homepage_url = fields.get("url")

            try:
                self.company_repo.upsert_company(
                    name=company_name,
                    homepage_url=homepage_url,
                    source_sheet="Online Presence",
                )
                stored += 1
            except Exception as exc:
                logger.error(
                    "failed_to_store_company",
                    company=company_name,
                    error=str(exc),
                )
                errors += 1

        summary = {
            "processed": processed,
            "stored": stored,
            "skipped": skipped,
            "errors": errors,
        }
        logger.info("extraction_complete", **summary)
        return summary

    def import_social_urls(
        self,
        social_link_repo: SocialMediaLinkRepository,
    ) -> dict[str, Any]:
        """Import social media and blog URLs from Airtable Online Presence table.

        Bulk-fetches company names in a single API call. Maps Airtable Resource
        types to platforms/blog types and stores them. Requires companies to
        already exist in the local database (run extract_companies first).

        Returns summary dict with: processed, social_stored, blog_stored, skipped, errors.
        """
        records = self.airtable.fetch_online_presence_records()
        name_lookup = self.airtable.build_company_name_lookup()
        now = datetime.now(UTC).isoformat()

        processed = 0
        social_stored = 0
        blog_stored = 0
        skipped = 0
        errors = 0

        # Cache local DB lookups: airtable record ID -> (company_name, company_id) | None
        company_cache: dict[str, tuple[str, int] | None] = {}

        for record in records:
            processed += 1
            fields = record.get("fields", {})

            resource = fields.get("Resource") or fields.get("resources", "")
            if isinstance(resource, list):
                resource_lower = resource[0].lower() if resource else ""
            elif isinstance(resource, str):
                resource_lower = resource.lower()
            else:
                skipped += 1
                continue

            # Skip non-importable resource types
            if resource_lower in _SKIP_RESOURCES or resource_lower == "":
                skipped += 1
                continue

            url = fields.get("url")
            if not url or not isinstance(url, str):
                skipped += 1
                continue

            url = url.strip()
            if not url.startswith(("http://", "https://")):
                skipped += 1
                continue

            # Resolve company name to local DB ID
            company_name_field = fields.get("company_name", [])
            if not company_name_field:
                skipped += 1
                continue

            if isinstance(company_name_field, list) and company_name_field:
                airtable_record_id = company_name_field[0]
            elif isinstance(company_name_field, str):
                airtable_record_id = company_name_field
            else:
                skipped += 1
                continue

            # Resolve via bulk lookup + local DB cache
            if airtable_record_id not in company_cache:
                company_cache[airtable_record_id] = self._resolve_company_id_from_lookup(
                    airtable_record_id, name_lookup
                )

            resolved = company_cache[airtable_record_id]
            if resolved is None:
                skipped += 1
                continue

            company_name, company_id = resolved

            try:
                if resource_lower in _RESOURCE_TO_PLATFORM:
                    stored = self._store_social_link(
                        social_link_repo=social_link_repo,
                        company_id=company_id,
                        url=url,
                        resource_lower=resource_lower,
                        now=now,
                    )
                    if stored:
                        social_stored += 1
                elif resource_lower in _BLOG_RESOURCES:
                    stored = self._store_blog_link(
                        social_link_repo=social_link_repo,
                        company_id=company_id,
                        url=url,
                        now=now,
                    )
                    if stored:
                        blog_stored += 1
                else:
                    logger.debug(
                        "unknown_resource_type",
                        resource=resource_lower,
                        url=url,
                    )
                    skipped += 1
            except Exception as exc:
                logger.error(
                    "failed_to_import_url",
                    company=company_name,
                    url=url,
                    error=str(exc),
                )
                errors += 1

        summary: dict[str, Any] = {
            "processed": processed,
            "social_stored": social_stored,
            "blog_stored": blog_stored,
            "skipped": skipped,
            "errors": errors,
        }
        logger.info("url_import_complete", **summary)
        return summary

    def _resolve_company_id_from_lookup(
        self,
        airtable_record_id: str,
        name_lookup: dict[str, str],
    ) -> tuple[str, int] | None:
        """Resolve an Airtable record ID to a local (company_name, company_id) pair.

        Uses the pre-fetched name_lookup instead of individual API calls.
        """
        company_name = name_lookup.get(airtable_record_id)
        if not company_name:
            return None

        company_name = normalize_company_name(company_name)
        company = self.company_repo.get_company_by_name(company_name)
        if not company:
            logger.debug("company_not_in_local_db", company=company_name)
            return None

        return company_name, company["id"]

    def _store_social_link(
        self,
        social_link_repo: SocialMediaLinkRepository,
        company_id: int,
        url: str,
        resource_lower: str,
        now: str,
    ) -> bool:
        """Normalize and store a social media link. Returns True if stored."""
        platform = _RESOURCE_TO_PLATFORM.get(resource_lower)
        if not platform:
            return False

        # Verify URL actually matches the expected platform via detection
        detected = detect_platform(url)
        if detected is not None:
            platform = detected.value

        normalized_url = normalize_social_url(url)

        account_type = None
        if resource_lower == "linkedin - person":
            account_type = "personal"
        elif resource_lower == "linkedin - corporate":
            account_type = "company"

        row_id = social_link_repo.store_social_link(
            {
                "company_id": company_id,
                "platform": platform,
                "profile_url": normalized_url,
                "discovery_method": "airtable_import",
                "verification_status": "manually_reviewed",
                "discovered_at": now,
                "account_type": account_type,
            }
        )
        return row_id > 0

    def _store_blog_link(
        self,
        social_link_repo: SocialMediaLinkRepository,
        company_id: int,
        url: str,
        now: str,
    ) -> bool:
        """Classify and store a blog link. Returns True if stored."""
        is_blog, blog_type = detect_blog_url(url)
        if not is_blog or blog_type is None:
            # URL tagged as Blog in Airtable but doesn't match known patterns.
            # Store as company_blog since the human curator classified it as a blog.
            blog_type = BlogType.COMPANY_BLOG

        normalized_url = normalize_blog_url(url)

        row_id = social_link_repo.store_blog_link(
            {
                "company_id": company_id,
                "blog_type": blog_type.value,
                "blog_url": normalized_url,
                "discovery_method": "airtable_import",
                "is_active": True,
                "discovered_at": now,
            }
        )
        return row_id > 0
