"""Comprehensive unit tests for news core verification logic.

Tests pure functions only -- no I/O, no mocking required.
"""

from __future__ import annotations

import pytest

from src.domains.news.core.verification_logic import (
    COMPETING_DOMAIN_PENALTY,
    DEFAULT_VERIFICATION_WEIGHTS,
    VERIFICATION_THRESHOLD,
    build_evidence_list,
    calculate_weighted_confidence,
    check_domain_in_content,
    check_domain_match,
    check_name_in_context,
    detect_competing_domain,
    extract_company_description,
    extract_domain_from_url,
    is_article_verified,
)

# ──────────────────────────────────────────────────────────────────────
# calculate_weighted_confidence
# ──────────────────────────────────────────────────────────────────────


class TestCalculateWeightedConfidence:
    """Tests for calculate_weighted_confidence."""

    def test_all_signals_at_one_gives_one(self) -> None:
        signals = {"domain": 1.0, "context": 1.0, "llm": 1.0}
        result = calculate_weighted_confidence(signals)
        assert result == pytest.approx(1.0)

    def test_no_signals_gives_zero(self) -> None:
        result = calculate_weighted_confidence({})
        assert result == pytest.approx(0.0)

    def test_all_signals_at_zero(self) -> None:
        signals = {"domain": 0.0, "context": 0.0, "llm": 0.0}
        result = calculate_weighted_confidence(signals)
        assert result == pytest.approx(0.0)

    def test_only_domain_signal(self) -> None:
        signals = {"domain": 1.0}
        result = calculate_weighted_confidence(signals)
        assert result == pytest.approx(0.35)

    def test_only_context_signal(self) -> None:
        signals = {"context": 1.0}
        result = calculate_weighted_confidence(signals)
        assert result == pytest.approx(0.25)

    def test_only_llm_signal(self) -> None:
        signals = {"llm": 1.0}
        result = calculate_weighted_confidence(signals)
        assert result == pytest.approx(0.40)

    def test_context_and_llm(self) -> None:
        signals = {"context": 1.0, "llm": 1.0}
        result = calculate_weighted_confidence(signals)
        assert result == pytest.approx(0.65)

    def test_partial_signal_value(self) -> None:
        signals = {"domain": 0.5, "llm": 0.5}
        result = calculate_weighted_confidence(signals)
        assert result == pytest.approx(0.375)

    def test_custom_weights(self) -> None:
        signals = {"domain": 1.0, "llm": 1.0}
        custom_weights = {"domain": 0.5, "llm": 0.5}
        result = calculate_weighted_confidence(signals, weights=custom_weights)
        assert result == pytest.approx(1.0)

    def test_unknown_signal_ignored(self) -> None:
        # Signal name not in default weights gets weight 0.0
        signals = {"unknown": 1.0}
        result = calculate_weighted_confidence(signals)
        assert result == pytest.approx(0.0)

    def test_clamped_to_max_one(self) -> None:
        # Even with custom weights that could exceed 1.0
        signals = {"a": 1.0, "b": 1.0}
        weights = {"a": 0.8, "b": 0.8}
        result = calculate_weighted_confidence(signals, weights=weights)
        assert result == pytest.approx(1.0)

    def test_clamped_to_min_zero(self) -> None:
        # Negative signal values
        signals = {"domain": -5.0}
        result = calculate_weighted_confidence(signals)
        assert result == pytest.approx(0.0)

    def test_default_weights_sum_to_one(self) -> None:
        total = sum(DEFAULT_VERIFICATION_WEIGHTS.values())
        assert total == pytest.approx(1.0)


# ──────────────────────────────────────────────────────────────────────
# check_domain_match
# ──────────────────────────────────────────────────────────────────────


