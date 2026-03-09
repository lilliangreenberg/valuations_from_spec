"""Multi-signal company verification logic for news articles."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Default verification signal weights
DEFAULT_VERIFICATION_WEIGHTS: dict[str, float] = {
    "domain": 0.35,
    "context": 0.25,
    "llm": 0.40,
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


# Penalty applied to the domain signal when a competing domain is detected.
COMPETING_DOMAIN_PENALTY: float = -0.20


def extract_company_description(markdown: str | None, max_length: int = 500) -> str:
    """Extract a meaningful company description from homepage markdown.

    Strips boilerplate lines (short nav items, bare links, empty lines) and
    returns the first ``max_length`` characters of substantive content.
    """
    if not markdown:
        return ""

    meaningful_lines: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        # Skip empty lines
        if not stripped:
            continue
        # Skip lines that are just markdown links or images
        if re.fullmatch(r"!?\[.*?\]\(.*?\)", stripped):
            continue
        # Skip very short lines (likely nav items, menu labels)
        if len(stripped) < 20:
            continue
        # Skip lines that are just URLs
        if re.fullmatch(r"https?://\S+", stripped):
            continue
        # Skip markdown heading markers with very short text (nav headings)
        heading_match = re.match(r"^#{1,6}\s+(.*)", stripped)
        if heading_match and len(heading_match.group(1).strip()) < 20:
            continue
        meaningful_lines.append(stripped)

    result = " ".join(meaningful_lines)
    return result[:max_length].strip()


def _extract_domain_name_part(domain: str) -> str:
    """Extract the name part of a domain (leftmost label without TLD).

    Examples:
        wand.app -> wand
        wand.ai -> wand
        arch0.com -> arch0
        www.techcrunch.com -> techcrunch  (www already stripped by callers)
        blog.acme.io -> blog.acme  (preserves subdomains)
    """
    if not domain:
        return ""
    # Remove port if present
    domain = domain.split(":")[0]
    parts = domain.split(".")
    if len(parts) <= 1:
        return domain
    # Drop the TLD (last part)
    return ".".join(parts[:-1])


def detect_competing_domain(article_url: str, company_domain: str) -> bool:
    """Detect if the article URL belongs to a competing company with a similar name.

    Returns True when the article's domain shares a similar name part with the
    company domain but is a different domain entirely. This indicates the article
    is likely about a different company.

    Examples:
        wand.ai vs wand.app -> True (same name, different domain)
        techcrunch.com vs wand.app -> False (unrelated, not competing)
        wand.app vs wand.app -> False (same domain, not competing)
    """
    if not article_url or not company_domain:
        return False

    article_domain = extract_domain_from_url(article_url)
    if not article_domain:
        return False

    # Same domain is not competing
    if article_domain == company_domain:
        return False

    article_name = _extract_domain_name_part(article_domain)
    company_name = _extract_domain_name_part(company_domain)

    if not article_name or not company_name:
        return False

    # Exact name match with different TLD (wand.ai vs wand.app)
    if article_name == company_name:
        return True

    # One name starts with the other (e.g., "wand" vs "wandtech")
    shorter, longer = sorted([article_name, company_name], key=len)
    return longer.startswith(shorter) and len(shorter) >= 3
