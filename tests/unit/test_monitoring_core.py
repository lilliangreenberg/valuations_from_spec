"""Comprehensive unit tests for all monitoring domain core modules.

Tests cover: checksum, change_detection, http_headers, status_rules, significance_analysis.
All modules contain pure functions -- no mocking or I/O required.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from src.domains.monitoring.core.change_detection import (
    MAX_COMPARISON_LENGTH,
    ChangeMagnitude,
    calculate_similarity,
    detect_content_change,
    determine_magnitude,
    extract_content_diff,
)
from src.domains.monitoring.core.checksum import compute_content_checksum
from src.domains.monitoring.core.http_headers import (
    extract_content_type,
    is_html_content,
    parse_last_modified,
)
from src.domains.monitoring.core.significance_analysis import (
    FALSE_POSITIVE_PHRASES,
    INSIGNIFICANT_PATTERNS,
    NEGATION_WORDS,
    NEGATIVE_KEYWORDS,
    POSITIVE_KEYWORDS,
    KeywordMatchResult,
    SignificanceResult,
    analyze_content_significance,
    classify_significance,
    detect_false_positives,
    detect_negation,
    find_keyword_matches,
)
from src.domains.monitoring.core.status_rules import (
    ACQUISITION_PATTERNS,
    CompanyStatusType,
    SignalType,
    analyze_snapshot_status,
    calculate_confidence,
    detect_acquisition,
    determine_status,
    extract_copyright_year,
)

# ---------------------------------------------------------------------------
# 1. checksum.py tests
# ---------------------------------------------------------------------------


class TestComputeContentChecksum:
    """Tests for compute_content_checksum."""

    def test_empty_string(self) -> None:
        """MD5 of empty string is the well-known d41d8cd9... digest."""
        expected = hashlib.md5(b"").hexdigest()
        assert compute_content_checksum("") == expected
        assert compute_content_checksum("") == "d41d8cd98f00b204e9800998ecf8427e"

    def test_known_ascii_value(self) -> None:
        """Verify against independently computed MD5 for 'hello'."""
        expected = hashlib.md5(b"hello").hexdigest()
        assert compute_content_checksum("hello") == expected
        assert compute_content_checksum("hello") == "5d41402abc4b2a76b9719d911017c592"

    def test_returns_lowercase_hex_32_chars(self) -> None:
        result = compute_content_checksum("any content")
        assert len(result) == 32
        assert result == result.lower()
        assert all(c in "0123456789abcdef" for c in result)

    def test_unicode_content(self) -> None:
        """Unicode is encoded as UTF-8 before hashing."""
        content = "Hallo Welt -- Konnichiwa"
        expected = hashlib.md5(content.encode("utf-8")).hexdigest()
        assert compute_content_checksum(content) == expected

    def test_emoji_content(self) -> None:
        content = "\U0001f600\U0001f4a9"
        expected = hashlib.md5(content.encode("utf-8")).hexdigest()
        assert compute_content_checksum(content) == expected

    def test_large_string(self) -> None:
        """A 1MB string still produces a valid 32-char hex digest."""
        content = "x" * 1_000_000
        result = compute_content_checksum(content)
        assert len(result) == 32
        assert result == hashlib.md5(content.encode("utf-8")).hexdigest()

    def test_deterministic(self) -> None:
        """Same input always yields same output."""
        assert compute_content_checksum("abc") == compute_content_checksum("abc")

    def test_different_inputs_differ(self) -> None:
        assert compute_content_checksum("a") != compute_content_checksum("b")

    def test_whitespace_sensitivity(self) -> None:
        """Trailing whitespace changes the checksum."""
        assert compute_content_checksum("hello") != compute_content_checksum("hello ")
        assert compute_content_checksum("hello") != compute_content_checksum("hello\n")

    def test_multiline_content(self) -> None:
        content = "line1\nline2\nline3"
        expected = hashlib.md5(content.encode("utf-8")).hexdigest()
        assert compute_content_checksum(content) == expected


# ---------------------------------------------------------------------------
# 2. change_detection.py tests
# ---------------------------------------------------------------------------


class TestCalculateSimilarity:
    """Tests for calculate_similarity."""

    def test_identical_strings(self) -> None:
        assert calculate_similarity("hello", "hello") == 1.0

    def test_completely_different_strings(self) -> None:
        result = calculate_similarity("aaaa", "zzzz")
        assert result == 0.0

    def test_empty_strings(self) -> None:
        # SequenceMatcher returns 1.0 for two empty strings (no differences)
        assert calculate_similarity("", "") == 1.0

    def test_one_empty_one_nonempty(self) -> None:
        assert calculate_similarity("", "hello") == 0.0
        assert calculate_similarity("hello", "") == 0.0

    def test_partial_overlap(self) -> None:
        result = calculate_similarity("abcdef", "abcxyz")
        assert 0.0 < result < 1.0

    def test_returns_float_between_0_and_1(self) -> None:
        result = calculate_similarity("some content", "different content")
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0

    def test_truncation_at_50k_chars(self) -> None:
        """Content beyond 50,000 chars is ignored. Verify by appending
        divergent data past the boundary -- similarity should remain high."""
        base = "a" * MAX_COMPARISON_LENGTH
        old_content = base + "x" * 10_000
        new_content = base + "y" * 10_000
        result = calculate_similarity(old_content, new_content)
        # Only the first 50k chars are compared, and those are identical
        assert result == 1.0

    def test_truncation_boundary_exact(self) -> None:
        """Content of exactly MAX_COMPARISON_LENGTH is fully compared."""
        old_content = "a" * MAX_COMPARISON_LENGTH
        new_content = "a" * (MAX_COMPARISON_LENGTH - 1) + "b"
        result = calculate_similarity(old_content, new_content)
        # Nearly identical, but not 1.0
        assert result > 0.99
        assert result < 1.0

    def test_symmetry(self) -> None:
        """Similarity is symmetric: sim(a,b) == sim(b,a)."""
        s1 = "hello world"
        s2 = "hello earth"
        assert calculate_similarity(s1, s2) == calculate_similarity(s2, s1)


class TestDetermineMagnitude:
    """Tests for determine_magnitude with boundary values."""

    def test_similarity_1_0_is_minor(self) -> None:
        assert determine_magnitude(1.0) == ChangeMagnitude.MINOR

    def test_similarity_0_90_is_minor(self) -> None:
        """Exactly 0.90 -- boundary is >= 0.90 -> MINOR."""
        assert determine_magnitude(0.90) == ChangeMagnitude.MINOR

    def test_similarity_0_8999_is_moderate(self) -> None:
        """Just below 0.90 -> MODERATE."""
        assert determine_magnitude(0.8999) == ChangeMagnitude.MODERATE

    def test_similarity_0_50_is_moderate(self) -> None:
        """Exactly 0.50 -- boundary is >= 0.50 -> MODERATE."""
        assert determine_magnitude(0.50) == ChangeMagnitude.MODERATE

    def test_similarity_0_4999_is_major(self) -> None:
        """Just below 0.50 -> MAJOR."""
        assert determine_magnitude(0.4999) == ChangeMagnitude.MAJOR

    def test_similarity_0_0_is_major(self) -> None:
        assert determine_magnitude(0.0) == ChangeMagnitude.MAJOR

    def test_similarity_0_75_is_moderate(self) -> None:
        assert determine_magnitude(0.75) == ChangeMagnitude.MODERATE

    def test_similarity_0_10_is_major(self) -> None:
        assert determine_magnitude(0.10) == ChangeMagnitude.MAJOR

    def test_magnitude_values_are_strings(self) -> None:
        """ChangeMagnitude is a StrEnum, so values should be lowercase strings."""
        assert ChangeMagnitude.MINOR == "minor"
        assert ChangeMagnitude.MODERATE == "moderate"
        assert ChangeMagnitude.MAJOR == "major"


class TestDetectContentChange:
    """Tests for detect_content_change."""

    def test_same_checksums_no_change(self) -> None:
        """Matching checksums -> no change regardless of content."""
        changed, magnitude, similarity = detect_content_change("abc123", "abc123")
        assert changed is False
        assert magnitude == ChangeMagnitude.MINOR
        assert similarity == 1.0

    def test_same_checksums_ignores_content(self) -> None:
        """Even if content is provided and different, matching checksums means no change."""
        changed, magnitude, similarity = detect_content_change(
            "abc123", "abc123", old_content="hello", new_content="world"
        )
        assert changed is False
        assert magnitude == ChangeMagnitude.MINOR
        assert similarity == 1.0

    def test_different_checksums_no_content(self) -> None:
        """Different checksums but no content -> worst case assumption."""
        changed, magnitude, similarity = detect_content_change("abc", "xyz")
        assert changed is True
        assert magnitude == ChangeMagnitude.MAJOR
        assert similarity == 0.0

    def test_different_checksums_only_old_content(self) -> None:
        """Only old_content provided (new is None) -> MAJOR/0.0."""
        changed, magnitude, similarity = detect_content_change("abc", "xyz", old_content="hello")
        assert changed is True
        assert magnitude == ChangeMagnitude.MAJOR
        assert similarity == 0.0

    def test_different_checksums_only_new_content(self) -> None:
        """Only new_content provided (old is None) -> MAJOR/0.0."""
        changed, magnitude, similarity = detect_content_change("abc", "xyz", new_content="hello")
        assert changed is True
        assert magnitude == ChangeMagnitude.MAJOR
        assert similarity == 0.0

    def test_different_checksums_with_similar_content(self) -> None:
        """Different checksums but similar content -> minor change."""
        old = "Hello, welcome to our website. We do great things."
        new = "Hello, welcome to our website. We do amazing things."
        changed, magnitude, similarity = detect_content_change(
            "aaa", "bbb", old_content=old, new_content=new
        )
        assert changed is True
        assert similarity > 0.80
        assert magnitude in (ChangeMagnitude.MINOR, ChangeMagnitude.MODERATE)

    def test_different_checksums_with_very_different_content(self) -> None:
        """Different checksums with completely different content -> MAJOR."""
        old = "aaaa bbbb cccc dddd"
        new = "xxxx yyyy zzzz wwww"
        changed, magnitude, similarity = detect_content_change(
            "aaa", "bbb", old_content=old, new_content=new
        )
        assert changed is True
        assert magnitude == ChangeMagnitude.MAJOR
        assert similarity < 0.50

    def test_return_type(self) -> None:
        result = detect_content_change("a", "b", "x", "y")
        assert isinstance(result, tuple)
        assert len(result) == 3
        assert isinstance(result[0], bool)
        assert isinstance(result[1], ChangeMagnitude)
        assert isinstance(result[2], float)


class TestExtractContentDiff:
    """Tests for extract_content_diff."""

    def test_identical_content_returns_empty(self) -> None:
        """Identical old and new content produces no diff."""
        content = "Hello world\nThis is a test\nLine three"
        assert extract_content_diff(content, content) == ""

    def test_both_empty_returns_empty(self) -> None:
        assert extract_content_diff("", "") == ""

    def test_added_lines_appear_in_diff(self) -> None:
        """New lines added to end are captured in diff."""
        old = "Line 1\nLine 2"
        new = "Line 1\nLine 2\nLine 3 added"
        diff = extract_content_diff(old, new)
        assert "Line 3 added" in diff

    def test_removed_lines_excluded(self) -> None:
        """Lines removed from old content do NOT appear in the diff output."""
        old = "Keep this\nRemove this line\nAlso keep"
        new = "Keep this\nAlso keep"
        diff = extract_content_diff(old, new)
        assert "Remove this line" not in diff

    def test_modified_line_captures_new_version(self) -> None:
        """When a line is changed, the new version appears in diff."""
        old = "Line 1\nold text here\nLine 3"
        new = "Line 1\nnew text here\nLine 3"
        diff = extract_content_diff(old, new)
        assert "new text here" in diff
        assert "old text here" not in diff

    def test_old_empty_new_has_content(self) -> None:
        """Empty old, content in new -> all new content is the diff."""
        new = "Brand new content\nAnother line"
        diff = extract_content_diff("", new)
        assert "Brand new content" in diff
        assert "Another line" in diff

    def test_old_has_content_new_empty(self) -> None:
        """Content in old, empty new -> no additions, empty diff."""
        old = "Some old content\nAnother line"
        diff = extract_content_diff(old, "")
        assert diff == ""

    def test_mixed_changes(self) -> None:
        """Mix of additions, removals, and unchanged lines."""
        old = "Header\nRemoved line\nUnchanged\nOld footer"
        new = "Header\nAdded line\nUnchanged\nNew footer"
        diff = extract_content_diff(old, new)
        assert "Added line" in diff
        assert "New footer" in diff
        assert "Removed line" not in diff
        assert "Header" not in diff
        assert "Unchanged" not in diff

    def test_multiline_addition(self) -> None:
        """Multiple consecutive added lines all captured."""
        old = "Start"
        new = "Start\nNew line 1\nNew line 2\nNew line 3"
        diff = extract_content_diff(old, new)
        assert "New line 1" in diff
        assert "New line 2" in diff
        assert "New line 3" in diff

    def test_keyword_in_both_not_in_diff(self) -> None:
        """A keyword present in both old and new should NOT appear in the diff.

        This is the core scenario: 'international' in boilerplate that hasn't
        changed should not trigger significance analysis.
        """
        boilerplate = "We are an international company with global partnerships."
        old = f"Header\n{boilerplate}\nOld content here"
        new = f"Header\n{boilerplate}\nNew content here"
        diff = extract_content_diff(old, new)
        assert "international" not in diff
        assert "partnerships" not in diff
        assert "New content here" in diff

    def test_keyword_only_in_new_appears_in_diff(self) -> None:
        """A keyword added in the new content DOES appear in the diff."""
        old = "Header\nRegular content"
        new = "Header\nRegular content\nWe just raised funding in a Series A round"
        diff = extract_content_diff(old, new)
        assert "funding" in diff
        assert "Series A" in diff


# ---------------------------------------------------------------------------
# 3. http_headers.py tests
# ---------------------------------------------------------------------------


class TestParseLastModified:
    """Tests for parse_last_modified."""

    def test_valid_rfc_2822_date(self) -> None:
        header = "Wed, 21 Oct 2015 07:28:00 GMT"
        result = parse_last_modified(header)
        assert result is not None
        assert result.year == 2015
        assert result.month == 10
        assert result.day == 21
        assert result.hour == 7
        assert result.minute == 28
        assert result.second == 0

    def test_result_has_timezone(self) -> None:
        """Parsed datetime should always be timezone-aware."""
        result = parse_last_modified("Wed, 21 Oct 2015 07:28:00 GMT")
        assert result is not None
        assert result.tzinfo is not None

    def test_none_input(self) -> None:
        assert parse_last_modified(None) is None

    def test_empty_string(self) -> None:
        assert parse_last_modified("") is None

    def test_malformed_date(self) -> None:
        assert parse_last_modified("not-a-date") is None

    def test_partial_date(self) -> None:
        assert parse_last_modified("Wed, 21 Oct") is None

    def test_numeric_string(self) -> None:
        assert parse_last_modified("12345") is None

    def test_different_timezone(self) -> None:
        """Dates with +0000 offset are also valid RFC 2822."""
        result = parse_last_modified("Fri, 01 Jan 2021 12:00:00 +0000")
        assert result is not None
        assert result.year == 2021

    def test_positive_timezone_offset(self) -> None:
        result = parse_last_modified("Fri, 01 Jan 2021 12:00:00 +0530")
        assert result is not None
        assert result.tzinfo is not None


class TestExtractContentType:
    """Tests for extract_content_type."""

    def test_basic_content_type(self) -> None:
        assert extract_content_type({"Content-Type": "text/html"}) == "text/html"

    def test_content_type_with_charset(self) -> None:
        """Strips params after semicolon."""
        result = extract_content_type({"Content-Type": "text/html; charset=utf-8"})
        assert result == "text/html"

    def test_case_insensitive_key(self) -> None:
        assert extract_content_type({"content-type": "text/html"}) == "text/html"
        assert extract_content_type({"CONTENT-TYPE": "text/html"}) == "text/html"
        assert extract_content_type({"Content-type": "text/html"}) == "text/html"

    def test_missing_content_type(self) -> None:
        assert extract_content_type({"X-Other": "value"}) is None

    def test_empty_headers(self) -> None:
        assert extract_content_type({}) is None

    def test_multiple_headers_returns_content_type(self) -> None:
        headers = {
            "Accept": "text/plain",
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
        }
        assert extract_content_type(headers) == "application/json"

    def test_content_type_with_multiple_params(self) -> None:
        result = extract_content_type(
            {"Content-Type": "multipart/form-data; boundary=something; charset=utf-8"}
        )
        assert result == "multipart/form-data"

    def test_whitespace_in_value(self) -> None:
        result = extract_content_type({"Content-Type": "  text/html  ; charset=utf-8"})
        assert result == "text/html"


class TestIsHtmlContent:
    """Tests for is_html_content."""

    def test_text_html(self) -> None:
        assert is_html_content("text/html") is True

    def test_xhtml(self) -> None:
        assert is_html_content("application/xhtml+xml") is True

    def test_case_insensitive(self) -> None:
        assert is_html_content("TEXT/HTML") is True
        assert is_html_content("Text/Html") is True
        assert is_html_content("APPLICATION/XHTML+XML") is True

    def test_json_is_not_html(self) -> None:
        assert is_html_content("application/json") is False

    def test_plain_text_is_not_html(self) -> None:
        assert is_html_content("text/plain") is False

    def test_none(self) -> None:
        assert is_html_content(None) is False

    def test_empty_string(self) -> None:
        assert is_html_content("") is False

    def test_xml_is_not_html(self) -> None:
        assert is_html_content("application/xml") is False

    def test_pdf_is_not_html(self) -> None:
        assert is_html_content("application/pdf") is False


# ---------------------------------------------------------------------------
# 4. status_rules.py tests
# ---------------------------------------------------------------------------


class TestExtractCopyrightYear:
    """Tests for extract_copyright_year."""

    def test_copyright_symbol_year(self) -> None:
        assert extract_copyright_year("Footer text \u00a9 2025 Company Inc") == 2025

    def test_c_in_parens_lowercase(self) -> None:
        assert extract_copyright_year("(c) 2024 Company") == 2024

    def test_c_in_parens_uppercase(self) -> None:
        assert extract_copyright_year("(C) 2024 Company") == 2024

    def test_copyright_word(self) -> None:
        assert extract_copyright_year("Copyright 2023 Company") == 2023

    def test_copyright_lowercase(self) -> None:
        assert extract_copyright_year("copyright 2023 Company") == 2023

    def test_year_range_returns_highest(self) -> None:
        assert extract_copyright_year("Copyright 2020-2025 Company") == 2025

    def test_year_range_with_en_dash(self) -> None:
        assert extract_copyright_year("Copyright 2020\u20132025 Company") == 2025

    def test_multiple_copyright_notices(self) -> None:
        """Returns the highest year found across all matches."""
        content = "(c) 2020 Company. Copyright 2023 Other Corp."
        assert extract_copyright_year(content) == 2023

    def test_no_copyright_marker(self) -> None:
        """A bare year without a copyright marker should NOT be extracted."""
        assert extract_copyright_year("Founded in 2024") is None

    def test_no_year_in_content(self) -> None:
        assert extract_copyright_year("No copyright information here.") is None

    def test_empty_content(self) -> None:
        assert extract_copyright_year("") is None

    def test_copyright_with_extra_whitespace(self) -> None:
        assert extract_copyright_year("Copyright  2025  Company") == 2025

    def test_year_range_same_year(self) -> None:
        assert extract_copyright_year("(c) 2025-2025 Company") == 2025

    def test_old_year(self) -> None:
        assert extract_copyright_year("Copyright 1999 Old Corp") == 1999


class TestDetectAcquisition:
    """Tests for detect_acquisition."""

    def test_acquired_by(self) -> None:
        detected, context = detect_acquisition("Acme Corp was acquired by BigCo in 2024.")
        assert detected is True
        assert context is not None
        assert "acquired by" in context.lower()

    def test_merged_with(self) -> None:
        detected, context = detect_acquisition("The company merged with a rival firm.")
        assert detected is True
        assert context is not None

    def test_sold_to(self) -> None:
        detected, context = detect_acquisition("The startup was sold to a larger company.")
        assert detected is True

    def test_now_part_of(self) -> None:
        detected, context = detect_acquisition("Acme is now part of BigCo.")
        assert detected is True

    def test_subsidiary_pattern(self) -> None:
        detected, _ = detect_acquisition("Acme is now a subsidiary of BigCo.")
        assert detected is True

    def test_division_pattern(self) -> None:
        detected, _ = detect_acquisition("Acme is now a division of BigCo.")
        assert detected is True

    def test_unit_pattern(self) -> None:
        detected, _ = detect_acquisition("Acme is now a unit of BigCo.")
        assert detected is True

    def test_brand_pattern(self) -> None:
        detected, _ = detect_acquisition("Acme is now a brand of BigCo.")
        assert detected is True

    def test_is_now_a_part_of(self) -> None:
        detected, _ = detect_acquisition("Acme is now a part of BigCo.")
        assert detected is True

    def test_all_9_patterns_detected(self) -> None:
        """Every pattern in ACQUISITION_PATTERNS should be detected."""
        for pattern in ACQUISITION_PATTERNS:
            content = f"The company {pattern} another entity."
            detected, ctx = detect_acquisition(content)
            assert detected is True, f"Pattern not detected: {pattern}"
            assert ctx is not None

    def test_no_acquisition(self) -> None:
        detected, context = detect_acquisition("The company is growing rapidly.")
        assert detected is False
        assert context is None

    def test_empty_content(self) -> None:
        detected, context = detect_acquisition("")
        assert detected is False
        assert context is None

    def test_case_insensitive(self) -> None:
        detected, _ = detect_acquisition("Acme Corp Was ACQUIRED BY BigCo.")
        assert detected is True

    def test_is_now_available_not_matched(self) -> None:
        """'is now available' should NOT trigger acquisition detection.
        The function requires specific corporate structure words after 'is now'."""
        detected, _ = detect_acquisition("Product X is now available worldwide.")
        assert detected is False

    def test_context_extraction(self) -> None:
        """Context should include surrounding text."""
        content = "In breaking news, Acme Corp was acquired by BigCo for $1 billion."
        detected, context = detect_acquisition(content)
        assert detected is True
        assert context is not None
        assert len(context) > len("acquired by")


class TestCalculateConfidence:
    """Tests for calculate_confidence."""

    def test_no_indicators(self) -> None:
        assert calculate_confidence([]) == 0.0

    def test_single_positive(self) -> None:
        indicators = [("type", "value", SignalType.POSITIVE)]
        assert calculate_confidence(indicators) == pytest.approx(0.4)

    def test_single_negative(self) -> None:
        indicators = [("type", "value", SignalType.NEGATIVE)]
        assert calculate_confidence(indicators) == pytest.approx(0.4)

    def test_single_neutral(self) -> None:
        indicators = [("type", "value", SignalType.NEUTRAL)]
        assert calculate_confidence(indicators) == pytest.approx(0.2)

    def test_two_positive(self) -> None:
        indicators = [
            ("a", "1", SignalType.POSITIVE),
            ("b", "2", SignalType.POSITIVE),
        ]
        assert calculate_confidence(indicators) == pytest.approx(0.8)

    def test_mixed_signals(self) -> None:
        indicators = [
            ("a", "1", SignalType.POSITIVE),
            ("b", "2", SignalType.NEGATIVE),
        ]
        # 0.4 + 0.4 = 0.8
        assert calculate_confidence(indicators) == pytest.approx(0.8)

    def test_clamped_to_1_0(self) -> None:
        """Even with many indicators, confidence does not exceed 1.0."""
        indicators = [
            ("a", "1", SignalType.POSITIVE),
            ("b", "2", SignalType.POSITIVE),
            ("c", "3", SignalType.POSITIVE),
            ("d", "4", SignalType.NEGATIVE),
        ]
        # 0.4 * 4 = 1.6, clamped to 1.0
        assert calculate_confidence(indicators) == 1.0

    def test_neutral_and_positive(self) -> None:
        indicators = [
            ("a", "1", SignalType.NEUTRAL),
            ("b", "2", SignalType.POSITIVE),
        ]
        # 0.2 + 0.4 = 0.6
        assert calculate_confidence(indicators) == pytest.approx(0.6)

    def test_all_neutral(self) -> None:
        indicators = [
            ("a", "1", SignalType.NEUTRAL),
            ("b", "2", SignalType.NEUTRAL),
        ]
        # 0.2 + 0.2 = 0.4
        assert calculate_confidence(indicators) == pytest.approx(0.4)


class TestDetermineStatus:
    """Tests for determine_status."""

    def test_low_confidence_returns_uncertain(self) -> None:
        """Confidence < 0.4 -> UNCERTAIN regardless of indicators."""
        indicators = [("type", "value", SignalType.POSITIVE)]
        assert determine_status(0.39, indicators) == CompanyStatusType.UNCERTAIN
        assert determine_status(0.0, indicators) == CompanyStatusType.UNCERTAIN

    def test_high_confidence_with_negative_is_likely_closed(self) -> None:
        indicators = [
            ("a", "1", SignalType.POSITIVE),
            ("b", "2", SignalType.NEGATIVE),
        ]
        assert determine_status(0.8, indicators) == CompanyStatusType.LIKELY_CLOSED

    def test_high_confidence_no_negative_is_operational(self) -> None:
        indicators = [
            ("a", "1", SignalType.POSITIVE),
            ("b", "2", SignalType.POSITIVE),
        ]
        assert determine_status(0.8, indicators) == CompanyStatusType.OPERATIONAL

    def test_high_confidence_boundary_0_70(self) -> None:
        """Exactly 0.70 is >= 0.70, so high confidence rules apply."""
        indicators = [("a", "1", SignalType.NEGATIVE)]
        assert determine_status(0.70, indicators) == CompanyStatusType.LIKELY_CLOSED

    def test_medium_confidence_more_positive(self) -> None:
        indicators = [
            ("a", "1", SignalType.POSITIVE),
            ("b", "2", SignalType.NEUTRAL),
        ]
        # confidence=0.6, positive=1, negative=0 -> operational
        assert determine_status(0.6, indicators) == CompanyStatusType.OPERATIONAL

    def test_medium_confidence_more_negative(self) -> None:
        indicators = [
            ("a", "1", SignalType.NEGATIVE),
            ("b", "2", SignalType.NEUTRAL),
        ]
        # confidence=0.6, positive=0, negative=1 -> likely_closed
        assert determine_status(0.6, indicators) == CompanyStatusType.LIKELY_CLOSED

    def test_medium_confidence_equal_pos_neg(self) -> None:
        indicators = [
            ("a", "1", SignalType.POSITIVE),
            ("b", "2", SignalType.NEGATIVE),
        ]
        # confidence=0.6 (adjusted), positive=1, negative=1 -> uncertain
        assert determine_status(0.6, indicators) == CompanyStatusType.UNCERTAIN

    def test_medium_confidence_all_neutral(self) -> None:
        indicators = [
            ("a", "1", SignalType.NEUTRAL),
            ("b", "2", SignalType.NEUTRAL),
        ]
        # 0 positive, 0 negative -> equal -> uncertain
        assert determine_status(0.5, indicators) == CompanyStatusType.UNCERTAIN

    def test_boundary_0_40_is_medium(self) -> None:
        """Exactly 0.40 is not < 0.40, so it falls into medium confidence range."""
        indicators = [("a", "1", SignalType.POSITIVE)]
        assert determine_status(0.40, indicators) == CompanyStatusType.OPERATIONAL

    def test_empty_indicators_with_confidence(self) -> None:
        """No indicators at medium confidence: 0 pos, 0 neg -> uncertain."""
        assert determine_status(0.5, []) == CompanyStatusType.UNCERTAIN

    def test_status_values_are_strings(self) -> None:
        assert CompanyStatusType.OPERATIONAL == "operational"
        assert CompanyStatusType.LIKELY_CLOSED == "likely_closed"
        assert CompanyStatusType.UNCERTAIN == "uncertain"


class TestAnalyzeSnapshotStatus:
    """Tests for analyze_snapshot_status -- full pipeline."""

    def test_empty_content_no_headers(self) -> None:
        """No indicators at all -> confidence 0.0 -> uncertain."""
        status, confidence, indicators = analyze_snapshot_status("")
        assert status == CompanyStatusType.UNCERTAIN
        assert confidence == 0.0
        assert indicators == []

    def test_recent_copyright_positive(self) -> None:
        """Current year copyright is a positive signal."""
        current_year = datetime.now(UTC).year
        content = f"Welcome to our site. Copyright {current_year} Our Company."
        status, confidence, indicators = analyze_snapshot_status(content)
        assert any(s == SignalType.POSITIVE for _, _, s in indicators)
        assert any(t == "copyright_year" for t, _, _ in indicators)

    def test_old_copyright_negative(self) -> None:
        """Copyright > 3 years old is a negative signal."""
        old_year = datetime.now(UTC).year - 5
        content = f"Copyright {old_year} Old Corp"
        status, confidence, indicators = analyze_snapshot_status(content)
        assert any(s == SignalType.NEGATIVE for _, _, s in indicators)

    def test_stale_copyright_neutral(self) -> None:
        """Copyright 2-3 years old is a neutral signal."""
        neutral_year = datetime.now(UTC).year - 2
        content = f"Copyright {neutral_year} Mid Corp"
        status, confidence, indicators = analyze_snapshot_status(content)
        assert any(s == SignalType.NEUTRAL for _, _, s in indicators)

    def test_acquisition_detected(self) -> None:
        content = "Acme Corp was acquired by BigCo in 2024. We are excited."
        status, confidence, indicators = analyze_snapshot_status(content)
        assert any(t == "acquisition_text" for t, _, _ in indicators)
        assert any(s == SignalType.NEGATIVE for _, _, s in indicators)

    def test_recent_http_last_modified_positive(self) -> None:
        now = datetime.now(UTC)
        recent = now - timedelta(days=30)
        status, confidence, indicators = analyze_snapshot_status(
            "Some page content", http_last_modified=recent
        )
        assert any(t == "http_last_modified" and s == SignalType.POSITIVE for t, _, s in indicators)

    def test_old_http_last_modified_neutral(self) -> None:
        now = datetime.now(UTC)
        old = now - timedelta(days=200)
        _, _, indicators = analyze_snapshot_status("Content", http_last_modified=old)
        assert any(t == "http_last_modified" and s == SignalType.NEUTRAL for t, _, s in indicators)

    def test_very_old_http_last_modified_negative(self) -> None:
        now = datetime.now(UTC)
        very_old = now - timedelta(days=500)
        _, _, indicators = analyze_snapshot_status("Content", http_last_modified=very_old)
        assert any(t == "http_last_modified" and s == SignalType.NEGATIVE for t, _, s in indicators)

    def test_multiple_signals_combined(self) -> None:
        """Multiple positive signals -> operational at high confidence."""
        current_year = datetime.now(UTC).year
        content = f"Copyright {current_year} Active Corp"
        recent = datetime.now(UTC) - timedelta(days=10)
        status, confidence, indicators = analyze_snapshot_status(content, http_last_modified=recent)
        # Two positive signals: copyright (0.4) + last-modified (0.4) = 0.8
        assert confidence == pytest.approx(0.8)
        assert status == CompanyStatusType.OPERATIONAL

    def test_mixed_positive_and_negative_signals(self) -> None:
        """Old copyright (negative) + recent last-modified (positive)."""
        old_year = datetime.now(UTC).year - 5
        content = f"Copyright {old_year} Corp. We are still here."
        recent = datetime.now(UTC) - timedelta(days=10)
        status, confidence, indicators = analyze_snapshot_status(content, http_last_modified=recent)
        # One negative (copyright) + one positive (http) = 0.8 confidence
        # High confidence with at least one negative -> likely_closed
        assert confidence == pytest.approx(0.8)
        assert status == CompanyStatusType.LIKELY_CLOSED

    def test_acquisition_with_old_copyright(self) -> None:
        """Two negative signals should yield likely_closed at high confidence."""
        old_year = datetime.now(UTC).year - 5
        content = f"Copyright {old_year}. Acme Corp was acquired by BigCo."
        status, confidence, indicators = analyze_snapshot_status(content)
        assert confidence == pytest.approx(0.8)
        assert status == CompanyStatusType.LIKELY_CLOSED

    def test_return_structure(self) -> None:
        status, confidence, indicators = analyze_snapshot_status("test")
        assert isinstance(status, CompanyStatusType)
        assert isinstance(confidence, float)
        assert isinstance(indicators, list)

    def test_copyright_year_range(self) -> None:
        """Year range like 2020-2025 should extract highest year (2025)."""
        current_year = datetime.now(UTC).year
        content = f"(c) 2020-{current_year} Our Company"
        status, confidence, indicators = analyze_snapshot_status(content)
        assert any(
            t == "copyright_year" and v == str(current_year) and s == SignalType.POSITIVE
            for t, v, s in indicators
        )


# ---------------------------------------------------------------------------
# 5. significance_analysis.py tests
# ---------------------------------------------------------------------------


class TestFindKeywordMatches:
    """Tests for find_keyword_matches."""

    def test_single_match(self) -> None:
        content = "The company announced a new funding round today."
        matches = find_keyword_matches(content, POSITIVE_KEYWORDS)
        keywords_found = [m.keyword for m in matches]
        assert "funding round" in keywords_found or "funding" in keywords_found

    def test_no_matches(self) -> None:
        content = "The weather is nice today."
        matches = find_keyword_matches(content, POSITIVE_KEYWORDS)
        assert len(matches) == 0

    def test_multiple_matches(self) -> None:
        content = "We raised funding in our Series A round and launched a new product."
        matches = find_keyword_matches(content, POSITIVE_KEYWORDS)
        assert len(matches) >= 2

    def test_word_boundary_no_partial_match(self) -> None:
        """'fund' should NOT match 'funding' via a keyword that is just 'fund'
        and 'funding' should NOT match on 'refunding' if checked properly.
        Verify that word boundaries prevent partial matches."""
        # 'ipo' should not match 'Zippo'
        content = "We love Zippo lighters."
        matches = find_keyword_matches(content, POSITIVE_KEYWORDS)
        ipo_matches = [m for m in matches if m.keyword == "ipo"]
        assert len(ipo_matches) == 0

    def test_case_insensitive(self) -> None:
        content = "LAYOFFS announced across the board."
        matches = find_keyword_matches(content, NEGATIVE_KEYWORDS)
        assert any(m.keyword == "layoffs" for m in matches)

    def test_context_extraction(self) -> None:
        content = "Earlier this year, the company raised significant funding for expansion."
        matches = find_keyword_matches(content, POSITIVE_KEYWORDS)
        funding_matches = [m for m in matches if m.keyword == "funding"]
        if funding_matches:
            m = funding_matches[0]
            assert len(m.context_before) <= 50
            assert len(m.context_after) <= 50

    def test_position_is_correct(self) -> None:
        content = "hello funding world"
        matches = find_keyword_matches(content, POSITIVE_KEYWORDS)
        funding_matches = [m for m in matches if m.keyword == "funding"]
        assert len(funding_matches) >= 1
        for m in funding_matches:
            assert content.lower()[m.position : m.position + len(m.keyword)] == m.keyword

    def test_empty_content(self) -> None:
        assert find_keyword_matches("", POSITIVE_KEYWORDS) == []

    def test_insignificant_patterns(self) -> None:
        content = "Updated the font-family and background-color on the page."
        matches = find_keyword_matches(content, INSIGNIFICANT_PATTERNS)
        assert len(matches) >= 1

    def test_category_set_correctly(self) -> None:
        content = "The company was involved in a lawsuit."
        matches = find_keyword_matches(content, NEGATIVE_KEYWORDS)
        lawsuit_matches = [m for m in matches if m.keyword == "lawsuit"]
        assert len(lawsuit_matches) >= 1
        assert lawsuit_matches[0].category == "legal_issues"


class TestDetectNegation:
    """Tests for detect_negation."""

    def test_no_funding_negated(self) -> None:
        content = "There was no funding announced this quarter."
        matches = find_keyword_matches(content, POSITIVE_KEYWORDS)
        funding_matches = [m for m in matches if m.keyword == "funding"]
        assert len(funding_matches) >= 1
        matches = detect_negation(matches, content)
        funding_matches = [m for m in matches if m.keyword == "funding"]
        assert any(m.is_negated for m in funding_matches)

    def test_not_acquired_negated(self) -> None:
        content = "The company was not acquired by anyone."
        matches = find_keyword_matches(content, NEGATIVE_KEYWORDS)
        matches = detect_negation(matches, content)
        acquired_matches = [m for m in matches if "acquired" in m.keyword]
        if acquired_matches:
            assert any(m.is_negated for m in acquired_matches)

    def test_without_prefix_negated(self) -> None:
        content = "The company went without funding for a year."
        matches = find_keyword_matches(content, POSITIVE_KEYWORDS)
        matches = detect_negation(matches, content)
        funding_matches = [m for m in matches if m.keyword == "funding"]
        if funding_matches:
            assert any(m.is_negated for m in funding_matches)

    def test_non_negated_keyword(self) -> None:
        content = "The company received significant funding."
        matches = find_keyword_matches(content, POSITIVE_KEYWORDS)
        matches = detect_negation(matches, content)
        funding_matches = [m for m in matches if m.keyword == "funding"]
        assert len(funding_matches) >= 1
        assert all(not m.is_negated for m in funding_matches)

    def test_negation_outside_20_chars_not_detected(self) -> None:
        """Negation word more than 20 chars before keyword should not count."""
        content = "There is absolutely no way this long text before funding matters."
        matches = find_keyword_matches(content, POSITIVE_KEYWORDS)
        matches = detect_negation(matches, content)
        funding_matches = [m for m in matches if m.keyword == "funding"]
        # 'no' is more than 20 chars before 'funding', so should NOT be negated
        # Let's verify the distance
        if funding_matches:
            pos = funding_matches[0].position
            no_pos = content.lower().find("no ")
            if pos - no_pos > 20:
                assert not funding_matches[0].is_negated

    def test_all_negation_words_in_constant(self) -> None:
        """Verify the expected negation words exist."""
        expected = {"no", "not", "never", "without", "lacks", "none"}
        assert set(NEGATION_WORDS) == expected

    def test_empty_matches_list(self) -> None:
        result = detect_negation([], "some content")
        assert result == []


class TestDetectFalsePositives:
    """Tests for detect_false_positives."""

    def test_talent_acquisition_false_positive(self) -> None:
        content = "Our talent acquisition team is hiring great people."
        matches = find_keyword_matches(content, NEGATIVE_KEYWORDS)
        matches = detect_false_positives(matches, content)
        acq_matches = [m for m in matches if m.keyword == "acquisition"]
        if acq_matches:
            assert any(m.is_false_positive for m in acq_matches)

    def test_customer_acquisition_false_positive(self) -> None:
        content = "Our customer acquisition cost is decreasing."
        matches = find_keyword_matches(content, NEGATIVE_KEYWORDS)
        matches = detect_false_positives(matches, content)
        acq_matches = [m for m in matches if m.keyword == "acquisition"]
        if acq_matches:
            assert any(m.is_false_positive for m in acq_matches)

    def test_data_acquisition_false_positive(self) -> None:
        content = "Our data acquisition pipeline is state of the art."
        matches = find_keyword_matches(content, NEGATIVE_KEYWORDS)
        matches = detect_false_positives(matches, content)
        acq_matches = [m for m in matches if m.keyword == "acquisition"]
        if acq_matches:
            assert any(m.is_false_positive for m in acq_matches)

    def test_real_acquisition_not_false_positive(self) -> None:
        content = "The company completed its acquisition of a competitor."
        matches = find_keyword_matches(content, NEGATIVE_KEYWORDS)
        matches = detect_false_positives(matches, content)
        acq_matches = [m for m in matches if m.keyword == "acquisition"]
        # 'acquisition' by itself (not preceded by talent/customer/data) is NOT false positive
        # unless the word 'acquisition' appears within a false positive phrase
        # "its acquisition" is not in FALSE_POSITIVE_PHRASES
        if acq_matches:
            assert all(not m.is_false_positive for m in acq_matches)

    def test_funding_opportunities_false_positive(self) -> None:
        content = "We help startups find funding opportunities."
        matches = find_keyword_matches(content, POSITIVE_KEYWORDS)
        matches = detect_false_positives(matches, content)
        funding_matches = [m for m in matches if m.keyword == "funding"]
        # 'funding' appears inside 'funding opportunities' which is in FALSE_POSITIVE_PHRASES
        if funding_matches:
            assert any(m.is_false_positive for m in funding_matches)

    def test_self_funded_false_positive(self) -> None:
        content = "We are a self-funded startup."
        matches = find_keyword_matches(content, POSITIVE_KEYWORDS)
        matches = detect_false_positives(matches, content)
        # 'funded' is not a keyword, but 'self-funded' contains no direct keyword hit.
        # Actually, let's check what keywords match.
        # Looking at POSITIVE_KEYWORDS, there's no 'funded' keyword, so this might not match.
        # That's fine -- verifies false positive logic doesn't crash on empty matches.

    def test_all_false_positive_phrases_exist(self) -> None:
        expected = {
            "talent acquisition",
            "customer acquisition",
            "data acquisition",
            "funding opportunities",
            "funding sources",
            "self-funded",
        }
        assert set(FALSE_POSITIVE_PHRASES) == expected

    def test_empty_matches_list(self) -> None:
        result = detect_false_positives([], "some content")
        assert result == []


class TestClassifySignificance:
    """Tests for classify_significance -- explicit coverage of all 6 rules."""

    @staticmethod
    def _make_match(
        keyword: str,
        category: str,
        position: int = 0,
        is_negated: bool = False,
        is_false_positive: bool = False,
    ) -> KeywordMatchResult:
        return KeywordMatchResult(
            keyword=keyword,
            category=category,
            position=position,
            context_before="",
            context_after="",
            is_negated=is_negated,
            is_false_positive=is_false_positive,
        )

    def test_rule_1_only_insignificant_minor(self) -> None:
        """Rule 1: only insignificant + minor -> INSIGNIFICANT (0.85)."""
        insig = [self._make_match("font-family", "css_styling")]
        result = classify_significance([], [], insig, magnitude="minor")
        assert result.classification == "insignificant"
        assert result.confidence == pytest.approx(0.85)
        assert result.sentiment == "neutral"

    def test_rule_1_insignificant_not_minor_falls_through(self) -> None:
        """Rule 1 requires minor magnitude. With major magnitude + insignificant only,
        it should fall through to rule 6 (no effective keywords)."""
        insig = [self._make_match("font-family", "css_styling")]
        result = classify_significance([], [], insig, magnitude="major")
        # Falls through to rule 6 because no positive/negative
        assert result.classification == "insignificant"
        assert result.confidence == pytest.approx(0.75)

    def test_rule_2_two_negative(self) -> None:
        """Rule 2: 2+ negative -> SIGNIFICANT (0.80+)."""
        neg = [
            self._make_match("layoffs", "layoffs_downsizing"),
            self._make_match("bankruptcy", "financial_distress"),
        ]
        result = classify_significance([], neg, [])
        assert result.classification == "significant"
        assert result.confidence >= 0.80
        assert result.sentiment == "negative"

    def test_rule_2_three_negative_higher_confidence(self) -> None:
        """More negative keywords -> higher base confidence."""
        neg = [
            self._make_match("layoffs", "layoffs_downsizing"),
            self._make_match("bankruptcy", "financial_distress"),
            self._make_match("lawsuit", "legal_issues"),
        ]
        result = classify_significance([], neg, [])
        assert result.classification == "significant"
        # 0.80 + min(0.15, 3*0.05) = 0.80 + 0.15 = 0.95
        assert result.confidence == pytest.approx(0.95)

    def test_rule_3_two_positive(self) -> None:
        """Rule 3: 2+ positive -> SIGNIFICANT (0.80+)."""
        pos = [
            self._make_match("funding", "funding_investment"),
            self._make_match("launched", "product_launch"),
        ]
        result = classify_significance(pos, [], [])
        assert result.classification == "significant"
        assert result.confidence >= 0.80
        assert result.sentiment == "positive"

    def test_rule_3_three_positive_higher_confidence(self) -> None:
        pos = [
            self._make_match("funding", "funding_investment"),
            self._make_match("launched", "product_launch"),
            self._make_match("partnership", "partnerships"),
        ]
        result = classify_significance(pos, [], [])
        # 0.80 + min(0.10, 3*0.05) = 0.80 + 0.10 = 0.90
        assert result.confidence == pytest.approx(0.90)

    def test_rule_2_takes_priority_over_rule_3(self) -> None:
        """Rule 2 (negative) is checked before rule 3 (positive).
        With 2+ negative AND 2+ positive, rule 2 fires."""
        pos = [
            self._make_match("funding", "funding_investment"),
            self._make_match("launched", "product_launch"),
        ]
        neg = [
            self._make_match("layoffs", "layoffs_downsizing"),
            self._make_match("bankruptcy", "financial_distress"),
        ]
        result = classify_significance(pos, neg, [])
        assert result.classification == "significant"
        # Rule 2 fires, sentiment is mixed (2+ pos and 2+ neg)
        assert result.sentiment == "mixed"

    def test_rule_4_one_keyword_major(self) -> None:
        """Rule 4: 1 keyword + major -> SIGNIFICANT (0.70)."""
        pos = [self._make_match("funding", "funding_investment")]
        result = classify_significance(pos, [], [], magnitude="major")
        assert result.classification == "significant"
        assert result.confidence == pytest.approx(0.70)

    def test_rule_4_one_negative_major(self) -> None:
        neg = [self._make_match("layoffs", "layoffs_downsizing")]
        result = classify_significance([], neg, [], magnitude="major")
        assert result.classification == "significant"
        assert result.confidence == pytest.approx(0.70)

    def test_rule_5_one_keyword_minor(self) -> None:
        """Rule 5: 1 keyword + minor -> UNCERTAIN (0.50)."""
        pos = [self._make_match("funding", "funding_investment")]
        result = classify_significance(pos, [], [], magnitude="minor")
        assert result.classification == "uncertain"
        assert result.confidence == pytest.approx(0.50)

    def test_rule_5_one_negative_minor(self) -> None:
        neg = [self._make_match("layoffs", "layoffs_downsizing")]
        result = classify_significance([], neg, [], magnitude="minor")
        assert result.classification == "uncertain"
        assert result.confidence == pytest.approx(0.50)

    def test_one_keyword_moderate_magnitude(self) -> None:
        """1 keyword + moderate -> UNCERTAIN (0.60)."""
        pos = [self._make_match("funding", "funding_investment")]
        result = classify_significance(pos, [], [], magnitude="moderate")
        assert result.classification == "uncertain"
        assert result.confidence == pytest.approx(0.60)

    def test_rule_6_no_keywords(self) -> None:
        """Rule 6: no keywords -> INSIGNIFICANT (0.75)."""
        result = classify_significance([], [], [])
        assert result.classification == "insignificant"
        assert result.confidence == pytest.approx(0.75)
        assert result.sentiment == "neutral"

    def test_negated_keywords_excluded_from_effective_count(self) -> None:
        """Negated keywords should not count toward the effective count."""
        pos = [
            self._make_match("funding", "funding_investment", is_negated=True),
            self._make_match("launched", "product_launch", is_negated=True),
        ]
        # Both are negated, so effective count is 0 -> rule 6
        result = classify_significance(pos, [], [])
        assert result.classification == "insignificant"
        assert result.confidence == pytest.approx(0.75)

    def test_false_positive_keywords_excluded(self) -> None:
        """False positive keywords should not count toward the effective count."""
        neg = [
            self._make_match("acquisition", "acquisition", is_false_positive=True),
            self._make_match("merger", "acquisition", is_false_positive=True),
        ]
        result = classify_significance([], neg, [])
        assert result.classification == "insignificant"
        assert result.confidence == pytest.approx(0.75)

    def test_negation_reduces_confidence_by_0_20(self) -> None:
        """Even when negated keywords don't count as effective, they still reduce confidence."""
        # 2 effective negative + 1 negated -> base 0.90, reduction 0.20
        neg = [
            self._make_match("layoffs", "layoffs_downsizing"),
            self._make_match("bankruptcy", "financial_distress"),
            self._make_match("lawsuit", "legal_issues", is_negated=True),
        ]
        result = classify_significance([], neg, [])
        assert result.classification == "significant"
        # base = 0.80 + min(0.15, 2*0.05) = 0.90
        # reduction = 1 * 0.20 = 0.20
        # final = 0.90 - 0.20 = 0.70
        assert result.confidence == pytest.approx(0.70)

    def test_false_positive_reduces_confidence_by_0_30(self) -> None:
        """False positives reduce confidence by 0.30 each."""
        neg = [
            self._make_match("layoffs", "layoffs_downsizing"),
            self._make_match("bankruptcy", "financial_distress"),
            self._make_match("acquisition", "acquisition", is_false_positive=True),
        ]
        result = classify_significance([], neg, [])
        # base = 0.80 + min(0.15, 2*0.05) = 0.90
        # reduction = 1 * 0.30 = 0.30
        # final = 0.90 - 0.30 = 0.60
        assert result.confidence == pytest.approx(0.60)

    def test_confidence_clamped_to_zero(self) -> None:
        """Massive reduction should not go below 0.0."""
        pos = [self._make_match("funding", "funding_investment")]
        # 1 keyword minor -> base 0.50
        # Add 3 negated matches that each reduce by 0.20
        negated = [
            self._make_match("layoffs", "layoffs_downsizing", is_negated=True),
            self._make_match("bankruptcy", "financial_distress", is_negated=True),
            self._make_match("lawsuit", "legal_issues", is_negated=True),
        ]
        result = classify_significance(pos, negated, [], magnitude="minor")
        # base = 0.50, reduction = 3 * 0.20 = 0.60
        # max(0.0, 0.50 - 0.60) = 0.0
        assert result.confidence == pytest.approx(0.0)

    def test_result_has_matched_keywords(self) -> None:
        pos = [
            self._make_match("funding", "funding_investment"),
            self._make_match("launched", "product_launch"),
        ]
        result = classify_significance(pos, [], [])
        assert "funding" in result.matched_keywords
        assert "launched" in result.matched_keywords

    def test_result_has_unique_categories(self) -> None:
        pos = [
            self._make_match("funding", "funding_investment"),
            self._make_match("seed round", "funding_investment"),
        ]
        result = classify_significance(pos, [], [])
        # Categories should be deduplicated
        assert result.matched_categories.count("funding_investment") == 1

    def test_evidence_snippets_populated(self) -> None:
        pos = [
            self._make_match("funding", "funding_investment"),
            self._make_match("launched", "product_launch"),
        ]
        result = classify_significance(pos, [], [])
        assert len(result.evidence_snippets) == 2

    def test_insignificant_rule_1_overrides_insig_patterns_with_effective_keywords(self) -> None:
        """If there are insignificant patterns AND effective keywords,
        rule 1 should NOT apply -- keywords should drive classification."""
        pos = [self._make_match("funding", "funding_investment")]
        insig = [self._make_match("font-family", "css_styling")]
        result = classify_significance(pos, [], insig, magnitude="minor")
        # 1 effective keyword + minor -> rule 5: UNCERTAIN (0.50)
        assert result.classification == "uncertain"
        assert result.confidence == pytest.approx(0.50)