class TestCheckDomainMatch:
    """Tests for check_domain_match."""

    def test_domain_in_url_path(self) -> None:
        # "acme.com-raises" has a hyphen immediately after the domain, which is
        # caught by the negative lookahead (?![a-zA-Z0-9\-]), so this does NOT match.
        assert check_domain_match("https://techcrunch.com/acme.com-raises-10m", "acme.com") is False

    def test_domain_in_url_path_followed_by_slash(self) -> None:
        assert check_domain_match("https://techcrunch.com/acme.com/raises-10m", "acme.com") is True

    def test_domain_exact_match(self) -> None:
        assert check_domain_match("https://acme.com/about", "acme.com") is True

    def test_domain_not_in_url(self) -> None:
        assert check_domain_match("https://techcrunch.com/article", "acme.com") is False

    def test_empty_domain(self) -> None:
        assert check_domain_match("https://example.com", "") is False

    def test_word_boundary_prevents_substring_match(self) -> None:
        # "acme.com" should NOT match inside "notacme.com" due to word boundary
        assert check_domain_match("https://notacme.com/page", "acme.com") is False

    def test_word_boundary_allows_after_slash(self) -> None:
        assert check_domain_match("https://news.com/acme.com", "acme.com") is True

    def test_case_insensitive(self) -> None:
        assert check_domain_match("https://news.com/ACME.COM", "acme.com") is True

    def test_subdomain_match(self) -> None:
        # www.acme.com has a dot before acme.com, which should be caught by
        # the lookbehind since '.' IS in the lookbehind set
        # The pattern is (?<![a-zA-Z0-9.\-])acme\.com(?![a-zA-Z0-9\-])
        # A period before acme.com means the lookbehind fails, so this should NOT match
        assert check_domain_match("https://www.acme.com", "acme.com") is False

    def test_hyphenated_prefix_does_not_match(self) -> None:
        # "not-acme.com" has a hyphen before acme, which is in the lookbehind set
        assert check_domain_match("https://not-acme.com", "acme.com") is False


# ──────────────────────────────────────────────────────────────────────
# check_domain_in_content
# ──────────────────────────────────────────────────────────────────────


class TestCheckDomainInContent:
    """Tests for check_domain_in_content."""

    def test_domain_in_content(self) -> None:
        content = "The company acme.com announced a new product."
        assert check_domain_in_content(content, "acme.com") is True

    def test_domain_not_in_content(self) -> None:
        content = "The company announced a new product."
        assert check_domain_in_content(content, "acme.com") is False

    def test_empty_content(self) -> None:
        assert check_domain_in_content("", "acme.com") is False

    def test_empty_domain(self) -> None:
        assert check_domain_in_content("some content", "") is False

    def test_word_boundary_prevents_substring(self) -> None:
        content = "Visit notacme.com for details"
        assert check_domain_in_content(content, "acme.com") is False

    def test_case_insensitive(self) -> None:
        content = "Visit ACME.COM for details"
        assert check_domain_in_content(content, "acme.com") is True

    def test_domain_at_start_of_content(self) -> None:
        content = "acme.com is a great company"
        assert check_domain_in_content(content, "acme.com") is True

    def test_domain_at_end_of_content(self) -> None:
        content = "Check out acme.com"
        assert check_domain_in_content(content, "acme.com") is True


# ──────────────────────────────────────────────────────────────────────
# check_name_in_context
# ──────────────────────────────────────────────────────────────────────


class TestCheckNameInContext:
    """Tests for check_name_in_context."""

    def test_name_with_business_term(self) -> None:
        content = "Acme Corp announced a new funding round of $50M."
        assert check_name_in_context(content, "Acme Corp") is True

    def test_name_near_raised(self) -> None:
        content = "Acme Corp raised $10M in Series A."
        assert check_name_in_context(content, "Acme Corp") is True

    def test_name_near_ceo(self) -> None:
        content = "The CEO of Acme Corp shared the vision."
        assert check_name_in_context(content, "Acme Corp") is True

    def test_name_near_founded(self) -> None:
        content = "Acme Corp was founded in 2020 in San Francisco."
        assert check_name_in_context(content, "Acme Corp") is True

    def test_name_without_business_context(self) -> None:
        content = "I visited Acme Corp once. The weather was nice."
        assert check_name_in_context(content, "Acme Corp") is False

    def test_name_not_in_content(self) -> None:
        content = "A different company announced funding."
        assert check_name_in_context(content, "Acme Corp") is False

    def test_empty_content(self) -> None:
        assert check_name_in_context("", "Acme Corp") is False

    def test_empty_company_name(self) -> None:
        assert check_name_in_context("Some content", "") is False

    def test_case_insensitive_name_matching(self) -> None:
        content = "acme corp launched a new product line this quarter."
        assert check_name_in_context(content, "Acme Corp") is True

    def test_business_term_far_from_name(self) -> None:
        # Business term must be within 200 chars
        filler = "x " * 150  # 300 chars of filler
        content = f"Acme Corp {filler} raised $10M."
        assert check_name_in_context(content, "Acme Corp") is False

    def test_business_term_within_window(self) -> None:
        filler = "x " * 50  # 100 chars of filler, within 200 char window
        content = f"Acme Corp {filler} raised $10M."
        assert check_name_in_context(content, "Acme Corp") is True

    def test_name_appears_multiple_times_one_in_context(self) -> None:
        filler = "y " * 150
        content = f"Acme Corp {filler} not relevant. The startup Acme Corp raised $5M."
        assert check_name_in_context(content, "Acme Corp") is True

    def test_all_business_terms_recognized(self) -> None:
        business_terms = [
            "announced",
            "raised",
            "launched",
            "acquired",
            "partnered",
            "company",
            "startup",
            "funding",
            "revenue",
            "customers",
            "product",
            "service",
            "platform",
            "technology",
            "ceo",
            "founded",
            "headquartered",
            "employees",
            "valuation",
        ]
        for term in business_terms:
            content = f"Acme Corp {term} something important."
            assert check_name_in_context(content, "Acme Corp") is True, (
                f"Failed to detect business term: {term}"
            )


