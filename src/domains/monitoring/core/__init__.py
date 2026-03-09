"""Monitoring domain core -- pure functions for website change detection and status analysis."""

from __future__ import annotations

from src.domains.monitoring.core.change_detection import (
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
    HOMEPAGE_EXCLUDED_CATEGORIES,
    SOCIAL_MEDIA_EXCLUDED_CATEGORIES,
    KeywordMatchResult,
    SignificanceResult,
    analyze_content_significance,
    classify_significance,
    detect_false_positives,
    detect_negation,
    find_keyword_matches,
)
from src.domains.monitoring.core.social_content_analysis import (
    check_posting_inactivity,
    extract_latest_post_date,
    prepare_social_context,
)
from src.domains.monitoring.core.status_rules import (
    CompanyStatusType,
    SignalType,
    analyze_snapshot_status,
    calculate_confidence,
    detect_acquisition,
    determine_status,
    extract_copyright_year,
)

__all__ = [
    # change_detection
    "ChangeMagnitude",
    "calculate_similarity",
    "detect_content_change",
    "determine_magnitude",
    "extract_content_diff",
    # checksum
    "compute_content_checksum",
    # http_headers
    "extract_content_type",
    "is_html_content",
    "parse_last_modified",
    # significance_analysis
    "HOMEPAGE_EXCLUDED_CATEGORIES",
    "SOCIAL_MEDIA_EXCLUDED_CATEGORIES",
    "KeywordMatchResult",
    "SignificanceResult",
    "analyze_content_significance",
    "classify_significance",
    "detect_false_positives",
    "detect_negation",
    "find_keyword_matches",
    # social_content_analysis
    "check_posting_inactivity",
    "extract_latest_post_date",
    "prepare_social_context",
    # status_rules
    "CompanyStatusType",
    "SignalType",
    "analyze_snapshot_status",
    "calculate_confidence",
    "detect_acquisition",
    "determine_status",
    "extract_copyright_year",
]
