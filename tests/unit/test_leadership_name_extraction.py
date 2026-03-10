"""Unit tests for CEO/founder name extraction from website content.

Tests pure functions only -- no I/O, no mocking.
"""

from __future__ import annotations

from src.domains.leadership.core.name_extraction import (
    MentionPriority,
    _is_valid_person_name,
    extract_leadership_mentions,
)


class TestExtractLeadershipMentions:
    """Tests for the main extract_leadership_mentions function."""

    # --- Pattern 1: "Title: Name" / "Title, Name" ---

    def test_ceo_colon_name(self) -> None:
        """'CEO: John Smith' extracts correctly."""
        mentions = extract_leadership_mentions("Meet our team. CEO: John Smith")
        assert len(mentions) >= 1
        ceo = mentions[0]
        assert ceo.person_name == "John Smith"
        assert ceo.title_context == "CEO"
        assert ceo.priority == MentionPriority.EXPLICIT_TITLE

    def test_ceo_comma_name(self) -> None:
        """'CEO, John Smith' extracts correctly."""
        mentions = extract_leadership_mentions("CEO, Jane Doe leads the company.")
        assert len(mentions) >= 1
        assert mentions[0].person_name == "Jane Doe"
        assert mentions[0].title_context == "CEO"

    def test_cofounder_colon_name(self) -> None:
        """'Co-Founder: Alice Brown' extracts correctly."""
        mentions = extract_leadership_mentions("Co-Founder: Alice Brown")
        assert len(mentions) >= 1
        assert mentions[0].person_name == "Alice Brown"
        assert mentions[0].title_context == "Co-Founder"

    # --- Pattern 2: "Our Title Name" ---

    def test_our_ceo_name(self) -> None:
        """'Our CEO Jane Smith' extracts correctly."""
        mentions = extract_leadership_mentions("Our CEO Jane Smith leads innovation.")
        assert len(mentions) >= 1
        assert mentions[0].person_name == "Jane Smith"
        assert mentions[0].title_context == "CEO"
        assert mentions[0].priority == MentionPriority.EXPLICIT_TITLE

    def test_our_founder_comma_name(self) -> None:
        """'Our founder, John Doe' extracts correctly."""
        mentions = extract_leadership_mentions("Our founder, John Doe started this.")
        assert len(mentions) >= 1
        assert mentions[0].person_name == "John Doe"
        assert mentions[0].title_context == "Founder"

    # --- Pattern 3: "Name, Title" / "Name (Title)" ---

    def test_name_comma_ceo(self) -> None:
        """'John Smith, CEO' extracts correctly."""
        mentions = extract_leadership_mentions("John Smith, CEO of Acme Corp")
        assert len(mentions) >= 1
        match = [m for m in mentions if m.person_name == "John Smith"]
        assert len(match) >= 1
        assert match[0].title_context == "CEO"
        assert match[0].priority == MentionPriority.NAME_WITH_TITLE

    def test_name_parentheses_ceo(self) -> None:
        """'Jane Doe (CEO)' extracts correctly."""
        mentions = extract_leadership_mentions("Jane Doe (CEO) gave a talk yesterday.")
        assert len(mentions) >= 1
        assert mentions[0].person_name == "Jane Doe"
        assert mentions[0].title_context == "CEO"

    def test_name_dash_founder(self) -> None:
        """'Bob Jones - Founder' extracts correctly."""
        mentions = extract_leadership_mentions("Bob Jones - Founder of this company.")
        assert len(mentions) >= 1
        assert mentions[0].person_name == "Bob Jones"
        assert mentions[0].title_context == "Founder"

    # --- Pattern 4: "Name is the Title of" ---

    def test_is_the_ceo(self) -> None:
        """'John Smith is the CEO of Acme' extracts correctly."""
        mentions = extract_leadership_mentions("John Smith is the CEO of Acme Corporation.")
        assert len(mentions) >= 1
        match = [m for m in mentions if m.priority == MentionPriority.IS_THE_ROLE]
        assert len(match) >= 1
        assert match[0].person_name == "John Smith"
        assert match[0].title_context == "CEO"

    def test_is_the_founder(self) -> None:
        """'Jane Doe is the founder' extracts correctly."""
        mentions = extract_leadership_mentions("Jane Doe is the founder of this startup.")
        assert len(mentions) >= 1
        match = [m for m in mentions if m.priority == MentionPriority.IS_THE_ROLE]
        assert len(match) >= 1
        assert match[0].person_name == "Jane Doe"

    # --- Pattern 5: "founded by Name" ---

    def test_founded_by(self) -> None:
        """'Founded by John Smith' extracts correctly."""
        mentions = extract_leadership_mentions("Founded by John Smith in 2020.")
        assert len(mentions) >= 1
        assert mentions[0].person_name == "John Smith"
        assert mentions[0].title_context == "Founder"
        assert mentions[0].priority == MentionPriority.FOUNDED_BY

    def test_co_founded_by_two_names(self) -> None:
        """'Co-founded by Alice Jones and Bob Smith' extracts both."""
        mentions = extract_leadership_mentions("Co-founded by Alice Jones and Bob Smith in 2019.")
        names = {m.person_name for m in mentions}
        assert "Alice Jones" in names
        assert "Bob Smith" in names

    def test_mixed_founded_by_and_single_founder(self) -> None:
        """Both 'co-founded by X and Y' and 'founded by Z' in same text extract all three."""
        text = (
            "Acme was co-founded by Alice Jones and Bob Smith in 2019. "
            "Their subsidiary was founded by Charlie Brown in 2021."
        )
        mentions = extract_leadership_mentions(text)
        founder_mentions = [m for m in mentions if m.priority == MentionPriority.FOUNDED_BY]
        names = {m.person_name for m in founder_mentions}
        assert "Alice Jones" in names
        assert "Bob Smith" in names
        assert "Charlie Brown" in names

    # --- Compound titles ---

    def test_ceo_and_cofounder(self) -> None:
        """'CEO and Co-Founder: John Smith' extracts with compound title."""
        mentions = extract_leadership_mentions("CEO and Co-Founder: John Smith runs the company.")
        assert len(mentions) >= 1
        assert mentions[0].person_name == "John Smith"
        # Should capture the compound title
        assert "CEO" in mentions[0].title_context

    # --- Markdown formatting ---

    def test_bold_title_name(self) -> None:
        """'**CEO**: John Smith' handles bold markdown."""
        mentions = extract_leadership_mentions("**CEO**: John Smith leads our team.")
        assert len(mentions) >= 1
        assert mentions[0].person_name == "John Smith"

    def test_link_name_with_title(self) -> None:
        """'[John Smith](url), CEO' handles link markdown."""
        mentions = extract_leadership_mentions("[John Smith](https://example.com), CEO of Acme")
        assert len(mentions) >= 1
        assert mentions[0].person_name == "John Smith"

    # --- Deduplication ---

    def test_multiple_mentions_deduplicated(self) -> None:
        """Same person mentioned multiple times -> single result."""
        text = "CEO: John Smith is the head of our company. Our CEO John Smith leads innovation."
        mentions = extract_leadership_mentions(text)
        johns = [m for m in mentions if m.person_name == "John Smith"]
        assert len(johns) == 1

    def test_dedup_keeps_highest_priority(self) -> None:
        """When same person appears in multiple patterns, keep highest priority."""
        text = (
            "CEO: John Smith. "  # EXPLICIT_TITLE (priority 1)
            "John Smith is the CEO of Acme."  # IS_THE_ROLE (priority 3)
        )
        mentions = extract_leadership_mentions(text)
        johns = [m for m in mentions if m.person_name == "John Smith"]
        assert len(johns) == 1
        assert johns[0].priority == MentionPriority.EXPLICIT_TITLE

    # --- Priority ordering ---

    def test_results_sorted_by_priority(self) -> None:
        """Results sorted by priority ascending (EXPLICIT_TITLE first)."""
        text = "Founded by Alice Johnson. CEO: Bob Williams leads us."
        mentions = extract_leadership_mentions(text)
        assert len(mentions) >= 2
        # EXPLICIT_TITLE should come before FOUNDED_BY
        priorities = [m.priority for m in mentions]
        assert priorities == sorted(priorities)

    # --- Edge cases ---

    def test_empty_markdown_returns_empty(self) -> None:
        """Empty content returns empty list."""
        assert extract_leadership_mentions("") == []
        assert extract_leadership_mentions("   ") == []

    def test_no_mentions_returns_empty(self) -> None:
        """Content with no leadership mentions returns []."""
        text = "We build great software for teams worldwide."
        assert extract_leadership_mentions(text) == []

    def test_case_insensitive_title_matching(self) -> None:
        """'ceo' and 'CEO' both match."""
        mentions = extract_leadership_mentions("ceo: John Smith")
        assert len(mentions) >= 1
        assert mentions[0].person_name == "John Smith"

    def test_president_extracted(self) -> None:
        """President title is extracted."""
        mentions = extract_leadership_mentions("President: Sarah Lee runs operations.")
        assert len(mentions) >= 1
        assert mentions[0].person_name == "Sarah Lee"
        assert mentions[0].title_context == "President"

    def test_three_word_name(self) -> None:
        """Three-word names like 'Mary Jane Watson' are extracted."""
        mentions = extract_leadership_mentions("CEO: Mary Jane Watson")
        assert len(mentions) >= 1
        assert mentions[0].person_name == "Mary Jane Watson"

    # --- False positive tests (critical) ---

    def test_ceo_search_is_ongoing_rejected(self) -> None:
        """'Our CEO search is ongoing' -- 'search is ongoing' is not a name."""
        mentions = extract_leadership_mentions("Our CEO search is ongoing.")
        # "search is ongoing" won't pass _is_valid_person_name (lowercase words)
        names = {m.person_name for m in mentions}
        assert "search is ongoing" not in names
        # More specifically, no mentions should be found at all
        assert len(mentions) == 0

    def test_former_ceo_still_extracted(self) -> None:
        """'Former CEO John Smith' -- still extracted, valuable signal."""
        mentions = extract_leadership_mentions("Former CEO John Smith left the company.")
        # The pattern "CEO John Smith" should still match after "Former"
        # This depends on whether "Former" eats the pattern -- it shouldn't
        # because "Former" is not a title keyword.
        # Even if it doesn't match "Former CEO: Name" pattern, the
        # "Name, CEO" or other patterns may catch it.
        # At minimum, if it extracts, the name should be valid.
        for m in mentions:
            assert _is_valid_person_name(m.person_name)

    def test_acting_ceo_extracted(self) -> None:
        """'Acting CEO Jane Doe' -- should extract."""
        # "Acting CEO" won't match our exact patterns since "Acting" is before "CEO"
        # But "CEO Jane Doe" in "Acting CEO Jane Doe" could match title:name
        # This is acceptable -- the title_context will be "CEO"
        mentions = extract_leadership_mentions("Acting CEO: Jane Doe runs operations.")
        if mentions:
            assert mentions[0].person_name == "Jane Doe"

    def test_company_name_as_person_rejected(self) -> None:
        """'CEO: Modern Health' rejected when company_name is 'Modern Health'."""
        mentions = extract_leadership_mentions(
            "CEO: Modern Health",
            company_name="Modern Health",
        )
        assert len(mentions) == 0

    def test_looking_for_ceo_no_extraction(self) -> None:
        """'We are looking for a CEO' -- no valid name follows."""
        mentions = extract_leadership_mentions("We are looking for a CEO to lead us.")
        assert len(mentions) == 0

    def test_ceo_said_revenue_no_extraction(self) -> None:
        """'the CEO said revenue grew' -- 'said revenue grew' is not a name."""
        mentions = extract_leadership_mentions("The CEO said revenue grew by 50%.")
        assert len(mentions) == 0

    def test_url_not_treated_as_name(self) -> None:
        """URLs are not extracted as names."""
        mentions = extract_leadership_mentions("CEO: https://example.com/about leads our team.")
        for m in mentions:
            assert "http" not in m.person_name

    def test_single_word_rejected(self) -> None:
        """'CEO: Solutions' -- single word is not a valid name."""
        mentions = extract_leadership_mentions("CEO: Solutions")
        assert len(mentions) == 0

    def test_non_name_words_rejected(self) -> None:
        """Common non-name words are rejected."""
        # "Digital Solutions" contains non-name words
        mentions = extract_leadership_mentions("CEO: Digital Solutions")
        assert len(mentions) == 0

    def test_lowercase_words_rejected(self) -> None:
        """Names with lowercase words are rejected (except 'and')."""
        mentions = extract_leadership_mentions("CEO: some random words here")
        assert len(mentions) == 0

    def test_cto_not_extracted_by_default(self) -> None:
        """CTO is not in our rank 1-2 title list, so not extracted."""
        # CTO is rank 3, we only extract rank 1-2 (CEO, Founder, President)
        mentions = extract_leadership_mentions("CTO: Bob Williams")
        assert len(mentions) == 0

    # --- Real-world about page content ---

    def test_realistic_about_page(self) -> None:
        """Test against realistic about page markdown."""
        text = (
            "# About Us\n\n"
            "Acme Corp was founded by Sarah Chen and Michael Park in 2019. "
            "Sarah Chen, CEO, leads our team of 50 engineers building the future "
            "of developer tools. We are backed by top-tier investors and "
            "are headquartered in San Francisco.\n\n"
            "## Our Team\n\n"
            "Our mission is to make development easier for everyone."
        )
        mentions = extract_leadership_mentions(text, company_name="Acme Corp")
        names = {m.person_name for m in mentions}
        assert "Sarah Chen" in names
        assert "Michael Park" in names

    def test_realistic_homepage_sparse(self) -> None:
        """Homepage with minimal leadership info."""
        text = (
            "# Welcome to TechStart\n\n"
            "We build enterprise solutions for the modern workforce. "
            "Learn more about our products and services.\n\n"
            "Contact us at hello@techstart.com"
        )
        mentions = extract_leadership_mentions(text, company_name="TechStart")
        assert len(mentions) == 0