# ──────────────────────────────────────────────────────────────────────
# extract_domain_from_url
# ──────────────────────────────────────────────────────────────────────


class TestExtractDomainFromUrl:
    """Tests for extract_domain_from_url."""

    def test_simple_url(self) -> None:
        assert extract_domain_from_url("https://example.com/page") == "example.com"

    def test_www_removed(self) -> None:
        assert extract_domain_from_url("https://www.example.com") == "example.com"

    def test_preserves_subdomain(self) -> None:
        assert extract_domain_from_url("https://blog.example.com") == "blog.example.com"

    def test_lowercased(self) -> None:
        assert extract_domain_from_url("https://WWW.EXAMPLE.COM") == "example.com"

    def test_with_port(self) -> None:
        result = extract_domain_from_url("https://example.com:8443/api")
        assert "example.com" in result

    def test_with_path_and_query(self) -> None:
        assert extract_domain_from_url("https://example.com/a/b?c=d") == "example.com"


# ──────────────────────────────────────────────────────────────────────
# build_evidence_list
# ──────────────────────────────────────────────────────────────────────


class TestBuildEvidenceList:
    """Tests for build_evidence_list."""

    def test_no_matches_empty_list(self) -> None:
        evidence = build_evidence_list(
            domain_match=False,
            domain_name="example.com",
            context_match=False,
            company_name="Acme",
            llm_match=None,
        )
        assert evidence == []

    def test_domain_match_only(self) -> None:
        evidence = build_evidence_list(
            domain_match=True,
            domain_name="acme.com",
            context_match=False,
            company_name="Acme",
            llm_match=None,
        )
        assert len(evidence) == 1
        assert "Domain match: acme.com" in evidence[0]

    def test_context_match_only(self) -> None:
        evidence = build_evidence_list(
            domain_match=False,
            domain_name="",
            context_match=True,
            company_name="Acme Corp",
            llm_match=None,
        )
        assert len(evidence) == 1
        assert "Name in business context: Acme Corp" in evidence[0]

    def test_llm_match_only(self) -> None:
        evidence = build_evidence_list(
            domain_match=False,
            domain_name="",
            context_match=False,
            company_name="Acme",
            llm_match=(True, "Confirmed match based on product description"),
        )
        assert len(evidence) == 1
        assert "LLM verification" in evidence[0]
        assert "Confirmed match" in evidence[0]

    def test_all_matches(self) -> None:
        evidence = build_evidence_list(
            domain_match=True,
            domain_name="acme.com",
            context_match=True,
            company_name="Acme Corp",
            llm_match=(True, "Match confirmed"),
        )
        assert len(evidence) == 3

    def test_llm_false_not_included(self) -> None:
        evidence = build_evidence_list(
            domain_match=False,
            domain_name="",
            context_match=False,
            company_name="Acme",
            llm_match=(False, "Not a match"),
        )
        assert evidence == []


# ──────────────────────────────────────────────────────────────────────
# is_article_verified
# ──────────────────────────────────────────────────────────────────────


class TestIsArticleVerified:
    """Tests for is_article_verified."""

    def test_above_default_threshold(self) -> None:
        assert is_article_verified(0.50) is True

    def test_at_default_threshold(self) -> None:
        assert is_article_verified(VERIFICATION_THRESHOLD) is True

    def test_below_default_threshold(self) -> None:
        assert is_article_verified(0.39) is False

    def test_zero_confidence(self) -> None:
        assert is_article_verified(0.0) is False

    def test_full_confidence(self) -> None:
        assert is_article_verified(1.0) is True

    def test_custom_threshold(self) -> None:
        assert is_article_verified(0.70, threshold=0.50) is True
        assert is_article_verified(0.30, threshold=0.50) is False

    def test_custom_threshold_boundary(self) -> None:
        assert is_article_verified(0.50, threshold=0.50) is True
        assert is_article_verified(0.4999, threshold=0.50) is False

    def test_default_threshold_is_0_40(self) -> None:
        assert pytest.approx(0.40) == VERIFICATION_THRESHOLD


# ──────────────────────────────────────────────────────────────────────
# extract_company_description
# ──────────────────────────────────────────────────────────────────────


