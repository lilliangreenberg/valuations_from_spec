"""Contract tests for the AuthService (mocked Google APIs, real file I/O)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from src.models.auth import GoogleUserInfo, StoredCredentials
from src.services.auth import AuthService


@pytest.fixture()
def auth_service() -> AuthService:
    return AuthService(client_id="test-client-id", client_secret="test-client-secret")


@pytest.fixture()
def sample_credentials() -> StoredCredentials:
    return StoredCredentials(
        access_token="ya29.test-access-token",
        refresh_token="1//test-refresh-token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="test-client-id",
        client_secret="test-client-secret",
        expiry=datetime(2026, 12, 31, 12, 0, 0, tzinfo=UTC),
        user_info=GoogleUserInfo(
            email="alice@example.com",
            name="Alice Smith",
            picture="https://example.com/photo.jpg",
        ),
    )


class TestCredentialPersistence:
    def test_save_and_load_roundtrip(
        self, auth_service: AuthService, sample_credentials: StoredCredentials, tmp_path: Path
    ) -> None:
        token_path = tmp_path / "auth.json"
        with patch("src.services.auth.AUTH_TOKEN_PATH", token_path):
            auth_service.save_credentials(sample_credentials)
            loaded = auth_service.load_credentials()

        assert loaded is not None
        assert loaded.user_info.email == "alice@example.com"
        assert loaded.access_token == "ya29.test-access-token"

    def test_load_missing_file(self, auth_service: AuthService, tmp_path: Path) -> None:
        token_path = tmp_path / "nonexistent" / "auth.json"
        with patch("src.services.auth.AUTH_TOKEN_PATH", token_path):
            result = auth_service.load_credentials()
        assert result is None

    def test_load_corrupt_file(self, auth_service: AuthService, tmp_path: Path) -> None:
        token_path = tmp_path / "auth.json"
        token_path.write_text("not valid json {{{")
        with patch("src.services.auth.AUTH_TOKEN_PATH", token_path):
            result = auth_service.load_credentials()
        assert result is None

    def test_clear_credentials(
        self, auth_service: AuthService, sample_credentials: StoredCredentials, tmp_path: Path
    ) -> None:
        token_path = tmp_path / "auth.json"
        with patch("src.services.auth.AUTH_TOKEN_PATH", token_path):
            auth_service.save_credentials(sample_credentials)
            assert token_path.exists()
            auth_service.clear_credentials()
            assert not token_path.exists()

    def test_clear_nonexistent_is_noop(self, auth_service: AuthService, tmp_path: Path) -> None:
        token_path = tmp_path / "auth.json"
        with patch("src.services.auth.AUTH_TOKEN_PATH", token_path):
            auth_service.clear_credentials()  # Should not raise


class TestGetCurrentUser:
    def test_returns_user_when_valid(
        self, auth_service: AuthService, sample_credentials: StoredCredentials, tmp_path: Path
    ) -> None:
        token_path = tmp_path / "auth.json"
        with patch("src.services.auth.AUTH_TOKEN_PATH", token_path):
            auth_service.save_credentials(sample_credentials)
            user = auth_service.get_current_user()

        assert user is not None
        assert user.email == "alice@example.com"

    def test_returns_none_when_not_logged_in(
        self, auth_service: AuthService, tmp_path: Path
    ) -> None:
        token_path = tmp_path / "nonexistent" / "auth.json"
        with patch("src.services.auth.AUTH_TOKEN_PATH", token_path):
            user = auth_service.get_current_user()
        assert user is None

    def test_refreshes_expired_token(
        self, auth_service: AuthService, tmp_path: Path
    ) -> None:
        expired_creds = StoredCredentials(
            access_token="ya29.expired",
            refresh_token="1//refresh",
            client_id="test-client-id",
            client_secret="test-client-secret",
            expiry=datetime(2020, 1, 1, tzinfo=UTC),
            user_info=GoogleUserInfo(email="alice@example.com", name="Alice"),
        )
        token_path = tmp_path / "auth.json"
        with (
            patch("src.services.auth.AUTH_TOKEN_PATH", token_path),
            patch.object(auth_service, "_refresh_credentials") as mock_refresh,
        ):
            auth_service.save_credentials(expired_creds)
            mock_refresh.return_value = expired_creds.model_copy(
                update={
                    "access_token": "ya29.refreshed",
                    "expiry": datetime.now(UTC) + timedelta(hours=1),
                }
            )
            user = auth_service.get_current_user()

        assert user is not None
        assert user.email == "alice@example.com"
        mock_refresh.assert_called_once()

    def test_returns_none_when_refresh_fails(
        self, auth_service: AuthService, tmp_path: Path
    ) -> None:
        expired_creds = StoredCredentials(
            access_token="ya29.expired",
            refresh_token="1//refresh",
            client_id="test-client-id",
            client_secret="test-client-secret",
            expiry=datetime(2020, 1, 1, tzinfo=UTC),
            user_info=GoogleUserInfo(email="alice@example.com", name="Alice"),
        )
        token_path = tmp_path / "auth.json"
        with (
            patch("src.services.auth.AUTH_TOKEN_PATH", token_path),
            patch.object(auth_service, "_refresh_credentials", return_value=None),
        ):
            auth_service.save_credentials(expired_creds)
            user = auth_service.get_current_user()

        assert user is None


class TestIsAuthenticated:
    def test_true_when_valid_credentials(
        self, auth_service: AuthService, sample_credentials: StoredCredentials, tmp_path: Path
    ) -> None:
        token_path = tmp_path / "auth.json"
        with patch("src.services.auth.AUTH_TOKEN_PATH", token_path):
            auth_service.save_credentials(sample_credentials)
            assert auth_service.is_authenticated() is True

    def test_false_when_no_credentials(
        self, auth_service: AuthService, tmp_path: Path
    ) -> None:
        token_path = tmp_path / "nonexistent.json"
        with patch("src.services.auth.AUTH_TOKEN_PATH", token_path):
            assert auth_service.is_authenticated() is False


class TestFetchUserInfo:
    def test_fetches_user_info(self, auth_service: AuthService) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "email": "alice@example.com",
            "name": "Alice Smith",
            "picture": "https://example.com/photo.jpg",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("src.services.auth.requests.get", return_value=mock_response) as mock_get:
            user = auth_service.fetch_user_info("ya29.test-token")

        assert user.email == "alice@example.com"
        assert user.name == "Alice Smith"
        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args
        assert "Bearer ya29.test-token" in str(call_kwargs)

    def test_uses_email_as_name_fallback(self, auth_service: AuthService) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {"email": "alice@example.com"}
        mock_response.raise_for_status = MagicMock()

        with patch("src.services.auth.requests.get", return_value=mock_response):
            user = auth_service.fetch_user_info("ya29.test-token")

        assert user.name == "alice@example.com"
