"""FastAPI application factory for the dashboard."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from src.domains.dashboard.core import formatting
from src.domains.dashboard.routes import (
    changes,
    companies,
    leadership,
    news,
    operations,
    overview,
    widgets,
)
from src.domains.dashboard.services.query_service import QueryService
from src.domains.dashboard.services.task_runner import TaskRunner
from src.domains.leadership.repositories.leadership_repository import LeadershipRepository
from src.domains.monitoring.repositories.change_record_repository import ChangeRecordRepository
from src.domains.monitoring.repositories.company_status_repository import (
    CompanyStatusRepository,
)
from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository
from src.domains.news.repositories.news_article_repository import NewsArticleRepository
from src.repositories.company_repository import CompanyRepository
from src.services.database import Database

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = structlog.get_logger(__name__)

_DASHBOARD_DIR = Path(__file__).parent
_TEMPLATES_DIR = _DASHBOARD_DIR / "templates"
_STATIC_DIR = _DASHBOARD_DIR / "static"


def _css_version() -> str:
    """Compute a short hash of dashboard.css for cache-busting."""
    import hashlib

    css_path = _STATIC_DIR / "css" / "dashboard.css"
    return hashlib.md5(css_path.read_bytes()).hexdigest()[:8]  # noqa: S324


def _js_version() -> str:
    """Compute a short hash of dashboard.js for cache-busting."""
    import hashlib

    js_path = _STATIC_DIR / "js" / "dashboard.js"
    return hashlib.md5(js_path.read_bytes()).hexdigest()[:8]  # noqa: S324


def _register_template_filters(templates: Jinja2Templates) -> None:
    """Register custom Jinja2 filters and globals from formatting module."""
    env = templates.env
    env.filters["relative_time"] = formatting.format_relative_time
    env.filters["significance_badge"] = formatting.significance_badge_class
    env.filters["sentiment_color"] = formatting.sentiment_color_class
    env.filters["magnitude"] = formatting.magnitude_indicator
    env.filters["truncate_url"] = formatting.truncate_url
    env.filters["platform_name"] = formatting.platform_display_name
    env.filters["status_badge"] = formatting.status_badge_class
    env.filters["confidence"] = formatting.format_confidence
    env.filters["date_short"] = formatting.format_date_short
    env.globals["empty_state_message"] = formatting.empty_state_message
    env.filters["freshness_tier"] = formatting.freshness_tier
    env.filters["freshness_tier_label"] = formatting.freshness_tier_label
    env.filters["health_grid_color"] = formatting.health_grid_color
    env.globals["health_tooltip_reason"] = formatting.health_tooltip_reason
    env.globals["css_version"] = _css_version()
    env.globals["js_version"] = _js_version()


def create_app(
    database_path: str = "data/companies.db",
    database: Database | None = None,
) -> FastAPI:
    """Create and configure the FastAPI dashboard application.

    Args:
        database_path: Path to the SQLite database file.
        database: Optional pre-configured Database instance (used in testing).
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        logger.info("dashboard_starting", database=database_path)
        yield
        logger.info("dashboard_shutting_down")
        if hasattr(app.state, "task_runner"):
            await app.state.task_runner.cleanup()
        if hasattr(app.state, "db"):
            app.state.db.close()

    app = FastAPI(
        title="Portfolio Company Monitor",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    # Static files
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Templates
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    _register_template_filters(templates)
    app.state.templates = templates

    # Database and repositories
    if database is not None:
        db = database
    else:
        db = Database(db_path=database_path, check_same_thread=False)
        db.init_db()
    app.state.db = db
    app.state.company_repo = CompanyRepository(db)
    app.state.snapshot_repo = SnapshotRepository(db)
    app.state.change_repo = ChangeRecordRepository(db)
    app.state.status_repo = CompanyStatusRepository(db)
    app.state.news_repo = NewsArticleRepository(db)
    app.state.leadership_repo = LeadershipRepository(db)

    # Dashboard services
    app.state.query_service = QueryService(db)
    app.state.task_runner = TaskRunner(max_concurrent=2)

    # Routes
    app.include_router(overview.router)
    app.include_router(companies.router)
    app.include_router(changes.router)
    app.include_router(news.router)
    app.include_router(leadership.router)
    app.include_router(operations.router)
    app.include_router(widgets.router)

    return app


def main() -> None:
    """Entry point for running the dashboard directly."""
    import uvicorn

    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
