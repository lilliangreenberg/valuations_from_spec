"""Unit tests for LinkedIn verification context builder.

Pure function tests -- no I/O.
"""

from __future__ import annotations

from src.domains.leadership.core.change_detection import (
    LeadershipChangeType,
    build_linkedin_verification_context,
)


class TestBuildLinkedinVerificationContext:
    def test_empty_inputs(self) -> None:
        result = build_linkedin_verification_context([], [])
        assert result == ""

    def test_leadership_records_only(self) -> None:
        records = [
            {
                "person_name": "Jane Smith",
                "title": "CEO",
                "is_current": True,
                "last_verified_at": "2026-03-24T00:00:00",
                "discovery_method": "cdp_scrape",
            },
        ]
        result = build_linkedin_verification_context([], records)
        assert "Jane Smith" in result
        assert "CEO" in result
        assert "cdp_scrape" in result

    def test_verification_with_changes(self) -> None:
        records = [
            {"person_name": "Jane", "title": "CEO", "is_current": True,
             "last_verified_at": "2026-03-24", "discovery_method": "cdp_scrape"},
        ]
        verifications = [
            {
                "person_name": "Bob Jones",
                "title": "CTO",
                "status": "departed",
                "confidence": "0.85",
                "evidence": "Now at Other Co",
                "change_detected": "True",
            },
        ]
        result = build_linkedin_verification_context(verifications, records)
        assert "Bob Jones" in result
        assert "departed" in result
        assert "change" in result.lower()

    def test_all_leaders_confirmed(self) -> None:
        records = [
            {"person_name": "Jane", "title": "CEO", "is_current": True,
             "last_verified_at": "2026-03-24", "discovery_method": "cdp_scrape"},
        ]
        verifications = [
            {
                "person_name": "Jane",
                "status": "employed",
                "confidence": "0.90",
                "evidence": "Still CEO",
                "change_detected": "",
            },
        ]
        result = build_linkedin_verification_context(verifications, records)
        assert "confirmed current" in result.lower()


class TestLeadershipChangeTypeNewValues:
    def test_wrong_person_type_exists(self) -> None:
        assert LeadershipChangeType.WRONG_PERSON == "wrong_person"

    def test_verified_current_type_exists(self) -> None:
        assert LeadershipChangeType.VERIFIED_CURRENT == "verified_current"
