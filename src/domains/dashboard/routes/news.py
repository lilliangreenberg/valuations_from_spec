"""News articles view routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from src.domains.dashboard.dependencies import get_query_service, get_templates

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/", response_class=HTMLResponse)
async def news_page(
    request: Request,
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """Render the news view page."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    result = qs.get_news_filtered()

    return tmpl.TemplateResponse(
        request,
        "news.html",
        {
            "articles": result["items"],
            "total": result["total"],
            "page": result["page"],
            "per_page": result["per_page"],
            "total_pages": result["total_pages"],
            "classification": "",
            "sentiment": "",
            "days": 180,
        },
    )


@router.get("/partials/list", response_class=HTMLResponse)
async def news_list_partial(
    request: Request,
    classification: str = "",
    sentiment: str = "",
    days: int = 180,
    page: int = 1,
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """HTMX partial: filtered news list."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    result = qs.get_news_filtered(
        classification=classification or None,
        sentiment=sentiment or None,
        days=days,
        page=page,
    )

    return tmpl.TemplateResponse(
        request,
        "partials/news_filters.html",
        {
            "articles": result["items"],
            "total": result["total"],
            "page": result["page"],
            "per_page": result["per_page"],
            "total_pages": result["total_pages"],
            "classification": classification,
            "sentiment": sentiment,
            "days": days,
        },
    )
