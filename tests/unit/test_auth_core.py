"""Unit tests for authentication pure functions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.core.auth import (
    build_oauth_client_config,
    build_web_oauth_client_config,
    get_operator_from_user_info,
    is_token_expired,
)
from src.models.auth import GoogleUserInfo


class TestIsTokenExpired:
    def test_none_expiry_is_expired(self) -> None:
        assert is_token_expired(None) is True

    def test_future_expiry_not_expired(self) -> None:
        future = datetime.now(UTC) + timedelta(hours=1)
        assert is_token_expired(future) is False

    def test_past_expiry_is_expired(self) -> None:
        past = datetime.now(UTC) - timedelta(hours=1)
        assert is_token_expired(past) is True

    def test_within_buffer_is_expired(self) -> None:
        # 3 minutes in the future, but buffer is 5 minutes
        near_future = datetime.now(UTC) + timedelta(minutes=3)
        assert is_token_expired(near_future, buffer_minutes=5) is True

    def test_beyond_buffer_not_expired(self) -> None:
        near_future = datetime.now(UTC) + timedelta(minutes=10)
        assert is_token_expired(near_future, buffer_minutes=5) is False

    def test_naive_datetime_treated_as_utc(self) -> None:
        future = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)
        assert is_token_expired(future) is False


class TestGetOperatorFromUserInfo:
    def test_returns_name(self) -> None:
        user = GoogleUserInfo(email="alice@example.com", name="Alice Smith")
        assert get_operator_from_user_info(user) == "Alice Smith"

    def test_falls_back_to_email_when_no_name(self) -> None:
        user = GoogleUserInfo(email="alice@example.com", name="")
        assert get_operator_from_user_info(user) == "alice@example.com"


class TestBuildOAuthClientConfig:
    def test_installed_format(self) -> None:
        config = build_oauth_client_config("my-client-id", "my-secret")
        assert "installed" in config
        installed = config["installed"]
        assert installed["client_id"] == "my-client-id"
        assert installed["client_secret"] == "my-secret"
        assert "token_uri" in installed
        assert "auth_uri" in installed

    def test_web_format(self) -> None:
        config = build_web_oauth_client_config("my-client-id", "my-secret")
        assert "web" in config
        web = config["web"]
        assert web["client_id"] == "my-client-id"
        assert web["client_secret"] == "my-secret"
