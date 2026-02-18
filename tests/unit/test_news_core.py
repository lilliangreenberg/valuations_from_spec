"""Comprehensive unit tests for news core verification logic.

Tests pure functions only -- no I/O, no mocking required.
"""

from __future__ import annotations

import pytest

from src.domains.news.core.verification_logic import (
    DEFAULT_VERIFICATION_WEIGHTS,
    VERIFICATION_THRESHOLD,
    build_evidence_list,
    calculate_weighted_confidence,
    check_domain_in_content,
    check_domain_match,
    check_name_in_context,
    extract_domain_from_url,
    is_article_verified,
)

# ──────────────────────────────────────────────────────────────────────
# calculate_weighted_confidence
# ──────────────────────────────────────────────────────────────────────


class TestCalculateWeightedConfidence:
    """Tests for calculate_weighted_confidence."""

    def test_all_signals_at_one_gives_one(self) -> None:
        signals = {"logo": 1.0, "domain": 1.0, "context": 1.0, "llm": 1.0}
        result = calculate_weighted_confidence(signals)
        assert result == pytest.approx(1.0)

    def test_no_signals_gives_zero(self) -> None:
        result = calculate_weighted_confidence({})
        assert result == pytest.approx(0.0)

    def test_all_signals_at_zero(self) -> None:
        signals = {"logo": 0.0, "domain": 0.0, "context": 0.0, "llm": 0.0}
        result = calculate_weighted_confidence(signals)
        assert result == pytest.approx(0.0)

    def test_only_logo_signal(self) -> None:
        signals = {"logo": 1.0}
        result = calculate_weighted_confidence(signals)
        assert result == pytest.approx(0.30)

    def test_only_domain_signal(self) -> None:
        signals = {"domain": 1.0}
        result = calculate_weighted_confidence(signals)
        assert result == pytest.approx(0.30)

    def test_only_context_signal(self) -> None:
        signals = {"context": 1.0}
        result = calculate_weighted_confidence(signals)
        assert result == pytest.approx(0.15)

    def test_only_llm_signal(self) -> None:
        signals = {"llm": 1.0}
        result = calculate_weighted_confidence(signals)
        assert result == pytest.approx(0.25)

    def test_logo_and_domain(self) -> None:
        signals = {"logo": 1.0, "domain": 1.0}
        result = calculate_weighted_confidence(signals)
        assert result == pytest.approx(0.60)

    def test_partial_signal_value(self) -> None:
        signals = {"logo": 0.5, "domain": 0.5}
        result = calculate_weighted_confidence(signals)
        assert result == pytest.approx(0.30)

    def test_custom_weights(self) -> None:
        signals = {"logo": 1.0, "domain": 1.0}
        custom_weights = {"logo": 0.5, "domain": 0.5}
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
        signals = {"logo": -5.0}
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
            logo_match=None,
            domain_match=False,
            domain_name="example.com",
            context_match=False,
            company_name="Acme",
            llm_match=None,
        )
        assert evidence == []

    def test_logo_match_only(self) -> None:
        evidence = build_evidence_list(
            logo_match=(True, 0.95),
            domain_match=False,
            domain_name="example.com",
            context_match=False,
            company_name="Acme",
            llm_match=None,
        )
        assert len(evidence) == 1
        assert "Logo similarity: 0.95" in evidence[0]

    def test_domain_match_only(self) -> None:
        evidence = build_evidence_list(
            logo_match=None,
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
            logo_match=None,
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
            logo_match=None,
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
            logo_match=(True, 0.88),
            domain_match=True,
            domain_name="acme.com",
            context_match=True,
            company_name="Acme Corp",
            llm_match=(True, "Match confirmed"),
        )
        assert len(evidence) == 4

    def test_logo_false_not_included(self) -> None:
        evidence = build_evidence_list(
            logo_match=(False, 0.10),
            domain_match=False,
            domain_name="",
            context_match=False,
            company_name="Acme",
            llm_match=None,
        )
        assert evidence == []

    def test_llm_false_not_included(self) -> None:
        evidence = build_evidence_list(
            logo_match=None,
            domain_match=False,
            domain_name="",
            context_match=False,
            company_name="Acme",
            llm_match=(False, "Not a match"),
        )
        assert evidence == []

    def test_logo_formatting(self) -> None:
        evidence = build_evidence_list(
            logo_match=(True, 0.12345),
            domain_match=False,
            domain_name="",
            context_match=False,
            company_name="",
            llm_match=None,
        )
        assert "0.12" in evidence[0]


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
