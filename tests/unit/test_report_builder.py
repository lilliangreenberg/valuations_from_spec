"""Unit tests for report builder pure functions."""

from __future__ import annotations

from typing import Any

from src.core.report_builder import (
    build_capture_snapshots_report,
    build_capture_social_snapshots_report,
    build_detect_changes_report,
    build_detect_social_changes_report,
    build_discover_social_media_report,
    build_extract_leadership_report,
    build_search_news_report,
)


def _base_tracker_result(
    processed: int = 10,
    successful: int = 8,
    failed: int = 1,
    skipped: int = 1,
    duration: float = 42.5,
) -> dict[str, Any]:
    """Build a minimal ProgressTracker-style result dict."""
    return {
        "processed": processed,
        "successful": successful,
        "failed": failed,
        "skipped": skipped,
        "duration_seconds": duration,
        "errors": ["test error"],
    }


class TestBuildCaptureSnapshotsReport:
    """Tests for build_capture_snapshots_report."""

    def test_basic_structure(self) -> None:
        result = _base_tracker_result()
        result["report_details"] = {
            "failed": [
                {
                    "company_id": 1,
                    "name": "FailCo",
                    "homepage_url": "https://fail.co",
                    "error": "timeout",
                }
            ],
            "skipped": [
                {"company_id": 2, "name": "SkipCo", "reason": "no_homepage_url"}
            ],
        }

        report = build_capture_snapshots_report(result, {"mode": "batch", "batch_size": 50})

        assert report["command"] == "capture-snapshots"
        assert "timestamp" in report
        assert report["config"]["mode"] == "batch"
        assert report["summary"]["total_companies"] == 11  # processed + skipped
        assert report["summary"]["successful"] == 8
        assert report["summary"]["failed"] == 1
        assert report["summary"]["skipped"] == 1
        assert report["summary"]["duration_seconds"] == 42.5
        assert len(report["companies"]["failed"]) == 1
        assert len(report["companies"]["skipped"]) == 1
        assert report["companies"]["failed"][0]["name"] == "FailCo"

    def test_empty_details(self) -> None:
        result = _base_tracker_result(processed=5, successful=5, failed=0, skipped=0)
        result["report_details"] = {"failed": [], "skipped": []}

        report = build_capture_snapshots_report(result, {})

        assert report["companies"]["failed"] == []
        assert report["companies"]["skipped"] == []

    def test_missing_report_details(self) -> None:
        result = _base_tracker_result()
        # No report_details key at all
        report = build_capture_snapshots_report(result, {})
        assert report["companies"]["failed"] == []
        assert report["companies"]["skipped"] == []


class TestBuildDetectChangesReport:
    """Tests for build_detect_changes_report."""

    def test_breakdowns_computed_from_changed(self) -> None:
        result = _base_tracker_result(processed=10, successful=10, failed=0, skipped=0)
        result["changes_found"] = 3
        result["report_details"] = {
            "changed": [
                {
                    "company_id": 1,
                    "name": "A",
                    "homepage_url": "https://a.com",
                    "change_magnitude": "major",
                    "significance": "significant",
                    "sentiment": "positive",
                    "confidence": 0.9,
                    "matched_keywords": ["funding"],
                    "matched_categories": ["funding"],
                    "significance_notes": "",
                },
                {
                    "company_id": 2,
                    "name": "B",
                    "homepage_url": "https://b.com",
                    "change_magnitude": "minor",
                    "significance": "insignificant",
                    "sentiment": "neutral",
                    "confidence": 0.8,
                    "matched_keywords": [],
                    "matched_categories": [],
                    "significance_notes": "",
                },
                {
                    "company_id": 3,
                    "name": "C",
                    "homepage_url": "https://c.com",
                    "change_magnitude": "moderate",
                    "significance": "significant",
                    "sentiment": "negative",
                    "confidence": 0.85,
                    "matched_keywords": ["layoffs"],
                    "matched_categories": ["layoffs"],
                    "significance_notes": "",
                },
            ],
            "failed": [],
            "skipped": [],
        }

        report = build_detect_changes_report(result, {"limit": None})

        assert report["summary"]["changes_found"] == 3
        assert report["summary"]["no_change"] == 7
        assert report["significance_breakdown"]["significant"] == 2
        assert report["significance_breakdown"]["insignificant"] == 1
        assert report["sentiment_breakdown"]["positive"] == 1
        assert report["sentiment_breakdown"]["negative"] == 1
        assert report["magnitude_breakdown"]["major"] == 1
        assert report["magnitude_breakdown"]["moderate"] == 1
        assert report["magnitude_breakdown"]["minor"] == 1


