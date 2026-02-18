"""Company verification service for news articles."""

from __future__ import annotations

from typing import Any

import structlog

from src.domains.news.core.verification_logic import (
    calculate_weighted_confidence,
    check_domain_in_content,
    check_domain_match,
    check_name_in_context,
    extract_domain_from_url,
)

logger = structlog.get_logger(__name__)


class CompanyVerifier:
    """Verifies if a news article is about a specific company."""

    def __init__(self, llm_client: Any | None = None) -> None:
        self.llm_client = llm_client

    def verify(
        self,
        article: dict[str, Any],
        company_name: str,
        company_url: str,
    ) -> tuple[float, list[str]]:
        """Verify article matches company.

        Returns (confidence, evidence_list).
        """
        company_domain = extract_domain_from_url(company_url) if company_url else ""
        signals: dict[str, float] = {}

        # Domain match
        domain_matched = check_domain_match(article.get("url", ""), company_domain)
        if not domain_matched:
            domain_matched = check_domain_in_content(article.get("snippet", ""), company_domain)
        signals["domain"] = 1.0 if domain_matched else 0.0

        # Name context match
        context_matched = check_name_in_context(article.get("snippet", ""), company_name)
        signals["context"] = 1.0 if context_matched else 0.0

        # LLM verification
        if self.llm_client:
            try:
                is_match, reasoning = self.llm_client.verify_company_identity(
                    company_name=company_name,
                    company_url=company_url,
                    article_title=article.get("title", ""),
                    article_source=article.get("source", ""),
                    article_snippet=article.get("snippet", ""),
                )
                signals["llm"] = 1.0 if is_match else 0.0
            except Exception:
                pass

        confidence = calculate_weighted_confidence(signals)

        evidence: list[str] = []
        if domain_matched:
            evidence.append(f"Domain match: {company_domain}")
        if context_matched:
            evidence.append(f"Name in context: {company_name}")

        return confidence, evidence
