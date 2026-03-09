"""Unit tests for social media content analysis pure functions.

Tests cover: extract_latest_post_date, check_posting_inactivity,
prepare_social_context, and SOCIAL_MEDIA_EXCLUDED_CATEGORIES.
All functions are pure -- no mocking or I/O required.
"""

from __future__ import annotations

from datetime import datetime

from src.domains.monitoring.core.significance_analysis import (
    HOMEPAGE_EXCLUDED_CATEGORIES,
    SOCIAL_MEDIA_EXCLUDED_CATEGORIES,
)
from src.domains.monitoring.core.social_content_analysis import (
    check_posting_inactivity,
    extract_latest_post_date,
    prepare_social_context,
)

# ---------------------------------------------------------------------------
# 1. extract_latest_post_date tests
# ---------------------------------------------------------------------------

REFERENCE_DATE = datetime(2025, 6, 15)


class TestExtractLatestPostDate:
    """Tests for extract_latest_post_date."""

    def test_empty_string_returns_none(self) -> None:
        assert extract_latest_post_date("") is None

    def test_no_dates_returns_none(self) -> None:
        assert extract_latest_post_date("No dates in this content at all.") is None

    def test_iso_date(self) -> None:
        result = extract_latest_post_date("Published on 2025-03-15")
        assert result == datetime(2025, 3, 15)

    def test_multiple_iso_dates_returns_most_recent(self) -> None:
        content = "First post 2024-01-10, second post 2025-06-01, third 2024-12-25"
        result = extract_latest_post_date(content, reference_date=REFERENCE_DATE)
        assert result == datetime(2025, 6, 1)

    def test_month_day_year_full(self) -> None:
        result = extract_latest_post_date("January 15, 2025")
        assert result == datetime(2025, 1, 15)

    def test_month_day_year_abbreviated(self) -> None:
        result = extract_latest_post_date("Mar 3, 2025")
        assert result == datetime(2025, 3, 3)

    def test_month_day_year_without_comma(self) -> None:
        result = extract_latest_post_date("August 22 2024")
        assert result == datetime(2024, 8, 22)

    def test_day_month_year(self) -> None:
        result = extract_latest_post_date("15 January 2025")
        assert result == datetime(2025, 1, 15)

    def test_day_month_year_abbreviated(self) -> None:
        result = extract_latest_post_date("3 Mar 2025")
        assert result == datetime(2025, 3, 3)

    def test_relative_days_ago(self) -> None:
        result = extract_latest_post_date("Posted 5 days ago", reference_date=REFERENCE_DATE)
        assert result == datetime(2025, 6, 10)

    def test_relative_weeks_ago(self) -> None:
        result = extract_latest_post_date("Published 2 weeks ago", reference_date=REFERENCE_DATE)
        assert result == datetime(2025, 6, 1)

    def test_relative_months_ago(self) -> None:
        result = extract_latest_post_date("Written 3 months ago", reference_date=REFERENCE_DATE)
        # 3 months * 30 days = 90 days before June 15
        expected = datetime(2025, 3, 17)
        assert result == expected

    def test_relative_date_without_reference_ignored(self) -> None:
        """Relative dates are ignored when no reference_date is provided."""
        result = extract_latest_post_date("Posted 5 days ago")
        assert result is None

    def test_mixed_formats_returns_most_recent(self) -> None:
        content = "Archive: 2023-01-01\nLatest: January 10, 2025\nAlso: 5 Mar 2024"
        result = extract_latest_post_date(content, reference_date=REFERENCE_DATE)
        assert result == datetime(2025, 1, 10)

    def test_invalid_date_values_skipped(self) -> None:
        """Dates with invalid day/month are silently skipped."""
        result = extract_latest_post_date("2025-13-45 and 2025-01-15")
        assert result == datetime(2025, 1, 15)

    def test_dates_before_2000_filtered(self) -> None:
        result = extract_latest_post_date("1999-12-31 and 2020-06-01")
        assert result == datetime(2020, 6, 1)

    def test_future_dates_filtered(self) -> None:
        content = "2030-01-01 and 2025-03-01"
        result = extract_latest_post_date(content, reference_date=REFERENCE_DATE)
        assert result == datetime(2025, 3, 1)

    def test_only_invalid_dates_returns_none(self) -> None:
        result = extract_latest_post_date("2025-13-45 and 2025-00-00")
        assert result is None

    def test_sept_abbreviation(self) -> None:
        """Sept is a valid abbreviation for September."""
        result = extract_latest_post_date("Sept 10, 2024")
        assert result == datetime(2024, 9, 10)

    def test_case_insensitive_month(self) -> None:
        result = extract_latest_post_date("JANUARY 5, 2025")
        assert result == datetime(2025, 1, 5)


# ---------------------------------------------------------------------------
# 2. check_posting_inactivity tests
# ---------------------------------------------------------------------------