class TestBuildDiscoverSocialMediaReport:
    """Tests for build_discover_social_media_report."""

    def test_platform_and_blog_breakdowns(self) -> None:
        result = _base_tracker_result()
        result["total_links_found"] = 5
        result["total_blogs_found"] = 2
        result["report_details"] = {
            "discovered": [
                {
                    "company_id": 1,
                    "name": "Co1",
                    "homepage_url": "https://co1.com",
                    "social_links": [
                        {"platform": "linkedin", "profile_url": "https://li.com/co1"},
                        {"platform": "twitter", "profile_url": "https://x.com/co1"},
                        {"platform": "linkedin", "profile_url": "https://li.com/co1p"},
                    ],
                    "blogs": [
                        {"blog_type": "company_blog", "blog_url": "https://co1.com/blog"},
                    ],
                },
                {
                    "company_id": 2,
                    "name": "Co2",
                    "homepage_url": "https://co2.com",
                    "social_links": [
                        {"platform": "github", "profile_url": "https://github.com/co2"},
                        {"platform": "twitter", "profile_url": "https://x.com/co2"},
                    ],
                    "blogs": [
                        {"blog_type": "medium", "blog_url": "https://medium.com/@co2"},
                    ],
                },
            ],
            "no_links_found": [],
            "failed": [],
            "skipped": [],
        }

        report = build_discover_social_media_report(result, {"batch_size": 50})

        assert report["platform_breakdown"]["linkedin"] == 2
        assert report["platform_breakdown"]["twitter"] == 2
        assert report["platform_breakdown"]["github"] == 1
        assert report["blog_type_breakdown"]["company_blog"] == 1
        assert report["blog_type_breakdown"]["medium"] == 1
        assert report["summary"]["total_links_found"] == 5
        assert report["summary"]["total_blogs_found"] == 2
        assert len(report["companies"]["discovered"]) == 2


class TestBuildExtractLeadershipReport:
    """Tests for build_extract_leadership_report."""

    def test_method_and_change_breakdowns(self) -> None:
        result = _base_tracker_result()
        result["total_leaders_found"] = 5
        result["critical_changes"] = [
            {
                "company_id": 1,
                "company_name": "Co1",
                "change_type": "ceo_departure",
                "person_name": "Jane",
                "title": "CEO",
                "severity": "critical",
            }
        ]
        result["report_details"] = {
            "extracted": [
                {
                    "company_id": 1,
                    "name": "Co1",
                    "method_used": "playwright_scrape",
                    "leaders_found": 3,
                    "leaders": [],
                    "leadership_changes": [
                        {
                            "change_type": "ceo_departure",
                            "person_name": "Jane",
                            "title": "CEO",
                            "severity": "critical",
                        },
                        {
                            "change_type": "new_ceo",
                            "person_name": "Bob",
                            "title": "Interim CEO",
                            "severity": "notable",
                        },
                    ],
                },
                {
                    "company_id": 2,
                    "name": "Co2",
                    "method_used": "kagi_search",
                    "leaders_found": 2,
                    "leaders": [],
                    "leadership_changes": [],
                },
            ],
            "failed": [],
            "skipped": [],
        }

        report = build_extract_leadership_report(result, {"limit": None})

        assert report["method_breakdown"]["playwright_scrape"] == 1
        assert report["method_breakdown"]["kagi_search"] == 1
        assert report["change_summary"]["total_changes_detected"] == 2
        assert report["change_summary"]["critical"] == 1
        assert report["change_summary"]["notable"] == 1
        assert len(report["critical_changes"]) == 1
        assert report["summary"]["total_leaders_found"] == 5


