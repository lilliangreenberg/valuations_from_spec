"""FastAPI application factory for the dashboard."""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates

from src.domains.dashboard.core import formatting
from src.domains.dashboard.middleware import AuthMiddleware
from src.domains.dashboard.routes import (
    auth,
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
    google_oauth_client_id: str | None = None,
    google_oauth_client_secret: str | None = None,
    session_secret_key: str | None = None,
) -> FastAPI:
    """Create and configure the FastAPI dashboard application.

    Args:
        database_path: Path to the SQLite database file.
        database: Optional pre-configured Database instance (used in testing).
        google_oauth_client_id: Google OAuth client ID (enables OAuth when set).
        google_oauth_client_secret: Google OAuth client secret.
        session_secret_key: Secret key for session cookie signing.
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

    # OAuth setup
    oauth_enabled = bool(google_oauth_client_id and google_oauth_client_secret)
    if oauth_enabled:
        from src.services.auth import AuthService

        app.state.auth_service = AuthService(
            client_id=google_oauth_client_id,  # type: ignore[arg-type]
            client_secret=google_oauth_client_secret,  # type: ignore[arg-type]
        )
    else:
        app.state.auth_service = None

    # Middleware order matters: Starlette wraps in LIFO order.
    # AuthMiddleware added first (innermost) so it runs AFTER SessionMiddleware.
    app.add_middleware(AuthMiddleware, oauth_enabled=oauth_enabled)
    secret_key = session_secret_key or secrets.token_urlsafe(32)
    app.add_middleware(SessionMiddleware, secret_key=secret_key)

    # Static files
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Templates
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    _register_template_filters(templates)
    app.state.templates = templates

    # Database (repositories are created per-request in dependencies.py)
    if database is not None:
        db = database
    else:
        db = Database(db_path=database_path, check_same_thread=False)
        db.init_db()
    app.state.db = db

    # Dashboard services
    app.state.query_service = QueryService(db)
    app.state.task_runner = TaskRunner(max_concurrent=2)

    # Routes
    app.include_router(auth.router)
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

    from src.models.config import Config

    try:
        config = Config()  # type: ignore[call-arg]
    except Exception:
        config = None

    app = create_app(
        google_oauth_client_id=getattr(config, "google_oauth_client_id", None),
        google_oauth_client_secret=getattr(config, "google_oauth_client_secret", None),
        session_secret_key=getattr(config, "session_secret_key", None),
    )
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")
