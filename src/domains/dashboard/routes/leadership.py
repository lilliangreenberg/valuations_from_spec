"""Leadership profiles view routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from src.domains.dashboard.dependencies import get_query_service, get_templates

router = APIRouter(prefix="/leadership", tags=["leadership"])


@router.get("/", response_class=HTMLResponse)
async def leadership_page(
    request: Request,
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """Render the leadership view page."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    result = qs.get_leadership_overview()

    return tmpl.TemplateResponse(
        request,
        "leadership.html",
        {
            "leaders": result["items"],
            "total": result["total"],
            "page": result["page"],
            "per_page": result["per_page"],
            "total_pages": result["total_pages"],
            "current_only": True,
        },
    )


@router.get("/partials/list", response_class=HTMLResponse)
async def leadership_list_partial(
    request: Request,
    current_only: bool = True,
    page: int = 1,
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """HTMX partial: leadership profiles list."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    result = qs.get_leadership_overview(current_only=current_only, page=page)

    return tmpl.TemplateResponse(
        request,
        "partials/leadership_card.html",
        {
            "leaders": result["items"],
            "total": result["total"],
            "page": result["page"],
            "per_page": result["per_page"],
            "total_pages": result["total_pages"],
            "current_only": current_only,
        },
    )
