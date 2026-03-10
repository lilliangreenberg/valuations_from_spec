"""CEO/founder name extraction from website content.

Pure functions for extracting leadership names from markdown text.
No I/O operations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum


class MentionPriority(IntEnum):
    """Priority ranking for leadership mentions. Lower = higher priority."""

    EXPLICIT_TITLE = 1  # "CEO: John Smith", "Our CEO John Smith"
    NAME_WITH_TITLE = 2  # "John Smith, CEO", "John Smith (CEO)"
    IS_THE_ROLE = 3  # "John Smith is the CEO of"
    FOUNDED_BY = 4  # "Founded by John Smith"


@dataclass(frozen=True)
class LeadershipMention:
    """A mention of a leadership figure extracted from text."""

    person_name: str
    title_context: str  # "CEO", "Founder", "Co-Founder & CEO", etc.
    priority: MentionPriority
    source_snippet: str  # The text fragment where the mention was found


# Titles to match -- rank 1-2 from LEADERSHIP_TITLES (CEO, Founder, President).
# We only extract the most senior leadership from website mentions.
_TITLE_PATTERNS: list[str] = [
    "CEO",
    "Chief Executive Officer",
    "Founder",
    "Co-Founder",
    "Cofounder",
    "Co Founder",
    "President",
]

# Build a case-insensitive inline alternation for title patterns.
# Using (?i:...) scoped flag so ONLY the title part is case-insensitive,
# keeping the name pattern case-sensitive (requires uppercase starts).
_TITLE_ALTERNATION_CI = "(?i:" + "|".join(re.escape(t) for t in _TITLE_PATTERNS) + ")"

# Compound title: "CEO and Co-Founder", "CEO & Founder", etc.
# The (?i:...) scoping on alternation keeps title case-insensitive.
_COMPOUND_TITLE_CI = (
    rf"(?:{_TITLE_ALTERNATION_CI}"
    rf"(?:\s+(?:and|&)\s+{_TITLE_ALTERNATION_CI})*)"
)

# Name pattern: 2-4 capitalized words. Case-SENSITIVE -- requires uppercase start.
# Handles middle names, hyphenated surnames, apostrophes (O'Brien).
# Uses [ \t]+ (not \s+) to prevent matching across newlines.
_NAME_PATTERN = r"[A-Z][a-zA-Z'-]+(?:[ \t]+[A-Z][a-zA-Z'-]+){1,3}"

# Words that should not be treated as person names
_NON_NAME_WORDS: set[str] = {
    "team",
    "company",
    "solutions",
    "search",
    "vision",
    "mission",
    "strategy",
    "services",
    "technology",
    "management",
    "executive",
    "leadership",
    "position",
    "role",
    "office",
    "group",
    "board",
    "partners",
    "consulting",
    "capital",
    "ventures",
    "labs",
    "health",
    "media",
    "digital",
    "global",
    "analytics",
    "systems",
    "network",
    "platform",
    "software",
    "research",
    "design",
    "studio",
    "academy",
    "institute",
    "foundation",
}

# Markdown link pattern: [text](url) -> text
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# Markdown formatting chars: bold, italic, code, remaining brackets
_MARKDOWN_FORMAT_PATTERN = re.compile(r"[*_`\[\]]+")


def extract_leadership_mentions(
    markdown: str,
    company_name: str | None = None,
) -> list[LeadershipMention]:
    """Extract CEO/founder name mentions from markdown content.

    Scans for patterns like:
    - "CEO: John Smith" or "CEO, John Smith"
    - "Our CEO John Smith" or "Our CEO, John Smith"
    - "John Smith, CEO" or "John Smith (CEO)"
    - "John Smith is the founder of Acme"
    - "Founded by John Smith"
    - "CEO and Co-Founder John Smith"

    Returns deduplicated list of LeadershipMention sorted by priority (best first).
    """
    if not markdown or not markdown.strip():
        return []

    # Strip markdown formatting for cleaner matching
    cleaned = _strip_markdown_formatting(markdown)

    mentions: list[LeadershipMention] = []
    mentions.extend(_extract_pattern_title_then_name(cleaned))
    mentions.extend(_extract_pattern_our_title_name(cleaned))
    mentions.extend(_extract_pattern_name_then_title(cleaned))
    mentions.extend(_extract_pattern_is_the_role(cleaned))
    mentions.extend(_extract_pattern_founded_by(cleaned))

    # Validate all names
    validated = [m for m in mentions if _is_valid_person_name(m.person_name, company_name)]

    return _deduplicate_mentions(validated)


def _strip_markdown_formatting(text: str) -> str:
    """Remove markdown formatting while preserving readable text.

    Handles: [text](url) -> text, **bold** -> bold, *italic* -> italic
    """
    # First convert links [text](url) to just text
    result = _MARKDOWN_LINK_PATTERN.sub(r"\1", text)
    # Then strip remaining formatting characters
    return _MARKDOWN_FORMAT_PATTERN.sub("", result)


def _extract_pattern_title_then_name(text: str) -> list[LeadershipMention]:
    """Extract 'Title: Name' or 'Title, Name' patterns.

    Examples: "CEO: John Smith", "CEO, Jane Doe", "Co-Founder: Alice Bob"
    No re.IGNORECASE -- title uses (?i:...) inline, name is case-sensitive.
    """
    pattern = re.compile(rf"\b({_COMPOUND_TITLE_CI})\s*[,:]\s*({_NAME_PATTERN})")
    results: list[LeadershipMention] = []
    for match in pattern.finditer(text):
        title_ctx = _normalize_title_context(match.group(1))
        name = match.group(2).strip()
        snippet = _get_snippet(text, match.start(), match.end())
        results.append(
            LeadershipMention(
                person_name=name,
                title_context=title_ctx,
                priority=MentionPriority.EXPLICIT_TITLE,
                source_snippet=snippet,
            )
        )
    return results


def _extract_pattern_our_title_name(text: str) -> list[LeadershipMention]:
    """Extract 'Our Title Name' or 'Our Title, Name' patterns.

    Examples: "Our CEO John Smith", "Our CEO, Jane Doe"
    """
    pattern = re.compile(rf"\b[Oo]ur\s+({_COMPOUND_TITLE_CI})[,\s]+({_NAME_PATTERN})")
    results: list[LeadershipMention] = []
    for match in pattern.finditer(text):
        title_ctx = _normalize_title_context(match.group(1))
        name = match.group(2).strip()
        snippet = _get_snippet(text, match.start(), match.end())
        results.append(
            LeadershipMention(
                person_name=name,
                title_context=title_ctx,
                priority=MentionPriority.EXPLICIT_TITLE,
                source_snippet=snippet,
            )
        )
    return results


def _extract_pattern_name_then_title(text: str) -> list[LeadershipMention]:
    """Extract 'Name, Title' or 'Name (Title)' or 'Name - Title' patterns.

    Examples: "John Smith, CEO", "Jane Doe (Founder)", "Alice Bob - President"
    """
    # Name, Title or Name - Title
    pattern_comma = re.compile(rf"({_NAME_PATTERN})\s*[,\-]\s*({_COMPOUND_TITLE_CI})\b")
    # Name (Title)
    pattern_parens = re.compile(rf"({_NAME_PATTERN})\s*\(\s*({_COMPOUND_TITLE_CI})\s*\)")
    results: list[LeadershipMention] = []
    for pattern in (pattern_comma, pattern_parens):
        for match in pattern.finditer(text):
            name = match.group(1).strip()
            title_ctx = _normalize_title_context(match.group(2))
            snippet = _get_snippet(text, match.start(), match.end())
            results.append(
                LeadershipMention(
                    person_name=name,
                    title_context=title_ctx,
                    priority=MentionPriority.NAME_WITH_TITLE,
                    source_snippet=snippet,
                )
            )
    return results


def _extract_pattern_is_the_role(text: str) -> list[LeadershipMention]:
    """Extract 'Name is the Title' patterns.

    Examples: "John Smith is the CEO of Acme", "Jane Doe is the founder"
    """
    pattern = re.compile(rf"({_NAME_PATTERN})\s+(?i:is\s+the)\s+({_COMPOUND_TITLE_CI})\b")
    results: list[LeadershipMention] = []
    for match in pattern.finditer(text):
        name = match.group(1).strip()
        title_ctx = _normalize_title_context(match.group(2))
        snippet = _get_snippet(text, match.start(), match.end())
        results.append(
            LeadershipMention(
                person_name=name,
                title_context=title_ctx,
                priority=MentionPriority.IS_THE_ROLE,
                source_snippet=snippet,
            )
        )
    return results


def _extract_pattern_founded_by(text: str) -> list[LeadershipMention]:
    """Extract 'founded by Name' or 'co-founded by Name and Name' patterns.

    Examples: "Founded by John Smith", "Co-founded by Alice Jones and Bob Smith"
    """
    # Multi-founder: "founded by Name and Name"
    pattern_and = re.compile(
        rf"\b(?i:(?:co-?)?founded\s+by)\s+({_NAME_PATTERN})\s+(?i:and)\s+({_NAME_PATTERN})"
    )
    # Single founder: "founded by Name"
    pattern_single = re.compile(rf"\b(?i:(?:co-?)?founded\s+by)\s+({_NAME_PATTERN})")

    results: list[LeadershipMention] = []
    consumed_spans: list[tuple[int, int]] = []

    # Try the "and" pattern first for multi-founder cases
    for match in pattern_and.finditer(text):
        snippet = _get_snippet(text, match.start(), match.end())
        consumed_spans.append((match.start(), match.end()))
        for group_idx in (1, 2):
            name = match.group(group_idx).strip()
            results.append(
                LeadershipMention(
                    person_name=name,
                    title_context="Founder",
                    priority=MentionPriority.FOUNDED_BY,
                    source_snippet=snippet,
                )
            )

    # Also try single founder -- skip matches that overlap with "and" spans
    for match in pattern_single.finditer(text):
        if any(start <= match.start() < end for start, end in consumed_spans):
            continue
        name = match.group(1).strip()
        snippet = _get_snippet(text, match.start(), match.end())
        results.append(
            LeadershipMention(
                person_name=name,
                title_context="Founder",
                priority=MentionPriority.FOUNDED_BY,
                source_snippet=snippet,
            )
        )

    return results


def _is_valid_person_name(
    name: str,
    company_name: str | None = None,
) -> bool:
    """Validate that a string looks like a real person name.

    Rules:
    - At least 2 words
    - Each word starts with an uppercase letter
    - Between 3 and 60 chars total
    - No URLs
    - No common non-name words
    - Not the company name
    """
    if not name or not name.strip():
        return False

    name = name.strip()

    # Reject names containing newlines (corrupted extraction)
    if "\n" in name or "\r" in name:
        return False

    # Length check
    if len(name) < 3 or len(name) > 60:
        return False

    # No URLs (case-insensitive check)
    name_lower = name.lower()
    if "http" in name_lower or "www" in name_lower or ".com" in name_lower:
        return False

    # Split into words
    words = name.split()
    if len(words) < 2:
        return False

    # Each word must start with uppercase (allow hyphens like "Smith-Jones")
    for word in words:
        if not word[0].isupper():
            return False

    # Check for non-name words
    lower_words = name_lower.split()
    for non_name in _NON_NAME_WORDS:
        if non_name in lower_words:
            return False

    # Check against company name
    if company_name:
        company_lower = company_name.strip().lower()
        if name_lower == company_lower:
            return False

    return True


def _deduplicate_mentions(
    mentions: list[LeadershipMention],
) -> list[LeadershipMention]:
    """Deduplicate by (person_name, title_context), keeping highest priority.

    Returns sorted by priority ascending (best first).
    """
    best: dict[tuple[str, str], LeadershipMention] = {}

    for mention in mentions:
        key = (mention.person_name.lower(), mention.title_context.lower())
        existing = best.get(key)
        if existing is None or mention.priority < existing.priority:
            best[key] = mention

    return sorted(best.values(), key=lambda m: m.priority)


def _normalize_title_context(raw_title: str) -> str:
    """Normalize title context to a canonical form.

    Examples: "ceo" -> "CEO", "co-founder" -> "Co-Founder",
    "CEO and Co-Founder" -> "CEO and Co-Founder"
    """
    _canonical: dict[str, str] = {
        "ceo": "CEO",
        "chief executive officer": "Chief Executive Officer",
        "founder": "Founder",
        "co-founder": "Co-Founder",
        "cofounder": "Co-Founder",
        "co founder": "Co-Founder",
        "president": "President",
    }
    stripped = raw_title.strip()
    lower = stripped.lower()
    if lower in _canonical:
        return _canonical[lower]
    # Handle compound titles: normalize each part
    if " and " in lower or " & " in lower:
        parts = re.split(r"\s+(?:and|&)\s+", stripped)
        normalized_parts = [_normalize_title_context(p) for p in parts]
        return " and ".join(normalized_parts)
    return stripped


def _get_snippet(text: str, start: int, end: int, context: int = 30) -> str:
    """Get a text snippet around a match with surrounding context."""
    snippet_start = max(0, start - context)
    snippet_end = min(len(text), end + context)
    snippet = text[snippet_start:snippet_end].strip()
    if snippet_start > 0:
        snippet = "..." + snippet
    if snippet_end < len(text):
        snippet = snippet + "..."
    return snippet
