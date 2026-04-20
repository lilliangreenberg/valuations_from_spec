"""Unit tests for leadership mention reconciliation pure functions."""

from __future__ import annotations

from src.domains.leadership.core.reconciliation import (
    ReconciliationFlag,
    names_match,
    reconcile_leadership,
)


class TestNamesMatch:
    def test_identical_full_names(self) -> None:
        assert names_match("Jane Smith", "Jane Smith")

    def test_case_insensitive(self) -> None:
        assert names_match("JANE SMITH", "jane smith")

    def test_middle_initial_matches_without(self) -> None:
        assert names_match("Jane Q. Smith", "Jane Smith")

    def test_different_first_name_does_not_match(self) -> None:
        assert not names_match("Jane Smith", "John Smith")

    def test_different_last_name_does_not_match(self) -> None:
        assert not names_match("Jane Smith", "Jane Doe")

    def test_empty_name_does_not_match(self) -> None:
        assert not names_match("", "Jane Smith")
        assert not names_match("Jane Smith", "")

    def test_honorifics_stripped(self) -> None:
        assert names_match("Dr. Jane Smith", "Jane Smith")

    def test_single_token_does_not_match(self) -> None:
        # Too few tokens to be confident
        assert not names_match("Smith", "Jane Smith")


class TestReconcileLeadership:
    def test_both_empty_returns_empty(self) -> None:
        assert reconcile_leadership([], []) == []

    def test_mention_matches_leader(self) -> None:
        mentions = [{"person_name": "Jane Smith", "title_context": "CEO"}]
        leaders = [{"person_name": "Jane Smith", "title": "CEO"}]
        results = reconcile_leadership(mentions, leaders)
        assert len(results) == 1
        assert results[0].flag == ReconciliationFlag.MATCHED

    def test_mention_without_leader_is_missing_in_db(self) -> None:
        mentions = [{"person_name": "New Hire", "title_context": "CEO"}]
        results = reconcile_leadership(mentions, [])
        assert len(results) == 1
        assert results[0].flag == ReconciliationFlag.MISSING_IN_DB
        assert results[0].person_name == "New Hire"

    def test_leader_without_mention_is_missing_on_website(self) -> None:
        leaders = [{"person_name": "Stale Person", "title": "CEO"}]
        results = reconcile_leadership([], leaders)
        assert len(results) == 1
        assert results[0].flag == ReconciliationFlag.MISSING_ON_WEBSITE

    def test_mixed_results(self) -> None:
        mentions = [
            {"person_name": "Jane Smith", "title_context": "CEO"},
            {"person_name": "New Hire", "title_context": "CTO"},
        ]
        leaders = [
            {"person_name": "Jane Smith", "title": "CEO"},
            {"person_name": "Old Cto", "title": "CTO"},
        ]
        results = reconcile_leadership(mentions, leaders)
        flags = {r.flag for r in results}
        assert ReconciliationFlag.MATCHED in flags
        assert ReconciliationFlag.MISSING_IN_DB in flags
        assert ReconciliationFlag.MISSING_ON_WEBSITE in flags

    def test_matches_with_middle_initial(self) -> None:
        mentions = [{"person_name": "John R. Smith", "title_context": "Founder"}]
        leaders = [{"person_name": "John Smith", "title": "Founder"}]
        results = reconcile_leadership(mentions, leaders)
        assert len(results) == 1
        assert results[0].flag == ReconciliationFlag.MATCHED
