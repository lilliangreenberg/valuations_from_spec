"""Social media account classification service."""

from __future__ import annotations

import structlog

from src.core.social_account_extractor import extract_handle
from src.domains.discovery.core.account_patterns import is_company_account_pattern

logger = structlog.get_logger(__name__)


class AccountClassifier:
    """Classifies social media accounts as company or personal."""

    def classify_account(
        self,
        url: str,
        platform: str,
        company_name: str,
        html_location: str | None = None,
        logo_similarity: float | None = None,
    ) -> tuple[str, float]:
        """Classify a social media account.

        Returns (account_type, confidence).
        account_type is "company", "personal", or "unknown".
        """
        confidence = 0.0

        # Extract handle from URL
        handle = extract_handle(url)

        # Check if handle matches company name
        if handle and is_company_account_pattern(handle, company_name):
            confidence += 0.4

        # Higher confidence if found in footer/header
        if html_location in ("footer", "header", "nav"):
            confidence += 0.3
        elif html_location == "main":
            confidence += 0.1

        # Logo similarity boost
        if logo_similarity is not None and logo_similarity > 0.85:
            confidence += 0.3

        confidence = min(1.0, confidence)

        if confidence >= 0.6:
            return "company", confidence
        elif confidence <= 0.2:
            return "personal", 1.0 - confidence
        else:
            return "unknown", confidence
