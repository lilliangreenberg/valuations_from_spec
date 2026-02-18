"""Content change detection logic."""

from __future__ import annotations

from difflib import SequenceMatcher
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
    old_checksum: str,
    new_checksum: str,
    old_content: str | None = None,
    new_content: str | None = None,
) -> tuple[bool, ChangeMagnitude, float]:
    """Detect if content has changed and determine magnitude.

    Returns (has_changed, magnitude, similarity_ratio).
    If checksums match, returns (False, MINOR, 1.0).
    If content is not provided but checksums differ, returns (True, MAJOR, 0.0).
    """
    if old_checksum == new_checksum:
        return False, ChangeMagnitude.MINOR, 1.0

    if old_content is None or new_content is None:
        return True, ChangeMagnitude.MAJOR, 0.0

    similarity = calculate_similarity(old_content, new_content)
    magnitude = determine_magnitude(similarity)
    return True, magnitude, similarity
