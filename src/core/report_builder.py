"""Pure functions for building structured JSON reports from command results.

Each build_*_report function takes the raw service result dict (which includes
report_details populated by the service) plus config metadata, and returns a
report dict matching the approved JSON schema in docs/example_reports/.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any


def _timestamp() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_capture_snapshots_report(
    result: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Build report for capture-snapshots command.

    Only includes failed and skipped companies (not the full success list).
    """
    details = result.get("report_details", {})

    return {
        "command": "capture-snapshots",
        "timestamp": _timestamp(),
        "config": config,
        "summary": {
            "total_companies": result.get("processed", 0) + result.get("skipped", 0),
            "processed": result.get("processed", 0),
            "successful": result.get("successful", 0),
            "failed": result.get("failed", 0),
            "skipped": result.get("skipped", 0),
            "duration_seconds": result.get("duration_seconds", 0.0),
        },
        "companies": {
            "failed": details.get("failed", []),
            "skipped": details.get("skipped", []),
        },
    }


def build_detect_changes_report(
    result: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Build report for detect-changes command.

    Includes per-company detail for changed companies, plus breakdowns.
    """
    details = result.get("report_details", {})
    changed = details.get("changed", [])
    status_changes = details.get("status_changes", [])

    significance_counts: Counter[str] = Counter()
    sentiment_counts: Counter[str] = Counter()
    magnitude_counts: Counter[str] = Counter()

    for company in changed:
        significance_counts[company.get("significance", "unknown")] += 1
        sentiment_counts[company.get("sentiment", "unknown")] += 1
        magnitude_counts[company.get("change_magnitude", "unknown")] += 1

    return {
        "command": "detect-changes",
        "timestamp": _timestamp(),
        "config": config,
        "summary": {
            "total_companies": result.get("processed", 0) + result.get("skipped", 0),
            "processed": result.get("processed", 0),
            "successful": result.get("successful", 0),
            "failed": result.get("failed", 0),
            "skipped": result.get("skipped", 0),
            "changes_found": result.get("changes_found", 0),
            "no_change": (result.get("successful", 0) - result.get("changes_found", 0)),
            "status_changes": len(status_changes),
            "duration_seconds": result.get("duration_seconds", 0.0),
        },
        "significance_breakdown": {
            "significant": significance_counts.get("significant", 0),
            "insignificant": significance_counts.get("insignificant", 0),
            "uncertain": significance_counts.get("uncertain", 0),
        },
        "sentiment_breakdown": {
            "positive": sentiment_counts.get("positive", 0),
            "negative": sentiment_counts.get("negative", 0),
            "mixed": sentiment_counts.get("mixed", 0),
            "neutral": sentiment_counts.get("neutral", 0),
        },
        "magnitude_breakdown": {
            "major": magnitude_counts.get("major", 0),
            "moderate": magnitude_counts.get("moderate", 0),
            "minor": magnitude_counts.get("minor", 0),
        },
        "companies": {
            "changed": changed,
            "status_changes": status_changes,
            "failed": details.get("failed", []),
            "skipped": details.get("skipped", []),
        },
    }


def build_discover_social_media_report(
    result: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Build report for discover-social-media command.

    Includes per-company social links/blogs for all discovered companies,
    plus aggregate platform and blog type breakdowns.
    """
    details = result.get("report_details", {})
    discovered = details.get("discovered", [])

    platform_counts: Counter[str] = Counter()
    blog_type_counts: Counter[str] = Counter()

    for company in discovered:
        for link in company.get("social_links", []):
            platform_counts[link.get("platform", "unknown")] += 1
        for blog in company.get("blogs", []):
            blog_type_counts[blog.get("blog_type", "unknown")] += 1

    return {
        "command": "discover-social-media",
        "timestamp": _timestamp(),
        "config": config,
        "summary": {
            "total_companies": result.get("processed", 0) + result.get("skipped", 0),
            "processed": result.get("processed", 0),
            "successful": result.get("successful", 0),
            "failed": result.get("failed", 0),
            "skipped": result.get("skipped", 0),
            "total_links_found": result.get("total_links_found", 0),
            "total_blogs_found": result.get("total_blogs_found", 0),
            "duration_seconds": result.get("duration_seconds", 0.0),
        },
        "platform_breakdown": dict(platform_counts.most_common()),
        "blog_type_breakdown": dict(blog_type_counts.most_common()),
        "companies": {
            "no_links_found": details.get("no_links_found", []),
            "failed": details.get("failed", []),
            "skipped": details.get("skipped", []),
            "discovered": discovered,
        },
    }


def build_extract_leadership_report(
    result: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Build report for extract-leadership-all command.

    Includes per-company leader lists, change detection, and method breakdown.
    """
    details = result.get("report_details", {})
    extracted = details.get("extracted", [])
    critical_changes = result.get("critical_changes", [])

    method_counts: Counter[str] = Counter()
    change_severity_counts: Counter[str] = Counter()
    total_changes = 0

    for company in extracted:
        method_counts[company.get("method_used", "unknown")] += 1
        for change in company.get("leadership_changes", []):
            change_severity_counts[change.get("severity", "unknown")] += 1
            total_changes += 1

    return {
        "command": "extract-leadership-all",
        "timestamp": _timestamp(),
        "config": config,
        "summary": {
            "total_companies": result.get("processed", 0) + result.get("skipped", 0),
            "processed": result.get("processed", 0),
            "successful": result.get("successful", 0),
            "failed": result.get("failed", 0),
            "skipped": result.get("skipped", 0),
            "total_leaders_found": result.get("total_leaders_found", 0),
            "duration_seconds": result.get("duration_seconds", 0.0),
        },
        "method_breakdown": dict(method_counts.most_common()),
        "critical_changes": critical_changes,
        "change_summary": {
            "total_changes_detected": total_changes,
            "critical": change_severity_counts.get("critical", 0),
            "notable": change_severity_counts.get("notable", 0),
            "minor": change_severity_counts.get("minor", 0),
        },
        "companies": {
            "extracted": extracted,
            "failed": details.get("failed", []),
            "skipped": details.get("skipped", []),
        },
    }


def build_capture_social_snapshots_report(
    result: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Build report for capture-social-snapshots command.

    Only includes failed and skipped (not the full success list).
    """
    details = result.get("report_details", {})
    captured = details.get("captured", [])

    source_type_counts: Counter[str] = Counter()
    for item in captured:
        for source in item.get("sources", []):
            source_type_counts[source.get("source_type", "unknown")] += 1

    return {
        "command": "capture-social-snapshots",
        "timestamp": _timestamp(),
        "config": config,
        "summary": {
            "total_urls": result.get("total", 0),
            "captured": result.get("captured", 0),
            "failed": result.get("failed", 0),
            "skipped": result.get("skipped", 0),
            "duration_seconds": result.get("duration_seconds", 0.0),
        },
        "source_type_breakdown": dict(source_type_counts.most_common()),
        "companies": {
            "failed": details.get("failed", []),
            "skipped": details.get("skipped", []),
        },
    }


def build_detect_social_changes_report(
    result: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Build report for detect-social-changes command.

    Includes per-source detail for changed sources, plus breakdowns.
    """
    details = result.get("report_details", {})
    changed = details.get("changed", [])

    significance_counts: Counter[str] = Counter()
    sentiment_counts: Counter[str] = Counter()
    magnitude_counts: Counter[str] = Counter()
    source_type_counts: Counter[str] = Counter()

    for source in changed:
        significance_counts[source.get("significance", "unknown")] += 1
        sentiment_counts[source.get("sentiment", "unknown")] += 1
        magnitude_counts[source.get("change_magnitude", "unknown")] += 1
        source_type_counts[source.get("source_type", "unknown")] += 1

    return {
        "command": "detect-social-changes",
        "timestamp": _timestamp(),
        "config": config,
        "summary": {
            "total_sources": result.get("processed", 0) + result.get("skipped", 0),
            "processed": result.get("processed", 0),
            "successful": result.get("successful", 0),
            "failed": result.get("failed", 0),
            "skipped": result.get("skipped", 0),
            "changes_found": result.get("changes_found", 0),
            "no_change": (result.get("successful", 0) - result.get("changes_found", 0)),
            "duration_seconds": result.get("duration_seconds", 0.0),
        },
        "significance_breakdown": {
            "significant": significance_counts.get("significant", 0),
            "insignificant": significance_counts.get("insignificant", 0),
            "uncertain": significance_counts.get("uncertain", 0),
        },
        "sentiment_breakdown": {
            "positive": sentiment_counts.get("positive", 0),
            "negative": sentiment_counts.get("negative", 0),
            "mixed": sentiment_counts.get("mixed", 0),
            "neutral": sentiment_counts.get("neutral", 0),
        },
        "magnitude_breakdown": {
            "major": magnitude_counts.get("major", 0),
            "moderate": magnitude_counts.get("moderate", 0),
            "minor": magnitude_counts.get("minor", 0),
        },
        "source_type_breakdown": dict(source_type_counts.most_common()),
        "companies": {
            "changed": changed,
            "failed": details.get("failed", []),
            "skipped": details.get("skipped", []),
        },
    }


def build_search_news_report(
    result: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Build report for search-news-all command.

    Includes per-company article lists with significance data.
    """
    details = result.get("report_details", {})
    with_news = details.get("with_news", [])

    significance_counts: Counter[str] = Counter()
    sentiment_counts: Counter[str] = Counter()

    for company in with_news:
        for article in company.get("articles", []):
            significance_counts[article.get("significance", "unknown")] += 1
            sentiment_counts[article.get("sentiment", "unknown")] += 1

    return {
        "command": "search-news-all",
        "timestamp": _timestamp(),
        "config": config,
        "summary": {
            "total_companies": result.get("processed", 0) + result.get("skipped", 0),
            "processed": result.get("processed", 0),
            "successful": result.get("successful", 0),
            "failed": result.get("failed", 0),
            "skipped": result.get("skipped", 0),
            "total_articles_found": result.get("total_found", 0),
            "total_articles_verified": result.get("total_verified", 0),
            "total_articles_stored": result.get("total_stored", 0),
            "total_duplicates_skipped": (
                result.get("total_verified", 0) - result.get("total_stored", 0)
            ),
            "duration_seconds": result.get("duration_seconds", 0.0),
        },
        "significance_breakdown": {
            "significant": significance_counts.get("significant", 0),
            "insignificant": significance_counts.get("insignificant", 0),
            "uncertain": significance_counts.get("uncertain", 0),
        },
        "sentiment_breakdown": {
            "positive": sentiment_counts.get("positive", 0),
            "negative": sentiment_counts.get("negative", 0),
            "mixed": sentiment_counts.get("mixed", 0),
            "neutral": sentiment_counts.get("neutral", 0),
        },
        "companies": {
            "with_news": with_news,
            "failed": details.get("failed", []),
            "skipped": details.get("skipped", []),
        },
    }
