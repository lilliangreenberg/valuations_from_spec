"""Content change detection logic."""

from __future__ import annotations

from difflib import SequenceMatcher, unified_diff
from enum import StrEnum


class ChangeMagnitude(StrEnum):
    MINOR = "minor"  # similarity >= 0.90
    MODERATE = "moderate"  # similarity 0.50-0.90
    MAJOR = "major"  # similarity < 0.50


# Max chars to compare to avoid excessive computation
MAX_COMPARISON_LENGTH = 50_000


def calculate_similarity(old_content: str, new_content: str) -> float:
    """Calculate similarity ratio between two content strings.

    For content > 50,000 characters, only the first 50k chars are compared.
    Returns float between 0.0 and 1.0.
    """
    old_trimmed = old_content[:MAX_COMPARISON_LENGTH]
    new_trimmed = new_content[:MAX_COMPARISON_LENGTH]
    return SequenceMatcher(None, old_trimmed, new_trimmed).ratio()


def determine_magnitude(similarity: float) -> ChangeMagnitude:
    """Determine change magnitude from similarity ratio."""
    if similarity >= 0.90:
        return ChangeMagnitude.MINOR
    elif similarity >= 0.50:
        return ChangeMagnitude.MODERATE
    else:
        return ChangeMagnitude.MAJOR


def detect_content_change(
    old_checksum: str | None,
    new_checksum: str | None,
    old_content: str | None = None,
    new_content: str | None = None,
) -> tuple[bool, ChangeMagnitude, float]:
    """Detect if content has changed and determine magnitude.

    Handles NULL checksums (failed snapshots with no content):
    - Both checksums None -> no content either side -> no change
      (callers can detect error-state transitions via error_message).
    - One checksum None, the other present -> state changed
      (content appeared or disappeared). Magnitude MAJOR.
    - Both present and equal -> no change.
    - Both present and different -> compare content, compute magnitude.

    Returns (has_changed, magnitude, similarity_ratio).
    """
    # Both snapshots have no checksum -> both failed captures. Treat as
    # unchanged from a content-diff perspective; the caller is responsible
    # for detecting error-state transitions via error_message fields.
    if old_checksum is None and new_checksum is None:
        return False, ChangeMagnitude.MINOR, 1.0

    # Transition into or out of a failed-capture state. Content appeared
    # or vanished entirely -- that is always a major change.
    if old_checksum is None or new_checksum is None:
        return True, ChangeMagnitude.MAJOR, 0.0

    if old_checksum == new_checksum:
        return False, ChangeMagnitude.MINOR, 1.0

    if old_content is None or new_content is None:
        return True, ChangeMagnitude.MAJOR, 0.0

    similarity = calculate_similarity(old_content, new_content)
    magnitude = determine_magnitude(similarity)
    return True, magnitude, similarity


def detect_error_state_transition(
    old_error: str | None,
    new_error: str | None,
    old_checksum: str | None,
    new_checksum: str | None,
) -> tuple[bool, str]:
    """Detect transitions in the error state between two snapshots.

    Returns (is_transition, description). A transition occurs when:
    - Previous snapshot had content and current has an error (site broke)
    - Previous snapshot had an error and current has content (site recovered)
    - Both snapshots have errors, but the error messages differ
    """
    old_has_content = old_checksum is not None
    new_has_content = new_checksum is not None

    if old_has_content and not new_has_content:
        return True, f"Content recovery -> error: {(new_error or 'unknown')[:200]}"
    if not old_has_content and new_has_content:
        return True, "Site recovered from previous error"
    if not old_has_content and not new_has_content:
        old_msg = (old_error or "").strip()
        new_msg = (new_error or "").strip()
        if old_msg != new_msg and new_msg:
            return True, f"Error state changed: {new_msg[:200]}"

    return False, ""


def extract_content_diff(old_content: str, new_content: str) -> str:
    """Extract only the added/modified lines between two content versions.

    Uses unified_diff to identify changes, then collects lines prefixed with '+'
    (additions) while excluding the '+++' header line. This produces a string
    containing only the new content that was added or changed -- suitable for
    keyword-based significance analysis without false positives from static content.

    Returns empty string if inputs are empty or identical.
    """
    if not old_content and not new_content:
        return ""

    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff_lines: list[str] = []
    for line in unified_diff(old_lines, new_lines, n=0):
        # Skip diff headers
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        # Collect added lines (strip the leading '+')
        if line.startswith("+"):
            diff_lines.append(line[1:])

    return "".join(diff_lines)
