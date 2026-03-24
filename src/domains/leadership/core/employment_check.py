"""Employment status determination from LinkedIn profile data.

Pure functions -- no I/O operations.
Determines if a person is currently employed at a specific company
based on DOM-extracted and Vision-extracted profile data.
"""

from __future__ import annotations

from typing import Any

# Employment status constants
STATUS_EMPLOYED = "employed"
STATUS_DEPARTED = "departed"
STATUS_WRONG_PERSON = "wrong_person"
STATUS_UNKNOWN = "unknown"


def determine_employment_status(
    dom_data: dict[str, Any],
    vision_data: dict[str, Any],
    company_name: str,
) -> dict[str, Any]:
    """Determine if a person is still employed at a given company.

    Combines DOM-extracted profile data with Claude Vision analysis
    to determine employment status.

    Args:
        dom_data: Profile data from DOM extraction (experience list, headline).
        vision_data: Parsed result from Claude Vision analysis.
        company_name: The company name to check against.

    Returns:
        Dict with keys:
            status: "employed", "departed", "wrong_person", or "unknown"
            confidence: float 0.0-1.0
            evidence: str explaining the determination
            current_title: str (if available)
            current_employer: str (if available)
    """
    # Vision result is the primary signal
    if vision_data and not vision_data.get("error"):
        return _determine_from_vision(vision_data, company_name)

    # Fall back to DOM-only analysis
    if dom_data:
        return _determine_from_dom(dom_data, company_name)

    return {
        "status": STATUS_UNKNOWN,
        "confidence": 0.0,
        "evidence": "No data available from either DOM or Vision extraction",
        "current_title": "",
        "current_employer": "",
    }


def _determine_from_vision(
    vision_data: dict[str, Any],
    company_name: str,
) -> dict[str, Any]:
    """Determine employment from Vision analysis result."""
    is_employed = vision_data.get("is_employed", False)
    never_employed = vision_data.get("never_employed", False)
    evidence = vision_data.get("evidence", "")
    current_title = vision_data.get("current_title", "")
    current_employer = vision_data.get("current_employer", "")

    if never_employed:
        return {
            "status": STATUS_WRONG_PERSON,
            "confidence": 0.85,
            "evidence": f"Never employed at {company_name}. {evidence}",
            "current_title": current_title,
            "current_employer": current_employer,
        }

    if is_employed:
        return {
            "status": STATUS_EMPLOYED,
            "confidence": 0.90,
            "evidence": f"Currently employed at {company_name}. {evidence}",
            "current_title": current_title,
            "current_employer": current_employer,
        }

    # Not currently employed but was at some point
    return {
        "status": STATUS_DEPARTED,
        "confidence": 0.85,
        "evidence": f"No longer employed at {company_name}. {evidence}",
        "current_title": current_title,
        "current_employer": current_employer,
    }


def _determine_from_dom(
    dom_data: dict[str, Any],
    company_name: str,
) -> dict[str, Any]:
    """Determine employment from DOM-extracted data only."""
    experience = dom_data.get("experience", [])
    headline = dom_data.get("headline", "")
    company_lower = company_name.lower()

    # Check headline for company name
    if _company_name_matches(headline, company_lower):
        return {
            "status": STATUS_EMPLOYED,
            "confidence": 0.75,
            "evidence": f"Company name found in headline: {headline}",
            "current_title": headline,
            "current_employer": company_name,
        }

    # Check experience entries
    found_in_any = False
    found_as_current = False

    for exp in experience:
        exp_company = exp.get("company", "")
        dates = exp.get("dates", "")

        if _company_name_matches(exp_company, company_lower):
            found_in_any = True
            if _is_current_role(dates):
                found_as_current = True
                return {
                    "status": STATUS_EMPLOYED,
                    "confidence": 0.80,
                    "evidence": (
                        f"Current role at {exp_company}: "
                        f"{exp.get('title', '')} ({dates})"
                    ),
                    "current_title": exp.get("title", ""),
                    "current_employer": exp_company,
                }

    if found_in_any and not found_as_current:
        return {
            "status": STATUS_DEPARTED,
            "confidence": 0.70,
            "evidence": "Company found in past experience but not as current role",
            "current_title": "",
            "current_employer": "",
        }

    if not found_in_any and experience:
        return {
            "status": STATUS_WRONG_PERSON,
            "confidence": 0.60,
            "evidence": (
                f"Company '{company_name}' not found in any of "
                f"{len(experience)} experience entries"
            ),
            "current_title": "",
            "current_employer": "",
        }

    return {
        "status": STATUS_UNKNOWN,
        "confidence": 0.3,
        "evidence": "Insufficient experience data to determine employment status",
        "current_title": "",
        "current_employer": "",
    }


def _company_name_matches(text: str, company_lower: str) -> bool:
    """Check if text contains the company name (flexible matching)."""
    text_lower = text.lower()
    if company_lower in text_lower:
        return True

    # Try matching without common suffixes
    for suffix in (" inc", " inc.", " llc", " ltd", " corp", " co.", " labs"):
        stripped = company_lower.rstrip(suffix).strip()
        if stripped and stripped in text_lower:
            return True

    return False


def _is_current_role(dates: str) -> bool:
    """Check if a dates string indicates a current role."""
    lower = dates.lower()
    return "present" in lower or "current" in lower
