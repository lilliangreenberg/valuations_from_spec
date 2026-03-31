"""Pure functions for authentication logic (functional core, no I/O)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.models.auth import GoogleUserInfo


def is_token_expired(expiry: datetime | None, buffer_minutes: int = 5) -> bool:
    """Check if a token has expired or will expire within the buffer period.

    Args:
        expiry: Token expiration time (UTC). None means no expiry info available.
        buffer_minutes: Minutes before actual expiry to consider token expired.

    Returns:
        True if the token is expired or expiry is unknown.
    """
    if expiry is None:
        return True
    # Ensure expiry is timezone-aware (treat naive as UTC)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    return datetime.now(UTC) >= expiry - timedelta(minutes=buffer_minutes)


def get_operator_from_user_info(user_info: GoogleUserInfo) -> str:
    """Extract the operator identifier from Google user info.

    Returns the user's full name for human-readable audit trails.
    Falls back to email if name is not available.
    """
    return user_info.name if user_info.name else user_info.email


def build_oauth_client_config(client_id: str, client_secret: str) -> dict[str, Any]:
    """Build the client configuration dict expected by google-auth-oauthlib.

    This produces the format that InstalledAppFlow.from_client_config() expects.
    """
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        },
    }


def build_web_oauth_client_config(client_id: str, client_secret: str) -> dict[str, Any]:
    """Build the client configuration dict for web application OAuth flow.

    This produces the format that google_auth_oauthlib.flow.Flow.from_client_config() expects
    for web applications (dashboard).
    """
    return {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        },
    }
