"""Unit tests for manual status override pure functions."""

from __future__ import annotations

import json

import pytest

from src.domains.monitoring.core.manual_override import prepare_manual_override


class TestPrepareManualOverride:
    """Tests for prepare_manual_override()."""

    def test_valid_operational(self) -> None:
        result = prepare_manual_override(42, "operational", "2026-03-16T00:00:00+00:00")
        assert result["company_id"] == 42
        assert result["status"] == "operational"

    def test_valid_likely_closed(self) -> None:
        result = prepare_manual_override(1, "likely_closed", "2026-03-16T00:00:00+00:00")
        assert result["status"] == "likely_closed"

    def test_valid_uncertain(self) -> None:
        result = prepare_manual_override(1, "uncertain", "2026-03-16T00:00:00+00:00")
        assert result["status"] == "uncertain"

    def test_invalid_status_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid status"):
            prepare_manual_override(1, "bogus", "2026-03-16T00:00:00+00:00")

    def test_empty_status_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid status"):
            prepare_manual_override(1, "", "2026-03-16T00:00:00+00:00")

    def test_confidence_is_one(self) -> None:
        result = prepare_manual_override(1, "operational", "2026-03-16T00:00:00+00:00")
        assert result["confidence"] == 1.0

    def test_manual_override_flag_set(self) -> None:
        result = prepare_manual_override(1, "operational", "2026-03-16T00:00:00+00:00")
        assert result["is_manual_override"] is True

    def test_last_checked_matches_input(self) -> None:
        ts = "2026-03-16T12:30:00+00:00"
        result = prepare_manual_override(1, "operational", ts)
        assert result["last_checked"] == ts

    def test_indicators_contain_manual_override_type(self) -> None:
        result = prepare_manual_override(1, "operational", "2026-03-16T00:00:00+00:00")
        indicators = json.loads(result["indicators"])
        assert len(indicators) == 1
        assert indicators[0]["type"] == "manual_override"
        assert indicators[0]["signal"] == "neutral"

    def test_http_last_modified_is_none(self) -> None:
        result = prepare_manual_override(1, "operational", "2026-03-16T00:00:00+00:00")
        assert result["http_last_modified"] is None
