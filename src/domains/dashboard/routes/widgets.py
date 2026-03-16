"""Widget endpoint routes for the dashboard homepage.

Each widget has an HTML partial endpoint (for HTMX refresh) and the trending
widget additionally exposes a JSON data endpoint for Chart.js updates.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

from src.domains.dashboard.dependencies import get_query_service, get_templates

router = APIRouter(prefix="/widgets", tags=["widgets"])


@router.get("/changes", response_class=HTMLResponse)
async def changes_widget(
    request: Request,
    size: str = "small",
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """Render the changes-since-last-scan widget."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.core.widget_data import format_changes_widget
    from src.domains.dashboard.core.widget_types import validate_widget_size
    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    validated_size = validate_widget_size("changes", size)
    raw = qs.get_changes_since_last_scan()
    data = format_changes_widget(raw, validated_size)

    return tmpl.TemplateResponse(
        request,
        "partials/widgets/changes_widget.html",
        {"widget": data},
    )


@router.get("/alerts", response_class=HTMLResponse)
async def alerts_widget(
    request: Request,
    size: str = "small",
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """Render the alerts summary widget."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.core.widget_data import format_alerts_widget
    from src.domains.dashboard.core.widget_types import validate_widget_size
    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    validated_size = validate_widget_size("alerts", size)
    raw = qs.get_alerts_summary()
    data = format_alerts_widget(raw, validated_size)

    return tmpl.TemplateResponse(
        request,
        "partials/widgets/alerts_widget.html",
        {"widget": data},
    )


@router.get("/trending", response_class=HTMLResponse)
async def trending_widget(
    request: Request,
    size: str = "large",
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """Render the trending graph widget (canvas + Chart.js init)."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.core.widget_data import build_trending_chart_config
    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    raw = qs.get_trending_data()
    chart_config = build_trending_chart_config(raw)

    return tmpl.TemplateResponse(
        request,
        "partials/widgets/trending_widget.html",
        {"widget": {"chart_config": chart_config, "size": size}},
    )


@router.get("/trending/data")
async def trending_data(
    request: Request,
    weeks: int = 12,
    query_service: object = Depends(get_query_service),
) -> JSONResponse:
    """Return trending data as JSON for Chart.js updates."""
    from src.domains.dashboard.core.widget_data import build_trending_chart_config
    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)

    raw = qs.get_trending_data(weeks=weeks)
    chart_config = build_trending_chart_config(raw)

    return JSONResponse(content=chart_config)


@router.get("/freshness", response_class=HTMLResponse)
async def freshness_widget(
    request: Request,
    size: str = "small",
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """Render the snapshot freshness widget."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.core.widget_data import format_freshness_widget
    from src.domains.dashboard.core.widget_types import validate_widget_size
    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    validated_size = validate_widget_size("freshness", size)
    raw = qs.get_snapshot_freshness()
    data = format_freshness_widget(raw, validated_size)

    return tmpl.TemplateResponse(
        request,
        "partials/widgets/freshness_widget.html",
        {"widget": data},
    )


@router.get("/activity", response_class=HTMLResponse)
async def activity_widget(
    request: Request,
    size: str = "large",
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """Render the recent activity feed widget."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    activity = qs.get_activity_feed(limit=10)

    return tmpl.TemplateResponse(
        request,
        "partials/widgets/activity_widget.html",
        {"widget": {"activity": activity, "size": size}},
    )


@router.get("/health-grid", response_class=HTMLResponse)
async def health_grid_widget(
    request: Request,
    size: str = "large",
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """Render the company health grid widget."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    companies = qs.get_company_health_grid()

    return tmpl.TemplateResponse(
        request,
        "partials/widgets/health_grid_widget.html",
        {"widget": {"companies": companies, "size": size}},
    )
