"""Unit tests for widget core pure functions.

Tests widget_types, widget_data, and new formatting functions.
No I/O, no mocking.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.domains.dashboard.core.formatting import (
    freshness_tier,
    freshness_tier_label,
    health_grid_color,
)
from src.domains.dashboard.core.widget_data import (
    build_trending_chart_config,
    format_alerts_widget,
    format_changes_widget,
    format_freshness_widget,
)
from src.domains.dashboard.core.widget_types import (
    LAYOUT_PRESETS,
    WIDGET_REGISTRY,
    WIDGET_SIZE_LARGE,
    WIDGET_SIZE_SMALL,
    get_default_widget_config,
    get_preset_widget_ids,
    validate_widget_id,
    validate_widget_size,
)

# -- widget_types tests --


class TestWidgetRegistry:
    def test_has_six_widgets(self) -> None:
        assert len(WIDGET_REGISTRY) == 6

    def test_all_widgets_have_title(self) -> None:
        for widget_id, widget_def in WIDGET_REGISTRY.items():
            assert "title" in widget_def, f"{widget_id} missing title"

    def test_all_widgets_have_sizes(self) -> None:
        for widget_id, widget_def in WIDGET_REGISTRY.items():
            assert "sizes" in widget_def, f"{widget_id} missing sizes"
            assert len(widget_def["sizes"]) > 0

    def test_all_widgets_have_default_size(self) -> None:
        for _widget_id, widget_def in WIDGET_REGISTRY.items():
            assert widget_def["default_size"] in widget_def["sizes"]

    def test_all_widgets_have_endpoint(self) -> None:
        for _widget_id, widget_def in WIDGET_REGISTRY.items():
            assert "endpoint" in widget_def
            assert widget_def["endpoint"].startswith("/widgets/")

    def test_all_widgets_have_refresh_seconds(self) -> None:
        for _widget_id, widget_def in WIDGET_REGISTRY.items():
            assert "refresh_seconds" in widget_def
            assert widget_def["refresh_seconds"] > 0

    def test_trending_is_large_only(self) -> None:
        assert WIDGET_REGISTRY["trending"]["sizes"] == [WIDGET_SIZE_LARGE]

    def test_changes_supports_both_sizes(self) -> None:
        assert WIDGET_SIZE_SMALL in WIDGET_REGISTRY["changes"]["sizes"]
        assert WIDGET_SIZE_LARGE in WIDGET_REGISTRY["changes"]["sizes"]


class TestLayoutPresets:
    def test_has_four_presets(self) -> None:
        assert len(LAYOUT_PRESETS) == 4

    def test_full_dashboard_contains_all_widgets(self) -> None:
        preset = LAYOUT_PRESETS["full_dashboard"]
        for widget_id in WIDGET_REGISTRY:
            assert widget_id in preset["widgets"]

    def test_quick_glance_has_two_widgets(self) -> None:
        assert LAYOUT_PRESETS["quick_glance"]["widgets"] == ["changes", "alerts"]

    def test_executive_summary_has_three_widgets(self) -> None:
        assert LAYOUT_PRESETS["executive_summary"]["widgets"] == [
            "changes",
            "trending",
            "health_grid",
        ]

    def test_custom_preset_has_empty_widgets(self) -> None:
        assert LAYOUT_PRESETS["custom"]["widgets"] == []

    def test_all_preset_widgets_are_valid(self) -> None:
        for preset_name, preset_def in LAYOUT_PRESETS.items():
            for widget_id in preset_def["widgets"]:
                assert widget_id in WIDGET_REGISTRY, (
                    f"Preset '{preset_name}' references unknown widget '{widget_id}'"
                )

    def test_all_presets_have_label(self) -> None:
        for name, preset in LAYOUT_PRESETS.items():
            assert "label" in preset, f"Preset '{name}' missing label"

    def test_all_presets_have_description(self) -> None:
        for name, preset in LAYOUT_PRESETS.items():
            assert "description" in preset, f"Preset '{name}' missing description"


class TestGetDefaultWidgetConfig:
    def test_returns_config_for_all_widgets(self) -> None:
        config = get_default_widget_config()
        assert len(config) == len(WIDGET_REGISTRY)

    def test_all_widgets_visible_by_default(self) -> None:
        config = get_default_widget_config()
        for widget_id, widget_config in config.items():
            assert widget_config["visible"] is True, f"{widget_id} not visible"

    def test_sizes_match_defaults(self) -> None:
        config = get_default_widget_config()
        for widget_id, widget_config in config.items():
            assert widget_config["size"] == WIDGET_REGISTRY[widget_id]["default_size"]


class TestGetPresetWidgetIds:
    def test_full_dashboard(self) -> None:
        ids = get_preset_widget_ids("full_dashboard")
        assert len(ids) == 6

    def test_quick_glance(self) -> None:
        ids = get_preset_widget_ids("quick_glance")
        assert ids == ["changes", "alerts"]

    def test_unknown_preset_returns_empty(self) -> None:
        ids = get_preset_widget_ids("nonexistent")
        assert ids == []

    def test_custom_preset_returns_empty(self) -> None:
        ids = get_preset_widget_ids("custom")
        assert ids == []


class TestValidateWidgetId:
    def test_valid_ids(self) -> None:
        assert validate_widget_id("changes") is True
        assert validate_widget_id("alerts") is True
        assert validate_widget_id("trending") is True
        assert validate_widget_id("freshness") is True
        assert validate_widget_id("activity") is True
        assert validate_widget_id("health_grid") is True

    def test_invalid_id(self) -> None:
        assert validate_widget_id("nonexistent") is False
        assert validate_widget_id("") is False


class TestValidateWidgetSize:
    def test_valid_size(self) -> None:
        assert validate_widget_size("changes", "small") == "small"
        assert validate_widget_size("changes", "large") == "large"

    def test_invalid_size_falls_back(self) -> None:
        assert validate_widget_size("trending", "small") == "large"

    def test_unknown_widget_returns_small(self) -> None:
        assert validate_widget_size("nonexistent", "large") == "small"


# -- widget_data tests --


class TestFormatChangesWidget:
    def test_small_has_total_and_scan_date(self) -> None:
        raw = {"total_changes": 5, "scan_date": "2026-02-25", "by_magnitude": {"minor": 3}}
        result = format_changes_widget(raw, "small")
        assert result["total_changes"] == 5
        assert result["scan_date"] == "2026-02-25"
        assert result["size"] == "small"

    def test_small_excludes_breakdowns(self) -> None:
        raw = {
            "total_changes": 5,
            "by_magnitude": {"minor": 3},
            "by_significance": {"significant": 1},
        }
        result = format_changes_widget(raw, "small")
        assert "by_magnitude" not in result
        assert "by_significance" not in result

    def test_large_includes_breakdowns(self) -> None:
        raw = {
            "total_changes": 5,
            "by_magnitude": {"minor": 3},
            "by_significance": {"significant": 1},
        }
        result = format_changes_widget(raw, "large")
        assert result["by_magnitude"] == {"minor": 3}
        assert result["by_significance"] == {"significant": 1}

    def test_empty_raw_data(self) -> None:
        result = format_changes_widget({}, "small")
        assert result["total_changes"] == 0
        assert result["scan_date"] is None


class TestFormatAlertsWidget:
    def test_small_has_counts(self) -> None:
        raw = {"negative_significant_count": 3, "uncertain_count": 7, "total_alerts": 10}
        result = format_alerts_widget(raw, "small")
        assert result["negative_significant_count"] == 3
        assert result["uncertain_count"] == 7
        assert result["total_alerts"] == 10
        assert result["size"] == "small"

    def test_small_excludes_flagged_list(self) -> None:
        raw = {"flagged_companies": [{"id": 1, "name": "Acme"}]}
        result = format_alerts_widget(raw, "small")
        assert "flagged_companies" not in result

    def test_large_includes_flagged_list(self) -> None:
        raw = {
            "negative_significant_count": 0,
            "uncertain_count": 0,
            "total_alerts": 0,
            "flagged_companies": [{"id": 1, "name": "Acme"}],
        }
        result = format_alerts_widget(raw, "large")
        assert result["flagged_companies"] == [{"id": 1, "name": "Acme"}]

    def test_empty_raw_data(self) -> None:
        result = format_alerts_widget({}, "small")
        assert result["negative_significant_count"] == 0
        assert result["uncertain_count"] == 0
        assert result["total_alerts"] == 0


class TestFormatFreshnessWidget:
    def test_small_has_summary(self) -> None:
        raw = {"summary": {"fresh": 10, "stale": 5}, "companies_by_tier": {"fresh": []}}
        result = format_freshness_widget(raw, "small")
        assert result["summary"] == {"fresh": 10, "stale": 5}
        assert "companies_by_tier" not in result

    def test_large_includes_companies(self) -> None:
        raw = {"summary": {"fresh": 10}, "companies_by_tier": {"fresh": [{"id": 1}]}}
        result = format_freshness_widget(raw, "large")
        assert "companies_by_tier" in result

    def test_empty_raw_data(self) -> None:
        result = format_freshness_widget({}, "small")
        assert result["summary"] == {}


class TestBuildTrendingChartConfig:
    def test_returns_chart_structure(self) -> None:
        raw = {
            "labels": ["W1", "W2"],
            "significant_changes": [1, 2],
            "news_articles": [3, 4],
            "leadership_discoveries": [0, 1],
        }
        config = build_trending_chart_config(raw)
        assert config["type"] == "line"
        assert config["data"]["labels"] == ["W1", "W2"]
        assert len(config["data"]["datasets"]) == 3

    def test_datasets_have_labels(self) -> None:
        raw = {
            "labels": [],
            "significant_changes": [],
            "news_articles": [],
            "leadership_discoveries": [],
        }
        config = build_trending_chart_config(raw)
        labels = [ds["label"] for ds in config["data"]["datasets"]]
        assert "Significant Changes" in labels
        assert "News Articles" in labels
        assert "Leadership Discoveries" in labels

    def test_has_options(self) -> None:
        config = build_trending_chart_config({})
        assert "options" in config
        assert config["options"]["responsive"] is True

    def test_empty_raw_data(self) -> None:
        config = build_trending_chart_config({})
        assert config["data"]["labels"] == []
        for ds in config["data"]["datasets"]:
            assert ds["data"] == []


# -- formatting function tests --


class TestFreshnessTier:
    def test_none_returns_never(self) -> None:
        assert freshness_tier(None) == "never"

    def test_empty_returns_never(self) -> None:
        assert freshness_tier("") == "never"

    def test_fresh(self) -> None:
        recent = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        assert freshness_tier(recent) == "fresh"

    def test_recent(self) -> None:
        two_weeks = (datetime.now(UTC) - timedelta(days=15)).isoformat()
        assert freshness_tier(two_weeks) == "recent"

    def test_stale(self) -> None:
        two_months = (datetime.now(UTC) - timedelta(days=60)).isoformat()
        assert freshness_tier(two_months) == "stale"

    def test_very_stale(self) -> None:
        six_months = (datetime.now(UTC) - timedelta(days=180)).isoformat()
        assert freshness_tier(six_months) == "very_stale"

    def test_invalid_returns_never(self) -> None:
        assert freshness_tier("not-a-date") == "never"


class TestFreshnessTierLabel:
    def test_fresh(self) -> None:
        assert freshness_tier_label("fresh") == "Fresh (< 7 days)"

    def test_recent(self) -> None:
        assert freshness_tier_label("recent") == "Recent (7-30 days)"

    def test_stale(self) -> None:
        assert freshness_tier_label("stale") == "Stale (30-90 days)"

    def test_very_stale(self) -> None:
        assert freshness_tier_label("very_stale") == "Very Stale (> 90 days)"

    def test_never(self) -> None:
        assert freshness_tier_label("never") == "Never Scanned"

    def test_unknown_returns_input(self) -> None:
        assert freshness_tier_label("something") == "something"


class TestHealthGridColor:
    def test_operational(self) -> None:
        assert health_grid_color("operational") == "health-green"

    def test_likely_closed(self) -> None:
        assert health_grid_color("likely_closed") == "health-red"

    def test_uncertain(self) -> None:
        assert health_grid_color("uncertain") == "health-yellow"

    def test_unknown(self) -> None:
        assert health_grid_color("unknown") == "health-gray"

    def test_none(self) -> None:
        assert health_grid_color(None) == "health-gray"

    def test_empty_string(self) -> None:
        assert health_grid_color("") == "health-gray"

    def test_likely_closed_manual_override(self) -> None:
        assert health_grid_color("likely_closed", is_manual_override=True) == "health-manual-closed"

    def test_likely_closed_not_manual(self) -> None:
        assert health_grid_color("likely_closed", is_manual_override=False) == "health-red"

    def test_operational_manual_override_ignored(self) -> None:
        assert health_grid_color("operational", is_manual_override=True) == "health-green"