class TestExtractCompanyDescription:
    """Tests for extract_company_description."""

    def test_none_input(self) -> None:
        assert extract_company_description(None) == ""

    def test_empty_string(self) -> None:
        assert extract_company_description("") == ""

    def test_meaningful_content_extracted(self) -> None:
        markdown = (
            "Wand Technologies builds the next generation of creative tools "
            "for designers and artists worldwide."
        )
        result = extract_company_description(markdown)
        assert "creative tools" in result

    def test_short_nav_lines_stripped(self) -> None:
        markdown = (
            "Home\nAbout\nProducts\nContact\nWand Technologies builds creative tools for designers."
        )
        result = extract_company_description(markdown)
        assert "Home" not in result
        assert "creative tools" in result

    def test_bare_links_stripped(self) -> None:
        markdown = "[Logo](https://wand.app/logo.png)\nWand builds design tools for the modern era."
        result = extract_company_description(markdown)
        assert "Logo" not in result
        assert "design tools" in result

    def test_bare_urls_stripped(self) -> None:
        markdown = "https://wand.app\nWand is a design platform for creative professionals."
        result = extract_company_description(markdown)
        assert "https://wand.app" not in result
        assert "design platform" in result

    def test_truncated_to_max_length(self) -> None:
        markdown = "A" * 100 + " meaningful content. " + "B" * 600
        result = extract_company_description(markdown, max_length=50)
        assert len(result) <= 50

    def test_short_headings_stripped(self) -> None:
        markdown = "# Nav\n## Menu\nWand Technologies is a design platform for teams."
        result = extract_company_description(markdown)
        assert "Nav" not in result
        assert "design platform" in result

    def test_long_headings_preserved(self) -> None:
        markdown = "# Wand Technologies - Creative Design Platform\nBuilding tools for teams."
        result = extract_company_description(markdown)
        assert "Creative Design Platform" in result

    def test_image_links_stripped(self) -> None:
        markdown = "![Company Logo](https://wand.app/logo.png)\nWand is a creative design company."
        result = extract_company_description(markdown)
        assert "Company Logo" not in result
        assert "creative design" in result

    def test_default_max_length_is_500(self) -> None:
        markdown = "X" * 30 + " " + "Y" * 600
        result = extract_company_description(markdown)
        assert len(result) <= 500


# ──────────────────────────────────────────────────────────────────────
# detect_competing_domain
# ──────────────────────────────────────────────────────────────────────


class TestDetectCompetingDomain:
    """Tests for detect_competing_domain."""

    def test_same_name_different_tld(self) -> None:
        assert detect_competing_domain("https://wand.ai/blog/post", "wand.app") is True

    def test_same_name_different_tld_reversed(self) -> None:
        assert detect_competing_domain("https://wand.app/page", "wand.ai") is True

    def test_same_domain_not_competing(self) -> None:
        assert detect_competing_domain("https://wand.app/blog", "wand.app") is False

    def test_unrelated_domains_not_competing(self) -> None:
        assert detect_competing_domain("https://techcrunch.com/article", "wand.app") is False

    def test_empty_article_url(self) -> None:
        assert detect_competing_domain("", "wand.app") is False

    def test_empty_company_domain(self) -> None:
        assert detect_competing_domain("https://wand.ai/blog", "") is False

    def test_prefix_match_competing(self) -> None:
        # "wand" starts with "wand" from "wandtech.com"
        assert detect_competing_domain("https://wand.ai/page", "wandtech.com") is True

    def test_prefix_match_other_direction(self) -> None:
        assert detect_competing_domain("https://wandtech.com/page", "wand.app") is True

    def test_short_prefix_not_competing(self) -> None:
        # "ab" is too short (< 3 chars) to be a meaningful prefix match
        assert detect_competing_domain("https://ab.com/page", "abc.io") is False

    def test_no_overlap_not_competing(self) -> None:
        assert detect_competing_domain("https://google.com/article", "acme.io") is False

    def test_www_stripped(self) -> None:
        assert detect_competing_domain("https://www.wand.ai/blog", "wand.app") is True

    def test_competing_domain_penalty_is_negative(self) -> None:
        assert COMPETING_DOMAIN_PENALTY < 0

    def test_subdomain_handling(self) -> None:
        # blog.wand.ai -> name part is "blog.wand", company is "wand.app" -> name part is "wand"
        # "blog.wand" starts with "wand"? No, "wand" starts with "wand" from "blog.wand"? No.
        # Actually shorter="wand", longer="blog.wand", longer.startswith("wand")? No.
        # So this should NOT be competing -- the subdomain changes the name part.
        assert detect_competing_domain("https://blog.wand.ai/post", "wand.app") is False
