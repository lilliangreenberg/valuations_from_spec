"""Pure functions to transform raw query results into widget display data.

No I/O. Takes dicts from QueryService and returns presentation-ready dicts.
"""

from __future__ import annotations

from typing import Any


def format_changes_widget(raw: dict[str, Any], size: str) -> dict[str, Any]:
    """Transform raw changes-since-last-scan data for template rendering.

    For small size: just totals. For large: include magnitude/significance breakdowns.
    """
    result: dict[str, Any] = {
        "total_changes": raw.get("total_changes", 0),
        "scan_date": raw.get("scan_date"),
        "size": size,
        "by_significance": raw.get("by_significance", {}),
    }
    if size == "large":
        result["by_magnitude"] = raw.get("by_magnitude", {})
    return result


def format_alerts_widget(raw: dict[str, Any], size: str) -> dict[str, Any]:
    """Transform raw alerts summary data for template rendering.

    For small: counts only. For large: include flagged company list.
    """
    result: dict[str, Any] = {
        "negative_significant_count": raw.get("negative_significant_count", 0),
        "uncertain_count": raw.get("uncertain_count", 0),
        "total_alerts": raw.get("total_alerts", 0),
        "size": size,
    }
    if size == "large":
        result["flagged_companies"] = raw.get("flagged_companies", [])
    return result


def format_freshness_widget(raw: dict[str, Any], size: str) -> dict[str, Any]:
    """Transform raw snapshot freshness data for template rendering.

    For small: summary tier counts only. For large: grouped company lists.
    """
    result: dict[str, Any] = {
        "summary": raw.get("summary", {}),
        "size": size,
    }
    if size == "large":
        result["companies_by_tier"] = raw.get("companies_by_tier", {})
    return result


def build_trending_chart_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Build a Chart.js-compatible configuration dict from trending data.

    Returns a structure suitable for JSON serialization that Chart.js
    can consume directly.
    """
    labels = raw.get("labels", [])
    return {
        "type": "line",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "label": "Significant Changes",
                    "data": raw.get("significant_changes", []),
                    "borderColor": "#f59e0b",
                    "backgroundColor": "rgba(245, 158, 11, 0.1)",
                    "tension": 0.3,
                    "fill": True,
                },
                {
                    "label": "News Articles",
                    "data": raw.get("news_articles", []),
                    "borderColor": "#3b82f6",
                    "backgroundColor": "rgba(59, 130, 246, 0.1)",
                    "tension": 0.3,
                    "fill": True,
                },
                {
                    "label": "Leadership Discoveries",
                    "data": raw.get("leadership_discoveries", []),
                    "borderColor": "#8b5cf6",
                    "backgroundColor": "rgba(139, 92, 246, 0.1)",
                    "tension": 0.3,
                    "fill": True,
                },
            ],
        },
        "options": {
            "responsive": True,
            "maintainAspectRatio": False,
            "plugins": {
                "legend": {"position": "bottom", "labels": {"boxWidth": 12}},
            },
            "scales": {
                "y": {"beginAtZero": True, "ticks": {"stepSize": 1}},
                "x": {"grid": {"display": False}},
            },
        },
    }
