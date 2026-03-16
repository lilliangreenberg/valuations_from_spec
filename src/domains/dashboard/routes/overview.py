"""Overview / landing page routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from src.domains.dashboard.dependencies import get_query_service, get_templates

router = APIRouter(tags=["overview"])


@router.get("/", response_class=HTMLResponse)
async def overview_page(
    request: Request,
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """Render the dashboard overview page with widget grid."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.core.widget_data import (
        build_trending_chart_config,
        format_alerts_widget,
        format_changes_widget,
        format_freshness_widget,
    )
    from src.domains.dashboard.core.widget_types import (
        LAYOUT_PRESETS,
        WIDGET_REGISTRY,
        get_default_widget_config,
    )
    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    # Fetch all widget data for server-side initial render
    changes_raw = qs.get_changes_since_last_scan()
    alerts_raw = qs.get_alerts_summary()
    trending_raw = qs.get_trending_data()
    freshness_raw = qs.get_snapshot_freshness()
    activity = qs.get_activity_feed(limit=10)
    health_grid = qs.get_company_health_grid()

    # Format widget data (use default sizes from registry)
    widget_data = {
        "changes": format_changes_widget(changes_raw, WIDGET_REGISTRY["changes"]["default_size"]),
        "alerts": format_alerts_widget(alerts_raw, WIDGET_REGISTRY["alerts"]["default_size"]),
        "trending": {
            "chart_config": build_trending_chart_config(trending_raw),
            "size": WIDGET_REGISTRY["trending"]["default_size"],
        },
        "freshness": format_freshness_widget(
            freshness_raw, WIDGET_REGISTRY["freshness"]["default_size"]
        ),
        "activity": {
            "activity": activity,
            "size": WIDGET_REGISTRY["activity"]["default_size"],
        },
        "health_grid": {
            "companies": health_grid,
            "size": WIDGET_REGISTRY["health_grid"]["default_size"],
        },
    }

    return tmpl.TemplateResponse(
        request,
        "overview.html",
        {
            "widget_data": widget_data,
            "widget_registry": WIDGET_REGISTRY,
            "layout_presets": LAYOUT_PRESETS,
            "default_config": get_default_widget_config(),
        },
    )


@router.get("/partials/activity-feed", response_class=HTMLResponse)
async def activity_feed_partial(
    request: Request,
    page: int = 1,
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """HTMX partial: load more activity feed items."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    offset = (page - 1) * 30
    activity = qs.get_activity_feed(limit=30, offset=offset)

    return tmpl.TemplateResponse(
        request,
        "partials/activity_feed.html",
        {"activity": activity, "page": page},
    )


@router.get("/partials/stats", response_class=HTMLResponse)
async def stats_partial(
    request: Request,
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """HTMX partial: refreshable stats cards."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    stats = qs.get_overview_stats()

    return tmpl.TemplateResponse(
        request,
        "partials/stats_cards.html",
        {"stats": stats},
    )
