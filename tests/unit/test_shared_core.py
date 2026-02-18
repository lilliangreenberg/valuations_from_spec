"""Comprehensive unit tests for shared core modules.

Tests pure functions only -- no I/O, no mocking required.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from src.core.advanced_extraction import (
    extract_meta_social_handles,
    extract_schema_org_social_links,
    extract_social_links_from_regex,
)
from src.core.data_access import (
    deserialize_json_field,
    format_datetime,
    parse_datetime,
    row_to_dict,
    serialize_json_field,
)
from src.core.duplicate_resolver import deduplicate_blog_links, deduplicate_links
from src.core.link_aggregator import aggregate_links_from_pages, merge_discovery_results
from src.core.llm_prompts import (
    build_company_verification_prompt,
    build_news_significance_prompt,
    build_significance_validation_prompt,
)
from src.core.result_aggregation import aggregate_batch_results, format_batch_summary
from src.core.social_account_extractor import extract_handle
from src.core.transformers import (
    normalize_company_name,
    prepare_company_data,
    prepare_snapshot_data,
)
from src.core.validators import (
    validate_airtable_base_id,
    validate_checksum,
    validate_confidence,
    validate_not_future,
    validate_status_code,
)
from src.core.website_mapper import (
    extract_base_domain,
    group_urls_by_domain,
    is_same_domain,
    is_subdomain_of,
)

# ──────────────────────────────────────────────────────────────────────
# Module 1: transformers
# ──────────────────────────────────────────────────────────────────────


class TestPrepareSnapshotData:
    """Tests for prepare_snapshot_data."""

    def test_basic_scrape_result(self) -> None:
        result = prepare_snapshot_data(
            company_id=7,
            url="https://example.com",
            scrape_result={"markdown": "# Hello", "html": "<h1>Hello</h1>", "statusCode": 200},
        )
        assert result["company_id"] == 7
        assert result["url"] == "https://example.com"
        assert result["content_markdown"] == "# Hello"
        assert result["content_html"] == "<h1>Hello</h1>"
        assert result["status_code"] == 200
        expected_checksum = hashlib.md5(b"# Hello").hexdigest()
        assert result["content_checksum"] == expected_checksum
        assert result["captured_at"] is not None

    def test_empty_markdown_gives_none_checksum(self) -> None:
        result = prepare_snapshot_data(
            company_id=1,
            url="https://x.com",
            scrape_result={"markdown": "", "html": ""},
        )
        assert result["content_checksum"] is None
        assert result["content_markdown"] is None

    def test_none_markdown_gives_none_checksum(self) -> None:
        result = prepare_snapshot_data(
            company_id=1,
            url="https://x.com",
            scrape_result={"markdown": None},
        )
        assert result["content_checksum"] is None

    def test_missing_markdown_key(self) -> None:
        result = prepare_snapshot_data(
            company_id=1,
            url="https://x.com",
            scrape_result={},
        )
        assert result["content_checksum"] is None
        assert result["content_markdown"] is None
        assert result["content_html"] is None

    def test_status_code_from_status_code_key(self) -> None:
        result = prepare_snapshot_data(
            company_id=1,
            url="https://x.com",
            scrape_result={"status_code": 404},
        )
        assert result["status_code"] == 404

    def test_metadata_last_modified_header(self) -> None:
        result = prepare_snapshot_data(
            company_id=1,
            url="https://x.com",
            scrape_result={
                "markdown": "content",
                "metadata": {"last-modified": "Sat, 29 Oct 2024 19:43:31 GMT"},
            },
        )
        assert result["http_last_modified"] is not None
        assert "2024-10-29" in result["http_last_modified"]

    def test_metadata_last_modified_uppercase_key(self) -> None:
        result = prepare_snapshot_data(
            company_id=1,
            url="https://x.com",
            scrape_result={
                "markdown": "content",
                "metadata": {"Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT"},
            },
        )
        assert result["http_last_modified"] is not None

    def test_metadata_none_gives_no_last_modified(self) -> None:
        result = prepare_snapshot_data(
            company_id=1,
            url="https://x.com",
            scrape_result={"markdown": "x", "metadata": None},
        )
        assert result["http_last_modified"] is None

    def test_invalid_last_modified_is_ignored(self) -> None:
        result = prepare_snapshot_data(
            company_id=1,
            url="https://x.com",
            scrape_result={"markdown": "x", "metadata": {"last-modified": "not a date"}},
        )
        assert result["http_last_modified"] is None

    def test_error_field_captured(self) -> None:
        result = prepare_snapshot_data(
            company_id=1,
            url="https://x.com",
            scrape_result={"error": "timeout"},
        )
        assert result["error_message"] == "timeout"

    def test_paywall_and_auth_fields(self) -> None:
        result = prepare_snapshot_data(
            company_id=1,
            url="https://x.com",
            scrape_result={"has_paywall": True, "has_auth_required": True},
        )
        assert result["has_paywall"] is True
        assert result["has_auth_required"] is True

    def test_paywall_defaults_to_false(self) -> None:
        result = prepare_snapshot_data(
            company_id=1,
            url="https://x.com",
            scrape_result={},
        )
        assert result["has_paywall"] is False
        assert result["has_auth_required"] is False

    def test_capture_metadata_is_none(self) -> None:
        result = prepare_snapshot_data(1, "https://x.com", {})
        assert result["capture_metadata"] is None


class TestPrepareCompanyData:
    """Tests for prepare_company_data."""

    def test_basic(self) -> None:
        data = prepare_company_data("Acme Corp", "https://acme.com", "Sheet1")
        assert data["name"] == "Acme Corp"
        assert data["homepage_url"] == "https://acme.com"
        assert data["source_sheet"] == "Sheet1"
        assert data["flagged_for_review"] is False
        assert data["flag_reason"] is None
        assert data["created_at"] is not None
        assert data["updated_at"] is not None

    def test_strips_name(self) -> None:
        data = prepare_company_data("  Acme Corp  ", None, "Sheet1")
        assert data["name"] == "Acme Corp"

    def test_none_homepage(self) -> None:
        data = prepare_company_data("Test", None, "Sheet1")
        assert data["homepage_url"] is None


class TestNormalizeCompanyName:
    """Tests for normalize_company_name."""

    def test_strips_whitespace(self) -> None:
        assert normalize_company_name("  acme  ") == "Acme"

    def test_collapses_spaces(self) -> None:
        assert normalize_company_name("acme   corp   inc") == "Acme Corp Inc"

    def test_title_case(self) -> None:
        assert normalize_company_name("hello world") == "Hello World"

    def test_already_title_case(self) -> None:
        assert normalize_company_name("Acme Corp") == "Acme Corp"

    def test_all_uppercase(self) -> None:
        assert normalize_company_name("ACME CORP") == "Acme Corp"

    def test_tabs_and_newlines(self) -> None:
        assert normalize_company_name("acme\tcorp\n inc") == "Acme Corp Inc"

    def test_single_word(self) -> None:
        assert normalize_company_name("acme") == "Acme"


# ──────────────────────────────────────────────────────────────────────
# Module 2: validators
# ──────────────────────────────────────────────────────────────────────


class TestValidateChecksum:
    """Tests for validate_checksum."""

    def test_valid_lowercase_hex(self) -> None:
        assert validate_checksum("d41d8cd98f00b204e9800998ecf8427e") is True

    def test_all_zeros(self) -> None:
        assert validate_checksum("0" * 32) is True

    def test_all_fs(self) -> None:
        assert validate_checksum("f" * 32) is True

    def test_uppercase_hex_fails(self) -> None:
        assert validate_checksum("D41D8CD98F00B204E9800998ECF8427E") is False

    def test_mixed_case_fails(self) -> None:
        assert validate_checksum("d41d8cd98f00b204E9800998ecf8427e") is False

    def test_too_short(self) -> None:
        assert validate_checksum("d41d8cd98f00b204e9800998ecf8427") is False

    def test_too_long(self) -> None:
        assert validate_checksum("d41d8cd98f00b204e9800998ecf8427e0") is False

    def test_non_hex_character(self) -> None:
        assert validate_checksum("g41d8cd98f00b204e9800998ecf8427e") is False

    def test_empty_string(self) -> None:
        assert validate_checksum("") is False


class TestValidateConfidence:
    """Tests for validate_confidence."""

    def test_zero(self) -> None:
        assert validate_confidence(0.0) is True

    def test_one(self) -> None:
        assert validate_confidence(1.0) is True

    def test_midpoint(self) -> None:
        assert validate_confidence(0.5) is True

    def test_negative(self) -> None:
        assert validate_confidence(-0.01) is False

    def test_above_one(self) -> None:
        assert validate_confidence(1.01) is False

    def test_large_negative(self) -> None:
        assert validate_confidence(-100.0) is False


class TestValidateNotFuture:
    """Tests for validate_not_future."""

    def test_past_datetime(self) -> None:
        past = datetime(2020, 1, 1, tzinfo=UTC)
        assert validate_not_future(past) is True

    def test_current_datetime(self) -> None:
        now = datetime.now(UTC)
        assert validate_not_future(now) is True

    def test_near_future_within_tolerance(self) -> None:
        near_future = datetime.now(UTC) + timedelta(seconds=30)
        assert validate_not_future(near_future) is True

    def test_far_future_fails(self) -> None:
        far_future = datetime.now(UTC) + timedelta(hours=1)
        assert validate_not_future(far_future) is False

    def test_just_beyond_tolerance_fails(self) -> None:
        beyond = datetime.now(UTC) + timedelta(seconds=120)
        assert validate_not_future(beyond) is False

    def test_naive_datetime_treated_as_utc(self) -> None:
        past = datetime(2020, 1, 1)
        assert validate_not_future(past) is True


class TestValidateStatusCode:
    """Tests for validate_status_code."""

    def test_99_invalid(self) -> None:
        assert validate_status_code(99) is False

    def test_100_valid(self) -> None:
        assert validate_status_code(100) is True

    def test_200_valid(self) -> None:
        assert validate_status_code(200) is True

    def test_599_valid(self) -> None:
        assert validate_status_code(599) is True

    def test_600_invalid(self) -> None:
        assert validate_status_code(600) is False

    def test_zero_invalid(self) -> None:
        assert validate_status_code(0) is False

    def test_negative_invalid(self) -> None:
        assert validate_status_code(-1) is False


class TestValidateAirtableBaseId:
    """Tests for validate_airtable_base_id."""

    def test_valid_id(self) -> None:
        assert validate_airtable_base_id("appXYZ123abc") is True

    def test_missing_app_prefix(self) -> None:
        assert validate_airtable_base_id("XYZ123abc") is False

    def test_app_only(self) -> None:
        # Must have at least one character after 'app'
        assert validate_airtable_base_id("app") is False

    def test_special_chars_fail(self) -> None:
        assert validate_airtable_base_id("app-123") is False
        assert validate_airtable_base_id("app_123") is False

    def test_empty_string(self) -> None:
        assert validate_airtable_base_id("") is False


# ──────────────────────────────────────────────────────────────────────
# Module 3: data_access
# ──────────────────────────────────────────────────────────────────────


class TestRowToDict:
    """Tests for row_to_dict."""

    def test_none_returns_empty_dict(self) -> None:
        assert row_to_dict(None) == {}

    def test_sqlite_row(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE t (id INTEGER, name TEXT)")
        conn.execute("INSERT INTO t VALUES (1, 'test')")
        row = conn.execute("SELECT * FROM t").fetchone()
        result = row_to_dict(row)
        assert result == {"id": 1, "name": "test"}
        conn.close()

    def test_regular_dict_passthrough(self) -> None:
        # dict(dict) returns a shallow copy
        d = {"a": 1, "b": 2}
        assert row_to_dict(d) == {"a": 1, "b": 2}


class TestSerializeDeserializeJson:
    """Tests for serialize_json_field and deserialize_json_field."""

    def test_serialize_none(self) -> None:
        assert serialize_json_field(None) is None

    def test_serialize_list(self) -> None:
        result = serialize_json_field([1, 2, 3])
        assert result == "[1, 2, 3]"

    def test_serialize_dict(self) -> None:
        result = serialize_json_field({"key": "value"})
        assert result is not None
        assert '"key"' in result

    def test_deserialize_none(self) -> None:
        assert deserialize_json_field(None) == []

    def test_deserialize_valid_list(self) -> None:
        assert deserialize_json_field("[1, 2, 3]") == [1, 2, 3]

    def test_deserialize_valid_dict(self) -> None:
        assert deserialize_json_field('{"a": 1}') == {"a": 1}

    def test_deserialize_invalid_json(self) -> None:
        assert deserialize_json_field("not json at all") == []

    def test_deserialize_plain_string_json(self) -> None:
        # A JSON string literal is not a list or dict
        assert deserialize_json_field('"hello"') == []

    def test_deserialize_number_json(self) -> None:
        assert deserialize_json_field("42") == []

    def test_round_trip_list(self) -> None:
        original: list[Any] = [1, "two", {"three": 3}]
        serialized = serialize_json_field(original)
        deserialized = deserialize_json_field(serialized)
        assert deserialized == original

    def test_round_trip_dict(self) -> None:
        original: dict[str, Any] = {"nested": [1, 2]}
        serialized = serialize_json_field(original)
        deserialized = deserialize_json_field(serialized)
        assert deserialized == original

    def test_serialize_empty_list(self) -> None:
        assert serialize_json_field([]) == "[]"

    def test_deserialize_empty_list(self) -> None:
        assert deserialize_json_field("[]") == []


class TestFormatParseDatetime:
    """Tests for format_datetime and parse_datetime."""

    def test_format_none(self) -> None:
        assert format_datetime(None) is None

    def test_parse_none(self) -> None:
        assert parse_datetime(None) is None

    def test_round_trip_utc(self) -> None:
        dt = datetime(2024, 6, 15, 12, 30, 0, tzinfo=UTC)
        iso = format_datetime(dt)
        parsed = parse_datetime(iso)
        assert parsed is not None
        assert parsed == dt

    def test_naive_datetime_gets_utc(self) -> None:
        naive = datetime(2024, 1, 1, 0, 0, 0)
        iso = format_datetime(naive)
        assert iso is not None
        parsed = parse_datetime(iso)
        assert parsed is not None
        assert parsed.tzinfo is not None

    def test_parse_invalid_string(self) -> None:
        assert parse_datetime("not a date") is None

    def test_parse_empty_string(self) -> None:
        assert parse_datetime("") is None

    def test_format_with_different_timezone(self) -> None:
        eastern = timezone(timedelta(hours=-5))
        dt = datetime(2024, 6, 15, 12, 0, 0, tzinfo=eastern)
        iso = format_datetime(dt)
        assert iso is not None
        assert "-05:00" in iso

    def test_parse_naive_string_gets_utc(self) -> None:
        parsed = parse_datetime("2024-01-01T00:00:00")
        assert parsed is not None
        assert parsed.tzinfo == UTC


# ──────────────────────────────────────────────────────────────────────
# Module 4: duplicate_resolver
# ──────────────────────────────────────────────────────────────────────


class TestDeduplicateLinks:
    """Tests for deduplicate_links."""

    def test_empty_list(self) -> None:
        assert deduplicate_links([]) == []

    def test_no_duplicates(self) -> None:
        links = [
            {"profile_url": "https://twitter.com/a", "similarity_score": 0.9},
            {"profile_url": "https://twitter.com/b", "similarity_score": 0.8},
        ]
        result = deduplicate_links(links)
        assert len(result) == 2

    def test_duplicates_keep_higher_score(self) -> None:
        links = [
            {"profile_url": "https://twitter.com/a", "similarity_score": 0.5},
            {"profile_url": "https://twitter.com/a", "similarity_score": 0.9},
        ]
        result = deduplicate_links(links)
        assert len(result) == 1
        assert result[0]["similarity_score"] == 0.9

    def test_duplicates_keep_first_when_scores_equal(self) -> None:
        links = [
            {"profile_url": "https://twitter.com/a", "similarity_score": 0.5, "source": "first"},
            {"profile_url": "https://twitter.com/a", "similarity_score": 0.5, "source": "second"},
        ]
        result = deduplicate_links(links)
        assert len(result) == 1
        assert result[0]["source"] == "first"

    def test_trailing_slash_normalized(self) -> None:
        links = [
            {"profile_url": "https://twitter.com/a/", "similarity_score": 0.5},
            {"profile_url": "https://twitter.com/a", "similarity_score": 0.9},
        ]
        result = deduplicate_links(links)
        assert len(result) == 1
        assert result[0]["similarity_score"] == 0.9

    def test_case_insensitive(self) -> None:
        links = [
            {"profile_url": "https://Twitter.com/A", "similarity_score": 0.5},
            {"profile_url": "https://twitter.com/a", "similarity_score": 0.9},
        ]
        result = deduplicate_links(links)
        assert len(result) == 1

    def test_empty_url_skipped(self) -> None:
        links = [
            {"profile_url": "", "similarity_score": 0.9},
            {"profile_url": "https://twitter.com/a", "similarity_score": 0.5},
        ]
        result = deduplicate_links(links)
        assert len(result) == 1

    def test_missing_key_skipped(self) -> None:
        links = [
            {"other_field": "val"},
            {"profile_url": "https://twitter.com/a", "similarity_score": 0.5},
        ]
        result = deduplicate_links(links)
        assert len(result) == 1

    def test_none_similarity_scores(self) -> None:
        links = [
            {"profile_url": "https://twitter.com/a", "similarity_score": None},
            {"profile_url": "https://twitter.com/a", "similarity_score": 0.5},
        ]
        result = deduplicate_links(links)
        assert len(result) == 1
        assert result[0]["similarity_score"] == 0.5

    def test_custom_key_field(self) -> None:
        links = [
            {"url": "https://a.com", "similarity_score": 0.3},
            {"url": "https://a.com", "similarity_score": 0.8},
        ]
        result = deduplicate_links(links, key_field="url")
        assert len(result) == 1
        assert result[0]["similarity_score"] == 0.8


class TestDeduplicateBlogLinks:
    """Tests for deduplicate_blog_links."""

    def test_empty_list(self) -> None:
        assert deduplicate_blog_links([]) == []

    def test_no_duplicates(self) -> None:
        blogs = [
            {"blog_url": "https://blog.a.com"},
            {"blog_url": "https://blog.b.com"},
        ]
        result = deduplicate_blog_links(blogs)
        assert len(result) == 2

    def test_keeps_first_seen(self) -> None:
        blogs = [
            {"blog_url": "https://blog.a.com", "source": "first"},
            {"blog_url": "https://blog.a.com", "source": "second"},
        ]
        result = deduplicate_blog_links(blogs)
        assert len(result) == 1
        assert result[0]["source"] == "first"

    def test_trailing_slash_normalized(self) -> None:
        blogs = [
            {"blog_url": "https://blog.a.com/"},
            {"blog_url": "https://blog.a.com"},
        ]
        result = deduplicate_blog_links(blogs)
        assert len(result) == 1

    def test_case_insensitive(self) -> None:
        blogs = [
            {"blog_url": "https://Blog.A.com"},
            {"blog_url": "https://blog.a.com"},
        ]
        result = deduplicate_blog_links(blogs)
        assert len(result) == 1

    def test_empty_url_skipped(self) -> None:
        blogs: list[dict[str, Any]] = [{"blog_url": ""}]
        result = deduplicate_blog_links(blogs)
        assert len(result) == 0


# ──────────────────────────────────────────────────────────────────────
# Module 5: link_aggregator
# ──────────────────────────────────────────────────────────────────────


class TestAggregatLinksFromPages:
    """Tests for aggregate_links_from_pages."""

    def test_empty_pages(self) -> None:
        assert aggregate_links_from_pages([]) == []

    def test_single_page_single_link(self) -> None:
        pages = [{"links": [{"profile_url": "https://twitter.com/a"}]}]
        result = aggregate_links_from_pages(pages)
        assert len(result) == 1

    def test_multiple_pages_deduplicated(self) -> None:
        pages = [
            {"links": [{"profile_url": "https://twitter.com/a"}]},
            {"links": [{"profile_url": "https://twitter.com/a"}]},
        ]
        result = aggregate_links_from_pages(pages)
        assert len(result) == 1

    def test_multiple_pages_unique_links(self) -> None:
        pages = [
            {"links": [{"profile_url": "https://twitter.com/a"}]},
            {"links": [{"profile_url": "https://github.com/b"}]},
        ]
        result = aggregate_links_from_pages(pages)
        assert len(result) == 2

    def test_page_missing_links_key(self) -> None:
        pages: list[dict[str, list[dict[str, Any]]]] = [{"other": []}]  # type: ignore[dict-item]
        result = aggregate_links_from_pages(pages)
        assert len(result) == 0

    def test_trailing_slash_dedup(self) -> None:
        pages = [
            {"links": [{"profile_url": "https://twitter.com/a/"}]},
            {"links": [{"profile_url": "https://twitter.com/a"}]},
        ]
        result = aggregate_links_from_pages(pages)
        assert len(result) == 1

    def test_empty_profile_url_skipped(self) -> None:
        pages = [{"links": [{"profile_url": ""}]}]
        result = aggregate_links_from_pages(pages)
        assert len(result) == 0


class TestMergeDiscoveryResults:
    """Tests for merge_discovery_results."""

    def test_empty_both(self) -> None:
        assert merge_discovery_results([], []) == []

    def test_new_links_added(self) -> None:
        existing: list[dict[str, Any]] = []
        new = [{"profile_url": "https://twitter.com/x", "similarity_score": 0.8}]
        result = merge_discovery_results(existing, new)
        assert len(result) == 1

    def test_new_wins_if_higher_score(self) -> None:
        existing = [{"profile_url": "https://twitter.com/x", "similarity_score": 0.5}]
        new = [{"profile_url": "https://twitter.com/x", "similarity_score": 0.9}]
        result = merge_discovery_results(existing, new)
        assert len(result) == 1
        assert result[0]["similarity_score"] == 0.9

    def test_existing_kept_if_higher_score(self) -> None:
        existing = [{"profile_url": "https://twitter.com/x", "similarity_score": 0.9}]
        new = [{"profile_url": "https://twitter.com/x", "similarity_score": 0.3}]
        result = merge_discovery_results(existing, new)
        assert len(result) == 1
        assert result[0]["similarity_score"] == 0.9

    def test_merge_distinct_urls(self) -> None:
        existing = [{"profile_url": "https://twitter.com/a", "similarity_score": 0.9}]
        new = [{"profile_url": "https://github.com/b", "similarity_score": 0.8}]
        result = merge_discovery_results(existing, new)
        assert len(result) == 2


# ──────────────────────────────────────────────────────────────────────
# Module 6: result_aggregation
# ──────────────────────────────────────────────────────────────────────


class TestAggregateBatchResults:
    """Tests for aggregate_batch_results."""

    def test_empty_results(self) -> None:
        result = aggregate_batch_results([])
        assert result["processed"] == 0
        assert result["successful"] == 0
        assert result["failed"] == 0
        assert result["skipped"] == 0
        assert result["errors"] == []

    def test_single_result(self) -> None:
        results = [{"processed": 10, "successful": 8, "failed": 1, "skipped": 1, "errors": ["e1"]}]
        result = aggregate_batch_results(results)
        assert result["processed"] == 10
        assert result["successful"] == 8
        assert result["failed"] == 1
        assert result["skipped"] == 1
        assert result["errors"] == ["e1"]

    def test_multiple_results_summed(self) -> None:
        results = [
            {"processed": 10, "successful": 8, "failed": 1, "skipped": 1, "errors": ["e1"]},
            {"processed": 5, "successful": 4, "failed": 1, "skipped": 0, "errors": ["e2"]},
        ]
        result = aggregate_batch_results(results)
        assert result["processed"] == 15
        assert result["successful"] == 12
        assert result["failed"] == 2
        assert result["skipped"] == 1
        assert result["errors"] == ["e1", "e2"]

    def test_missing_keys_default_to_zero(self) -> None:
        results: list[dict[str, Any]] = [{}]
        result = aggregate_batch_results(results)
        assert result["processed"] == 0
        assert result["errors"] == []


# ──────────────────────────────────────────────────────────────────────
# Module 7: website_mapper
# ──────────────────────────────────────────────────────────────────────


class TestFormatBatchSummary:
    """Tests for format_batch_summary."""

    def test_basic_summary(self) -> None:
        stats: dict[str, Any] = {
            "processed": 10,
            "successful": 8,
            "failed": 1,
            "skipped": 1,
            "errors": [],
        }
        summary = format_batch_summary(stats)
        assert "Processed: 10" in summary
        assert "Successful: 8" in summary
        assert "Failed: 1" in summary
        assert "Skipped: 1" in summary

    def test_summary_with_errors(self) -> None:
        stats: dict[str, Any] = {
            "processed": 2,
            "successful": 1,
            "failed": 1,
            "skipped": 0,
            "errors": ["oops"],
        }
        summary = format_batch_summary(stats)
        assert "Errors (1):" in summary
        assert "oops" in summary

    def test_summary_truncates_over_10_errors(self) -> None:
        errors = [f"error_{i}" for i in range(15)]
        stats: dict[str, Any] = {
            "processed": 15,
            "successful": 0,
            "failed": 15,
            "skipped": 0,
            "errors": errors,
        }
        summary = format_batch_summary(stats)
        assert "... and 5 more" in summary
        assert "error_0" in summary
        assert "error_9" in summary
        # error_10 through error_14 should not be individually listed
        assert "error_10" not in summary

    def test_empty_stats(self) -> None:
        summary = format_batch_summary({})
        assert "Processed: 0" in summary


class TestExtractBaseDomain:
    """Tests for extract_base_domain."""

    def test_simple_url(self) -> None:
        assert extract_base_domain("https://example.com/page") == "example.com"

    def test_www_removed(self) -> None:
        assert extract_base_domain("https://www.example.com") == "example.com"

    def test_subdomain_removed(self) -> None:
        assert extract_base_domain("https://blog.example.com") == "example.com"

    def test_deep_subdomain(self) -> None:
        assert extract_base_domain("https://a.b.c.example.com") == "example.com"

    def test_co_uk_handling(self) -> None:
        # The implementation takes last two parts, so co.uk domains
        # return "co.uk" (not ideal but that is how it works)
        result = extract_base_domain("https://www.example.co.uk")
        assert result == "co.uk"

    def test_no_scheme(self) -> None:
        # urlparse with no scheme puts everything in path
        result = extract_base_domain("example.com")
        assert result == ""  # netloc is empty without scheme


class TestIsSameDomain:
    """Tests for is_same_domain."""

    def test_same_domain(self) -> None:
        assert is_same_domain("https://example.com/a", "https://example.com/b") is True

    def test_different_subdomains_same_base(self) -> None:
        assert is_same_domain("https://blog.example.com", "https://www.example.com") is True

    def test_different_domains(self) -> None:
        assert is_same_domain("https://example.com", "https://other.com") is False


class TestIsSubdomainOf:
    """Tests for is_subdomain_of."""

    def test_exact_match(self) -> None:
        assert is_subdomain_of("https://example.com", "example.com") is True

    def test_subdomain_match(self) -> None:
        assert is_subdomain_of("https://blog.example.com", "example.com") is True

    def test_not_subdomain(self) -> None:
        assert is_subdomain_of("https://notexample.com", "example.com") is False

    def test_www_is_subdomain(self) -> None:
        assert is_subdomain_of("https://www.example.com", "example.com") is True


class TestGroupUrlsByDomain:
    """Tests for group_urls_by_domain."""

    def test_empty_list(self) -> None:
        assert group_urls_by_domain([]) == {}

    def test_single_domain(self) -> None:
        urls = ["https://example.com/a", "https://example.com/b"]
        groups = group_urls_by_domain(urls)
        assert len(groups) == 1
        assert len(groups["example.com"]) == 2

    def test_multiple_domains(self) -> None:
        urls = ["https://a.com/1", "https://b.com/2", "https://a.com/3"]
        groups = group_urls_by_domain(urls)
        assert len(groups) == 2
        assert len(groups["a.com"]) == 2
        assert len(groups["b.com"]) == 1


# ──────────────────────────────────────────────────────────────────────
# Module 8: social_account_extractor
# ──────────────────────────────────────────────────────────────────────


class TestExtractHandle:
    """Tests for extract_handle."""

    def test_linkedin_company(self) -> None:
        assert extract_handle("https://linkedin.com/company/acme-corp") == "acme-corp"

    def test_linkedin_personal(self) -> None:
        assert extract_handle("https://linkedin.com/in/jdoe") == "jdoe"

    def test_linkedin_www(self) -> None:
        assert extract_handle("https://www.linkedin.com/company/acme") == "acme"

    def test_twitter(self) -> None:
        assert extract_handle("https://twitter.com/acmecorp") == "acmecorp"

    def test_twitter_with_at(self) -> None:
        assert extract_handle("https://twitter.com/@acmecorp") == "acmecorp"

    def test_x_dot_com(self) -> None:
        assert extract_handle("https://x.com/acmecorp") == "acmecorp"

    def test_youtube_at_handle(self) -> None:
        assert extract_handle("https://youtube.com/@acmecorp") == "acmecorp"

    def test_youtube_channel(self) -> None:
        assert extract_handle("https://youtube.com/channel/UCabc123") == "UCabc123"

    def test_youtube_c_handle(self) -> None:
        assert extract_handle("https://youtube.com/c/acmecorp") == "acmecorp"

    def test_youtube_user(self) -> None:
        assert extract_handle("https://youtube.com/user/acmevideos") == "acmevideos"

    def test_github(self) -> None:
        assert extract_handle("https://github.com/acme-corp") == "acme-corp"

    def test_instagram(self) -> None:
        assert extract_handle("https://instagram.com/acme") == "acme"

    def test_facebook(self) -> None:
        assert extract_handle("https://facebook.com/acme") == "acme"

    def test_fb_dot_com(self) -> None:
        assert extract_handle("https://fb.com/acme") == "acme"

    def test_tiktok(self) -> None:
        assert extract_handle("https://tiktok.com/@acmeofficial") == "acmeofficial"

    def test_medium_at_user(self) -> None:
        assert extract_handle("https://medium.com/@acmeauthor") == "acmeauthor"

    def test_medium_subdomain(self) -> None:
        # The medium.com subdomain branch is unreachable when the netloc contains
        # "medium.com", because the "if medium.com in netloc" branch matches first.
        # When path_parts[0] does not start with @, it falls through to the generic
        # return which returns the first path part.
        assert extract_handle("https://acme.medium.com/article") == "article"

    def test_bluesky(self) -> None:
        assert extract_handle("https://bsky.app/profile/acme.bsky.social") == "acme.bsky.social"

    def test_threads(self) -> None:
        assert extract_handle("https://threads.net/@acmeofficial") == "acmeofficial"

    def test_mastodon(self) -> None:
        assert extract_handle("https://mastodon.social/@acme") == "acme"

    def test_pinterest(self) -> None:
        assert extract_handle("https://pinterest.com/acmepins") == "acmepins"

    def test_no_path_returns_none(self) -> None:
        assert extract_handle("https://twitter.com") is None
        assert extract_handle("https://twitter.com/") is None

    def test_unknown_domain_returns_first_path(self) -> None:
        result = extract_handle("https://unknownsite.com/myhandle")
        assert result == "myhandle"


# ──────────────────────────────────────────────────────────────────────
# Module 9: llm_prompts
# ──────────────────────────────────────────────────────────────────────


class TestBuildSignificanceValidationPrompt:
    """Tests for build_significance_validation_prompt."""

    def test_returns_tuple(self) -> None:
        system, user = build_significance_validation_prompt(
            content_excerpt="company raised $10M",
            keywords=["raised", "funding"],
            categories=["funding"],
            initial_classification="significant",
            magnitude="MAJOR",
        )
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_content_in_user_prompt(self) -> None:
        _, user = build_significance_validation_prompt(
            content_excerpt="company raised $10M",
            keywords=["raised"],
            categories=["funding"],
            initial_classification="significant",
            magnitude="MAJOR",
        )
        assert "company raised $10M" in user
        assert "raised" in user
        assert "funding" in user
        assert "significant" in user
        assert "MAJOR" in user

    def test_system_prompt_mentions_vc(self) -> None:
        system, _ = build_significance_validation_prompt(
            content_excerpt="x",
            keywords=[],
            categories=[],
            initial_classification="uncertain",
            magnitude="MINOR",
        )
        assert "venture capital" in system.lower()

    def test_content_truncated_to_2000(self) -> None:
        long_content = "x" * 5000
        _, user = build_significance_validation_prompt(
            content_excerpt=long_content,
            keywords=[],
            categories=[],
            initial_classification="uncertain",
            magnitude="MINOR",
        )
        # The truncated content should appear, but not the full 5000 chars
        assert "x" * 2000 in user
        assert "x" * 2001 not in user

    def test_empty_keywords(self) -> None:
        _, user = build_significance_validation_prompt(
            content_excerpt="text",
            keywords=[],
            categories=[],
            initial_classification="uncertain",
            magnitude="MINOR",
        )
        assert "Detected keywords:" in user


class TestBuildNewsSignificancePrompt:
    """Tests for build_news_significance_prompt."""

    def test_returns_tuple(self) -> None:
        system, user = build_news_significance_prompt(
            title="Acme raises $50M",
            source="techcrunch.com",
            content="Acme Corp announced...",
            keywords=["raises", "funding"],
            company_name="Acme Corp",
        )
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_all_fields_present_in_user_prompt(self) -> None:
        _, user = build_news_significance_prompt(
            title="Big News",
            source="reuters.com",
            content="The company announced...",
            keywords=["announced"],
            company_name="Test Inc",
        )
        assert "Big News" in user
        assert "reuters.com" in user
        assert "The company announced..." in user
        assert "announced" in user
        assert "Test Inc" in user

    def test_content_truncated_to_2000(self) -> None:
        long_content = "a" * 4000
        _, user = build_news_significance_prompt(
            title="T",
            source="S",
            content=long_content,
            keywords=[],
            company_name="C",
        )
        assert "a" * 2000 in user
        assert "a" * 2001 not in user


class TestBuildCompanyVerificationPrompt:
    """Tests for build_company_verification_prompt."""

    def test_returns_tuple(self) -> None:
        system, user = build_company_verification_prompt(
            company_name="Acme",
            company_url="https://acme.com",
            article_title="Acme raises funding",
            article_source="techcrunch.com",
            article_snippet="Acme Corp today announced...",
        )
        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_fields_in_user_prompt(self) -> None:
        _, user = build_company_verification_prompt(
            company_name="Acme",
            company_url="https://acme.com",
            article_title="Funding round",
            article_source="bloomberg.com",
            article_snippet="Details here",
        )
        assert "Acme" in user
        assert "https://acme.com" in user
        assert "Funding round" in user
        assert "bloomberg.com" in user
        assert "Details here" in user

    def test_snippet_truncated_to_1000(self) -> None:
        long_snippet = "b" * 2000
        _, user = build_company_verification_prompt(
            company_name="X",
            company_url="https://x.com",
            article_title="T",
            article_source="S",
            article_snippet=long_snippet,
        )
        assert "b" * 1000 in user
        assert "b" * 1001 not in user

    def test_system_prompt_mentions_verification(self) -> None:
        system, _ = build_company_verification_prompt(
            company_name="X",
            company_url="https://x.com",
            article_title="T",
            article_source="S",
            article_snippet="snip",
        )
        assert "verif" in system.lower()


# ──────────────────────────────────────────────────────────────────────
# Module 10: advanced_extraction
# ──────────────────────────────────────────────────────────────────────


class TestExtractSchemaOrgSocialLinks:
    """Tests for extract_schema_org_social_links."""

    def test_single_same_as_string(self) -> None:
        html = """<script type="application/ld+json">
        {"@type": "Organization", "sameAs": "https://twitter.com/acme"}
        </script>"""
        result = extract_schema_org_social_links(html)
        assert "https://twitter.com/acme" in result

    def test_same_as_list(self) -> None:
        html = """<script type="application/ld+json">
        {"@type": "Organization", "sameAs": [
            "https://twitter.com/acme",
            "https://linkedin.com/company/acme"
        ]}
        </script>"""
        result = extract_schema_org_social_links(html)
        assert len(result) >= 2
        assert "https://twitter.com/acme" in result
        assert "https://linkedin.com/company/acme" in result

    def test_nested_json_ld(self) -> None:
        html = """<script type="application/ld+json">
        {"@graph": [
            {"@type": "Organization", "sameAs": "https://github.com/acme"}
        ]}
        </script>"""
        result = extract_schema_org_social_links(html)
        assert "https://github.com/acme" in result

    def test_invalid_json_ignored(self) -> None:
        html = """<script type="application/ld+json">not valid json</script>"""
        result = extract_schema_org_social_links(html)
        assert result == []

    def test_no_script_tags(self) -> None:
        html = "<html><body><p>No schema</p></body></html>"
        result = extract_schema_org_social_links(html)
        assert result == []

    def test_non_http_urls_excluded(self) -> None:
        html = """<script type="application/ld+json">
        {"sameAs": ["ftp://example.com", "https://twitter.com/a"]}
        </script>"""
        result = extract_schema_org_social_links(html)
        assert len(result) == 1
        assert "https://twitter.com/a" in result

    def test_empty_html(self) -> None:
        assert extract_schema_org_social_links("") == []

    def test_multiple_script_blocks(self) -> None:
        html = """
        <script type="application/ld+json">
        {"sameAs": "https://twitter.com/a"}
        </script>
        <script type="application/ld+json">
        {"sameAs": "https://github.com/b"}
        </script>"""
        result = extract_schema_org_social_links(html)
        assert len(result) == 2


class TestExtractMetaSocialHandles:
    """Tests for extract_meta_social_handles."""

    def test_twitter_site_with_at(self) -> None:
        html = '<html><head><meta name="twitter:site" content="@acme"></head></html>'
        result = extract_meta_social_handles(html)
        assert len(result) == 1
        assert result[0][0] == "twitter"
        assert "acme" in result[0][1]

    def test_twitter_site_url(self) -> None:
        html = (
            "<html><head>"
            '<meta name="twitter:site" content="https://twitter.com/acme">'
            "</head></html>"
        )
        result = extract_meta_social_handles(html)
        assert len(result) == 1
        assert result[0][1] == "https://twitter.com/acme"

    def test_twitter_creator(self) -> None:
        html = '<html><head><meta name="twitter:creator" content="@author"></head></html>'
        result = extract_meta_social_handles(html)
        assert len(result) == 1
        assert "author" in result[0][1]

    def test_both_site_and_creator(self) -> None:
        html = """<html><head>
        <meta name="twitter:site" content="@acme">
        <meta name="twitter:creator" content="@author">
        </head></html>"""
        result = extract_meta_social_handles(html)
        assert len(result) == 2

    def test_no_meta_tags(self) -> None:
        html = "<html><head></head><body></body></html>"
        assert extract_meta_social_handles(html) == []

    def test_empty_content_attribute(self) -> None:
        html = '<html><head><meta name="twitter:site" content=""></head></html>'
        assert extract_meta_social_handles(html) == []


class TestExtractSocialLinksFromRegex:
    """Tests for extract_social_links_from_regex."""

    def test_finds_twitter_url(self) -> None:
        html = '<a href="https://twitter.com/acmecorp">Follow us</a>'
        result = extract_social_links_from_regex(html)
        assert any("twitter.com/acmecorp" in u for u in result)

    def test_finds_linkedin_url(self) -> None:
        html = "Visit https://www.linkedin.com/company/acme for more info"
        result = extract_social_links_from_regex(html)
        assert any("linkedin.com/company/acme" in u for u in result)

    def test_finds_github_url(self) -> None:
        html = '<a href="https://github.com/acme-corp">GitHub</a>'
        result = extract_social_links_from_regex(html)
        assert any("github.com/acme-corp" in u for u in result)

    def test_finds_bsky_url(self) -> None:
        html = "Check https://bsky.app/profile/acme.bsky.social"
        result = extract_social_links_from_regex(html)
        assert any("bsky.app/profile/acme.bsky.social" in u for u in result)

    def test_deduplicates(self) -> None:
        html = """
        <a href="https://twitter.com/acme">1</a>
        <a href="https://twitter.com/acme">2</a>
        """
        result = extract_social_links_from_regex(html)
        twitter_urls = [u for u in result if "twitter.com/acme" in u]
        assert len(twitter_urls) == 1

    def test_empty_html(self) -> None:
        assert extract_social_links_from_regex("") == []

    def test_no_social_links(self) -> None:
        html = '<a href="https://example.com">Not social</a>'
        assert extract_social_links_from_regex(html) == []

    def test_multiple_platforms(self) -> None:
        html = """
        <a href="https://twitter.com/a">T</a>
        <a href="https://github.com/b">G</a>
        <a href="https://instagram.com/c">I</a>
        """
        result = extract_social_links_from_regex(html)
        assert len(result) == 3

    def test_strips_trailing_punctuation(self) -> None:
        html = "Visit https://twitter.com/acme)."
        result = extract_social_links_from_regex(html)
        assert any(u.endswith("acme") for u in result)
