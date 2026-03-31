"""Authentication middleware for the dashboard."""

from __future__ import annotations

import getpass
from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse, Response

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request

# Paths that do not require authentication
_PUBLIC_PREFIXES = ("/auth/", "/static/")


class AuthMiddleware(BaseHTTPMiddleware):
    """Redirects unauthenticated requests to the login page.

    Sets request.state.operator from the session user email for
    downstream dependency injection.
    """

    def __init__(self, app: Any, *, oauth_enabled: bool = True) -> None:
        super().__init__(app)
        self.oauth_enabled = oauth_enabled

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        path = request.url.path

        # Always allow public paths
        if any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES):
            request.state.operator = getpass.getuser()
            response: Response = await call_next(request)
            return response

        if self.oauth_enabled:
            user_data = request.session.get("user")
            if user_data is None:
                return RedirectResponse(url="/auth/login-page", status_code=302)
            request.state.operator = user_data.get("name", user_data["email"])
        else:
            request.state.operator = getpass.getuser()

        response = await call_next(request)
        return response