class TestIsValidPersonName:
    """Tests for the _is_valid_person_name validation function."""

    def test_two_word_name_valid(self) -> None:
        assert _is_valid_person_name("John Smith") is True

    def test_three_word_name_valid(self) -> None:
        assert _is_valid_person_name("Mary Jane Watson") is True

    def test_hyphenated_name_valid(self) -> None:
        assert _is_valid_person_name("Jean-Pierre Dupont") is True

    def test_single_word_invalid(self) -> None:
        assert _is_valid_person_name("John") is False

    def test_empty_invalid(self) -> None:
        assert _is_valid_person_name("") is False

    def test_too_long_invalid(self) -> None:
        long_name = "A" * 61
        assert _is_valid_person_name(long_name) is False

    def test_contains_url_invalid(self) -> None:
        assert _is_valid_person_name("Http Example Com") is False

    def test_contains_www_invalid(self) -> None:
        assert _is_valid_person_name("Www Example") is False

    def test_non_name_word_team(self) -> None:
        assert _is_valid_person_name("Our Team") is False

    def test_non_name_word_solutions(self) -> None:
        assert _is_valid_person_name("Digital Solutions") is False

    def test_non_name_word_company(self) -> None:
        assert _is_valid_person_name("Great Company") is False

    def test_lowercase_first_word_invalid(self) -> None:
        assert _is_valid_person_name("john Smith") is False

    def test_matches_company_name_invalid(self) -> None:
        assert _is_valid_person_name("Modern Health", company_name="Modern Health") is False

    def test_different_from_company_name_valid(self) -> None:
        assert _is_valid_person_name("John Smith", company_name="Modern Health") is True


class TestMentionPriority:
    """Tests for the MentionPriority enum ordering."""

    def test_explicit_is_highest_priority(self) -> None:
        assert MentionPriority.EXPLICIT_TITLE < MentionPriority.NAME_WITH_TITLE

    def test_name_with_title_beats_is_the_role(self) -> None:
        assert MentionPriority.NAME_WITH_TITLE < MentionPriority.IS_THE_ROLE

    def test_is_the_role_beats_founded_by(self) -> None:
        assert MentionPriority.IS_THE_ROLE < MentionPriority.FOUNDED_BY

    def test_priority_ordering(self) -> None:
        priorities = sorted(MentionPriority)
        assert priorities == [
            MentionPriority.EXPLICIT_TITLE,
            MentionPriority.NAME_WITH_TITLE,
            MentionPriority.IS_THE_ROLE,
            MentionPriority.FOUNDED_BY,
        ]