class TestCheckPostingInactivity:
    """Tests for check_posting_inactivity."""

    def test_none_date_is_inactive(self) -> None:
        is_inactive, days = check_posting_inactivity(None, reference_date=REFERENCE_DATE)
        assert is_inactive is True
        assert days is None

    def test_recent_post_is_active(self) -> None:
        post_date = datetime(2025, 6, 1)
        is_inactive, days = check_posting_inactivity(post_date, reference_date=REFERENCE_DATE)
        assert is_inactive is False
        assert days == 14

    def test_old_post_is_inactive(self) -> None:
        post_date = datetime(2024, 1, 1)  # ~530 days before reference
        is_inactive, days = check_posting_inactivity(post_date, reference_date=REFERENCE_DATE)
        assert is_inactive is True
        assert days == 531

    def test_exactly_365_days_is_not_inactive(self) -> None:
        """At exactly 365 days, the post is NOT inactive (> threshold, not >=)."""
        post_date = datetime(2024, 6, 15)  # exactly 365 days before
        is_inactive, days = check_posting_inactivity(post_date, reference_date=REFERENCE_DATE)
        assert is_inactive is False
        assert days == 365

    def test_366_days_is_inactive(self) -> None:
        post_date = datetime(2024, 6, 14)  # 366 days before
        is_inactive, days = check_posting_inactivity(post_date, reference_date=REFERENCE_DATE)
        assert is_inactive is True
        assert days == 366

    def test_custom_threshold(self) -> None:
        post_date = datetime(2025, 3, 15)  # 92 days before reference
        is_inactive, days = check_posting_inactivity(
            post_date, threshold_days=90, reference_date=REFERENCE_DATE
        )
        assert is_inactive is True
        assert days == 92

    def test_same_day_post(self) -> None:
        is_inactive, days = check_posting_inactivity(REFERENCE_DATE, reference_date=REFERENCE_DATE)
        assert is_inactive is False
        assert days == 0


# ---------------------------------------------------------------------------
# 3. prepare_social_context tests
# ---------------------------------------------------------------------------


class TestPrepareSocialContext:
    """Tests for prepare_social_context."""

    def test_empty_list_returns_empty_string(self) -> None:
        result = prepare_social_context([], [])
        assert result == ""

    def test_single_active_source(self) -> None:
        snapshots = [
            {
                "source_url": "https://medium.com/@company",
                "source_type": "medium",
                "content_markdown": "Some blog content here.",
                "latest_post_date": "2025-06-01",
            },
        ]
        inactivity = [("https://medium.com/@company", False, 14)]

        result = prepare_social_context(snapshots, inactivity)

        assert "--- Social Media Activity ---" in result
        assert "https://medium.com/@company" in result
        assert "(medium)" in result
        assert "ACTIVE" in result
        assert "Some blog content here." in result
        assert result.endswith("---")

    def test_single_inactive_source(self) -> None:
        snapshots = [
            {
                "source_url": "https://company.com/blog",
                "source_type": "blog",
                "content_markdown": "Old content.",
                "latest_post_date": None,
            },
        ]
        inactivity = [("https://company.com/blog", True, None)]

        result = prepare_social_context(snapshots, inactivity)

        assert "INACTIVE (no posting date found)" in result

    def test_inactive_with_days(self) -> None:
        snapshots = [
            {
                "source_url": "https://medium.com/@co",
                "source_type": "medium",
                "content_markdown": "Content.",
                "latest_post_date": "2024-01-01",
            },
        ]
        inactivity = [("https://medium.com/@co", True, 531)]

        result = prepare_social_context(snapshots, inactivity)

        assert "INACTIVE (531 days since last post)" in result

    def test_multiple_sources(self) -> None:
        snapshots = [
            {
                "source_url": "https://medium.com/@company",
                "source_type": "medium",
                "content_markdown": "Medium post content.",
                "latest_post_date": "2025-06-01",
            },
            {
                "source_url": "https://company.com/blog",
                "source_type": "blog",
                "content_markdown": "Blog post content.",
                "latest_post_date": "2023-01-01",
            },
        ]
        inactivity = [
            ("https://medium.com/@company", False, 14),
            ("https://company.com/blog", True, 896),
        ]

        result = prepare_social_context(snapshots, inactivity)

        assert "medium" in result
        assert "blog" in result
        assert "ACTIVE" in result
        assert "INACTIVE" in result

    def test_content_truncation(self) -> None:
        long_content = "A" * 5000
        snapshots = [
            {
                "source_url": "https://example.com/blog",
                "source_type": "blog",
                "content_markdown": long_content,
                "latest_post_date": "2025-06-01",
            },
        ]
        inactivity = [("https://example.com/blog", False, 14)]

        result = prepare_social_context(snapshots, inactivity, max_chars=500)

        # Content should be truncated, not the full 5000 chars
        assert len(result) < 2000
        assert "..." in result

    def test_none_content_handled(self) -> None:
        snapshots = [
            {
                "source_url": "https://example.com/blog",
                "source_type": "blog",
                "content_markdown": None,
                "latest_post_date": None,
            },
        ]
        inactivity = [("https://example.com/blog", True, None)]

        result = prepare_social_context(snapshots, inactivity)

        assert "--- Social Media Activity ---" in result
        assert "None detected" in result


# ---------------------------------------------------------------------------
# 4. SOCIAL_MEDIA_EXCLUDED_CATEGORIES tests
# ---------------------------------------------------------------------------


class TestSocialMediaExcludedCategories:
    """Tests for SOCIAL_MEDIA_EXCLUDED_CATEGORIES."""

    def test_equals_homepage_excluded_categories(self) -> None:
        """Social media exclusions are the same as homepage exclusions."""
        assert SOCIAL_MEDIA_EXCLUDED_CATEGORIES == HOMEPAGE_EXCLUDED_CATEGORIES

    def test_is_same_object(self) -> None:
        """It is an alias (same object), not a copy."""
        assert SOCIAL_MEDIA_EXCLUDED_CATEGORIES is HOMEPAGE_EXCLUDED_CATEGORIES

    def test_is_frozenset(self) -> None:
        assert isinstance(SOCIAL_MEDIA_EXCLUDED_CATEGORIES, frozenset)

    def test_contains_expected_categories(self) -> None:
        expected = {
            "legal_issues",
            "layoffs_downsizing",
            "financial_distress",
            "security_breach",
            "product_failures",
        }
        assert expected == SOCIAL_MEDIA_EXCLUDED_CATEGORIES
