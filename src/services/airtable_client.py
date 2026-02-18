"""Airtable API client for extracting company data."""

from __future__ import annotations

from typing import Any

import structlog
from pyairtable import Api

logger = structlog.get_logger(__name__)


class AirtableClient:
    """Client for Airtable API operations."""

    def __init__(self, api_key: str, base_id: str) -> None:
        self.api = Api(api_key)
        self.base_id = base_id

    def fetch_online_presence_records(self) -> list[dict[str, Any]]:
        """Fetch all records from the Online Presence table.

        Returns list of dicts with Airtable record structure.
        """
        table = self.api.table(self.base_id, "Online Presence")
        records = table.all()
        logger.info("fetched_airtable_records", count=len(records))
        return [{"id": r["id"], "fields": r["fields"]} for r in records]

    def resolve_company_name(self, record_id: str) -> str | None:
        """Resolve a linked record ID to a company name.

        The company_name field in Online Presence is a linked record
        pointer to the Portfolio Companies table.
        """
        try:
            table = self.api.table(self.base_id, "Portfolio Companies")
            record = table.get(record_id)
            if record and "fields" in record:
                # Prefer display name, fall back to company_name
                name = (
                    record["fields"].get("company_display_name")
                    or record["fields"].get("company_name")
                    or record["fields"].get("Name")
                    or record["fields"].get("Company Name")
                )
                return str(name) if name else None
        except Exception as exc:
            logger.warning(
                "failed_to_resolve_company_name",
                record_id=record_id,
                error=str(exc),
            )
        return None

    def fetch_portfolio_companies(self) -> list[dict[str, Any]]:
        """Fetch all records from the Portfolio Companies table."""
        table = self.api.table(self.base_id, "Portfolio Companies")
        records = table.all()
        logger.info("fetched_portfolio_companies", count=len(records))
        return [{"id": r["id"], "fields": r["fields"]} for r in records]

    def build_company_name_lookup(self) -> dict[str, str]:
        """Bulk-fetch all Portfolio Companies and build a record_id -> name mapping.

        Single API call replaces N individual resolve_company_name calls.
        """
        records = self.fetch_portfolio_companies()
        lookup: dict[str, str] = {}

        for record in records:
            fields = record.get("fields", {})
            name = (
                fields.get("company_display_name")
                or fields.get("company_name")
                or fields.get("Name")
                or fields.get("Company Name")
            )
            if name:
                lookup[record["id"]] = str(name)

        logger.info("built_company_name_lookup", entries=len(lookup))
        return lookup
