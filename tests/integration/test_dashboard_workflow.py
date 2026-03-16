"""Integration tests for dashboard web routes.

Uses FastAPI TestClient to test page rendering and HTMX partials.
"""

from __future__ import annotations

import sqlite3
import tempfile

import pytest
from fastapi.testclient import TestClient

from src.domains.dashboard.app import create_app
from src.services.database import Database


@pytest.fixture()
def temp_db() -> Database:
    """Create a temp database that allows cross-thread access.

    FastAPI TestClient runs requests in a separate thread, so we need
    check_same_thread=False on the underlying SQLite connection.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    db = Database(db_path=path)
    # Force-create the connection with check_same_thread=False
    # before init_db() uses it.
    db._connection = sqlite3.connect(path, check_same_thread=False)
    db._connection.row_factory = sqlite3.Row
    db._connection.execute("PRAGMA journal_mode=WAL")
    db._connection.execute("PRAGMA foreign_keys=ON")
    db.init_db()
    return db


@pytest.fixture()
def client(temp_db: Database) -> TestClient:
    """Create a FastAPI TestClient with a temp database."""
    app = create_app(database=temp_db)
    return TestClient(app)


class TestOverviewPage:
    def test_overview_returns_200(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200

    def test_overview_contains_html(self, client: TestClient) -> None:
        response = client.get("/")
        assert "Portfolio" in response.text

    def test_stats_partial_returns_200(self, client: TestClient) -> None:
        response = client.get("/partials/stats")
        assert response.status_code == 200

    def test_activity_feed_partial_returns_200(self, client: TestClient) -> None:
        response = client.get("/partials/activity-feed")
        assert response.status_code == 200


class TestCompaniesPage:
    def test_companies_list_returns_200(self, client: TestClient) -> None:
        response = client.get("/companies/")
        assert response.status_code == 200

    def test_companies_table_partial_returns_200(self, client: TestClient) -> None:
        response = client.get("/companies/partials/table")
        assert response.status_code == 200

    def test_companies_table_with_search(self, client: TestClient) -> None:
        response = client.get("/companies/partials/table?search=test")
        assert response.status_code == 200

    def test_companies_table_with_filters(self, client: TestClient) -> None:
        response = client.get(
            "/companies/partials/table?status=operational&sort_by=name&sort_order=asc"
        )
        assert response.status_code == 200

    def test_nonexistent_company_redirects(self, client: TestClient) -> None:
        response = client.get("/companies/99999", follow_redirects=False)
        assert response.status_code == 302


class TestChangesPage:
    def test_changes_page_returns_200(self, client: TestClient) -> None:
        response = client.get("/changes/")
        assert response.status_code == 200

    def test_changes_partial_returns_200(self, client: TestClient) -> None:
        response = client.get("/changes/partials/list")
        assert response.status_code == 200

    def test_changes_with_filters(self, client: TestClient) -> None:
        response = client.get(
            "/changes/partials/list?classification=significant&sentiment=negative&days=90"
        )
        assert response.status_code == 200


class TestNewsPage:
    def test_news_page_returns_200(self, client: TestClient) -> None:
        response = client.get("/news/")
        assert response.status_code == 200

    def test_news_partial_returns_200(self, client: TestClient) -> None:
        response = client.get("/news/partials/list")
        assert response.status_code == 200


class TestLeadershipPage:
    def test_leadership_page_returns_200(self, client: TestClient) -> None:
        response = client.get("/leadership/")
        assert response.status_code == 200

    def test_leadership_partial_returns_200(self, client: TestClient) -> None:
        response = client.get("/leadership/partials/list")
        assert response.status_code == 200

    def test_leadership_current_only(self, client: TestClient) -> None:
        response = client.get("/leadership/partials/list?current_only=true")
        assert response.status_code == 200


class TestOperationsPage:
    def test_operations_page_returns_200(self, client: TestClient) -> None:
        response = client.get("/operations/")
        assert response.status_code == 200

    def test_operations_contains_command_list(self, client: TestClient) -> None:
        response = client.get("/operations/")
        assert "extract-companies" in response.text
        assert "detect-changes" in response.text

    def test_operations_history_partial(self, client: TestClient) -> None:
        response = client.get("/operations/partials/history")
        assert response.status_code == 200


class TestStaticFiles:
    def test_css_accessible(self, client: TestClient) -> None:
        response = client.get("/static/css/dashboard.css")
        assert response.status_code == 200
        assert "text/css" in response.headers.get("content-type", "")

    def test_js_accessible(self, client: TestClient) -> None:
        response = client.get("/static/js/dashboard.js")
        assert response.status_code == 200


class TestWidgetEndpoints:
    """Test all widget partial endpoints."""

    def test_changes_widget_returns_200(self, client: TestClient) -> None:
        response = client.get("/widgets/changes")
        assert response.status_code == 200

    def test_changes_widget_with_size(self, client: TestClient) -> None:
        response = client.get("/widgets/changes?size=large")
        assert response.status_code == 200

    def test_alerts_widget_returns_200(self, client: TestClient) -> None:
        response = client.get("/widgets/alerts")
        assert response.status_code == 200

    def test_trending_widget_returns_200(self, client: TestClient) -> None:
        response = client.get("/widgets/trending")
        assert response.status_code == 200

    def test_trending_data_returns_json(self, client: TestClient) -> None:
        response = client.get("/widgets/trending/data")
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "line"
        assert "data" in data
        assert "datasets" in data["data"]

    def test_trending_data_with_weeks(self, client: TestClient) -> None:
        response = client.get("/widgets/trending/data?weeks=4")
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]["labels"]) == 4

    def test_freshness_widget_returns_200(self, client: TestClient) -> None:
        response = client.get("/widgets/freshness")
        assert response.status_code == 200

    def test_activity_widget_returns_200(self, client: TestClient) -> None:
        response = client.get("/widgets/activity")
        assert response.status_code == 200

    def test_health_grid_widget_returns_200(self, client: TestClient) -> None:
        response = client.get("/widgets/health-grid")
        assert response.status_code == 200

    def test_overview_contains_widget_grid(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert "widget-grid" in response.text
        assert "widget-container" in response.text

    def test_overview_contains_customize_button(self, client: TestClient) -> None:
        response = client.get("/")
        assert "Customize" in response.text

    def test_overview_includes_chart_js(self, client: TestClient) -> None:
        response = client.get("/")
        assert "chart.js" in response.text or "chart.umd.min.js" in response.text

    def test_overview_contains_all_widgets(self, client: TestClient) -> None:
        response = client.get("/")
        assert 'data-widget-id="changes"' in response.text
        assert 'data-widget-id="alerts"' in response.text
        assert 'data-widget-id="trending"' in response.text
        assert 'data-widget-id="freshness"' in response.text
        assert 'data-widget-id="activity"' in response.text
        assert 'data-widget-id="health_grid"' in response.text


class TestEmptyDatabase:
    """Verify all pages render gracefully with an empty database."""

    def test_overview_empty(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        # Should contain the empty state or zero counts
        assert "0" in response.text or "quiet" in response.text.lower()

    def test_companies_empty(self, client: TestClient) -> None:
        response = client.get("/companies/")
        assert response.status_code == 200

    def test_changes_empty(self, client: TestClient) -> None:
        response = client.get("/changes/")
        assert response.status_code == 200

    def test_news_empty(self, client: TestClient) -> None:
        response = client.get("/news/")
        assert response.status_code == 200

    def test_leadership_empty(self, client: TestClient) -> None:
        response = client.get("/leadership/")
        assert response.status_code == 200
