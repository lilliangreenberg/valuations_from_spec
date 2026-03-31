"""Google OAuth 2.0 authentication service (imperative shell)."""

from __future__ import annotations

import json
import secrets
from datetime import UTC
from pathlib import Path
from typing import Any

import requests
import structlog
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow, InstalledAppFlow

from src.core.auth import (
    build_oauth_client_config,
    build_web_oauth_client_config,
    is_token_expired,
)
from src.models.auth import GoogleUserInfo, OAuthConfig, StoredCredentials

logger = structlog.get_logger(__name__)

AUTH_TOKEN_PATH = Path("data/auth.json")
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


class AuthService:
    """Handles Google OAuth 2.0 authentication flows for CLI and dashboard."""

    def __init__(self, client_id: str, client_secret: str) -> None:
        self.config = OAuthConfig(client_id=client_id, client_secret=client_secret)

    def load_credentials(self) -> StoredCredentials | None:
        """Load stored credentials from disk.

        Returns:
            Stored credentials if file exists and is valid, None otherwise.
        """
        if not AUTH_TOKEN_PATH.exists():
            return None
        try:
            raw = json.loads(AUTH_TOKEN_PATH.read_text())
            return StoredCredentials.model_validate(raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning("auth_credentials_corrupt", path=str(AUTH_TOKEN_PATH))
            return None

    def save_credentials(self, credentials: StoredCredentials) -> None:
        """Save credentials to disk."""
        AUTH_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        AUTH_TOKEN_PATH.write_text(credentials.model_dump_json(indent=2))
        logger.info("auth_credentials_saved", path=str(AUTH_TOKEN_PATH))

    def clear_credentials(self) -> None:
        """Remove stored credentials from disk."""
        if AUTH_TOKEN_PATH.exists():
            AUTH_TOKEN_PATH.unlink()
            logger.info("auth_credentials_cleared", path=str(AUTH_TOKEN_PATH))

    def cli_login(self) -> GoogleUserInfo:
        """Run the CLI OAuth login flow (opens browser).

        Uses InstalledAppFlow which opens a browser window and captures
        the callback on a local server.

        Returns:
            The authenticated user's Google profile info.
        """
        client_config = build_oauth_client_config(self.config.client_id, self.config.client_secret)
        flow = InstalledAppFlow.from_client_config(client_config, scopes=self.config.scopes)
        google_creds = flow.run_local_server(port=8085, open_browser=True)

        user_info = self.fetch_user_info(google_creds.token)

        stored = StoredCredentials(
            access_token=google_creds.token,
            refresh_token=google_creds.refresh_token,
            token_uri=google_creds.token_uri,
            client_id=google_creds.client_id,
            client_secret=google_creds.client_secret,
            expiry=google_creds.expiry,
            user_info=user_info,
        )
        self.save_credentials(stored)
        logger.info("cli_login_success", user=user_info.email)
        return user_info

    def get_authorization_url(self, redirect_uri: str) -> tuple[str, str, str | None]:
        """Generate the Google OAuth authorization URL for dashboard login.

        Args:
            redirect_uri: The callback URL (e.g., http://localhost:8000/auth/callback).

        Returns:
            Tuple of (authorization_url, state, code_verifier).
            code_verifier must be stored in session and passed to exchange_code().
        """
        client_config = build_web_oauth_client_config(
            self.config.client_id, self.config.client_secret
        )
        flow = Flow.from_client_config(
            client_config,
            scopes=self.config.scopes,
            redirect_uri=redirect_uri,
        )
        state = secrets.token_urlsafe(32)
        authorization_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
            state=state,
        )
        # Extract the PKCE code verifier so we can pass it to exchange_code
        code_verifier = flow.code_verifier
        return authorization_url, state, code_verifier

    def exchange_code(
        self, code: str, redirect_uri: str, code_verifier: str | None = None
    ) -> StoredCredentials:
        """Exchange an authorization code for credentials (dashboard callback).

        Args:
            code: The authorization code from Google's callback.
            redirect_uri: Must match the redirect_uri used in get_authorization_url.
            code_verifier: The PKCE code verifier from get_authorization_url().

        Returns:
            Complete stored credentials with user info.
        """
        client_config = build_web_oauth_client_config(
            self.config.client_id, self.config.client_secret
        )
        flow = Flow.from_client_config(
            client_config,
            scopes=self.config.scopes,
            redirect_uri=redirect_uri,
        )
        flow.code_verifier = code_verifier
        flow.fetch_token(code=code)
        google_creds = flow.credentials

        user_info = self.fetch_user_info(google_creds.token)

        return StoredCredentials(
            access_token=google_creds.token,
            refresh_token=google_creds.refresh_token,
            token_uri=google_creds.token_uri,
            client_id=google_creds.client_id,
            client_secret=google_creds.client_secret,
            expiry=google_creds.expiry,
            user_info=user_info,
        )

    def get_current_user(self) -> GoogleUserInfo | None:
        """Get the currently authenticated user, refreshing token if needed.

        Returns:
            User info if authenticated, None otherwise.
        """
        stored = self.load_credentials()
        if stored is None:
            return None

        if is_token_expired(stored.expiry):
            refreshed = self._refresh_credentials(stored)
            if refreshed is None:
                return None
            stored = refreshed

        return stored.user_info

    def is_authenticated(self) -> bool:
        """Check if there is a valid (or refreshable) authentication session."""
        return self.get_current_user() is not None

    def fetch_user_info(self, access_token: str) -> GoogleUserInfo:
        """Fetch user profile from Google's userinfo endpoint.

        Args:
            access_token: A valid Google OAuth access token.

        Returns:
            GoogleUserInfo with email, name, and picture.

        Raises:
            requests.HTTPError: If the userinfo request fails.
        """
        resp = requests.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return GoogleUserInfo(
            email=data["email"],
            name=data.get("name", data["email"]),
            picture=data.get("picture"),
        )

    def _refresh_credentials(self, stored: StoredCredentials) -> StoredCredentials | None:
        """Attempt to refresh expired credentials.

        Returns:
            Updated credentials if refresh succeeded, None if refresh failed.
        """
        if stored.refresh_token is None:
            logger.warning("auth_no_refresh_token")
            return None

        try:
            creds = Credentials(  # type: ignore[no-untyped-call]
                token=stored.access_token,
                refresh_token=stored.refresh_token,
                token_uri=stored.token_uri,
                client_id=stored.client_id,
                client_secret=stored.client_secret,
            )
            creds.refresh(GoogleAuthRequest())

            access_token: str = creds.token or ""
            refreshed = StoredCredentials(
                access_token=access_token,
                refresh_token=creds.refresh_token or stored.refresh_token,
                token_uri=stored.token_uri,
                client_id=stored.client_id,
                client_secret=stored.client_secret,
                expiry=creds.expiry.replace(tzinfo=UTC) if creds.expiry else None,
                user_info=stored.user_info,
            )
            self.save_credentials(refreshed)
            logger.info("auth_token_refreshed", user=stored.user_info.email)
            return refreshed
        except Exception:
            logger.warning("auth_refresh_failed", exc_info=True)
            return None
