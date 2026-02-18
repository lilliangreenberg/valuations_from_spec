"""Unit tests for leadership core pure functions.

Tests title detection, profile parsing, change detection.
No I/O -- all pure functions.
"""

from __future__ import annotations

from src.domains.leadership.core.change_detection import (
    CRITICAL_TITLES,
    LeadershipChangeType,
    build_leadership_change_summary,
    classify_change_severity,
    compare_leadership,
)
from src.domains.leadership.core.profile_parsing import (
    extract_linkedin_profile_url,
    filter_leadership_results,
    parse_kagi_leadership_result,
    parse_linkedin_people_card,
)
from src.domains.leadership.core.title_detection import (
    LEADERSHIP_TITLES,
    classify_role,
    extract_leadership_title,
    is_leadership_title,
    normalize_title,
    rank_title,
)

# --- Title Detection Tests ---


class TestIsLeadershipTitle:
    def test_ceo_recognized(self) -> None:
        assert is_leadership_title("CEO") is True

    def test_chief_executive_officer_recognized(self) -> None:
        assert is_leadership_title("Chief Executive Officer") is True

    def test_founder_recognized(self) -> None:
        assert is_leadership_title("Founder") is True

    def test_co_founder_recognized(self) -> None:
        assert is_leadership_title("Co-Founder") is True

    def test_cofounder_no_hyphen_recognized(self) -> None:
        assert is_leadership_title("Cofounder") is True

    def test_cto_recognized(self) -> None:
        assert is_leadership_title("CTO") is True

    def test_coo_recognized(self) -> None:
        assert is_leadership_title("COO") is True

    def test_president_recognized(self) -> None:
        assert is_leadership_title("President") is True

    def test_managing_director_recognized(self) -> None:
        assert is_leadership_title("Managing Director") is True

    def test_software_engineer_not_leadership(self) -> None:
        assert is_leadership_title("Software Engineer") is False

    def test_product_manager_not_leadership(self) -> None:
        assert is_leadership_title("Product Manager") is False

    def test_intern_not_leadership(self) -> None:
        assert is_leadership_title("Intern") is False

    def test_case_insensitive(self) -> None:
        assert is_leadership_title("ceo") is True
        assert is_leadership_title("cto") is True
        assert is_leadership_title("founder") is True

    def test_empty_string_not_leadership(self) -> None:
        assert is_leadership_title("") is False

    def test_chief_people_officer_recognized(self) -> None:
        assert is_leadership_title("Chief People Officer") is True

    def test_cfo_recognized(self) -> None:
        assert is_leadership_title("CFO") is True

    def test_vp_engineering_recognized(self) -> None:
        assert is_leadership_title("VP of Engineering") is True


class TestExtractLeadershipTitle:
    def test_extract_ceo_from_full_text(self) -> None:
        result = extract_leadership_title("John Smith, CEO at Acme Corp")
        assert result is not None
        assert "ceo" in result.lower()

    def test_extract_founder_from_text(self) -> None:
        result = extract_leadership_title("Jane Doe - Founder & CEO")
        assert result is not None

    def test_no_leadership_title_returns_none(self) -> None:
        result = extract_leadership_title("Bob the Software Engineer")
        assert result is None

    def test_extract_from_multiline(self) -> None:
        text = "Alice Johnson\nChief Technology Officer\nAcme Inc"
        result = extract_leadership_title(text)
        assert result is not None

    def test_empty_string(self) -> None:
        assert extract_leadership_title("") is None


class TestNormalizeTitle:
    def test_chief_executive_officer_to_ceo(self) -> None:
        assert normalize_title("Chief Executive Officer") == "CEO"

    def test_chief_technology_officer_to_cto(self) -> None:
        assert normalize_title("Chief Technology Officer") == "CTO"

    def test_chief_operating_officer_to_coo(self) -> None:
        assert normalize_title("Chief Operating Officer") == "COO"

    def test_chief_financial_officer_to_cfo(self) -> None:
        assert normalize_title("Chief Financial Officer") == "CFO"

    def test_cofounder_normalized(self) -> None:
        result = normalize_title("Cofounder")
        assert result == "Co-Founder"

    def test_ceo_stays_ceo(self) -> None:
        assert normalize_title("CEO") == "CEO"

    def test_case_handling(self) -> None:
        assert normalize_title("ceo") == "CEO"


