"""Unit tests for vision prompt builders.

Pure function tests -- no I/O.
"""

from __future__ import annotations

from src.domains.leadership.core.vision_prompts import (
    build_company_page_prompt,
    build_people_tab_prompt,
    build_person_profile_prompt,
)


class TestBuildPeopleTabPrompt:
    def test_returns_string(self) -> None:
        result = build_people_tab_prompt()
        assert isinstance(result, str)

    def test_mentions_employees(self) -> None:
        result = build_people_tab_prompt()
        assert "employees" in result.lower() or "people" in result.lower()

    def test_requests_json_format(self) -> None:
        result = build_people_tab_prompt()
        assert "JSON" in result

    def test_mentions_name_and_title(self) -> None:
        result = build_people_tab_prompt()
        assert "name" in result
        assert "title" in result

    def test_mentions_profile_url(self) -> None:
        result = build_people_tab_prompt()
        assert "profile_url" in result


class TestBuildPersonProfilePrompt:
    def test_includes_company_name(self) -> None:
        result = build_person_profile_prompt("Acme Corp")
        assert "Acme Corp" in result

    def test_asks_about_employment(self) -> None:
        result = build_person_profile_prompt("Acme Corp")
        assert "employed" in result.lower() or "work" in result.lower()

    def test_asks_about_never_employed(self) -> None:
        result = build_person_profile_prompt("Acme Corp")
        assert "never_employed" in result

    def test_requests_json_format(self) -> None:
        result = build_person_profile_prompt("Acme Corp")
        assert "JSON" in result

    def test_different_company_names(self) -> None:
        r1 = build_person_profile_prompt("Acme Corp")
        r2 = build_person_profile_prompt("Widget Labs")
        assert "Acme Corp" in r1
        assert "Widget Labs" in r2
        assert r1 != r2


class TestBuildCompanyPagePrompt:
    def test_returns_string(self) -> None:
        result = build_company_page_prompt()
        assert isinstance(result, str)

    def test_mentions_company_name(self) -> None:
        result = build_company_page_prompt()
        assert "company_name" in result

    def test_mentions_leadership(self) -> None:
        result = build_company_page_prompt()
        assert "leadership" in result.lower()