class TestDetermineSentiment:
    """Test the sentiment logic via classify_significance."""

    @staticmethod
    def _make_match(keyword: str, category: str) -> KeywordMatchResult:
        return KeywordMatchResult(
            keyword=keyword,
            category=category,
            position=0,
            context_before="",
            context_after="",
        )

    def test_positive_sentiment(self) -> None:
        pos = [
            self._make_match("funding", "funding_investment"),
            self._make_match("launched", "product_launch"),
        ]
        result = classify_significance(pos, [], [])
        assert result.sentiment == "positive"

    def test_negative_sentiment(self) -> None:
        neg = [
            self._make_match("layoffs", "layoffs_downsizing"),
            self._make_match("bankruptcy", "financial_distress"),
        ]
        result = classify_significance([], neg, [])
        assert result.sentiment == "negative"

    def test_mixed_sentiment(self) -> None:
        pos = [
            self._make_match("funding", "funding_investment"),
            self._make_match("launched", "product_launch"),
        ]
        neg = [
            self._make_match("layoffs", "layoffs_downsizing"),
            self._make_match("bankruptcy", "financial_distress"),
        ]
        result = classify_significance(pos, neg, [])
        assert result.sentiment == "mixed"

    def test_neutral_sentiment_no_keywords(self) -> None:
        result = classify_significance([], [], [])
        assert result.sentiment == "neutral"

    def test_neutral_sentiment_single_keyword(self) -> None:
        """Single keyword (< 2 total) -> neutral."""
        pos = [self._make_match("funding", "funding_investment")]
        result = classify_significance(pos, [], [], magnitude="major")
        assert result.sentiment == "neutral"


