"""Leadership mention reconciliation.

Pure functions that compare website-extracted leadership mentions against
stored LinkedIn-based leadership records and surface discrepancies.

A discrepancy can mean several things:

- A person is mentioned on the website but has no LinkedIn record we know
  about (missing_in_db). Could be a recent hire, or a scraping gap.
- A leader is in the DB as current but not mentioned on the website at all
  (missing_on_website). Could indicate a stale roster (they departed and
  the scraper hasn't caught it yet).

Matching is done on a lightly-normalized person name. We deliberately use
a conservative name matcher (case-insensitive, stripped honorifics,
first/last token containment) rather than full fuzzy matching to keep
false positives low -- this output feeds a review queue, not an
automatic action.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# Words that often precede a proper name but should be ignored during matching.
_NAME_HONORIFICS: frozenset[str] = frozenset(
    {
        "mr",
        "mr.",
        "mrs",
        "mrs.",
        "ms",
        "ms.",
        "dr",
        "dr.",
        "prof",
        "prof.",
        "professor",
    }
)


class ReconciliationFlag(StrEnum):
    """Flag types produced by the reconciler."""

    MISSING_IN_DB = "missing_in_db"
    MISSING_ON_WEBSITE = "missing_on_website"
    MATCHED = "matched"


@dataclass(frozen=True)
class ReconciliationResult:
    """A single reconciliation finding for a company."""

    flag: ReconciliationFlag
    person_name: str
    title: str | None
    source: str
    notes: str


def _normalize_name(name: str) -> str:
    """Return a comparable form of a person name.

    Lowercase, strip honorifics, collapse whitespace. Keeps middle names
    so "John R. Smith" doesn't collide with "John R Smith" differently.
    """
    parts = [p for p in name.strip().lower().split() if p]
    filtered = [p for p in parts if p not in _NAME_HONORIFICS]
    return " ".join(filtered)


def _name_tokens(name: str) -> set[str]:
    """Return the set of meaningful tokens from a name.

    Used for token-overlap comparison where strict string equality is too
    brittle ("Jane Smith" vs "Jane Q. Smith").
    """
    normalized = _normalize_name(name)
    return {tok for tok in normalized.split() if len(tok) > 1}


def names_match(a: str, b: str) -> bool:
    """Return True when two names plausibly refer to the same person.

    Conservative: first AND last non-trivial tokens must overlap between
    the two names. "Jane Smith" matches "Jane Q. Smith" and "Smith, Jane".
    It does NOT match "Jane Doe" or "John Smith".
    """
    tokens_a = _name_tokens(a)
    tokens_b = _name_tokens(b)
    if not tokens_a or not tokens_b:
        return False

    # Require at least two overlapping tokens OR full equality of the
    # shorter name's tokens within the longer one.
    overlap = tokens_a & tokens_b
    if len(overlap) >= 2:
        return True

    shorter = tokens_a if len(tokens_a) <= len(tokens_b) else tokens_b
    longer = tokens_b if shorter is tokens_a else tokens_a
    return len(shorter) >= 2 and shorter.issubset(longer)


def reconcile_leadership(
    mentions: list[dict[str, str]],
    current_leadership: list[dict[str, str]],
) -> list[ReconciliationResult]:
    """Compare website mentions against the stored roster.

    Args:
        mentions: Rows from leadership_mentions. Each dict must have at
            least person_name and title_context.
        current_leadership: Rows from company_leadership with is_current=1.
            Each dict must have at least person_name and title.

    Returns:
        A list of ReconciliationResult findings -- missing-in-db,
        missing-on-website, and matched entries.
    """
    results: list[ReconciliationResult] = []

    if not mentions and not current_leadership:
        return results

    matched_leadership_ids: set[int] = set()

    for mention in mentions:
        mention_name = str(mention.get("person_name") or "").strip()
        if not mention_name:
            continue

        title_context = str(mention.get("title_context") or "")

        match_found = False
        for idx, leader in enumerate(current_leadership):
            leader_name = str(leader.get("person_name") or "").strip()
            if not leader_name:
                continue
            if names_match(mention_name, leader_name):
                match_found = True
                matched_leadership_ids.add(idx)
                results.append(
                    ReconciliationResult(
                        flag=ReconciliationFlag.MATCHED,
                        person_name=leader_name,
                        title=str(leader.get("title") or "") or None,
                        source="leadership_mentions + company_leadership",
                        notes=(
                            f"Website mention ({title_context}) "
                            f"matches stored leader ({leader.get('title', '')})"
                        ),
                    )
                )
                break

        if not match_found:
            results.append(
                ReconciliationResult(
                    flag=ReconciliationFlag.MISSING_IN_DB,
                    person_name=mention_name,
                    title=title_context or None,
                    source="leadership_mentions",
                    notes=(
                        f"Website mentions '{mention_name}' as {title_context!r} "
                        "but no matching leader is stored. Consider running "
                        "CEO LinkedIn discovery with this name."
                    ),
                )
            )

    for idx, leader in enumerate(current_leadership):
        if idx in matched_leadership_ids:
            continue
        leader_name = str(leader.get("person_name") or "").strip()
        if not leader_name:
            continue
        results.append(
            ReconciliationResult(
                flag=ReconciliationFlag.MISSING_ON_WEBSITE,
                person_name=leader_name,
                title=str(leader.get("title") or "") or None,
                source="company_leadership",
                notes=(
                    f"Stored leader '{leader_name}' "
                    f"({leader.get('title', '')}) is not mentioned on the "
                    "website; possibly stale, worth re-verifying."
                ),
            )
        )

    return results