class TestRankTitle:
    def test_ceo_highest_rank(self) -> None:
        assert rank_title("CEO") <= rank_title("CTO")

    def test_founder_highest_rank(self) -> None:
        assert rank_title("Founder") <= rank_title("CTO")

    def test_cto_ranks_below_ceo(self) -> None:
        assert rank_title("CTO") > rank_title("CEO")

    def test_unknown_title_gets_lowest_rank(self) -> None:
        assert rank_title("Software Engineer") > rank_title("CEO")

    def test_leadership_titles_dict_populated(self) -> None:
        assert len(LEADERSHIP_TITLES) > 0
        assert "ceo" in LEADERSHIP_TITLES


class TestClassifyRole:
    def test_ceo_classified(self) -> None:
        assert classify_role("CEO") == "ceo"

    def test_founder_classified(self) -> None:
        assert classify_role("Founder") == "founder"

    def test_co_founder_classified(self) -> None:
        assert classify_role("Co-Founder") == "co_founder"

    def test_cto_classified(self) -> None:
        assert classify_role("CTO") == "cto"

    def test_coo_classified(self) -> None:
        assert classify_role("COO") == "coo"

    def test_president_classified(self) -> None:
        assert classify_role("President") == "president"

    def test_unknown_classified(self) -> None:
        assert classify_role("Software Engineer") == "other"


# --- Profile Parsing Tests ---


class TestParseLinkedInPeopleCard:
    def test_valid_card_html(self) -> None:
        html = """
        <div class="org-people-profile-card">
            <a href="/in/john-smith-123">
                <div class="org-people-profile-card__profile-title">John Smith</div>
            </a>
            <div class="org-people-profile-card__subtitle">CEO</div>
        </div>
        """
        result = parse_linkedin_people_card(html)
        assert result is not None
        assert result["name"] == "John Smith"
        assert "CEO" in result["title"]
        assert "/in/john-smith" in result["profile_url"]

    def test_card_without_profile_url_returns_none(self) -> None:
        html = '<div class="card"><span>No link here</span></div>'
        result = parse_linkedin_people_card(html)
        assert result is None

    def test_empty_html_returns_none(self) -> None:
        assert parse_linkedin_people_card("") is None

    def test_card_with_company_url_not_personal(self) -> None:
        html = '<a href="/company/acme"><span>Acme Corp</span></a>'
        result = parse_linkedin_people_card(html)
        assert result is None


class TestParseKagiLeadershipResult:
    def test_kagi_result_with_linkedin_url(self) -> None:
        result = parse_kagi_leadership_result(
            title="John Smith - CEO - Acme Corp | LinkedIn",
            snippet="John Smith is the CEO of Acme Corp, leading the company since 2020.",
            url="https://linkedin.com/in/john-smith",
        )
        assert result is not None
        assert result["name"] == "John Smith"
        assert "CEO" in result["title"]

    def test_kagi_result_without_linkedin_url(self) -> None:
        result = parse_kagi_leadership_result(
            title="Acme Corp leadership team",
            snippet="The leadership of Acme includes many talented people.",
            url="https://acme.com/about",
        )
        assert result is None

    def test_kagi_result_company_linkedin_page(self) -> None:
        result = parse_kagi_leadership_result(
            title="Acme Corp | LinkedIn",
            snippet="Acme Corp is a technology company.",
            url="https://linkedin.com/company/acme",
        )
        assert result is None

    def test_kagi_result_extracts_name_from_title(self) -> None:
        result = parse_kagi_leadership_result(
            title="Jane Doe - Founder at TechCo | LinkedIn",
            snippet="Jane Doe founded TechCo in 2019.",
            url="https://linkedin.com/in/jane-doe",
        )
        assert result is not None
        assert result["name"] == "Jane Doe"


