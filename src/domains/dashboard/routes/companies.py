"""Company list and detail routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from src.domains.dashboard.dependencies import (
    get_query_service,
    get_status_repo,
    get_task_runner,
    get_templates,
)

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("/", response_class=HTMLResponse)
async def companies_list_page(
    request: Request,
    search: str = "",
    status: str = "",
    source_sheet: str = "",
    flagged: str = "",
    freshness: str = "",
    manual_override: str = "",
    sort_by: str = "name",
    sort_order: str = "asc",
    page: int = 1,
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """Render the company list page."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    flagged_filter: bool | None = None
    if flagged == "yes":
        flagged_filter = True
    elif flagged == "no":
        flagged_filter = False

    source_sheets = qs.get_source_sheets()
    result = qs.get_companies_list(
        search=search or None,
        status_filter=status or None,
        source_sheet_filter=source_sheet or None,
        flagged=flagged_filter,
        freshness=freshness or None,
        manual_override=manual_override or None,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
    )

    return tmpl.TemplateResponse(
        request,
        "companies/list.html",
        {
            "companies": result["items"],
            "total": result["total"],
            "page": result["page"],
            "per_page": result["per_page"],
            "total_pages": result["total_pages"],
            "source_sheets": source_sheets,
            "search": search,
            "status_filter": status,
            "source_sheet_filter": source_sheet,
            "flagged_filter": flagged,
            "freshness_filter": freshness,
            "manual_override_filter": manual_override,
            "sort_by": sort_by,
            "sort_order": sort_order,
        },
    )


