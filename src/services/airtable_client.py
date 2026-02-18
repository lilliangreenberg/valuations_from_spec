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
                # The actual company name field - commonly "Name" or "Company Name"
                name = record["fields"].get("Name") or record["fields"].get("Company Name")
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
