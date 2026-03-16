"""Widget type definitions, layout presets, and configuration.

No I/O. Pure data structures only.
"""

from __future__ import annotations

from typing import Any

WIDGET_SIZE_SMALL = "small"
WIDGET_SIZE_LARGE = "large"

WIDGET_REGISTRY: dict[str, dict[str, Any]] = {
    "changes": {
        "title": "Changes Since Last Check",
        "sizes": [WIDGET_SIZE_SMALL, WIDGET_SIZE_LARGE],
        "default_size": WIDGET_SIZE_SMALL,
        "endpoint": "/widgets/changes",
        "refresh_seconds": 120,
    },
    "alerts": {
        "title": "Alerts Needing Attention",
        "sizes": [WIDGET_SIZE_SMALL, WIDGET_SIZE_LARGE],
        "default_size": WIDGET_SIZE_SMALL,
        "endpoint": "/widgets/alerts",
        "refresh_seconds": 120,
    },
    "trending": {
        "title": "Investment Trending",
        "sizes": [WIDGET_SIZE_LARGE],
        "default_size": WIDGET_SIZE_LARGE,
        "endpoint": "/widgets/trending",
        "refresh_seconds": 300,
    },
    "freshness": {
        "title": "Snapshot Freshness",
        "sizes": [WIDGET_SIZE_SMALL, WIDGET_SIZE_LARGE],
        "default_size": WIDGET_SIZE_SMALL,
        "endpoint": "/widgets/freshness",
        "refresh_seconds": 300,
    },
    "activity": {
        "title": "Recent Activity",
        "sizes": [WIDGET_SIZE_LARGE],
        "default_size": WIDGET_SIZE_LARGE,
        "endpoint": "/widgets/activity",
        "refresh_seconds": 120,
    },
    "health_grid": {
        "title": "Company Health Grid",
        "sizes": [WIDGET_SIZE_LARGE],
        "default_size": WIDGET_SIZE_LARGE,
        "endpoint": "/widgets/health-grid",
        "refresh_seconds": 300,
    },
}

LAYOUT_PRESETS: dict[str, dict[str, Any]] = {
    "full_dashboard": {
        "label": "Full Dashboard",
        "description": "All 6 widgets",
        "widgets": ["changes", "alerts", "trending", "freshness", "activity", "health_grid"],
    },
    "quick_glance": {
        "label": "Quick Glance",
        "description": "Changes and alerts only",
        "widgets": ["changes", "alerts"],
    },
    "executive_summary": {
        "label": "Executive Summary",
        "description": "Changes, trending graph, and health grid",
        "widgets": ["changes", "trending", "health_grid"],
    },
    "custom": {
        "label": "Custom",
        "description": "Choose your own widgets",
        "widgets": [],
    },
}


def get_default_widget_config() -> dict[str, dict[str, str | bool]]:
    """Return the default widget configuration (full dashboard preset).

    Returns a dict keyed by widget_id with visibility and size for each.
    """
    config: dict[str, dict[str, str | bool]] = {}
    for widget_id, widget_def in WIDGET_REGISTRY.items():
        config[widget_id] = {
            "visible": True,
            "size": widget_def["default_size"],
        }
    return config


def get_preset_widget_ids(preset_name: str) -> list[str]:
    """Return the list of widget IDs for a given preset name.

    Returns an empty list for unknown presets or the 'custom' preset.
    """
    preset = LAYOUT_PRESETS.get(preset_name)
    if preset is None:
        return []
    return list(preset["widgets"])


def validate_widget_id(widget_id: str) -> bool:
    """Check whether a widget_id exists in the registry."""
    return widget_id in WIDGET_REGISTRY


def validate_widget_size(widget_id: str, size: str) -> str:
    """Validate and return a valid size for the given widget.

    Falls back to the widget's default_size if the requested size is invalid.
    """
    widget_def = WIDGET_REGISTRY.get(widget_id)
    if widget_def is None:
        return WIDGET_SIZE_SMALL
    if size in widget_def["sizes"]:
        return size
    default: str = widget_def["default_size"]
    return default
