"""Leadership change detection and severity classification.

Pure functions for comparing current vs previous leadership snapshots,
detecting departures and new arrivals, and classifying change severity.
No I/O operations.
"""

from __future__ import annotations

from enum import StrEnum

from src.domains.monitoring.core.significance_analysis import SignificanceResult

# Titles whose changes are flagged as critical (MAJOR significance)
CRITICAL_TITLES: set[str] = {
    "ceo",
    "chief executive officer",
    "founder",
    "co-founder",
    "cofounder",
    "co founder",
    "cto",
    "chief technology officer",
    "coo",
    "chief operating officer",
    "president",
}


class LeadershipChangeType(StrEnum):
    """Types of leadership changes detected."""

    CEO_DEPARTURE = "ceo_departure"
    FOUNDER_DEPARTURE = "founder_departure"
    CTO_DEPARTURE = "cto_departure"
    COO_DEPARTURE = "coo_departure"
    EXECUTIVE_DEPARTURE = "executive_departure"
    NEW_CEO = "new_ceo"
    NEW_LEADERSHIP = "new_leadership"
    NO_CHANGE = "no_change"


def _classify_departure(title: str) -> LeadershipChangeType:
    """Classify a departure by title."""
    lower = title.strip().lower()
    if lower in ("ceo", "chief executive officer"):
        return LeadershipChangeType.CEO_DEPARTURE
    if lower in ("founder", "co-founder", "cofounder", "co founder"):
        return LeadershipChangeType.FOUNDER_DEPARTURE
    if lower in ("cto", "chief technology officer"):
        return LeadershipChangeType.CTO_DEPARTURE
    if lower in ("coo", "chief operating officer"):
        return LeadershipChangeType.COO_DEPARTURE
    return LeadershipChangeType.EXECUTIVE_DEPARTURE


def _classify_arrival(title: str) -> LeadershipChangeType:
    """Classify a new arrival by title."""
    lower = title.strip().lower()
    if lower in ("ceo", "chief executive officer"):
        return LeadershipChangeType.NEW_CEO
    return LeadershipChangeType.NEW_LEADERSHIP


def compare_leadership(
    previous: list[dict[str, str]],
    current: list[dict[str, str]],
) -> list[dict[str, str | LeadershipChangeType]]:
    """Compare previous and current leadership rosters.

    Compares by linkedin_profile_url as the stable identifier.

    Returns list of change dicts with keys:
        change_type, person_name, title, profile_url, severity
    """
    prev_urls = {p["linkedin_profile_url"] for p in previous}
    curr_urls = {p["linkedin_profile_url"] for p in current}

    changes: list[dict[str, str | LeadershipChangeType]] = []

    # Departures: in previous but not in current
    for person in previous:
        url = person["linkedin_profile_url"]
        if url not in curr_urls:
            title = person.get("title", "")
            change_type = _classify_departure(title)
            severity = classify_change_severity(change_type, title)
            changes.append(
                {
                    "change_type": change_type,
                    "person_name": person.get("person_name", ""),
                    "title": title,
                    "profile_url": url,
                    "severity": severity,
                }
            )

    # New arrivals: in current but not in previous
    for person in current:
        url = person["linkedin_profile_url"]
        if url not in prev_urls:
            title = person.get("title", "")
            change_type = _classify_arrival(title)
            severity = classify_change_severity(change_type, title)
            changes.append(
                {
                    "change_type": change_type,
                    "person_name": person.get("person_name", ""),
                    "title": title,
                    "profile_url": url,
                    "severity": severity,
                }
            )

    return changes


def classify_change_severity(
    change_type: LeadershipChangeType,
    title: str,
) -> str:
    """Classify the severity of a leadership change.

    Returns:
        "critical" -- CEO/Founder/CTO/COO departures
        "notable" -- other executive departures, new CEO, new leadership
        "minor" -- lower-level changes (should not normally reach here)
    """
    departure_types = {
        LeadershipChangeType.CEO_DEPARTURE,
        LeadershipChangeType.FOUNDER_DEPARTURE,
        LeadershipChangeType.CTO_DEPARTURE,
        LeadershipChangeType.COO_DEPARTURE,
    }

    if change_type in departure_types:
        return "critical"

    if change_type in (
        LeadershipChangeType.NEW_CEO,
        LeadershipChangeType.NEW_LEADERSHIP,
        LeadershipChangeType.EXECUTIVE_DEPARTURE,
    ):
        return "notable"

    return "minor"


def build_leadership_change_summary(
    changes: list[dict[str, str | LeadershipChangeType]],
) -> SignificanceResult:
    """Build a SignificanceResult from leadership changes.

    Critical changes (CEO/Founder/CTO/COO departure) -> SIGNIFICANT, 0.95 confidence
    Notable changes (new CEO, other leadership) -> SIGNIFICANT, 0.80 confidence
    No changes -> INSIGNIFICANT
    """
    if not changes:
        return SignificanceResult(
            classification="insignificant",
            sentiment="neutral",
            confidence=0.75,
            notes="No leadership changes detected",
        )

    critical_changes = [c for c in changes if c.get("severity") == "critical"]
    notable_changes = [c for c in changes if c.get("severity") == "notable"]

    # Determine sentiment based on change types
    has_departures = any(str(c.get("change_type", "")).endswith("_departure") for c in changes)
    has_arrivals = any(str(c.get("change_type", "")).startswith("new_") for c in changes)

    if has_departures and has_arrivals:
        sentiment = "mixed"
    elif has_departures:
        sentiment = "negative"
    elif has_arrivals:
        sentiment = "positive"
    else:
        sentiment = "neutral"

    # Build matched keywords and evidence
    keywords = [str(c.get("change_type", "")) for c in changes]
    categories = list({str(c.get("severity", "")) for c in changes})
    evidence = [
        f"{c.get('person_name', 'Unknown')} ({c.get('title', '')}) - {c.get('change_type', '')}"
        for c in changes
    ]

    if critical_changes:
        return SignificanceResult(
            classification="significant",
            sentiment=sentiment,
            confidence=0.95,
            matched_keywords=keywords,
            matched_categories=categories,
            notes=f"{len(critical_changes)} critical leadership change(s) detected",
            evidence_snippets=evidence,
        )

    if notable_changes:
        return SignificanceResult(
            classification="significant",
            sentiment=sentiment,
            confidence=0.80,
            matched_keywords=keywords,
            matched_categories=categories,
            notes=f"{len(notable_changes)} notable leadership change(s) detected",
            evidence_snippets=evidence,
        )

    return SignificanceResult(
        classification="insignificant",
        sentiment="neutral",
        confidence=0.75,
        notes="No significant leadership changes",
    )
