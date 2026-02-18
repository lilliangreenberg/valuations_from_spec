"""Comprehensive unit tests for all Pydantic models.

Tests validation logic, boundary conditions, edge cases, and failure modes
for every model in src/models/. These tests call actual Pydantic constructors
with no mocking -- they exercise real validation paths.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from src.models.batch_result import BatchResult
from src.models.change_record import (
    ChangeMagnitude,
    ChangeRecord,
    SignificanceClassification,
    SignificanceSentiment,
)
from src.models.company import Company
from src.models.company_status import (
    CompanyStatus,
    CompanyStatusType,
    SignalType,
    StatusIndicator,
)
from src.models.config import Config
from src.models.keyword_match import KeywordMatch
from src.models.llm_validation import LLMValidationResult
from src.models.news_article import NewsArticle
from src.models.processing_error import ProcessingError
from src.models.snapshot import Snapshot
from src.models.social_media_link import (
    AccountType,
    DiscoveryMethod,
    HTMLRegion,
    Platform,
    RejectionReason,
    SocialMediaLink,
    VerificationStatus,
)

# ---------------------------------------------------------------------------
# Rebuild models that use TYPE_CHECKING / from __future__ import annotations
# with deferred type resolution. Without this, Pydantic cannot resolve the
# string-form annotations for datetime, SignificanceClassification, etc.
# ---------------------------------------------------------------------------
ChangeRecord.model_rebuild()
CompanyStatus.model_rebuild()
SocialMediaLink.model_rebuild()
NewsArticle.model_rebuild()
ProcessingError.model_rebuild()
LLMValidationResult.model_rebuild()

# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------

VALID_CHECKSUM = "a" * 32
VALID_CHECKSUM_UPPER = "A" * 32
PAST_DATETIME = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
NOW = datetime.now(UTC)


def _valid_company_kwargs() -> dict:
    return {
        "name": "Acme Corp",
        "source_sheet": "Sheet1",
    }


def _valid_snapshot_kwargs() -> dict:
    return {
        "company_id": 1,
        "url": "https://example.com",
        "content_markdown": "# Hello",
        "captured_at": PAST_DATETIME,
    }


def _valid_change_record_kwargs() -> dict:
    return {
        "company_id": 1,
        "snapshot_id_old": 1,
        "snapshot_id_new": 2,
        "checksum_old": VALID_CHECKSUM,
        "checksum_new": VALID_CHECKSUM,
        "has_changed": False,
        "change_magnitude": ChangeMagnitude.MINOR,
        "detected_at": PAST_DATETIME,
    }


def _valid_company_status_kwargs() -> dict:
    return {
        "company_id": 1,
        "status": CompanyStatusType.OPERATIONAL,
        "confidence": 0.9,
        "indicators": [StatusIndicator(type="http", value="200", signal=SignalType.POSITIVE)],
        "last_checked": PAST_DATETIME,
    }


def _valid_social_media_link_kwargs() -> dict:
    return {
        "company_id": 1,
        "platform": Platform.LINKEDIN,
        "profile_url": "https://linkedin.com/company/acme",
        "discovery_method": DiscoveryMethod.PAGE_FOOTER,
        "discovered_at": PAST_DATETIME,
    }


def _valid_news_article_kwargs() -> dict:
    return {
        "company_id": 1,
        "title": "Acme raises $10M",
        "content_url": "https://techcrunch.com/article",
        "source": "TechCrunch",
        "published_at": PAST_DATETIME,
        "discovered_at": PAST_DATETIME,
        "match_confidence": 0.85,
    }


def _valid_processing_error_kwargs() -> dict:
    return {
        "entity_type": "company",
        "entity_id": 1,
        "error_type": "ConnectionError",
        "error_message": "Timed out after 30s",
        "occurred_at": PAST_DATETIME,
    }


def _valid_keyword_match_kwargs() -> dict:
    return {
        "keyword": "funding",
        "category": "positive_financial",
        "position": 0,
        "context_before": "",
        "context_after": " round closed",
    }


# ===================================================================
# Company model tests
# ===================================================================


class TestCompany:
    """Tests for the Company Pydantic model."""

    def test_valid_company_creation(self) -> None:
        company = Company(**_valid_company_kwargs())
        assert company.name == "Acme Corp"
        assert company.source_sheet == "Sheet1"
        assert company.flagged_for_review is False
        assert company.flag_reason is None
        assert company.id is None
        assert company.homepage_url is None

    def test_name_strips_leading_trailing_whitespace(self) -> None:
        company = Company(name="  Acme Corp  ", source_sheet="S1")
        assert company.name == "Acme Corp"

    def test_name_collapses_internal_whitespace(self) -> None:
        company = Company(name="acme   corp   inc", source_sheet="S1")
        assert company.name == "Acme Corp Inc"

    def test_name_title_cases(self) -> None:
        company = Company(name="acme corp", source_sheet="S1")
        assert company.name == "Acme Corp"

    def test_name_title_case_preserves_single_word(self) -> None:
        company = Company(name="acme", source_sheet="S1")
        assert company.name == "Acme"

    def test_name_empty_string_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Name must not be empty"):
            Company(name="", source_sheet="S1")

    def test_name_whitespace_only_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Name must not be empty"):
            Company(name="   ", source_sheet="S1")

    def test_name_tab_only_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Name must not be empty"):
            Company(name="\t\n", source_sheet="S1")

    def test_name_exactly_500_chars_accepted(self) -> None:
        long_name = "a" * 500
        company = Company(name=long_name, source_sheet="S1")
        # title-cased: first char upper, rest lower
        assert len(company.name) == 500

    def test_name_501_chars_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Name must not exceed 500 characters"):
            Company(name="a" * 501, source_sheet="S1")

    def test_name_500_chars_with_leading_whitespace_stripped_then_accepted(self) -> None:
        """Leading whitespace is stripped before length check."""
        name_with_spaces = "  " + "a" * 500
        # After stripping: 500 chars -- should pass
        company = Company(name=name_with_spaces, source_sheet="S1")
        assert len(company.name) == 500

    def test_source_sheet_empty_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Source sheet must not be empty"):
            Company(name="Test", source_sheet="")

    def test_source_sheet_whitespace_only_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Source sheet must not be empty"):
            Company(name="Test", source_sheet="   ")

    def test_source_sheet_valid(self) -> None:
        company = Company(name="Test", source_sheet="Portfolio 2024")
        assert company.source_sheet == "Portfolio 2024"

    def test_flag_reason_none_accepted(self) -> None:
        company = Company(name="Test", source_sheet="S1", flag_reason=None)
        assert company.flag_reason is None

    def test_flag_reason_exactly_1000_chars_accepted(self) -> None:
        reason = "x" * 1000
        company = Company(
            name="Test",
            source_sheet="S1",
            flagged_for_review=True,
            flag_reason=reason,
        )
        assert len(company.flag_reason) == 1000  # type: ignore[arg-type]

    def test_flag_reason_1001_chars_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Flag reason must not exceed 1000 characters"):
            Company(
                name="Test",
                source_sheet="S1",
                flagged_for_review=True,
                flag_reason="x" * 1001,
            )

    def test_flagged_for_review_true_requires_flag_reason(self) -> None:
        with pytest.raises(
            ValidationError, match="flag_reason is required when flagged_for_review is True"
        ):
            Company(name="Test", source_sheet="S1", flagged_for_review=True)

    def test_flagged_for_review_true_with_reason_accepted(self) -> None:
        company = Company(
            name="Test",
            source_sheet="S1",
            flagged_for_review=True,
            flag_reason="Needs manual check",
        )
        assert company.flagged_for_review is True
        assert company.flag_reason == "Needs manual check"

    def test_flagged_for_review_false_with_reason_accepted(self) -> None:
        """flag_reason without flagged_for_review=True is allowed (no constraint)."""
        company = Company(
            name="Test", source_sheet="S1", flagged_for_review=False, flag_reason="Note"
        )
        assert company.flag_reason == "Note"

    def test_flagged_for_review_true_with_empty_reason_rejected(self) -> None:
        """Empty string is falsy, so it should fail the model validator."""
        with pytest.raises(
            ValidationError, match="flag_reason is required when flagged_for_review is True"
        ):
            Company(
                name="Test",
                source_sheet="S1",
                flagged_for_review=True,
                flag_reason="",
            )

    def test_homepage_url_valid(self) -> None:
        company = Company(name="Test", source_sheet="S1", homepage_url="https://example.com")
        assert str(company.homepage_url) == "https://example.com/"

    def test_homepage_url_invalid_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Company(name="Test", source_sheet="S1", homepage_url="not-a-url")

    def test_homepage_url_none_accepted(self) -> None:
        company = Company(name="Test", source_sheet="S1", homepage_url=None)
        assert company.homepage_url is None

    def test_strict_mode_rejects_int_for_name(self) -> None:
        """strict=True means no type coercion: int for a str field is rejected."""
        with pytest.raises(ValidationError):
            Company(name=123, source_sheet="S1")  # type: ignore[arg-type]

    def test_strict_mode_rejects_int_for_source_sheet(self) -> None:
        with pytest.raises(ValidationError):
            Company(name="Test", source_sheet=999)  # type: ignore[arg-type]

    def test_strict_mode_rejects_string_for_bool(self) -> None:
        with pytest.raises(ValidationError):
            Company(name="Test", source_sheet="S1", flagged_for_review="yes")  # type: ignore[arg-type]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            Company(name="Test", source_sheet="S1", unknown_field="value")  # type: ignore[call-arg]

    def test_created_at_defaults_to_now(self) -> None:
        before = datetime.now(UTC)
        company = Company(name="Test", source_sheet="S1")
        after = datetime.now(UTC)
        assert before <= company.created_at <= after

    def test_updated_at_defaults_to_now(self) -> None:
        before = datetime.now(UTC)
        company = Company(name="Test", source_sheet="S1")
        after = datetime.now(UTC)
        assert before <= company.updated_at <= after

    def test_name_with_mixed_whitespace_types(self) -> None:
        """Tabs, newlines, and multiple spaces should all collapse to single space."""
        company = Company(name="acme\t\ncorp\r\ninc", source_sheet="S1")
        assert company.name == "Acme Corp Inc"


# ===================================================================
# Snapshot model tests
# ===================================================================


class TestSnapshot:
    """Tests for the Snapshot Pydantic model."""

    def test_valid_snapshot_creation(self) -> None:
        snap = Snapshot(**_valid_snapshot_kwargs())
        assert snap.company_id == 1
        assert snap.content_markdown == "# Hello"
        assert snap.id is None

    def test_company_id_zero_rejected(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["company_id"] = 0
        with pytest.raises(ValidationError, match="company_id must be greater than 0"):
            Snapshot(**kwargs)

    def test_company_id_negative_rejected(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["company_id"] = -1
        with pytest.raises(ValidationError, match="company_id must be greater than 0"):
            Snapshot(**kwargs)

    def test_company_id_one_accepted(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["company_id"] = 1
        snap = Snapshot(**kwargs)
        assert snap.company_id == 1

    def test_content_markdown_exactly_10m_accepted(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["content_markdown"] = "x" * 10_000_000
        snap = Snapshot(**kwargs)
        assert len(snap.content_markdown) == 10_000_000  # type: ignore[arg-type]

    def test_content_markdown_over_10m_rejected(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["content_markdown"] = "x" * 10_000_001
        with pytest.raises(
            ValidationError, match="content_markdown must not exceed 10,000,000 characters"
        ):
            Snapshot(**kwargs)

    def test_content_html_exactly_10m_accepted(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["content_html"] = "<p>" + "x" * 9_999_997
        snap = Snapshot(**kwargs)
        assert len(snap.content_html) == 10_000_000  # type: ignore[arg-type]

    def test_content_html_over_10m_rejected(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["content_html"] = "x" * 10_000_001
        with pytest.raises(
            ValidationError, match="content_html must not exceed 10,000,000 characters"
        ):
            Snapshot(**kwargs)

    def test_status_code_100_accepted(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["status_code"] = 100
        snap = Snapshot(**kwargs)
        assert snap.status_code == 100

    def test_status_code_599_accepted(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["status_code"] = 599
        snap = Snapshot(**kwargs)
        assert snap.status_code == 599

    def test_status_code_99_rejected(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["status_code"] = 99
        with pytest.raises(ValidationError, match="status_code must be between 100 and 599"):
            Snapshot(**kwargs)

    def test_status_code_600_rejected(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["status_code"] = 600
        with pytest.raises(ValidationError, match="status_code must be between 100 and 599"):
            Snapshot(**kwargs)

    def test_status_code_zero_rejected(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["status_code"] = 0
        with pytest.raises(ValidationError):
            Snapshot(**kwargs)

    def test_status_code_none_accepted(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["status_code"] = None
        snap = Snapshot(**kwargs)
        assert snap.status_code is None

    def test_error_message_exactly_2000_accepted(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["error_message"] = "e" * 2000
        snap = Snapshot(**kwargs)
        assert len(snap.error_message) == 2000  # type: ignore[arg-type]

    def test_error_message_2001_rejected(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["error_message"] = "e" * 2001
        with pytest.raises(ValidationError, match="error_message must not exceed 2000 characters"):
            Snapshot(**kwargs)

    def test_checksum_valid_32_hex_accepted(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["content_checksum"] = "abcdef1234567890abcdef1234567890"
        snap = Snapshot(**kwargs)
        assert snap.content_checksum == "abcdef1234567890abcdef1234567890"

    def test_checksum_uppercase_auto_lowercased(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["content_checksum"] = "ABCDEF1234567890ABCDEF1234567890"
        snap = Snapshot(**kwargs)
        assert snap.content_checksum == "abcdef1234567890abcdef1234567890"

    def test_checksum_mixed_case_auto_lowercased(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["content_checksum"] = "AbCdEf1234567890aBcDeF1234567890"
        snap = Snapshot(**kwargs)
        assert snap.content_checksum == "abcdef1234567890abcdef1234567890"

    def test_checksum_31_chars_rejected(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["content_checksum"] = "a" * 31
        with pytest.raises(
            ValidationError, match="content_checksum must be a valid 32-character hex MD5 string"
        ):
            Snapshot(**kwargs)

    def test_checksum_33_chars_rejected(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["content_checksum"] = "a" * 33
        with pytest.raises(ValidationError):
            Snapshot(**kwargs)

    def test_checksum_non_hex_rejected(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["content_checksum"] = "g" * 32  # 'g' is not a hex char
        with pytest.raises(ValidationError):
            Snapshot(**kwargs)

    def test_checksum_with_spaces_rejected(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["content_checksum"] = "a" * 16 + " " * 16
        with pytest.raises(ValidationError):
            Snapshot(**kwargs)

    def test_checksum_none_accepted(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["content_checksum"] = None
        snap = Snapshot(**kwargs)
        assert snap.content_checksum is None

    def test_captured_at_past_accepted(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["captured_at"] = PAST_DATETIME
        snap = Snapshot(**kwargs)
        assert snap.captured_at == PAST_DATETIME

    def test_captured_at_future_rejected(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["captured_at"] = datetime.now(UTC) + timedelta(hours=1)
        with pytest.raises(ValidationError, match="captured_at must not be in the future"):
            Snapshot(**kwargs)

    def test_model_validator_no_content_no_error_rejected(self) -> None:
        """Must provide at least one of content_markdown, content_html, or error_message."""
        with pytest.raises(
            ValidationError,
            match="At least one of content_markdown, content_html, "
            "or error_message must be provided",
        ):
            Snapshot(
                company_id=1,
                url="https://example.com",
                captured_at=PAST_DATETIME,
                content_markdown=None,
                content_html=None,
                error_message=None,
            )

    def test_model_validator_only_error_message_accepted(self) -> None:
        snap = Snapshot(
            company_id=1,
            url="https://example.com",
            captured_at=PAST_DATETIME,
            error_message="Connection refused",
        )
        assert snap.content_markdown is None
        assert snap.error_message == "Connection refused"

    def test_model_validator_only_content_html_accepted(self) -> None:
        snap = Snapshot(
            company_id=1,
            url="https://example.com",
            captured_at=PAST_DATETIME,
            content_html="<p>Hi</p>",
        )
        assert snap.content_html == "<p>Hi</p>"

    def test_strict_mode_rejects_string_for_company_id(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["company_id"] = "1"
        with pytest.raises(ValidationError):
            Snapshot(**kwargs)

    def test_url_invalid_rejected(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["url"] = "not-a-url"
        with pytest.raises(ValidationError):
            Snapshot(**kwargs)


# ===================================================================
# ChangeRecord model tests
# ===================================================================


class TestChangeRecord:
    """Tests for the ChangeRecord Pydantic model."""

    def test_valid_change_record_creation(self) -> None:
        record = ChangeRecord(**_valid_change_record_kwargs())
        assert record.company_id == 1
        assert record.has_changed is False
        assert record.change_magnitude == ChangeMagnitude.MINOR

    def test_checksum_old_uppercase_auto_lowercased(self) -> None:
        kwargs = _valid_change_record_kwargs()
        kwargs["checksum_old"] = VALID_CHECKSUM_UPPER
        record = ChangeRecord(**kwargs)
        assert record.checksum_old == VALID_CHECKSUM_UPPER.lower()

    def test_checksum_new_uppercase_auto_lowercased(self) -> None:
        kwargs = _valid_change_record_kwargs()
        kwargs["checksum_new"] = VALID_CHECKSUM_UPPER
        record = ChangeRecord(**kwargs)
        assert record.checksum_new == VALID_CHECKSUM_UPPER.lower()

    def test_checksum_old_invalid_length_rejected(self) -> None:
        kwargs = _valid_change_record_kwargs()
        kwargs["checksum_old"] = "abc"
        with pytest.raises(
            ValidationError, match="Checksum must be a valid 32-character hex MD5 string"
        ):
            ChangeRecord(**kwargs)

    def test_checksum_new_non_hex_rejected(self) -> None:
        kwargs = _valid_change_record_kwargs()
        kwargs["checksum_new"] = "z" * 32
        with pytest.raises(ValidationError):
            ChangeRecord(**kwargs)

    def test_checksum_empty_string_rejected(self) -> None:
        kwargs = _valid_change_record_kwargs()
        kwargs["checksum_old"] = ""
        with pytest.raises(ValidationError):
            ChangeRecord(**kwargs)

    def test_significance_confidence_zero_accepted(self) -> None:
        kwargs = _valid_change_record_kwargs()
        kwargs["significance_confidence"] = 0.0
        record = ChangeRecord(**kwargs)
        assert record.significance_confidence == 0.0

    def test_significance_confidence_one_accepted(self) -> None:
        kwargs = _valid_change_record_kwargs()
        kwargs["significance_confidence"] = 1.0
        record = ChangeRecord(**kwargs)
        assert record.significance_confidence == 1.0

    def test_significance_confidence_midpoint_accepted(self) -> None:
        kwargs = _valid_change_record_kwargs()
        kwargs["significance_confidence"] = 0.5
        record = ChangeRecord(**kwargs)
        assert record.significance_confidence == 0.5

    def test_significance_confidence_negative_rejected(self) -> None:
        kwargs = _valid_change_record_kwargs()
        kwargs["significance_confidence"] = -0.01
        with pytest.raises(
            ValidationError, match="significance_confidence must be between 0.0 and 1.0"
        ):
            ChangeRecord(**kwargs)

    def test_significance_confidence_over_one_rejected(self) -> None:
        kwargs = _valid_change_record_kwargs()
        kwargs["significance_confidence"] = 1.01
        with pytest.raises(ValidationError):
            ChangeRecord(**kwargs)

    def test_significance_confidence_none_accepted(self) -> None:
        kwargs = _valid_change_record_kwargs()
        kwargs["significance_confidence"] = None
        record = ChangeRecord(**kwargs)
        assert record.significance_confidence is None

    def test_change_magnitude_enum_values(self) -> None:
        assert ChangeMagnitude.MINOR == "minor"
        assert ChangeMagnitude.MODERATE == "moderate"
        assert ChangeMagnitude.MAJOR == "major"

    def test_significance_classification_enum_values(self) -> None:
        assert SignificanceClassification.SIGNIFICANT == "significant"
        assert SignificanceClassification.INSIGNIFICANT == "insignificant"
        assert SignificanceClassification.UNCERTAIN == "uncertain"

    def test_significance_sentiment_enum_values(self) -> None:
        assert SignificanceSentiment.POSITIVE == "positive"
        assert SignificanceSentiment.NEGATIVE == "negative"
        assert SignificanceSentiment.NEUTRAL == "neutral"
        assert SignificanceSentiment.MIXED == "mixed"

    def test_invalid_change_magnitude_rejected(self) -> None:
        kwargs = _valid_change_record_kwargs()
        kwargs["change_magnitude"] = "huge"
        with pytest.raises(ValidationError):
            ChangeRecord(**kwargs)

    def test_all_optional_significance_fields(self) -> None:
        kwargs = _valid_change_record_kwargs()
        kwargs["significance_classification"] = SignificanceClassification.SIGNIFICANT
        kwargs["significance_sentiment"] = SignificanceSentiment.POSITIVE
        kwargs["significance_confidence"] = 0.85
        kwargs["matched_keywords"] = ["funding", "raised"]
        kwargs["matched_categories"] = ["positive_financial"]
        kwargs["significance_notes"] = "Strong signal"
        kwargs["evidence_snippets"] = ["raised $10M in Series A"]
        record = ChangeRecord(**kwargs)
        assert record.significance_classification == SignificanceClassification.SIGNIFICANT
        assert record.matched_keywords == ["funding", "raised"]

    def test_matched_keywords_defaults_empty_list(self) -> None:
        record = ChangeRecord(**_valid_change_record_kwargs())
        assert record.matched_keywords == []

    def test_evidence_snippets_defaults_empty_list(self) -> None:
        record = ChangeRecord(**_valid_change_record_kwargs())
        assert record.evidence_snippets == []

    def test_strict_mode_rejects_string_for_company_id(self) -> None:
        kwargs = _valid_change_record_kwargs()
        kwargs["company_id"] = "1"
        with pytest.raises(ValidationError):
            ChangeRecord(**kwargs)


# ===================================================================
# CompanyStatus model tests
# ===================================================================


class TestCompanyStatus:
    """Tests for the CompanyStatus Pydantic model."""

    def test_valid_company_status_creation(self) -> None:
        status = CompanyStatus(**_valid_company_status_kwargs())
        assert status.status == CompanyStatusType.OPERATIONAL
        assert status.confidence == 0.9

    def test_confidence_zero_accepted(self) -> None:
        kwargs = _valid_company_status_kwargs()
        kwargs["confidence"] = 0.0
        status = CompanyStatus(**kwargs)
        assert status.confidence == 0.0

    def test_confidence_one_accepted(self) -> None:
        kwargs = _valid_company_status_kwargs()
        kwargs["confidence"] = 1.0
        status = CompanyStatus(**kwargs)
        assert status.confidence == 1.0

    def test_confidence_negative_rejected(self) -> None:
        kwargs = _valid_company_status_kwargs()
        kwargs["confidence"] = -0.001
        with pytest.raises(ValidationError, match="confidence must be between 0.0 and 1.0"):
            CompanyStatus(**kwargs)

    def test_confidence_over_one_rejected(self) -> None:
        kwargs = _valid_company_status_kwargs()
        kwargs["confidence"] = 1.001
        with pytest.raises(ValidationError):
            CompanyStatus(**kwargs)

    def test_confidence_slightly_below_zero_rejected(self) -> None:
        kwargs = _valid_company_status_kwargs()
        kwargs["confidence"] = -1e-10
        with pytest.raises(ValidationError):
            CompanyStatus(**kwargs)

    def test_status_indicator_valid(self) -> None:
        indicator = StatusIndicator(
            type="dns_resolution", value="resolved", signal=SignalType.POSITIVE
        )
        assert indicator.type == "dns_resolution"
        assert indicator.signal == SignalType.POSITIVE

    def test_status_indicator_all_signal_types(self) -> None:
        for signal in SignalType:
            indicator = StatusIndicator(type="test", value="val", signal=signal)
            assert indicator.signal == signal

    def test_company_status_type_enum_values(self) -> None:
        assert CompanyStatusType.OPERATIONAL == "operational"
        assert CompanyStatusType.LIKELY_CLOSED == "likely_closed"
        assert CompanyStatusType.UNCERTAIN == "uncertain"

    def test_signal_type_enum_values(self) -> None:
        assert SignalType.POSITIVE == "positive"
        assert SignalType.NEGATIVE == "negative"
        assert SignalType.NEUTRAL == "neutral"

    def test_invalid_status_type_rejected(self) -> None:
        kwargs = _valid_company_status_kwargs()
        kwargs["status"] = "dead"
        with pytest.raises(ValidationError):
            CompanyStatus(**kwargs)

    def test_empty_indicators_list_accepted(self) -> None:
        kwargs = _valid_company_status_kwargs()
        kwargs["indicators"] = []
        status = CompanyStatus(**kwargs)
        assert status.indicators == []

    def test_multiple_indicators(self) -> None:
        kwargs = _valid_company_status_kwargs()
        kwargs["indicators"] = [
            StatusIndicator(type="http", value="200", signal=SignalType.POSITIVE),
            StatusIndicator(type="dns", value="resolved", signal=SignalType.POSITIVE),
            StatusIndicator(type="content", value="empty", signal=SignalType.NEGATIVE),
        ]
        status = CompanyStatus(**kwargs)
        assert len(status.indicators) == 3

    def test_http_last_modified_none_accepted(self) -> None:
        status = CompanyStatus(**_valid_company_status_kwargs())
        assert status.http_last_modified is None

    def test_http_last_modified_datetime_accepted(self) -> None:
        kwargs = _valid_company_status_kwargs()
        kwargs["http_last_modified"] = PAST_DATETIME
        status = CompanyStatus(**kwargs)
        assert status.http_last_modified == PAST_DATETIME

    def test_strict_mode_rejects_string_for_confidence(self) -> None:
        kwargs = _valid_company_status_kwargs()
        kwargs["confidence"] = "0.9"
        with pytest.raises(ValidationError):
            CompanyStatus(**kwargs)


# ===================================================================
# SocialMediaLink model tests
# ===================================================================


class TestSocialMediaLink:
    """Tests for the SocialMediaLink Pydantic model."""

    def test_valid_social_media_link_creation(self) -> None:
        link = SocialMediaLink(**_valid_social_media_link_kwargs())
        assert link.platform == Platform.LINKEDIN
        assert link.verification_status == VerificationStatus.UNVERIFIED

    def test_similarity_score_zero_accepted(self) -> None:
        kwargs = _valid_social_media_link_kwargs()
        kwargs["similarity_score"] = 0.0
        link = SocialMediaLink(**kwargs)
        assert link.similarity_score == 0.0

    def test_similarity_score_one_accepted(self) -> None:
        kwargs = _valid_social_media_link_kwargs()
        kwargs["similarity_score"] = 1.0
        link = SocialMediaLink(**kwargs)
        assert link.similarity_score == 1.0

    def test_similarity_score_negative_rejected(self) -> None:
        kwargs = _valid_social_media_link_kwargs()
        kwargs["similarity_score"] = -0.1
        with pytest.raises(ValidationError, match="similarity_score must be between 0.0 and 1.0"):
            SocialMediaLink(**kwargs)

    def test_similarity_score_over_one_rejected(self) -> None:
        kwargs = _valid_social_media_link_kwargs()
        kwargs["similarity_score"] = 1.1
        with pytest.raises(ValidationError):
            SocialMediaLink(**kwargs)

    def test_similarity_score_none_accepted(self) -> None:
        link = SocialMediaLink(**_valid_social_media_link_kwargs())
        assert link.similarity_score is None

    def test_account_confidence_zero_accepted(self) -> None:
        kwargs = _valid_social_media_link_kwargs()
        kwargs["account_confidence"] = 0.0
        link = SocialMediaLink(**kwargs)
        assert link.account_confidence == 0.0

    def test_account_confidence_one_accepted(self) -> None:
        kwargs = _valid_social_media_link_kwargs()
        kwargs["account_confidence"] = 1.0
        link = SocialMediaLink(**kwargs)
        assert link.account_confidence == 1.0

    def test_account_confidence_negative_rejected(self) -> None:
        kwargs = _valid_social_media_link_kwargs()
        kwargs["account_confidence"] = -0.01
        with pytest.raises(ValidationError, match="account_confidence must be between 0.0 and 1.0"):
            SocialMediaLink(**kwargs)

    def test_account_confidence_over_one_rejected(self) -> None:
        kwargs = _valid_social_media_link_kwargs()
        kwargs["account_confidence"] = 1.5
        with pytest.raises(ValidationError):
            SocialMediaLink(**kwargs)

    def test_all_platforms(self) -> None:
        """Every Platform enum variant should be accepted."""
        for platform in Platform:
            kwargs = _valid_social_media_link_kwargs()
            kwargs["platform"] = platform
            link = SocialMediaLink(**kwargs)
            assert link.platform == platform

    def test_all_discovery_methods(self) -> None:
        for method in DiscoveryMethod:
            kwargs = _valid_social_media_link_kwargs()
            kwargs["discovery_method"] = method
            link = SocialMediaLink(**kwargs)
            assert link.discovery_method == method

    def test_all_verification_statuses(self) -> None:
        for status in VerificationStatus:
            kwargs = _valid_social_media_link_kwargs()
            kwargs["verification_status"] = status
            link = SocialMediaLink(**kwargs)
            assert link.verification_status == status

    def test_all_html_regions(self) -> None:
        for region in HTMLRegion:
            kwargs = _valid_social_media_link_kwargs()
            kwargs["html_location"] = region
            link = SocialMediaLink(**kwargs)
            assert link.html_location == region

    def test_all_account_types(self) -> None:
        for acct_type in AccountType:
            kwargs = _valid_social_media_link_kwargs()
            kwargs["account_type"] = acct_type
            link = SocialMediaLink(**kwargs)
            assert link.account_type == acct_type

    def test_all_rejection_reasons(self) -> None:
        for reason in RejectionReason:
            kwargs = _valid_social_media_link_kwargs()
            kwargs["rejection_reason"] = reason
            link = SocialMediaLink(**kwargs)
            assert link.rejection_reason == reason

    def test_invalid_platform_rejected(self) -> None:
        kwargs = _valid_social_media_link_kwargs()
        kwargs["platform"] = "myspace"
        with pytest.raises(ValidationError):
            SocialMediaLink(**kwargs)

    def test_invalid_discovery_method_rejected(self) -> None:
        kwargs = _valid_social_media_link_kwargs()
        kwargs["discovery_method"] = "magic"
        with pytest.raises(ValidationError):
            SocialMediaLink(**kwargs)

    def test_platform_enum_count(self) -> None:
        """There should be 13 platforms (12 social + BLOG)."""
        assert len(Platform) == 13

    def test_rejection_reason_enum_count(self) -> None:
        assert len(RejectionReason) == 7

    def test_strict_mode_rejects_int_for_profile_url(self) -> None:
        kwargs = _valid_social_media_link_kwargs()
        kwargs["profile_url"] = 12345
        with pytest.raises(ValidationError):
            SocialMediaLink(**kwargs)


# ===================================================================
# NewsArticle model tests
# ===================================================================


class TestNewsArticle:
    """Tests for the NewsArticle Pydantic model."""

    def test_valid_news_article_creation(self) -> None:
        article = NewsArticle(**_valid_news_article_kwargs())
        assert article.title == "Acme raises $10M"
        assert article.match_confidence == 0.85

    def test_company_id_zero_rejected(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["company_id"] = 0
        with pytest.raises(ValidationError, match="company_id must be greater than 0"):
            NewsArticle(**kwargs)

    def test_company_id_negative_rejected(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["company_id"] = -5
        with pytest.raises(ValidationError):
            NewsArticle(**kwargs)

    def test_company_id_one_accepted(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["company_id"] = 1
        article = NewsArticle(**kwargs)
        assert article.company_id == 1

    def test_title_empty_rejected(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["title"] = ""
        with pytest.raises(ValidationError, match="Title must not be empty"):
            NewsArticle(**kwargs)

    def test_title_whitespace_only_rejected(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["title"] = "   "
        with pytest.raises(ValidationError, match="Title must not be empty"):
            NewsArticle(**kwargs)

    def test_title_exactly_500_chars_accepted(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["title"] = "T" * 500
        article = NewsArticle(**kwargs)
        assert len(article.title) == 500

    def test_title_501_chars_rejected(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["title"] = "T" * 501
        with pytest.raises(ValidationError, match="Title must not exceed 500 characters"):
            NewsArticle(**kwargs)

    def test_source_empty_rejected(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["source"] = ""
        with pytest.raises(ValidationError, match="Source must not be empty"):
            NewsArticle(**kwargs)

    def test_source_whitespace_only_rejected(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["source"] = "  \t  "
        with pytest.raises(ValidationError, match="Source must not be empty"):
            NewsArticle(**kwargs)

    def test_match_confidence_zero_accepted(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["match_confidence"] = 0.0
        article = NewsArticle(**kwargs)
        assert article.match_confidence == 0.0

    def test_match_confidence_one_accepted(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["match_confidence"] = 1.0
        article = NewsArticle(**kwargs)
        assert article.match_confidence == 1.0

    def test_match_confidence_negative_rejected(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["match_confidence"] = -0.01
        with pytest.raises(ValidationError, match="match_confidence must be between 0.0 and 1.0"):
            NewsArticle(**kwargs)

    def test_match_confidence_over_one_rejected(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["match_confidence"] = 1.001
        with pytest.raises(ValidationError):
            NewsArticle(**kwargs)

    def test_logo_similarity_zero_accepted(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["logo_similarity"] = 0.0
        article = NewsArticle(**kwargs)
        assert article.logo_similarity == 0.0

    def test_logo_similarity_one_accepted(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["logo_similarity"] = 1.0
        article = NewsArticle(**kwargs)
        assert article.logo_similarity == 1.0

    def test_logo_similarity_negative_rejected(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["logo_similarity"] = -0.5
        with pytest.raises(ValidationError, match="logo_similarity must be between 0.0 and 1.0"):
            NewsArticle(**kwargs)

    def test_logo_similarity_over_one_rejected(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["logo_similarity"] = 2.0
        with pytest.raises(ValidationError):
            NewsArticle(**kwargs)

    def test_logo_similarity_none_accepted(self) -> None:
        article = NewsArticle(**_valid_news_article_kwargs())
        assert article.logo_similarity is None

    def test_significance_confidence_zero_accepted(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["significance_confidence"] = 0.0
        article = NewsArticle(**kwargs)
        assert article.significance_confidence == 0.0

    def test_significance_confidence_one_accepted(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["significance_confidence"] = 1.0
        article = NewsArticle(**kwargs)
        assert article.significance_confidence == 1.0

    def test_significance_confidence_negative_rejected(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["significance_confidence"] = -0.1
        with pytest.raises(
            ValidationError,
            match="significance_confidence must be between 0.0 and 1.0",
        ):
            NewsArticle(**kwargs)

    def test_significance_confidence_over_one_rejected(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["significance_confidence"] = 1.5
        with pytest.raises(ValidationError):
            NewsArticle(**kwargs)

    def test_significance_confidence_none_accepted(self) -> None:
        article = NewsArticle(**_valid_news_article_kwargs())
        assert article.significance_confidence is None

    def test_content_url_invalid_rejected(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["content_url"] = "not-a-url"
        with pytest.raises(ValidationError):
            NewsArticle(**kwargs)

    def test_match_evidence_defaults_empty(self) -> None:
        article = NewsArticle(**_valid_news_article_kwargs())
        assert article.match_evidence == []

    def test_matched_keywords_defaults_empty(self) -> None:
        article = NewsArticle(**_valid_news_article_kwargs())
        assert article.matched_keywords == []

    def test_matched_categories_defaults_empty(self) -> None:
        article = NewsArticle(**_valid_news_article_kwargs())
        assert article.matched_categories == []

    def test_strict_mode_rejects_string_for_company_id(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["company_id"] = "1"
        with pytest.raises(ValidationError):
            NewsArticle(**kwargs)

    def test_all_significance_fields_populated(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["significance_classification"] = SignificanceClassification.SIGNIFICANT
        kwargs["significance_sentiment"] = SignificanceSentiment.POSITIVE
        kwargs["significance_confidence"] = 0.92
        kwargs["matched_keywords"] = ["funding"]
        kwargs["matched_categories"] = ["positive_financial"]
        kwargs["significance_notes"] = "Strong match"
        article = NewsArticle(**kwargs)
        assert article.significance_classification == SignificanceClassification.SIGNIFICANT
        assert article.significance_sentiment == SignificanceSentiment.POSITIVE


# ===================================================================
# KeywordMatch model tests
# ===================================================================


class TestKeywordMatch:
    """Tests for the KeywordMatch Pydantic model."""

    def test_valid_keyword_match_creation(self) -> None:
        match = KeywordMatch(**_valid_keyword_match_kwargs())
        assert match.keyword == "funding"
        assert match.position == 0
        assert match.is_negated is False
        assert match.is_false_positive is False

    def test_position_zero_accepted(self) -> None:
        kwargs = _valid_keyword_match_kwargs()
        kwargs["position"] = 0
        match = KeywordMatch(**kwargs)
        assert match.position == 0

    def test_position_large_value_accepted(self) -> None:
        kwargs = _valid_keyword_match_kwargs()
        kwargs["position"] = 999999
        match = KeywordMatch(**kwargs)
        assert match.position == 999999

    def test_position_negative_rejected(self) -> None:
        kwargs = _valid_keyword_match_kwargs()
        kwargs["position"] = -1
        with pytest.raises(ValidationError, match="position must be >= 0"):
            KeywordMatch(**kwargs)

    def test_context_before_exactly_50_chars_accepted(self) -> None:
        kwargs = _valid_keyword_match_kwargs()
        kwargs["context_before"] = "c" * 50
        match = KeywordMatch(**kwargs)
        assert len(match.context_before) == 50

    def test_context_before_51_chars_rejected(self) -> None:
        kwargs = _valid_keyword_match_kwargs()
        kwargs["context_before"] = "c" * 51
        with pytest.raises(ValidationError, match="context_before must not exceed 50 characters"):
            KeywordMatch(**kwargs)

    def test_context_before_empty_accepted(self) -> None:
        kwargs = _valid_keyword_match_kwargs()
        kwargs["context_before"] = ""
        match = KeywordMatch(**kwargs)
        assert match.context_before == ""

    def test_context_after_exactly_50_chars_accepted(self) -> None:
        kwargs = _valid_keyword_match_kwargs()
        kwargs["context_after"] = "c" * 50
        match = KeywordMatch(**kwargs)
        assert len(match.context_after) == 50

    def test_context_after_51_chars_rejected(self) -> None:
        kwargs = _valid_keyword_match_kwargs()
        kwargs["context_after"] = "c" * 51
        with pytest.raises(ValidationError, match="context_after must not exceed 50 characters"):
            KeywordMatch(**kwargs)

    def test_context_after_empty_accepted(self) -> None:
        kwargs = _valid_keyword_match_kwargs()
        kwargs["context_after"] = ""
        match = KeywordMatch(**kwargs)
        assert match.context_after == ""

    def test_is_negated_true(self) -> None:
        kwargs = _valid_keyword_match_kwargs()
        kwargs["is_negated"] = True
        match = KeywordMatch(**kwargs)
        assert match.is_negated is True

    def test_is_false_positive_true(self) -> None:
        kwargs = _valid_keyword_match_kwargs()
        kwargs["is_false_positive"] = True
        match = KeywordMatch(**kwargs)
        assert match.is_false_positive is True


# ===================================================================
# ProcessingError model tests
# ===================================================================


class TestProcessingError:
    """Tests for the ProcessingError Pydantic model."""

    def test_valid_processing_error_creation(self) -> None:
        error = ProcessingError(**_valid_processing_error_kwargs())
        assert error.entity_type == "company"
        assert error.error_type == "ConnectionError"
        assert error.retry_count == 0

    def test_entity_type_company_accepted(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["entity_type"] = "company"
        error = ProcessingError(**kwargs)
        assert error.entity_type == "company"

    def test_entity_type_snapshot_accepted(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["entity_type"] = "snapshot"
        error = ProcessingError(**kwargs)
        assert error.entity_type == "snapshot"

    def test_entity_type_invalid_rejected(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["entity_type"] = "user"
        with pytest.raises(ValidationError):
            ProcessingError(**kwargs)

    def test_entity_type_uppercase_rejected(self) -> None:
        """Literal is case-sensitive."""
        kwargs = _valid_processing_error_kwargs()
        kwargs["entity_type"] = "Company"
        with pytest.raises(ValidationError):
            ProcessingError(**kwargs)

    def test_error_type_pascal_case_accepted(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["error_type"] = "TimeoutError"
        error = ProcessingError(**kwargs)
        assert error.error_type == "TimeoutError"

    def test_error_type_single_word_pascal_case_accepted(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["error_type"] = "Error"
        error = ProcessingError(**kwargs)
        assert error.error_type == "Error"

    def test_error_type_with_digits_accepted(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["error_type"] = "Http429Error"
        error = ProcessingError(**kwargs)
        assert error.error_type == "Http429Error"

    def test_error_type_lowercase_start_rejected(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["error_type"] = "connectionError"
        with pytest.raises(ValidationError, match="error_type must be in PascalCase format"):
            ProcessingError(**kwargs)

    def test_error_type_all_lowercase_rejected(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["error_type"] = "error"
        with pytest.raises(ValidationError):
            ProcessingError(**kwargs)

    def test_error_type_with_underscores_rejected(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["error_type"] = "Connection_Error"
        with pytest.raises(ValidationError):
            ProcessingError(**kwargs)

    def test_error_type_with_spaces_rejected(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["error_type"] = "Connection Error"
        with pytest.raises(ValidationError):
            ProcessingError(**kwargs)

    def test_error_type_empty_rejected(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["error_type"] = ""
        with pytest.raises(
            ValidationError, match="error_type must be between 1 and 100 characters"
        ):
            ProcessingError(**kwargs)

    def test_error_type_101_chars_rejected(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["error_type"] = "A" * 101
        with pytest.raises(
            ValidationError, match="error_type must be between 1 and 100 characters"
        ):
            ProcessingError(**kwargs)

    def test_error_type_exactly_100_chars_accepted(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        # Must start with uppercase and contain only [a-zA-Z0-9]
        kwargs["error_type"] = "A" + "b" * 99
        error = ProcessingError(**kwargs)
        assert len(error.error_type) == 100

    def test_error_message_one_char_accepted(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["error_message"] = "x"
        error = ProcessingError(**kwargs)
        assert error.error_message == "x"

    def test_error_message_5000_chars_accepted(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["error_message"] = "m" * 5000
        error = ProcessingError(**kwargs)
        assert len(error.error_message) == 5000

    def test_error_message_5001_chars_rejected(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["error_message"] = "m" * 5001
        with pytest.raises(
            ValidationError,
            match="error_message must be between 1 and 5000 characters",
        ):
            ProcessingError(**kwargs)

    def test_error_message_empty_rejected(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["error_message"] = ""
        with pytest.raises(
            ValidationError,
            match="error_message must be between 1 and 5000 characters",
        ):
            ProcessingError(**kwargs)

    def test_retry_count_zero_accepted(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["retry_count"] = 0
        error = ProcessingError(**kwargs)
        assert error.retry_count == 0

    def test_retry_count_two_accepted(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["retry_count"] = 2
        error = ProcessingError(**kwargs)
        assert error.retry_count == 2

    def test_retry_count_three_rejected(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["retry_count"] = 3
        with pytest.raises(ValidationError, match="retry_count must be between 0 and 2"):
            ProcessingError(**kwargs)

    def test_retry_count_negative_rejected(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["retry_count"] = -1
        with pytest.raises(ValidationError, match="retry_count must be between 0 and 2"):
            ProcessingError(**kwargs)

    def test_retry_count_default_zero(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        del kwargs["entity_id"]  # use only required fields + error_type, error_message
        error = ProcessingError(**kwargs)
        assert error.retry_count == 0

    def test_strict_mode_rejects_string_for_retry_count(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["retry_count"] = "2"
        with pytest.raises(ValidationError):
            ProcessingError(**kwargs)

    def test_error_type_with_hyphen_rejected(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["error_type"] = "Connection-Error"
        with pytest.raises(ValidationError):
            ProcessingError(**kwargs)

    def test_error_type_starting_with_digit_rejected(self) -> None:
        kwargs = _valid_processing_error_kwargs()
        kwargs["error_type"] = "4xxError"
        with pytest.raises(ValidationError):
            ProcessingError(**kwargs)


# ===================================================================
# BatchResult model tests
# ===================================================================


class TestBatchResult:
    """Tests for the BatchResult Pydantic model."""

    def test_valid_batch_result_creation(self) -> None:
        result = BatchResult(
            processed=100,
            successful=95,
            failed=3,
            skipped=2,
            duration_seconds=45.7,
        )
        assert result.processed == 100
        assert result.successful == 95
        assert result.failed == 3
        assert result.skipped == 2
        assert result.duration_seconds == 45.7
        assert result.errors == []

    def test_batch_result_with_errors(self) -> None:
        result = BatchResult(
            processed=10,
            successful=8,
            failed=2,
            skipped=0,
            duration_seconds=12.3,
            errors=["Timeout on company 5", "404 on company 9"],
        )
        assert len(result.errors) == 2

    def test_batch_result_all_zeros(self) -> None:
        result = BatchResult(
            processed=0,
            successful=0,
            failed=0,
            skipped=0,
            duration_seconds=0.0,
        )
        assert result.processed == 0

    def test_batch_result_negative_duration_accepted(self) -> None:
        """BatchResult has no validator on duration_seconds, so negative is accepted."""
        result = BatchResult(
            processed=0,
            successful=0,
            failed=0,
            skipped=0,
            duration_seconds=-1.0,
        )
        assert result.duration_seconds == -1.0

    def test_batch_result_errors_default_empty(self) -> None:
        result = BatchResult(processed=1, successful=1, failed=0, skipped=0, duration_seconds=0.1)
        assert result.errors == []


# ===================================================================
# LLMValidationResult model tests
# ===================================================================


class TestLLMValidationResult:
    """Tests for the LLMValidationResult Pydantic model."""

    def test_valid_llm_validation_result_creation(self) -> None:
        result = LLMValidationResult(
            classification=SignificanceClassification.SIGNIFICANT,
            sentiment=SignificanceSentiment.POSITIVE,
            confidence=0.85,
            reasoning="Strong funding signal detected",
        )
        assert result.classification == SignificanceClassification.SIGNIFICANT
        assert result.confidence == 0.85
        assert result.error is None

    def test_confidence_zero_accepted(self) -> None:
        result = LLMValidationResult(
            classification=SignificanceClassification.UNCERTAIN,
            sentiment=SignificanceSentiment.NEUTRAL,
            confidence=0.0,
            reasoning="No signal",
        )
        assert result.confidence == 0.0

    def test_confidence_one_accepted(self) -> None:
        result = LLMValidationResult(
            classification=SignificanceClassification.SIGNIFICANT,
            sentiment=SignificanceSentiment.NEGATIVE,
            confidence=1.0,
            reasoning="Definitive closure notice",
        )
        assert result.confidence == 1.0

    def test_confidence_negative_rejected(self) -> None:
        with pytest.raises(ValidationError, match="confidence must be between 0.0 and 1.0"):
            LLMValidationResult(
                classification=SignificanceClassification.SIGNIFICANT,
                sentiment=SignificanceSentiment.POSITIVE,
                confidence=-0.1,
                reasoning="test",
            )

    def test_confidence_over_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LLMValidationResult(
                classification=SignificanceClassification.SIGNIFICANT,
                sentiment=SignificanceSentiment.POSITIVE,
                confidence=1.01,
                reasoning="test",
            )

    def test_validated_keywords_default_empty(self) -> None:
        result = LLMValidationResult(
            classification=SignificanceClassification.INSIGNIFICANT,
            sentiment=SignificanceSentiment.NEUTRAL,
            confidence=0.5,
            reasoning="Nothing found",
        )
        assert result.validated_keywords == []

    def test_false_positives_default_empty(self) -> None:
        result = LLMValidationResult(
            classification=SignificanceClassification.INSIGNIFICANT,
            sentiment=SignificanceSentiment.NEUTRAL,
            confidence=0.5,
            reasoning="Nothing found",
        )
        assert result.false_positives == []

    def test_error_field_populated(self) -> None:
        result = LLMValidationResult(
            classification=SignificanceClassification.UNCERTAIN,
            sentiment=SignificanceSentiment.NEUTRAL,
            confidence=0.0,
            reasoning="LLM call failed",
            error="Rate limited",
        )
        assert result.error == "Rate limited"

    def test_all_classification_sentiment_combos_accepted(self) -> None:
        """All combinations of classification and sentiment should be valid."""
        for cls_val in SignificanceClassification:
            for sent_val in SignificanceSentiment:
                result = LLMValidationResult(
                    classification=cls_val,
                    sentiment=sent_val,
                    confidence=0.5,
                    reasoning="test",
                )
                assert result.classification == cls_val
                assert result.sentiment == sent_val


# ===================================================================
# Config model tests (validator-level only, no .env)
# ===================================================================


class TestConfigValidators:
    """Tests for Config field validators called directly.

    We do NOT instantiate Config because it reads from .env.
    Instead we call the classmethod validators directly.
    """

    # -- airtable_base_id --

    def test_airtable_base_id_valid_simple(self) -> None:
        result = Config.validate_airtable_base_id("appXYZ123")
        assert result == "appXYZ123"

    def test_airtable_base_id_valid_long(self) -> None:
        result = Config.validate_airtable_base_id("appAbCdEfGhIjKlMnO")
        assert result == "appAbCdEfGhIjKlMnO"

    def test_airtable_base_id_missing_prefix_rejected(self) -> None:
        with pytest.raises(ValueError, match="airtable_base_id must match pattern"):
            Config.validate_airtable_base_id("tblXYZ123")

    def test_airtable_base_id_just_app_rejected(self) -> None:
        """'app' alone has no alphanumeric suffix -- should fail."""
        with pytest.raises(ValueError):
            Config.validate_airtable_base_id("app")

    def test_airtable_base_id_empty_rejected(self) -> None:
        with pytest.raises(ValueError):
            Config.validate_airtable_base_id("")

    def test_airtable_base_id_with_special_chars_rejected(self) -> None:
        with pytest.raises(ValueError):
            Config.validate_airtable_base_id("app-XYZ-123")

    def test_airtable_base_id_with_underscore_rejected(self) -> None:
        with pytest.raises(ValueError):
            Config.validate_airtable_base_id("app_XYZ123")

    def test_airtable_base_id_with_spaces_rejected(self) -> None:
        with pytest.raises(ValueError):
            Config.validate_airtable_base_id("app XYZ123")

    # -- log_level --

    def test_log_level_debug_accepted(self) -> None:
        assert Config.validate_log_level("DEBUG") == "DEBUG"

    def test_log_level_info_accepted(self) -> None:
        assert Config.validate_log_level("INFO") == "INFO"

    def test_log_level_warning_accepted(self) -> None:
        assert Config.validate_log_level("WARNING") == "WARNING"

    def test_log_level_error_accepted(self) -> None:
        assert Config.validate_log_level("ERROR") == "ERROR"

    def test_log_level_critical_accepted(self) -> None:
        assert Config.validate_log_level("CRITICAL") == "CRITICAL"

    def test_log_level_lowercase_accepted_and_uppercased(self) -> None:
        """Validator uppercases the value."""
        assert Config.validate_log_level("debug") == "DEBUG"

    def test_log_level_mixed_case_accepted(self) -> None:
        assert Config.validate_log_level("Info") == "INFO"

    def test_log_level_invalid_rejected(self) -> None:
        with pytest.raises(ValueError, match="log_level must be one of"):
            Config.validate_log_level("TRACE")

    def test_log_level_empty_rejected(self) -> None:
        with pytest.raises(ValueError):
            Config.validate_log_level("")

    def test_log_level_notset_rejected(self) -> None:
        """NOTSET is a valid Python level but not in the allowed set."""
        with pytest.raises(ValueError):
            Config.validate_log_level("NOTSET")

    # -- max_retry_attempts --

    def test_max_retry_attempts_zero_accepted(self) -> None:
        assert Config.validate_max_retry_attempts(0) == 0

    def test_max_retry_attempts_five_accepted(self) -> None:
        assert Config.validate_max_retry_attempts(5) == 5

    def test_max_retry_attempts_three_accepted(self) -> None:
        assert Config.validate_max_retry_attempts(3) == 3

    def test_max_retry_attempts_negative_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_retry_attempts must be between 0 and 5"):
            Config.validate_max_retry_attempts(-1)

    def test_max_retry_attempts_six_rejected(self) -> None:
        with pytest.raises(ValueError):
            Config.validate_max_retry_attempts(6)

    def test_max_retry_attempts_large_value_rejected(self) -> None:
        with pytest.raises(ValueError):
            Config.validate_max_retry_attempts(100)

    # -- airtable_api_key --

    def test_airtable_api_key_valid(self) -> None:
        result = Config.validate_airtable_api_key("pat.abc123")
        assert result == "pat.abc123"

    def test_airtable_api_key_empty_rejected(self) -> None:
        with pytest.raises(ValueError, match="airtable_api_key must not be empty"):
            Config.validate_airtable_api_key("")

    def test_airtable_api_key_whitespace_only_rejected(self) -> None:
        with pytest.raises(ValueError):
            Config.validate_airtable_api_key("   ")

    # -- firecrawl_api_key --

    def test_firecrawl_api_key_valid(self) -> None:
        result = Config.validate_firecrawl_api_key("fc-abc123")
        assert result == "fc-abc123"

    def test_firecrawl_api_key_empty_rejected(self) -> None:
        with pytest.raises(ValueError, match="firecrawl_api_key must not be empty"):
            Config.validate_firecrawl_api_key("")

    def test_firecrawl_api_key_whitespace_only_rejected(self) -> None:
        with pytest.raises(ValueError):
            Config.validate_firecrawl_api_key("   ")


# ===================================================================
# Cross-cutting / edge-case tests
# ===================================================================


class TestEdgeCases:
    """Tests that probe unusual edge cases across multiple models."""

    def test_company_name_single_char_accepted(self) -> None:
        """A single non-whitespace character is valid."""
        company = Company(name="x", source_sheet="S1")
        assert company.name == "X"  # title-cased

    def test_snapshot_all_three_content_fields_present(self) -> None:
        """Having all three content fields is fine -- at least one required."""
        snap = Snapshot(
            company_id=1,
            url="https://example.com",
            content_markdown="# hi",
            content_html="<p>hi</p>",
            error_message="partial load",
            captured_at=PAST_DATETIME,
        )
        assert snap.content_markdown is not None
        assert snap.content_html is not None
        assert snap.error_message is not None

    def test_change_record_checksums_can_be_identical(self) -> None:
        """If has_changed=False, old and new checksums may be the same."""
        kwargs = _valid_change_record_kwargs()
        kwargs["checksum_old"] = VALID_CHECKSUM
        kwargs["checksum_new"] = VALID_CHECKSUM
        kwargs["has_changed"] = False
        record = ChangeRecord(**kwargs)
        assert record.checksum_old == record.checksum_new

    def test_change_record_checksums_can_differ(self) -> None:
        kwargs = _valid_change_record_kwargs()
        kwargs["checksum_old"] = "a" * 32
        kwargs["checksum_new"] = "b" * 32
        kwargs["has_changed"] = True
        kwargs["change_magnitude"] = ChangeMagnitude.MAJOR
        record = ChangeRecord(**kwargs)
        assert record.checksum_old != record.checksum_new

    def test_snapshot_checksum_exactly_32_hex_boundary(self) -> None:
        """Test exact boundary: 32 hex chars with all valid digits."""
        kwargs = _valid_snapshot_kwargs()
        kwargs["content_checksum"] = "0123456789abcdef0123456789abcdef"
        snap = Snapshot(**kwargs)
        assert snap.content_checksum == "0123456789abcdef0123456789abcdef"

    def test_company_homepage_url_http_accepted(self) -> None:
        """HttpUrl should accept http:// URLs."""
        company = Company(name="Test", source_sheet="S1", homepage_url="http://example.com")
        assert company.homepage_url is not None

    def test_keyword_match_both_contexts_at_max(self) -> None:
        """Both context_before and context_after at exactly 50 chars."""
        match = KeywordMatch(
            keyword="layoff",
            category="negative_workforce",
            position=100,
            context_before="x" * 50,
            context_after="y" * 50,
        )
        assert len(match.context_before) == 50
        assert len(match.context_after) == 50

    def test_processing_error_entity_id_none_accepted(self) -> None:
        """entity_id is optional."""
        error = ProcessingError(
            entity_type="company",
            entity_id=None,
            error_type="ValidationError",
            error_message="Bad data",
            occurred_at=PAST_DATETIME,
        )
        assert error.entity_id is None

    def test_social_media_link_all_optional_fields_populated(self) -> None:
        """Set every optional field to verify they all work together."""
        link = SocialMediaLink(
            company_id=1,
            platform=Platform.GITHUB,
            profile_url="https://github.com/acme",
            discovery_method=DiscoveryMethod.PAGE_CONTENT,
            verification_status=VerificationStatus.LOGO_MATCHED,
            similarity_score=0.95,
            discovered_at=PAST_DATETIME,
            last_verified_at=PAST_DATETIME,
            html_location=HTMLRegion.FOOTER,
            account_type=AccountType.COMPANY,
            account_confidence=0.88,
            rejection_reason=None,
        )
        assert link.similarity_score == 0.95
        assert link.account_type == AccountType.COMPANY

    def test_company_validate_assignment_enforced(self) -> None:
        """With validate_assignment=True, modifying a field re-triggers validation."""
        company = Company(name="Test", source_sheet="S1")
        with pytest.raises(ValidationError, match="Name must not be empty"):
            company.name = "   "

    def test_company_validate_assignment_name_retitlecased(self) -> None:
        company = Company(name="Test", source_sheet="S1")
        company.name = "new name here"
        assert company.name == "New Name Here"

    def test_news_article_title_boundary_exactly_1_char(self) -> None:
        kwargs = _valid_news_article_kwargs()
        kwargs["title"] = "A"
        article = NewsArticle(**kwargs)
        assert article.title == "A"

    def test_snapshot_status_code_200_accepted(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["status_code"] = 200
        snap = Snapshot(**kwargs)
        assert snap.status_code == 200

    def test_snapshot_status_code_404_accepted(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["status_code"] = 404
        snap = Snapshot(**kwargs)
        assert snap.status_code == 404

    def test_snapshot_status_code_negative_rejected(self) -> None:
        kwargs = _valid_snapshot_kwargs()
        kwargs["status_code"] = -1
        with pytest.raises(ValidationError):
            Snapshot(**kwargs)

    def test_llm_validation_result_with_lists_populated(self) -> None:
        result = LLMValidationResult(
            classification=SignificanceClassification.SIGNIFICANT,
            sentiment=SignificanceSentiment.MIXED,
            confidence=0.72,
            reasoning="Found both positive and negative signals",
            validated_keywords=["funding", "layoffs"],
            false_positives=["talent acquisition"],
        )
        assert len(result.validated_keywords) == 2
        assert "talent acquisition" in result.false_positives

    def test_company_flag_reason_empty_string_is_falsy(self) -> None:
        """Confirm that empty string flag_reason with flagged_for_review=True fails
        because empty string is falsy in Python."""
        with pytest.raises(ValidationError):
            Company(
                name="Test",
                source_sheet="S1",
                flagged_for_review=True,
                flag_reason="",
            )

    def test_batch_result_type_coercion_int_to_float(self) -> None:
        """BatchResult does not use strict=True so int->float coercion is allowed."""
        result = BatchResult(processed=1, successful=1, failed=0, skipped=0, duration_seconds=10)
        assert result.duration_seconds == 10.0

    def test_change_record_with_all_magnitude_values(self) -> None:
        """All three magnitude values should be accepted."""
        for magnitude in ChangeMagnitude:
            kwargs = _valid_change_record_kwargs()
            kwargs["change_magnitude"] = magnitude
            record = ChangeRecord(**kwargs)
            assert record.change_magnitude == magnitude
