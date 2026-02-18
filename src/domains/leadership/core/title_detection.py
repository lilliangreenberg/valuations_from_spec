"""Leadership title detection and classification.

Pure functions for detecting, normalizing, and ranking leadership titles.
No I/O operations.
"""

from __future__ import annotations

import re

# Leadership titles mapped to seniority rank (lower = more senior).
# Used for sorting and filtering leadership from non-leadership titles.
LEADERSHIP_TITLES: dict[str, int] = {
    "ceo": 1,
    "chief executive officer": 1,
    "founder": 1,
    "co-founder": 2,
    "cofounder": 2,
    "co founder": 2,
    "president": 2,
    "cto": 3,
    "chief technology officer": 3,
    "coo": 3,
    "chief operating officer": 3,
    "cfo": 3,
    "chief financial officer": 3,
    "cmo": 4,
    "chief marketing officer": 4,
    "chief people officer": 4,
    "chief product officer": 4,
    "chief revenue officer": 4,
    "chief strategy officer": 4,
    "managing director": 4,
    "general manager": 5,
    "vp of engineering": 5,
    "vp engineering": 5,
    "vice president of engineering": 5,
    "vp of product": 5,
    "vp product": 5,
    "vice president": 5,
}

# Pattern to match "Chief X Officer" generically
_CHIEF_X_OFFICER_PATTERN = re.compile(
    r"\bchief\s+\w+\s+officer\b",
    re.IGNORECASE,
)

# Pattern to match VP titles
_VP_PATTERN = re.compile(
    r"\b(?:vp|vice\s+president)\b",
    re.IGNORECASE,
)

# Normalization map: long form -> short form
_NORMALIZATION_MAP: dict[str, str] = {
    "chief executive officer": "CEO",
    "chief technology officer": "CTO",
    "chief operating officer": "COO",
    "chief financial officer": "CFO",
    "chief marketing officer": "CMO",
    "chief people officer": "CPO",
    "chief product officer": "CPO",
    "chief revenue officer": "CRO",
    "chief strategy officer": "CSO",
    "cofounder": "Co-Founder",
    "co founder": "Co-Founder",
    "co-founder": "Co-Founder",
}

_DEFAULT_RANK = 99


def is_leadership_title(title: str) -> bool:
    """Check if a title string contains a leadership role.

    Case-insensitive. Checks for exact matches in LEADERSHIP_TITLES,
    word-boundary matches within longer strings, and generic
    "Chief X Officer" and VP patterns.
    """
    if not title:
        return False
    lower = title.strip().lower()

    # Exact match
    if lower in LEADERSHIP_TITLES:
        return True

    # Word-boundary match within longer strings (e.g., "CEO at Acme Corp")
    for known_title in LEADERSHIP_TITLES:
        pattern = re.compile(r"\b" + re.escape(known_title) + r"\b", re.IGNORECASE)
        if pattern.search(lower):
            return True

    # Generic patterns
    if _CHIEF_X_OFFICER_PATTERN.search(lower):
        return True
    return bool(_VP_PATTERN.search(lower))


def extract_leadership_title(raw_text: str) -> str | None:
    """Extract a leadership title from a raw text string.

    Scans the text for known leadership title patterns and returns
    the first match found. Returns None if no leadership title detected.
    """
    if not raw_text:
        return None

    text_lower = raw_text.lower()

    # Check for explicit titles in the text (longest match first)
    sorted_titles = sorted(LEADERSHIP_TITLES.keys(), key=len, reverse=True)
    for title in sorted_titles:
        pattern = re.compile(r"\b" + re.escape(title) + r"\b", re.IGNORECASE)
        match = pattern.search(text_lower)
        if match:
            return raw_text[match.start() : match.end()]

    # Check for generic "Chief X Officer" pattern
    match = _CHIEF_X_OFFICER_PATTERN.search(raw_text)
    if match:
        return match.group(0)

    # Check for VP pattern
    match = _VP_PATTERN.search(raw_text)
    if match:
        return match.group(0)

    return None


def normalize_title(title: str) -> str:
    """Normalize a leadership title to its canonical form.

    Converts long-form titles to abbreviations (e.g., "Chief Executive Officer" -> "CEO").
    Normalizes casing for known titles.
    """
    lower = title.strip().lower()

    # Check normalization map
    if lower in _NORMALIZATION_MAP:
        return _NORMALIZATION_MAP[lower]

    # Check if it's already a known abbreviation
    upper = title.strip().upper()
    abbreviations = {"CEO", "CTO", "COO", "CFO", "CMO", "CPO", "CRO", "CSO"}
    if upper in abbreviations:
        return upper

    # Capitalize known titles
    if lower in LEADERSHIP_TITLES:
        return title.strip().title()

    return title.strip()


def rank_title(title: str) -> int:
    """Return seniority ranking for a title (lower number = more senior).

    Unknown titles receive the lowest rank (99).
    """
    lower = title.strip().lower()
    if lower in LEADERSHIP_TITLES:
        return LEADERSHIP_TITLES[lower]

    # Check if it matches a Chief X Officer pattern
    if _CHIEF_X_OFFICER_PATTERN.search(lower):
        return 4

    # VP titles
    if _VP_PATTERN.search(lower):
        return 5

    return _DEFAULT_RANK


def classify_role(title: str) -> str:
    """Classify a title into a standardized role category.

    Returns one of: "ceo", "founder", "co_founder", "cto", "coo",
    "president", "cfo", "other_executive", or "other".
    """
    lower = title.strip().lower()

    if lower in ("ceo", "chief executive officer"):
        return "ceo"
    if lower in ("founder",):
        return "founder"
    if lower in ("co-founder", "cofounder", "co founder"):
        return "co_founder"
    if lower in ("cto", "chief technology officer"):
        return "cto"
    if lower in ("coo", "chief operating officer"):
        return "coo"
    if lower in ("president",):
        return "president"
    if lower in ("cfo", "chief financial officer"):
        return "cfo"

    # Generic chief officer or VP
    if _CHIEF_X_OFFICER_PATTERN.search(lower) or _VP_PATTERN.search(lower):
        return "other_executive"

    if lower in LEADERSHIP_TITLES:
        return "other_executive"

    return "other"
