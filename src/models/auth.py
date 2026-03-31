"""Authentication data models for Google OAuth 2.0."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from pydantic import BaseModel


class GoogleUserInfo(BaseModel):
    """User information retrieved from Google OAuth."""

    email: str
    name: str
    picture: str | None = None


class StoredCredentials(BaseModel):
    """OAuth credentials persisted to disk for session memory."""

    access_token: str
    refresh_token: str | None = None
    token_uri: str = "https://oauth2.googleapis.com/token"
    client_id: str
    client_secret: str
    expiry: datetime | None = None
    user_info: GoogleUserInfo


class OAuthConfig(BaseModel):
    """Google OAuth client configuration."""

    client_id: str
    client_secret: str
    scopes: list[str] = [
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    ]
