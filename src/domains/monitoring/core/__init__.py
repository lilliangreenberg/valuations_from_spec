"""Monitoring domain core -- pure functions for website change detection and status analysis."""

from __future__ import annotations

from src.domains.monitoring.core.change_detection import (
    ChangeMagnitude,
    calculate_similarity,
    detect_content_change,
    determine_magnitude,
)
from src.domains.monitoring.core.checksum import compute_content_checksum
from src.domains.monitoring.core.http_headers import (
    extract_content_type,
    is_html_content,
    parse_last_modified,
)
from src.domains.monitoring.core.significance_analysis import (
    KeywordMatchResult,
    SignificanceResult,
    analyze_content_significance,
    classify_significance,
    detect_false_positives,
    detect_negation,
    find_keyword_matches,
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
    # checksum
    "compute_content_checksum",
    # http_headers
    "extract_content_type",
    "is_html_content",
    "parse_last_modified",
    # significance_analysis
    "KeywordMatchResult",
    "SignificanceResult",
    "analyze_content_significance",
    "classify_significance",
    "detect_false_positives",
    "detect_negation",
    "find_keyword_matches",
    # status_rules
    "CompanyStatusType",
    "SignalType",
    "analyze_snapshot_status",
    "calculate_confidence",
    "detect_acquisition",
    "determine_status",
    "extract_copyright_year",
]
