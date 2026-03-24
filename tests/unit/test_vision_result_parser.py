"""Unit tests for vision result parsers.

Pure function tests -- no I/O.
"""

from __future__ import annotations

from src.domains.leadership.core.vision_result_parser import (
    merge_dom_and_vision_results,
    parse_people_tab_result,
    parse_person_employment_result,
    parse_vision_json_response,
)


class TestParsePeopleTabResult:
    def test_parses_valid_employees(self) -> None:
        data = {
            "employees": [
                {
                    "name": "Jane Smith",
                    "title": "CEO",
                    "profile_url": "https://www.linkedin.com/in/janesmith",
                },
                {
                    "name": "Bob Jones",
                    "title": "CTO",
                    "profile_url": "https://www.linkedin.com/in/bobjones",
                },
            ]
        }
        result = parse_people_tab_result(data)
        assert len(result) == 2
        assert result[0]["name"] == "Jane Smith"
        assert result[0]["title"] == "CEO"
        assert "janesmith" in result[0]["profile_url"]

    def test_skips_empty_names(self) -> None:
        data = {
            "employees": [
                {"name": "", "title": "CEO", "profile_url": "https://linkedin.com/in/x"},
                {"name": "Bob", "title": "CTO", "profile_url": "https://linkedin.com/in/bob"},
            ]
        }
        result = parse_people_tab_result(data)
        assert len(result) == 1
        assert result[0]["name"] == "Bob"

    def test_handles_null_profile_url(self) -> None:
        data = {
            "employees": [
                {"name": "Jane", "title": "CEO", "profile_url": None},
            ]
        }
        result = parse_people_tab_result(data)
        assert len(result) == 1
        assert result[0]["profile_url"] == ""

    def test_handles_null_string_profile_url(self) -> None:
        data = {
            "employees": [
                {"name": "Jane", "title": "CEO", "profile_url": "null"},
            ]
        }
        result = parse_people_tab_result(data)
        assert len(result) == 1
        assert result[0]["profile_url"] == ""

    def test_handles_empty_employees(self) -> None:
        result = parse_people_tab_result({"employees": []})
        assert result == []

    def test_handles_missing_employees_key(self) -> None:
        result = parse_people_tab_result({})
        assert result == []


class TestParsePersonEmploymentResult:
    def test_parses_employed_result(self) -> None:
        data = {
            "person_name": "Jane Smith",
            "current_title": "CEO",
            "current_employer": "Acme Corp",
            "is_employed": True,
            "never_employed": False,
            "evidence": "Listed as CEO at Acme Corp, Present",
        }
        result = parse_person_employment_result(data)
        assert result["person_name"] == "Jane Smith"
        assert result["is_employed"] is True
        assert result["never_employed"] is False

    def test_parses_departed_result(self) -> None:
        data = {
            "person_name": "Bob Jones",
            "current_title": "VP Engineering",
            "current_employer": "Other Co",
            "is_employed": False,
            "never_employed": False,
            "evidence": "Now at Other Co",
        }
        result = parse_person_employment_result(data)
        assert result["is_employed"] is False
        assert result["never_employed"] is False

    def test_parses_wrong_person_result(self) -> None:
        data = {
            "person_name": "Alice Wrong",
            "current_title": "Designer",
            "current_employer": "Design Co",
            "is_employed": False,
            "never_employed": True,
            "evidence": "No mention of Acme Corp",
        }
        result = parse_person_employment_result(data)
        assert result["never_employed"] is True

    def test_handles_missing_fields(self) -> None:
        result = parse_person_employment_result({})
        assert result["person_name"] == ""
        assert result["is_employed"] is False
        assert result["never_employed"] is False


class TestMergeDomAndVisionResults:
    def test_dom_only(self) -> None:
        dom = [
            {"name": "Jane", "title": "CEO", "profile_url": "https://linkedin.com/in/jane"},
        ]
        result = merge_dom_and_vision_results(dom, [])
        assert len(result) == 1
        assert result[0]["name"] == "Jane"

    def test_vision_fills_missing_title(self) -> None:
        dom = [
            {"name": "Jane Smith", "title": "", "profile_url": "https://linkedin.com/in/jane"},
        ]
        vision = [
            {"name": "Jane Smith", "title": "CEO", "profile_url": ""},
        ]
        result = merge_dom_and_vision_results(dom, vision)
        assert len(result) == 1
        assert result[0]["title"] == "CEO"
        assert result[0]["profile_url"] == "https://linkedin.com/in/jane"

    def test_vision_adds_new_people(self) -> None:
        dom = [
            {"name": "Jane", "title": "CEO", "profile_url": "https://linkedin.com/in/jane"},
        ]
        vision = [
            {"name": "Bob Jones", "title": "CTO", "profile_url": ""},
        ]
        result = merge_dom_and_vision_results(dom, vision)
        assert len(result) == 2

    def test_deduplicates_by_name(self) -> None:
        dom = [
            {"name": "Jane Smith", "title": "CEO", "profile_url": "https://linkedin.com/in/jane"},
        ]
        vision = [
            {"name": "Jane Smith", "title": "CEO", "profile_url": ""},
        ]
        result = merge_dom_and_vision_results(dom, vision)
        assert len(result) == 1

    def test_deduplicates_by_url(self) -> None:
        dom = [
            {"name": "Jane", "title": "CEO", "profile_url": "https://linkedin.com/in/jane"},
        ]
        vision = [
            {"name": "Jane S.", "title": "CEO", "profile_url": "https://linkedin.com/in/jane"},
        ]
        result = merge_dom_and_vision_results(dom, vision)
        assert len(result) == 1

    def test_vision_provides_longer_name(self) -> None:
        dom = [
            {"name": "Jane", "title": "CEO", "profile_url": "https://linkedin.com/in/jane"},
        ]
        vision = [
            {"name": "Jane Elizabeth Smith", "title": "CEO", "profile_url": ""},
        ]
        result = merge_dom_and_vision_results(dom, vision)
        assert len(result) == 1
        assert result[0]["name"] == "Jane Elizabeth Smith"

    def test_empty_inputs(self) -> None:
        result = merge_dom_and_vision_results([], [])
        assert result == []


class TestParseVisionJsonResponse:
    def test_parses_clean_json(self) -> None:
        result = parse_vision_json_response('{"employees": []}')
        assert result == {"employees": []}

    def test_parses_markdown_code_block(self) -> None:
        text = '```json\n{"employees": []}\n```'
        result = parse_vision_json_response(text)
        assert result == {"employees": []}

    def test_returns_error_on_invalid_json(self) -> None:
        result = parse_vision_json_response("not json")
        assert "error" in result

    def test_handles_whitespace(self) -> None:
        result = parse_vision_json_response('  \n{"key": "value"}\n  ')
        assert result == {"key": "value"}
