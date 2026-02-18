"""Company extraction orchestrator."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from src.core.transformers import normalize_company_name

if TYPE_CHECKING:
    from src.repositories.company_repository import CompanyRepository
    from src.services.airtable_client import AirtableClient

logger = structlog.get_logger(__name__)


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

        Returns summary dict with: processed, stored, skipped, errors.
        """
        records = self.airtable.fetch_online_presence_records()

        processed = 0
        stored = 0
        skipped = 0
        errors = 0

        for record in records:
            processed += 1
            fields = record.get("fields", {})

            # Filter for homepage records
            resources = fields.get("resources", [])
            if not isinstance(resources, list):
                resources = [resources] if resources else []

            if "homepage" not in [r.lower() if isinstance(r, str) else "" for r in resources]:
                skipped += 1
                continue

            # Get company name from linked record
            company_name_field = fields.get("company_name", [])
            if not company_name_field:
                logger.debug("record_missing_company_name", record_id=record.get("id"))
                skipped += 1
                continue

            # company_name is a linked record -- resolve it
            if isinstance(company_name_field, list) and company_name_field:
                record_id = company_name_field[0]
                company_name = self.airtable.resolve_company_name(record_id)
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
