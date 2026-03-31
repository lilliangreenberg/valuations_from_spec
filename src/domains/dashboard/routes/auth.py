"""Authentication routes for Google OAuth 2.0 login/logout."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login-page", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    """Render the login page with 'Sign in with Google' button."""
    templates = request.app.state.templates
    auth_service = getattr(request.app.state, "auth_service", None)
    oauth_configured = auth_service is not None
    resp: HTMLResponse = templates.TemplateResponse(
        "login.html",
        {"request": request, "oauth_configured": oauth_configured},
    )
    return resp


@router.get("/login")
async def login(request: Request) -> RedirectResponse:
    """Redirect to Google OAuth consent screen."""
    auth_service = request.app.state.auth_service
    base_url = str(request.base_url).rstrip("/")
    redirect_uri = f"{base_url}/auth/callback"
    authorization_url, state = auth_service.get_authorization_url(redirect_uri)
    request.session["oauth_state"] = state
    return RedirectResponse(url=authorization_url, status_code=302)


@router.get("/callback")
async def oauth_callback(request: Request) -> RedirectResponse:
    """Handle Google OAuth callback, store user in session."""
    code = request.query_params.get("code")
    if not code:
        logger.warning("oauth_callback_missing_code")
        return RedirectResponse(url="/auth/login-page", status_code=302)

    auth_service = request.app.state.auth_service
    base_url = str(request.base_url).rstrip("/")
    redirect_uri = f"{base_url}/auth/callback"

    try:
        stored_creds = auth_service.exchange_code(code, redirect_uri)
        request.session["user"] = {
            "email": stored_creds.user_info.email,
            "name": stored_creds.user_info.name,
            "picture": stored_creds.user_info.picture,
        }
        logger.info("oauth_login_success", user=stored_creds.user_info.email)
        return RedirectResponse(url="/", status_code=302)
    except Exception:
        logger.exception("oauth_callback_failed")
        return RedirectResponse(url="/auth/login-page", status_code=302)


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    """Clear session and redirect to login page."""
    user = request.session.get("user", {})
    request.session.clear()
    logger.info("oauth_logout", user=user.get("email", "unknown"))
    return RedirectResponse(url="/auth/login-page", status_code=302)
