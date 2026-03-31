"""Unit tests for employment status determination.

Pure function tests -- no I/O.
"""

from __future__ import annotations

from src.domains.leadership.core.employment_check import (
    STATUS_DEPARTED,
    STATUS_EMPLOYED,
    STATUS_UNKNOWN,
    STATUS_WRONG_PERSON,
    determine_employment_status,
)


class TestDetermineEmploymentStatusVision:
    """Tests where Vision data is the primary signal."""

    def test_vision_says_employed(self) -> None:
        vision = {
            "is_employed": True,
            "never_employed": False,
            "evidence": "CEO at Acme Corp, Present",
            "current_title": "CEO",
            "current_employer": "Acme Corp",
        }
        result = determine_employment_status({}, vision, "Acme Corp")
        assert result["status"] == STATUS_EMPLOYED
        assert result["confidence"] == 0.90

    def test_vision_says_departed(self) -> None:
        vision = {
            "is_employed": False,
            "never_employed": False,
            "evidence": "Now at Other Co",
            "current_title": "VP",
            "current_employer": "Other Co",
        }
        result = determine_employment_status({}, vision, "Acme Corp")
        assert result["status"] == STATUS_DEPARTED
        assert result["confidence"] == 0.85

    def test_vision_says_wrong_person(self) -> None:
        vision = {
            "is_employed": False,
            "never_employed": True,
            "evidence": "No record of Acme Corp",
            "current_title": "Designer",
            "current_employer": "Design Co",
        }
        result = determine_employment_status({}, vision, "Acme Corp")
        assert result["status"] == STATUS_WRONG_PERSON
        assert result["confidence"] == 0.85

    def test_vision_error_falls_to_dom(self) -> None:
        vision = {"error": "Failed to analyze"}
        dom = {
            "headline": "CEO at Acme Corp",
            "experience": [],
        }
        result = determine_employment_status(dom, vision, "Acme Corp")
        assert result["status"] == STATUS_EMPLOYED


class TestDetermineEmploymentStatusDom:
    """Tests where DOM data is the only signal."""

    def test_company_in_headline(self) -> None:
        dom = {"headline": "CEO at Acme Corp", "experience": []}
        result = determine_employment_status(dom, {}, "Acme Corp")
        assert result["status"] == STATUS_EMPLOYED
        assert result["confidence"] == 0.75

    def test_current_role_in_experience(self) -> None:
        dom = {
            "headline": "",
            "experience": [
                {
                    "title": "CEO",
                    "company": "Acme Corp",
                    "dates": "Jan 2020 - Present",
                },
            ],
        }
        result = determine_employment_status(dom, {}, "Acme Corp")
        assert result["status"] == STATUS_EMPLOYED
        assert result["confidence"] == 0.80

    def test_past_role_only(self) -> None:
        dom = {
            "headline": "VP at Other Co",
            "experience": [
                {
                    "title": "Engineer",
                    "company": "Acme Corp",
                    "dates": "Jan 2018 - Dec 2020",
                },
                {
                    "title": "VP",
                    "company": "Other Co",
                    "dates": "Jan 2021 - Present",
                },
            ],
        }
        result = determine_employment_status(dom, {}, "Acme Corp")
        assert result["status"] == STATUS_DEPARTED

    def test_company_never_in_experience(self) -> None:
        dom = {
            "headline": "Designer",
            "experience": [
                {"title": "Designer", "company": "Design Co", "dates": "2020 - Present"},
            ],
        }
        result = determine_employment_status(dom, {}, "Acme Corp")
        assert result["status"] == STATUS_WRONG_PERSON

    def test_no_experience_returns_unknown(self) -> None:
        dom = {"headline": "Something", "experience": []}
        result = determine_employment_status(dom, {}, "Acme Corp")
        assert result["status"] == STATUS_UNKNOWN


class TestDetermineEmploymentStatusNoData:
    def test_no_data_returns_unknown(self) -> None:
        result = determine_employment_status({}, {}, "Acme Corp")
        assert result["status"] == STATUS_UNKNOWN
        assert result["confidence"] == 0.0


class TestCompanyNameMatching:
    """Tests for flexible company name matching."""

    def test_exact_match(self) -> None:
        dom = {"headline": "CEO at Acme Corp", "experience": []}
        result = determine_employment_status(dom, {}, "Acme Corp")
        assert result["status"] == STATUS_EMPLOYED

    def test_case_insensitive(self) -> None:
        dom = {"headline": "CEO at acme corp", "experience": []}
        result = determine_employment_status(dom, {}, "Acme Corp")
        assert result["status"] == STATUS_EMPLOYED

    def test_matches_with_suffix(self) -> None:
        dom = {
            "headline": "CEO at Acme",
            "experience": [],
        }
        result = determine_employment_status(dom, {}, "Acme Inc")
        assert result["status"] == STATUS_EMPLOYED
