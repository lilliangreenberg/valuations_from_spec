"""FastAPI dependency functions for typed access to shared state."""

from __future__ import annotations

import getpass
from typing import TYPE_CHECKING

from starlette.requests import Request  # noqa: TC002 -- FastAPI needs this at runtime

if TYPE_CHECKING:
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.query_service import QueryService
    from src.domains.dashboard.services.task_runner import TaskRunner
    from src.services.database import Database

from src.domains.leadership.repositories.leadership_repository import LeadershipRepository
from src.domains.monitoring.repositories.change_record_repository import ChangeRecordRepository
from src.domains.monitoring.repositories.company_status_repository import (
    CompanyStatusRepository,
)
from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository
from src.domains.news.repositories.news_article_repository import NewsArticleRepository
from src.repositories.company_repository import CompanyRepository


def _get_operator(request: Request) -> str:
    """Extract operator identity from the request.

    Uses request.state.operator set by AuthMiddleware (from session user email).
    Falls back to system username if middleware has not set it.
    """
    operator: str = getattr(request.state, "operator", getpass.getuser())
    return operator


def get_db(request: Request) -> Database:
    """Get the shared Database instance."""
    return request.app.state.db  # type: ignore[no-any-return]


def get_company_repo(request: Request) -> CompanyRepository:
    """Get a CompanyRepository for the current request operator."""
    return CompanyRepository(request.app.state.db, _get_operator(request))


def get_snapshot_repo(request: Request) -> SnapshotRepository:
    """Get a SnapshotRepository for the current request operator."""
    return SnapshotRepository(request.app.state.db, _get_operator(request))


def get_change_repo(request: Request) -> ChangeRecordRepository:
    """Get a ChangeRecordRepository for the current request operator."""
    return ChangeRecordRepository(request.app.state.db, _get_operator(request))


def get_status_repo(request: Request) -> CompanyStatusRepository:
    """Get a CompanyStatusRepository for the current request operator."""
    return CompanyStatusRepository(request.app.state.db, _get_operator(request))


def get_news_repo(request: Request) -> NewsArticleRepository:
    """Get a NewsArticleRepository for the current request operator."""
    return NewsArticleRepository(request.app.state.db, _get_operator(request))


def get_leadership_repo(request: Request) -> LeadershipRepository:
    """Get a LeadershipRepository for the current request operator."""
    return LeadershipRepository(request.app.state.db, _get_operator(request))


def get_query_service(request: Request) -> QueryService:
    """Get the QueryService instance."""
    return request.app.state.query_service  # type: ignore[no-any-return]


def get_task_runner(request: Request) -> TaskRunner:
    """Get the TaskRunner instance."""
    return request.app.state.task_runner  # type: ignore[no-any-return]


def get_templates(request: Request) -> Jinja2Templates:
    """Get the Jinja2Templates instance."""
    return request.app.state.templates  # type: ignore[no-any-return]
