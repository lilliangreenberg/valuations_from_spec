"""Multi-signal company verification logic for news articles."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Default verification signal weights
DEFAULT_VERIFICATION_WEIGHTS: dict[str, float] = {
    "logo": 0.30,
    "domain": 0.30,
    "context": 0.15,
    "llm": 0.25,
}

# Minimum confidence threshold for verification
VERIFICATION_THRESHOLD: float = 0.40


def calculate_weighted_confidence(
    signals: dict[str, float],
    weights: dict[str, float] | None = None,
) -> float:
    """Calculate total weighted confidence score from verification signals.

    Args:
        signals: signal_name -> value (0.0 or 1.0)
        weights: signal_name -> weight (0.0-1.0), defaults to DEFAULT_VERIFICATION_WEIGHTS

    Returns:
        Total weighted confidence score (0.0-1.0).
    """
    if weights is None:
        weights = DEFAULT_VERIFICATION_WEIGHTS

    total = 0.0
    for signal_name, signal_value in signals.items():
        weight = weights.get(signal_name, 0.0)
        total += signal_value * weight

    return min(1.0, max(0.0, total))


def check_domain_match(article_url: str, company_domain: str) -> bool:
    """Check if company domain appears in article URL or content.

    Uses word-boundary regex to prevent false positives.
    Pattern: (?<![a-zA-Z0-9.\\-]){domain}(?![a-zA-Z0-9\\-])
    """
    if not company_domain:
        return False

    escaped_domain = re.escape(company_domain)
    pattern = rf"(?<![a-zA-Z0-9.\-]){escaped_domain}(?![a-zA-Z0-9\-])"

    return bool(re.search(pattern, article_url, re.IGNORECASE))


def check_domain_in_content(content: str, company_domain: str) -> bool:
    """Check if company domain appears in article content with word boundaries."""
    if not company_domain or not content:
        return False

    escaped_domain = re.escape(company_domain)
    pattern = rf"(?<![a-zA-Z0-9.\-]){escaped_domain}(?![a-zA-Z0-9\-])"

    return bool(re.search(pattern, content, re.IGNORECASE))


def check_name_in_context(content: str, company_name: str) -> bool:
    """Check if company name appears in a business context (not generic mention).

    Looks for the company name near business-related terms.
    """
    if not company_name or not content:
        return False

    content_lower = content.lower()
    name_lower = company_name.lower()

    if name_lower not in content_lower:
        return False

    # Business context terms
    business_terms = [
        "announced",
        "raised",
        "launched",
        "acquired",
        "partnered",
        "company",
        "startup",
        "funding",
        "revenue",
        "customers",
        "product",
        "service",
        "platform",
        "technology",
        "ceo",
        "founded",
        "headquartered",
        "employees",
        "valuation",
    ]

    # Find all occurrences of company name
    idx = 0
    while True:
        pos = content_lower.find(name_lower, idx)
        if pos == -1:
            break

        # Check context window around the name (200 chars each side)
        context_start = max(0, pos - 200)
        context_end = min(len(content), pos + len(name_lower) + 200)
        context_window = content_lower[context_start:context_end]

        if any(term in context_window for term in business_terms):
            return True

        idx = pos + 1

    return False


def extract_domain_from_url(url: str) -> str:
    """Extract the base domain from a URL (without www)."""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def build_evidence_list(
    logo_match: tuple[bool, float] | None,
    domain_match: bool,
    domain_name: str,
    context_match: bool,
    company_name: str,
    llm_match: tuple[bool, str] | None,
) -> list[str]:
    """Build a list of human-readable evidence strings.

    Each signal that matched adds an evidence string.
    """
    evidence: list[str] = []

    if logo_match is not None and logo_match[0]:
        evidence.append(f"Logo similarity: {logo_match[1]:.2f}")

    if domain_match:
        evidence.append(f"Domain match: {domain_name}")

    if context_match:
        evidence.append(f"Name in business context: {company_name}")

    if llm_match is not None and llm_match[0]:
        evidence.append(f"LLM verification: {llm_match[1]}")

    return evidence


def is_article_verified(confidence: float, threshold: float | None = None) -> bool:
    """Check if an article passes the verification threshold."""
    if threshold is None:
        threshold = VERIFICATION_THRESHOLD
    return confidence >= threshold
