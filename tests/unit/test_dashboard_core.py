"""Unit tests for dashboard core formatting functions.

Pure function tests -- no I/O, no mocking.
"""

from __future__ import annotations

from src.domains.dashboard.core.formatting import (
    empty_state_message,
    format_confidence,
    format_date_short,
    format_relative_time,
    magnitude_indicator,
    platform_display_name,
    sentiment_color_class,
    significance_badge_class,
    status_badge_class,
    truncate_url,
)


class TestFormatRelativeTime:
    def test_none_returns_na(self) -> None:
        assert format_relative_time(None) == "N/A"

    def test_empty_returns_na(self) -> None:
        assert format_relative_time("") == "N/A"

    def test_invalid_returns_na(self) -> None:
        assert format_relative_time("not-a-date") == "N/A"

    def test_iso_format_returns_string(self) -> None:
        result = format_relative_time("2020-01-01T00:00:00")
        assert isinstance(result, str)
        assert "ago" in result or "just now" in result

    def test_recent_date_says_ago(self) -> None:
        from datetime import UTC, datetime, timedelta

        recent = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        result = format_relative_time(recent)
        assert "ago" in result


class TestSignificanceBadgeClass:
    def test_significant(self) -> None:
        assert "significant" in significance_badge_class("significant")

    def test_insignificant(self) -> None:
        assert "insignificant" in significance_badge_class("insignificant")

    def test_uncertain(self) -> None:
        assert "uncertain" in significance_badge_class("uncertain")

    def test_unknown_value(self) -> None:
        result = significance_badge_class("other")
        assert isinstance(result, str)

    def test_none(self) -> None:
        result = significance_badge_class(None)
        assert isinstance(result, str)


class TestSentimentColorClass:
    def test_positive(self) -> None:
        result = sentiment_color_class("positive")
        assert "positive" in result

    def test_negative(self) -> None:
        result = sentiment_color_class("negative")
        assert "negative" in result

    def test_neutral(self) -> None:
        result = sentiment_color_class("neutral")
        assert isinstance(result, str)

    def test_none(self) -> None:
        result = sentiment_color_class(None)
        assert isinstance(result, str)


class TestMagnitudeIndicator:
    def test_minor(self) -> None:
        result = magnitude_indicator("minor")
        assert "MINOR" in result

    def test_moderate(self) -> None:
        result = magnitude_indicator("moderate")
        assert "MODERATE" in result

    def test_major(self) -> None:
        result = magnitude_indicator("major")
        assert "MAJOR" in result

    def test_none(self) -> None:
        result = magnitude_indicator(None)
        assert isinstance(result, str)


class TestTruncateUrl:
    def test_short_url_unchanged(self) -> None:
        assert truncate_url("https://example.com") == "https://example.com"

    def test_long_url_truncated(self) -> None:
        long = "https://example.com/" + "a" * 100
        result = truncate_url(long, max_length=40)
        assert len(result) <= 43  # max_length + "..."
        assert result.endswith("...")

    def test_none_returns_empty(self) -> None:
        assert truncate_url(None) == ""


class TestPlatformDisplayName:
    def test_linkedin(self) -> None:
        assert platform_display_name("linkedin") == "LinkedIn"

    def test_twitter(self) -> None:
        assert platform_display_name("twitter") == "Twitter/X"

    def test_github(self) -> None:
        assert platform_display_name("github") == "GitHub"

    def test_unknown(self) -> None:
        result = platform_display_name("unknown_platform")
        assert isinstance(result, str)


class TestStatusBadgeClass:
    def test_operational(self) -> None:
        result = status_badge_class("operational")
        assert "operational" in result

    def test_likely_closed(self) -> None:
        result = status_badge_class("likely_closed")
        assert "closed" in result

    def test_uncertain(self) -> None:
        result = status_badge_class("uncertain")
        assert "uncertain" in result

    def test_none(self) -> None:
        result = status_badge_class(None)
        assert isinstance(result, str)


class TestFormatConfidence:
    def test_zero(self) -> None:
        assert format_confidence(0.0) == "0%"

    def test_high(self) -> None:
        assert format_confidence(0.95) == "95%"

    def test_hundred(self) -> None:
        assert format_confidence(1.0) == "100%"

    def test_none(self) -> None:
        assert format_confidence(None) == "N/A"


class TestFormatDateShort:
    def test_iso_date(self) -> None:
        result = format_date_short("2024-06-15T10:30:00")
        assert "2024" in result
        assert "06" in result or "Jun" in result

    def test_none(self) -> None:
        assert format_date_short(None) == "N/A"

    def test_short_string(self) -> None:
        # format_date_short just takes first 10 chars
        assert format_date_short("not-a-date") == "not-a-date"


class TestEmptyStateMessage:
    def test_activity(self) -> None:
        result = empty_state_message("activity")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_companies(self) -> None:
        result = empty_state_message("companies")
        assert isinstance(result, str)

    def test_changes(self) -> None:
        result = empty_state_message("changes")
        assert isinstance(result, str)

    def test_news(self) -> None:
        result = empty_state_message("news")
        assert isinstance(result, str)

    def test_leadership(self) -> None:
        result = empty_state_message("leadership")
        assert isinstance(result, str)

    def test_operations(self) -> None:
        result = empty_state_message("operations")
        assert isinstance(result, str)

    def test_unknown_context(self) -> None:
        result = empty_state_message("something_else")
        assert isinstance(result, str)
