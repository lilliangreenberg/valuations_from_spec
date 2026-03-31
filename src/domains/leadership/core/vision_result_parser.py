"""Parsers for Claude Vision analysis results.

Pure functions -- no I/O operations.
Handles merging DOM-extracted data with Vision-extracted data.
"""

from __future__ import annotations

import json
from typing import Any

from src.domains.leadership.core.profile_parsing import extract_linkedin_profile_url


def parse_people_tab_result(vision_response: dict[str, Any]) -> list[dict[str, str]]:
    """Parse Claude Vision response for People tab screenshots.

    Args:
        vision_response: Parsed JSON dict from Claude Vision analysis.

    Returns:
        List of dicts with keys: name, title, profile_url
    """
    employees = vision_response.get("employees", [])
    results: list[dict[str, str]] = []

    for emp in employees:
        name = str(emp.get("name", "")).strip()
        title = str(emp.get("title", "")).strip()
        raw_url = emp.get("profile_url")

        if not name:
            continue

        profile_url = ""
        if raw_url and raw_url != "null":
            profile_url = extract_linkedin_profile_url(str(raw_url)) or ""

        results.append({
            "name": name,
            "title": title,
            "profile_url": profile_url,
        })

    return results


def parse_person_employment_result(
    vision_response: dict[str, Any],
) -> dict[str, Any]:
    """Parse Claude Vision response for personal profile employment check.

    Args:
        vision_response: Parsed JSON dict from Claude Vision analysis.

    Returns:
        Dict with keys: person_name, current_title, current_employer,
        is_employed, never_employed, evidence
    """
    return {
        "person_name": str(vision_response.get("person_name", "")).strip(),
        "current_title": str(vision_response.get("current_title", "")).strip(),
        "current_employer": str(vision_response.get("current_employer", "")).strip(),
        "is_employed": bool(vision_response.get("is_employed", False)),
        "never_employed": bool(vision_response.get("never_employed", False)),
        "evidence": str(vision_response.get("evidence", "")).strip(),
    }


def merge_dom_and_vision_results(
    dom_results: list[dict[str, str]],
    vision_results: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Merge DOM-extracted and Vision-extracted people results.

    Strategy:
    - DOM provides reliable profile URLs (vision often can't read them)
    - Vision catches names and titles that DOM selectors may miss
    - Matching is done by name similarity (case-insensitive)
    - DOM entries are primary; Vision entries fill gaps and add new people

    Args:
        dom_results: People extracted via DOM/JS selectors.
        vision_results: People extracted via Claude Vision analysis.

    Returns:
        Merged list of people dicts with keys: name, title, profile_url
    """
    # Index DOM results by normalized name for matching
    dom_by_name: dict[str, dict[str, str]] = {}
    dom_by_url: dict[str, dict[str, str]] = {}

    for person in dom_results:
        name_key = _normalize_name(person.get("name", ""))
        url = person.get("profile_url", "")
        if name_key:
            dom_by_name[name_key] = person
        if url:
            dom_by_url[url] = person

    merged: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    seen_names: set[str] = set()

    # Start with DOM results (they have reliable URLs)
    for person in dom_results:
        url = person.get("profile_url", "")
        name_key = _normalize_name(person.get("name", ""))

        # Try to enrich from Vision data
        enriched = dict(person)
        vision_match = _find_vision_match(name_key, vision_results)
        if vision_match:
            # Vision fills in missing title
            if not enriched.get("title") and vision_match.get("title"):
                enriched["title"] = vision_match["title"]
            # Vision may have a better name (full name vs truncated)
            if len(vision_match.get("name", "")) > len(enriched.get("name", "")):
                enriched["name"] = vision_match["name"]
            # Mark vision match's name as seen to prevent duplicate
            vision_name_key = _normalize_name(vision_match.get("name", ""))
            if vision_name_key:
                seen_names.add(vision_name_key)

        merged.append(enriched)
        if url:
            seen_urls.add(url)
        if name_key:
            seen_names.add(name_key)

    # Add Vision-only results (people DOM missed)
    for person in vision_results:
        name_key = _normalize_name(person.get("name", ""))
        url = person.get("profile_url", "")

        if url and url in seen_urls:
            continue
        if name_key and name_key in seen_names:
            continue

        # This is a new person found only by Vision
        merged.append(person)
        if url:
            seen_urls.add(url)
        if name_key:
            seen_names.add(name_key)

    return merged


def parse_vision_json_response(text: str) -> dict[str, Any]:
    """Parse a JSON response from Claude Vision, handling markdown code blocks.

    Args:
        text: Raw text response from Claude Vision.

    Returns:
        Parsed JSON dict.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first line (```json) and last line (```)
        if len(lines) > 2:
            cleaned = "\n".join(lines[1:-1])

    try:
        result: dict[str, Any] = json.loads(cleaned)
        return result
    except json.JSONDecodeError:
        return {"error": f"Failed to parse Vision response: {cleaned[:200]}"}


def _normalize_name(name: str) -> str:
    """Normalize a name for comparison."""
    return " ".join(name.lower().split())


def _find_vision_match(
    name_key: str,
    vision_results: list[dict[str, str]],
) -> dict[str, str] | None:
    """Find a matching Vision result by name."""
    if not name_key:
        return None

    for person in vision_results:
        vision_name = _normalize_name(person.get("name", ""))
        if vision_name == name_key:
            return person
        # Partial match: one name contains the other
        if vision_name and name_key and (
            vision_name in name_key or name_key in vision_name
        ):
            return person

    return None