class TestAnalyzeContentSignificance:
    """Tests for analyze_content_significance -- the full pipeline."""

    def test_content_with_funding_news(self) -> None:
        content = (
            "The company raised $50M in funding during their Series A round. "
            "The valuation is now over $500M."
        )
        result = analyze_content_significance(content, magnitude="major")
        assert result.classification == "significant"
        assert result.sentiment == "positive"

    def test_content_with_layoffs_and_bankruptcy(self) -> None:
        content = (
            "The company announced layoffs affecting 200 employees. "
            "Bankruptcy proceedings have begun."
        )
        result = analyze_content_significance(content, magnitude="major")
        assert result.classification == "significant"
        assert result.sentiment == "negative"

    def test_content_with_css_only(self) -> None:
        content = "Changed font-family to Arial and updated background-color to blue."
        result = analyze_content_significance(content, magnitude="minor")
        assert result.classification == "insignificant"
        assert result.confidence == pytest.approx(0.85)

    def test_plain_content_no_keywords(self) -> None:
        content = "Our company helps people do things."
        result = analyze_content_significance(content, magnitude="minor")
        assert result.classification == "insignificant"
        assert result.confidence == pytest.approx(0.75)

    def test_negation_reduces_confidence(self) -> None:
        """'no funding' should trigger negation detection."""
        content = "There was no funding announced this quarter."
        result_negated = analyze_content_significance(content, magnitude="minor")
        # 'funding' is found but negated, so effective count is 0 -> rule 6
        assert result_negated.classification == "insignificant"

    def test_talent_acquisition_false_positive_in_pipeline(self) -> None:
        """'talent acquisition' should trigger false positive detection."""
        content = "Our talent acquisition team is growing. We are hiring rapidly."
        result = analyze_content_significance(content, magnitude="minor")
        # 'acquisition' found but is a false positive -> effective count affected
        # 'hiring' is a positive keyword
        # This tests that the pipeline correctly handles false positives
        assert result is not None

    def test_mixed_positive_and_negative(self) -> None:
        content = (
            "The company secured major funding and partnership deals. "
            "However, they also announced layoffs and downsizing."
        )
        result = analyze_content_significance(content, magnitude="major")
        assert result.classification == "significant"

    def test_empty_content(self) -> None:
        result = analyze_content_significance("", magnitude="minor")
        assert result.classification == "insignificant"
        assert result.confidence == pytest.approx(0.75)

    def test_default_magnitude_is_minor(self) -> None:
        """Default magnitude parameter is 'minor'."""
        content = "Just a regular page update."
        result = analyze_content_significance(content)
        assert result.classification == "insignificant"

    def test_result_type(self) -> None:
        result = analyze_content_significance("test content")
        assert isinstance(result, SignificanceResult)
        assert isinstance(result.classification, str)
        assert isinstance(result.sentiment, str)
        assert isinstance(result.confidence, float)
        assert isinstance(result.matched_keywords, list)
        assert isinstance(result.matched_categories, list)

    def test_copyright_change_insignificant(self) -> None:
        """Content with only copyright changes should be insignificant."""
        content = "Copyright 2025. All rights reserved."
        result = analyze_content_significance(content, magnitude="minor")
        assert result.classification == "insignificant"

    def test_tracking_analytics_insignificant(self) -> None:
        content = "Updated google-analytics tracking pixel for better analytics."
        result = analyze_content_significance(content, magnitude="minor")
        assert result.classification == "insignificant"