class TestExtractLinkedInProfileUrl:
    def test_extract_from_full_url(self) -> None:
        result = extract_linkedin_profile_url(
            "Check out https://www.linkedin.com/in/john-smith for details"
        )
        assert result is not None
        assert "linkedin.com/in/john-smith" in result

    def test_extract_from_text_with_multiple_urls(self) -> None:
        text = "See https://linkedin.com/in/jane-doe and https://linkedin.com/company/acme"
        result = extract_linkedin_profile_url(text)
        assert result is not None
        assert "/in/jane-doe" in result

    def test_no_linkedin_url_returns_none(self) -> None:
        assert extract_linkedin_profile_url("No URLs here") is None

    def test_company_url_not_extracted(self) -> None:
        result = extract_linkedin_profile_url("https://linkedin.com/company/acme-corp")
        assert result is None

    def test_extract_without_www(self) -> None:
        result = extract_linkedin_profile_url("https://linkedin.com/in/alice-jones")
        assert result is not None
        assert "/in/alice-jones" in result


class TestFilterLeadershipResults:
    def test_filters_non_leadership(self) -> None:
        people = [
            {"name": "Alice", "title": "CEO", "profile_url": "linkedin.com/in/alice"},
            {
                "name": "Bob",
                "title": "Software Engineer",
                "profile_url": "linkedin.com/in/bob",
            },
        ]
        result = filter_leadership_results(people)
        assert len(result) == 1
        assert result[0]["name"] == "Alice"

    def test_deduplicates_by_url(self) -> None:
        people = [
            {"name": "Alice", "title": "CEO", "profile_url": "linkedin.com/in/alice"},
            {
                "name": "Alice",
                "title": "Chief Executive Officer",
                "profile_url": "linkedin.com/in/alice",
            },
        ]
        result = filter_leadership_results(people)
        assert len(result) == 1

    def test_sorts_by_seniority(self) -> None:
        people = [
            {"name": "CTO Person", "title": "CTO", "profile_url": "linkedin.com/in/cto"},
            {"name": "CEO Person", "title": "CEO", "profile_url": "linkedin.com/in/ceo"},
        ]
        result = filter_leadership_results(people)
        assert result[0]["name"] == "CEO Person"

    def test_empty_list(self) -> None:
        assert filter_leadership_results([]) == []

    def test_all_non_leadership_returns_empty(self) -> None:
        people = [
            {
                "name": "Bob",
                "title": "Engineer",
                "profile_url": "linkedin.com/in/bob",
            },
        ]
        assert filter_leadership_results(people) == []


# --- Change Detection Tests ---


class TestCompareLeadership:
    def test_no_changes(self) -> None:
        previous = [
            {
                "person_name": "Alice",
                "title": "CEO",
                "linkedin_profile_url": "linkedin.com/in/alice",
            },
        ]
        current = [
            {
                "person_name": "Alice",
                "title": "CEO",
                "linkedin_profile_url": "linkedin.com/in/alice",
            },
        ]
        changes = compare_leadership(previous, current)
        assert len(changes) == 0

    def test_ceo_departure_detected(self) -> None:
        previous = [
            {
                "person_name": "Alice",
                "title": "CEO",
                "linkedin_profile_url": "linkedin.com/in/alice",
            },
        ]
        current: list[dict[str, str]] = []
        changes = compare_leadership(previous, current)
        assert len(changes) == 1
        assert changes[0]["change_type"] == LeadershipChangeType.CEO_DEPARTURE

    def test_founder_departure_detected(self) -> None:
        previous = [
            {
                "person_name": "Bob",
                "title": "Founder",
                "linkedin_profile_url": "linkedin.com/in/bob",
            },
        ]
        current: list[dict[str, str]] = []
        changes = compare_leadership(previous, current)
        assert len(changes) == 1
        assert changes[0]["change_type"] == LeadershipChangeType.FOUNDER_DEPARTURE

    def test_new_ceo_detected(self) -> None:
        previous: list[dict[str, str]] = []
        current = [
            {
                "person_name": "Carol",
                "title": "CEO",
                "linkedin_profile_url": "linkedin.com/in/carol",
            },
        ]
        changes = compare_leadership(previous, current)
        assert len(changes) == 1
        assert changes[0]["change_type"] == LeadershipChangeType.NEW_CEO

    def test_new_non_ceo_leadership(self) -> None:
        previous: list[dict[str, str]] = []
        current = [
            {
                "person_name": "Dave",
                "title": "CTO",
                "linkedin_profile_url": "linkedin.com/in/dave",
            },
        ]
        changes = compare_leadership(previous, current)
        assert len(changes) == 1
        assert changes[0]["change_type"] == LeadershipChangeType.NEW_LEADERSHIP

    def test_cto_departure_detected(self) -> None:
        previous = [
            {
                "person_name": "Eve",
                "title": "CTO",
                "linkedin_profile_url": "linkedin.com/in/eve",
            },
        ]
        current: list[dict[str, str]] = []
        changes = compare_leadership(previous, current)
        assert len(changes) == 1
        assert changes[0]["change_type"] == LeadershipChangeType.CTO_DEPARTURE

    def test_multiple_changes(self) -> None:
        previous = [
            {
                "person_name": "Alice",
                "title": "CEO",
                "linkedin_profile_url": "linkedin.com/in/alice",
            },
            {
                "person_name": "Bob",
                "title": "CTO",
                "linkedin_profile_url": "linkedin.com/in/bob",
            },
        ]
        current = [
            {
                "person_name": "Carol",
                "title": "CEO",
                "linkedin_profile_url": "linkedin.com/in/carol",
            },
        ]
        changes = compare_leadership(previous, current)
        assert len(changes) >= 2  # Alice departed, Bob departed, Carol new


