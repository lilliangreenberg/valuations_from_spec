"""Risk surface routes -- the views that catch blind spots.

Exposes three cross-domain queries that the existing widgets don't:

- Status vs news contradictions (companies marked operational despite
  significant-negative news)
- Recent critical leadership departures across the portfolio
- Change-frequency anomalies (spikes or droughts vs per-company baseline)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from src.domains.dashboard.dependencies import get_query_service, get_templates

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/", response_class=HTMLResponse)
async def risk_page(
    request: Request,
    query_service: object = Depends(get_query_service),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """Render the risk surface page."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.query_service import QueryService

    qs = query_service
    assert isinstance(qs, QueryService)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    contradictions = qs.get_status_news_contradictions(days=30, limit=50)
    departures = qs.get_recent_leadership_departures(days=90, limit=50)
    anomalies = qs.get_change_frequency_anomalies(days=90, baseline_days=365)

    return tmpl.TemplateResponse(
        request,
        "risk.html",
        {
            "contradictions": contradictions,
            "departures": departures,
            "anomalies": anomalies,
        },
    )