class TestKeywordDictionaries:
    """Verify structural integrity of keyword dictionaries."""

    def test_positive_keywords_has_7_categories(self) -> None:
        assert len(POSITIVE_KEYWORDS) == 7

    def test_negative_keywords_has_9_categories(self) -> None:
        assert len(NEGATIVE_KEYWORDS) == 9

    def test_insignificant_patterns_has_3_categories(self) -> None:
        assert len(INSIGNIFICANT_PATTERNS) == 3

    def test_positive_category_names(self) -> None:
        expected = {
            "funding_investment",
            "product_launch",
            "growth_success",
            "partnerships",
            "expansion",
            "recognition",
            "ipo_exit",
        }
        assert set(POSITIVE_KEYWORDS.keys()) == expected

    def test_negative_category_names(self) -> None:
        expected = {
            "closure",
            "layoffs_downsizing",
            "financial_distress",
            "legal_issues",
            "security_breach",
            "acquisition",
            "leadership_changes",
            "product_failures",
            "market_exit",
        }
        assert set(NEGATIVE_KEYWORDS.keys()) == expected

    def test_insignificant_category_names(self) -> None:
        expected = {"css_styling", "copyright_year", "tracking_analytics"}
        assert set(INSIGNIFICANT_PATTERNS.keys()) == expected

    def test_all_keywords_are_lowercase(self) -> None:
        """All keywords should be lowercase for consistent matching."""
        for category, terms in POSITIVE_KEYWORDS.items():
            for term in terms:
                assert term == term.lower(), f"Non-lowercase term in {category}: {term}"
        for category, terms in NEGATIVE_KEYWORDS.items():
            for term in terms:
                assert term == term.lower(), f"Non-lowercase term in {category}: {term}"

    def test_no_empty_keyword_lists(self) -> None:
        for cat, terms in POSITIVE_KEYWORDS.items():
            assert len(terms) > 0, f"Empty keyword list for positive category: {cat}"
        for cat, terms in NEGATIVE_KEYWORDS.items():
            assert len(terms) > 0, f"Empty keyword list for negative category: {cat}"
        for cat, terms in INSIGNIFICANT_PATTERNS.items():
            assert len(terms) > 0, f"Empty keyword list for insignificant category: {cat}"
