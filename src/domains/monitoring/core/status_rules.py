"""Company status determination rules."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum


class CompanyStatusType(StrEnum):
    OPERATIONAL = "operational"
    LIKELY_CLOSED = "likely_closed"
    UNCERTAIN = "uncertain"


class SignalType(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


def extract_copyright_year(content: str) -> int | None:
    """Extract the highest copyright year from content.

    Patterns matched: (c) YYYY, (C) YYYY, Copyright YYYY, copyright-symbol YYYY
    Supports year ranges (e.g., 2020-2025). Returns highest year found.
    Requires a copyright marker before the year.
    """
    patterns = [
        r"(?:\(c\)|\(C\)|[Cc]opyright|©)\s*(\d{4})(?:\s*[-\u2013]\s*(\d{4}))?",
    ]

    max_year: int | None = None
    for pattern in patterns:
        for match in re.finditer(pattern, content):
            year1 = int(match.group(1))
            year2_str = match.group(2)
            year = int(year2_str) if year2_str else year1
            if max_year is None or year > max_year:
                max_year = year

    return max_year


# Acquisition detection keywords
ACQUISITION_PATTERNS: list[str] = [
    "acquired by",
    "merged with",
    "sold to",
    "now part of",
    "is now a subsidiary of",
    "is now a division of",
    "is now a part of",
    "is now a unit of",
    "is now a brand of",
]


def detect_acquisition(content: str) -> tuple[bool, str | None]:
    """Detect acquisition keywords in content.

    Returns (is_acquired, matched_text).
    Note: "is now" without a corporate structure word is NOT matched
    to avoid false positives like "Product X is now available".
    """
    content_lower = content.lower()
    for pattern in ACQUISITION_PATTERNS:
        if pattern in content_lower:
            # Find the context around the match
            idx = content_lower.index(pattern)
            start = max(0, idx - 30)
            end = min(len(content), idx + len(pattern) + 50)
            context = content[start:end].strip()
            return True, context
    return False, None


def calculate_confidence(indicators: list[tuple[str, str, SignalType]]) -> float:
    """Calculate confidence score from indicators.

    Each indicator contributes:
    - positive: +0.4
    - negative: +0.4
    - neutral: +0.2

    Result clamped to [0.0, 1.0].
    """
    if not indicators:
        return 0.0

    total = 0.0
    for _, _, signal in indicators:
        if signal in (SignalType.POSITIVE, SignalType.NEGATIVE):
            total += 0.4
        else:
            total += 0.2

    return min(1.0, max(0.0, total))


def determine_status(
    confidence: float,
    indicators: list[tuple[str, str, SignalType]],
) -> CompanyStatusType:
    """Determine company status from confidence and indicators.

    High confidence (>= 0.7):
      - Any negative signals -> likely_closed
      - Otherwise -> operational
    Medium confidence (0.4-0.7):
      - More positive than negative -> operational
      - More negative than positive -> likely_closed
      - Equal or all neutral -> uncertain
    Low confidence (< 0.4):
      -> uncertain
    """
    if confidence < 0.4:
        return CompanyStatusType.UNCERTAIN

    positive_count = sum(1 for _, _, s in indicators if s == SignalType.POSITIVE)
    negative_count = sum(1 for _, _, s in indicators if s == SignalType.NEGATIVE)

    if confidence >= 0.7:
        if negative_count > 0:
            return CompanyStatusType.LIKELY_CLOSED
        return CompanyStatusType.OPERATIONAL

    # Medium confidence: 0.4-0.7
    if positive_count > negative_count:
        return CompanyStatusType.OPERATIONAL
    elif negative_count > positive_count:
        return CompanyStatusType.LIKELY_CLOSED
    else:
        return CompanyStatusType.UNCERTAIN


def analyze_snapshot_status(
    content: str,
    http_last_modified: datetime | None = None,
) -> tuple[CompanyStatusType, float, list[tuple[str, str, SignalType]]]:
    """Analyze a snapshot to determine company status.

    Returns (status, confidence, indicators).
    Each indicator is (type, value, signal).
    """
    indicators: list[tuple[str, str, SignalType]] = []
    current_year = datetime.now(UTC).year

    # Check copyright year
    copyright_year = extract_copyright_year(content)
    if copyright_year is not None:
        if copyright_year >= current_year - 1:
            indicators.append(("copyright_year", str(copyright_year), SignalType.POSITIVE))
        elif copyright_year >= current_year - 3:
            indicators.append(("copyright_year", str(copyright_year), SignalType.NEUTRAL))
        else:
            indicators.append(("copyright_year", str(copyright_year), SignalType.NEGATIVE))

    # Check for acquisition
    is_acquired, acquisition_text = detect_acquisition(content)
    if is_acquired and acquisition_text:
        indicators.append(("acquisition_text", acquisition_text, SignalType.NEGATIVE))

    # Check HTTP Last-Modified header freshness
    if http_last_modified is not None:
        now = datetime.now(UTC)
        days_since = (now - http_last_modified).days
        if days_since <= 90:
            indicators.append(("http_last_modified", f"{days_since} days ago", SignalType.POSITIVE))
        elif days_since <= 365:
            indicators.append(("http_last_modified", f"{days_since} days ago", SignalType.NEUTRAL))
        else:
            indicators.append(("http_last_modified", f"{days_since} days ago", SignalType.NEGATIVE))

    confidence = calculate_confidence(indicators)
    status = determine_status(confidence, indicators)

    return status, confidence, indicators