class TestClassifyChangeSeverity:
    def test_ceo_departure_is_critical(self) -> None:
        assert classify_change_severity(LeadershipChangeType.CEO_DEPARTURE, "CEO") == "critical"

    def test_founder_departure_is_critical(self) -> None:
        assert (
            classify_change_severity(LeadershipChangeType.FOUNDER_DEPARTURE, "Founder")
            == "critical"
        )

    def test_cto_departure_is_critical(self) -> None:
        assert classify_change_severity(LeadershipChangeType.CTO_DEPARTURE, "CTO") == "critical"

    def test_new_ceo_is_notable(self) -> None:
        assert classify_change_severity(LeadershipChangeType.NEW_CEO, "CEO") == "notable"

    def test_new_leadership_is_notable(self) -> None:
        assert classify_change_severity(LeadershipChangeType.NEW_LEADERSHIP, "CTO") == "notable"

    def test_critical_titles_set_populated(self) -> None:
        assert "ceo" in CRITICAL_TITLES
        assert "founder" in CRITICAL_TITLES
        assert "cto" in CRITICAL_TITLES
        assert "coo" in CRITICAL_TITLES


class TestBuildLeadershipChangeSummary:
    def test_critical_departure_significant_negative(self) -> None:
        changes = [
            {
                "change_type": LeadershipChangeType.CEO_DEPARTURE,
                "person_name": "Alice",
                "title": "CEO",
                "profile_url": "linkedin.com/in/alice",
                "severity": "critical",
            },
        ]
        result = build_leadership_change_summary(changes)
        assert result.classification == "significant"
        assert result.sentiment == "negative"
        assert result.confidence >= 0.90

    def test_new_ceo_significant_positive(self) -> None:
        changes = [
            {
                "change_type": LeadershipChangeType.NEW_CEO,
                "person_name": "Bob",
                "title": "CEO",
                "profile_url": "linkedin.com/in/bob",
                "severity": "notable",
            },
        ]
        result = build_leadership_change_summary(changes)
        assert result.classification == "significant"
        assert result.sentiment == "positive"

    def test_no_changes_insignificant(self) -> None:
        result = build_leadership_change_summary([])
        assert result.classification == "insignificant"

    def test_notable_change_significant(self) -> None:
        changes = [
            {
                "change_type": LeadershipChangeType.NEW_LEADERSHIP,
                "person_name": "Carol",
                "title": "CTO",
                "profile_url": "linkedin.com/in/carol",
                "severity": "notable",
            },
        ]
        result = build_leadership_change_summary(changes)
        assert result.classification == "significant"
        assert result.confidence >= 0.75