class TestBuildCaptureSocialSnapshotsReport:
    """Tests for build_capture_social_snapshots_report."""

    def test_source_type_breakdown(self) -> None:
        result: dict[str, Any] = {
            "total": 10,
            "captured": 8,
            "failed": 1,
            "skipped": 1,
            "errors": [],
            "duration_seconds": 30.0,
            "report_details": {
                "captured": [
                    {
                        "company_id": 1,
                        "name": "Co1",
                        "sources": [
                            {"source_url": "https://co1.com/blog", "source_type": "blog"},
                            {"source_url": "https://medium.com/@co1", "source_type": "medium"},
                        ],
                    },
                    {
                        "company_id": 2,
                        "name": "Co2",
                        "sources": [
                            {"source_url": "https://co2.com/blog", "source_type": "blog"},
                        ],
                    },
                ],
                "failed": [],
                "skipped": [],
            },
        }

        report = build_capture_social_snapshots_report(result, {"batch_size": 50})

        assert report["source_type_breakdown"]["blog"] == 2
        assert report["source_type_breakdown"]["medium"] == 1
        assert report["summary"]["total_urls"] == 10
        assert report["summary"]["captured"] == 8


class TestBuildDetectSocialChangesReport:
    """Tests for build_detect_social_changes_report."""

    def test_breakdowns_computed_from_changed(self) -> None:
        result = _base_tracker_result()
        result["changes_found"] = 2
        result["report_details"] = {
            "changed": [
                {
                    "company_id": 1,
                    "name": "Co1",
                    "source_url": "https://co1.com/blog",
                    "source_type": "blog",
                    "change_magnitude": "moderate",
                    "significance": "significant",
                    "sentiment": "positive",
                    "confidence": 0.8,
                    "matched_keywords": ["launch"],
                    "matched_categories": ["product_launch"],
                },
                {
                    "company_id": 2,
                    "name": "Co2",
                    "source_url": "https://medium.com/@co2",
                    "source_type": "medium",
                    "change_magnitude": "minor",
                    "significance": "insignificant",
                    "sentiment": "neutral",
                    "confidence": 0.7,
                    "matched_keywords": [],
                    "matched_categories": [],
                },
            ],
            "failed": [],
            "skipped": [],
        }

        report = build_detect_social_changes_report(result, {"limit": None})

        assert report["source_type_breakdown"]["blog"] == 1
        assert report["source_type_breakdown"]["medium"] == 1
        assert report["significance_breakdown"]["significant"] == 1
        assert report["significance_breakdown"]["insignificant"] == 1


class TestBuildSearchNewsReport:
    """Tests for build_search_news_report."""

    def test_article_breakdowns(self) -> None:
        result = _base_tracker_result()
        result["total_found"] = 10
        result["total_verified"] = 7
        result["total_stored"] = 5
        result["report_details"] = {
            "with_news": [
                {
                    "company_id": 1,
                    "name": "Co1",
                    "homepage_url": "https://co1.com",
                    "articles_found": 5,
                    "articles_verified": 4,
                    "articles_stored": 3,
                    "articles": [
                        {
                            "title": "Co1 raises",
                            "content_url": "https://news.com/1",
                            "source": "News",
                            "published_at": "2026-03-01",
                            "match_confidence": 0.9,
                            "significance": "significant",
                            "sentiment": "positive",
                            "matched_keywords": ["raises"],
                            "matched_categories": ["funding"],
                        },
                        {
                            "title": "Co1 review",
                            "content_url": "https://news.com/2",
                            "source": "Blog",
                            "published_at": "2026-02-28",
                            "match_confidence": 0.7,
                            "significance": "insignificant",
                            "sentiment": "neutral",
                            "matched_keywords": [],
                            "matched_categories": [],
                        },
                    ],
                },
            ],
            "failed": [
                {"company_id": 2, "name": "FailCo", "error": "timeout"},
            ],
            "skipped": [],
        }

        report = build_search_news_report(result, {"limit": None, "max_workers": 5})

        assert report["summary"]["total_articles_found"] == 10
        assert report["summary"]["total_articles_verified"] == 7
        assert report["summary"]["total_articles_stored"] == 5
        assert report["summary"]["total_duplicates_skipped"] == 2
        assert report["significance_breakdown"]["significant"] == 1
        assert report["significance_breakdown"]["insignificant"] == 1
        assert report["sentiment_breakdown"]["positive"] == 1
        assert len(report["companies"]["with_news"]) == 1
        assert len(report["companies"]["failed"]) == 1