@router.get("/partials/table", response_class=HTMLResponse)
async def companies_table_partial(
    request: Request,
    search: str = "",
    status: str = "",
    source_sheet: str = "",
    flagged: str = "",
    freshness: str = "",
    manual_override: str = "",
    sort_by: str = "name",
    sort_order: str = "asc",
    page: int = 1,
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """HTMX partial: filtered/sorted/paginated company table."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    flagged_filter: bool | None = None
    if flagged == "yes":
        flagged_filter = True
    elif flagged == "no":
        flagged_filter = False

    result = qs.get_companies_list(
        search=search or None,
        status_filter=status or None,
        source_sheet_filter=source_sheet or None,
        flagged=flagged_filter,
        freshness=freshness or None,
        manual_override=manual_override or None,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
    )

    return tmpl.TemplateResponse(
        request,
        "partials/company_table.html",
        {
            "companies": result["items"],
            "total": result["total"],
            "page": result["page"],
            "per_page": result["per_page"],
            "total_pages": result["total_pages"],
            "search": search,
            "status_filter": status,
            "source_sheet_filter": source_sheet,
            "freshness_filter": freshness,
            "manual_override_filter": manual_override,
            "sort_by": sort_by,
            "sort_order": sort_order,
        },
    )


@router.get("/{company_id}", response_class=HTMLResponse)
async def company_detail_page(
    request: Request,
    company_id: int,
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """Render the company detail page."""
    from fastapi.responses import RedirectResponse
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    summary = qs.get_company_summary(company_id)
    if not summary:
        return RedirectResponse(url="/companies", status_code=302)  # type: ignore[return-value]

    return tmpl.TemplateResponse(
        request,
        "companies/detail.html",
        {"company": summary},
    )


@router.post("/{company_id}/status-override", response_class=HTMLResponse)
async def set_status_override(
    request: Request,
    company_id: int,
    status: str = Form(...),
    status_repo: object = Depends(get_status_repo),
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """Set a manual status override for a company."""
    from datetime import UTC, datetime

    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.query_service import QueryService
    from src.domains.monitoring.core.manual_override import prepare_manual_override
    from src.domains.monitoring.repositories.company_status_repository import (
        CompanyStatusRepository,
    )

    repo = status_repo
    assert isinstance(repo, CompanyStatusRepository)
    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    now_iso = datetime.now(UTC).isoformat()
    override_data = prepare_manual_override(company_id, status, now_iso)
    repo.store_status(override_data)

    # Re-fetch the updated status for the partial
    latest = repo.get_latest_status(company_id)

    return tmpl.TemplateResponse(
        request,
        "partials/status_override.html",
        {"company_id": company_id, "status_data": latest},
    )


@router.post("/{company_id}/status-override/clear", response_class=HTMLResponse)
async def clear_status_override(
    request: Request,
    company_id: int,
    status_repo: object = Depends(get_status_repo),
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """Clear the manual status override, allowing analyze-status to resume."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.query_service import QueryService
    from src.domains.monitoring.repositories.company_status_repository import (
        CompanyStatusRepository,
    )

    repo = status_repo
    assert isinstance(repo, CompanyStatusRepository)
    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    repo.clear_manual_override(company_id)

    latest = repo.get_latest_status(company_id)

    return tmpl.TemplateResponse(
        request,
        "partials/status_override.html",
        {"company_id": company_id, "status_data": latest},
    )


@router.post("/{company_id}/actions/run", response_class=HTMLResponse)
async def run_company_action(
    request: Request,
    company_id: int,
    action: str = Form(...),
    task_runner: object = Depends(get_task_runner),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """Start a per-company background action (rescrape or detect-changes)."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.task_runner import TaskRunner

    tr = task_runner
    assert isinstance(tr, TaskRunner)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    valid_actions: dict[str, tuple[str, list[str]]] = {
        "rescrape": ("capture-snapshots", ["--company-id", str(company_id)]),
        "detect-changes": ("detect-changes", ["--company-id", str(company_id)]),
    }

    if action not in valid_actions:
        return tmpl.TemplateResponse(
            request,
            "partials/company_action_progress.html",
            {"task": None, "error": f"Unknown action: {action}"},
        )

    if tr.get_running_count() >= tr.max_concurrent:
        return tmpl.TemplateResponse(
            request,
            "partials/company_action_progress.html",
            {
                "task": None,
                "error": "Maximum concurrent tasks reached. Wait for a task to complete.",
            },
        )

    command, args = valid_actions[action]
    task_id = await tr.start_task(command, args)
    task = tr.get_task(task_id)

    return tmpl.TemplateResponse(
        request,
        "partials/company_action_progress.html",
        {"task": task, "error": None},
    )


@router.post("/{company_id}/notes", response_class=HTMLResponse)
async def set_company_notes(
    request: Request,
    company_id: int,
    notes: str = Form(default=""),
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """Save analyst notes for a company."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.dependencies import get_company_repo
    from src.repositories.company_repository import CompanyRepository

    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)
    company_repo = get_company_repo(request)
    assert isinstance(company_repo, CompanyRepository)

    notes_value: str | None = notes.strip() or None
    company_repo.update_notes(company_id, notes_value)

    return tmpl.TemplateResponse(
        request,
        "partials/company_notes.html",
        {"company_id": company_id, "notes": notes_value or ""},
    )


@router.get("/{company_id}/partials/changes", response_class=HTMLResponse)
async def company_changes_partial(
    request: Request,
    company_id: int,
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """HTMX partial: change history for a company."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    summary = qs.get_company_summary(company_id)
    changes = summary.get("changes", []) if summary else []

    return tmpl.TemplateResponse(
        request,
        "partials/company_detail_sections.html",
        {"section": "changes", "items": changes, "company_id": company_id},
    )


@router.get("/{company_id}/partials/news", response_class=HTMLResponse)
async def company_news_partial(
    request: Request,
    company_id: int,
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """HTMX partial: news articles for a company."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    summary = qs.get_company_summary(company_id)
    articles = summary.get("news", []) if summary else []

    return tmpl.TemplateResponse(
        request,
        "partials/company_detail_sections.html",
        {"section": "news", "items": articles, "company_id": company_id},
    )


@router.get("/{company_id}/partials/social", response_class=HTMLResponse)
async def company_social_partial(
    request: Request,
    company_id: int,
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """HTMX partial: social media links for a company."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    summary = qs.get_company_summary(company_id)
    links = summary.get("social_links", []) if summary else []

    return tmpl.TemplateResponse(
        request,
        "partials/company_detail_sections.html",
        {"section": "social", "items": links, "company_id": company_id},
    )


@router.get("/{company_id}/partials/leadership", response_class=HTMLResponse)
async def company_leadership_partial(
    request: Request,
    company_id: int,
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """HTMX partial: leadership profiles for a company."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    summary = qs.get_company_summary(company_id)
    leaders = summary.get("leadership", []) if summary else []

    return tmpl.TemplateResponse(
        request,
        "partials/company_detail_sections.html",
        {"section": "leadership", "items": leaders, "company_id": company_id},
    )


# --- Entry Deletion Endpoints ---

_DELETE_TABLES: dict[str, str] = {
    "changes": "change_records",
    "news": "news_articles",
    "social": "social_media_links",
    "leadership": "company_leadership",
}


@router.delete("/{company_id}/{entry_type}/{entry_id}")
async def delete_entry(
    request: Request,
    company_id: int,
    entry_type: str,
    entry_id: int,
) -> HTMLResponse:
    """Delete a single entry by type and ID.

    Uses company_id guard to prevent cross-company deletion.
    Returns empty 200 so HTMX can remove the element from the DOM.
    """
    table = _DELETE_TABLES.get(entry_type)
    if not table:
        return HTMLResponse(status_code=404, content="Unknown entry type")

    import getpass
    from datetime import UTC, datetime

    operator = getattr(request.state, "operator", getpass.getuser())
    now = datetime.now(UTC).isoformat()

    db = request.app.state.db
    db.execute(
        f"DELETE FROM {table} WHERE id = ? AND company_id = ?",  # noqa: S608
        (entry_id, company_id),
    )
    # Log deletion for traceability
    db.execute(
        """INSERT INTO processing_errors
           (entity_type, entity_id, error_type, error_message,
            retry_count, created_at, performed_by)
           VALUES (?, ?, ?, ?, 0, ?, ?)""",
        (
            table,
            entry_id,
            "manual_deletion",
            f"Deleted {entry_type} entry {entry_id} for company {company_id}",
            now,
            operator,
        ),
    )
    db.connection.commit()
    return HTMLResponse(status_code=200, content="")
