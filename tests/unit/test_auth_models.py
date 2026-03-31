"""Unit tests for authentication data models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.models.auth import GoogleUserInfo, OAuthConfig, StoredCredentials


class TestGoogleUserInfo:
    def test_valid_user_info(self) -> None:
        user = GoogleUserInfo(email="alice@example.com", name="Alice Smith")
        assert user.email == "alice@example.com"
        assert user.name == "Alice Smith"
        assert user.picture is None

    def test_with_picture(self) -> None:
        user = GoogleUserInfo(
            email="alice@example.com",
            name="Alice Smith",
            picture="https://example.com/photo.jpg",
        )
        assert user.picture == "https://example.com/photo.jpg"

    def test_missing_email_raises(self) -> None:
        with pytest.raises(ValueError):
            GoogleUserInfo(name="Alice Smith")  # type: ignore[call-arg]

    def test_missing_name_raises(self) -> None:
        with pytest.raises(ValueError):
            GoogleUserInfo(email="alice@example.com")  # type: ignore[call-arg]


class TestStoredCredentials:
    def test_valid_credentials(self) -> None:
        creds = StoredCredentials(
            access_token="ya29.access",
            refresh_token="1//refresh",
            client_id="client-id",
            client_secret="client-secret",
            expiry=datetime(2026, 3, 30, 12, 0, 0, tzinfo=UTC),
            user_info=GoogleUserInfo(email="alice@example.com", name="Alice"),
        )
        assert creds.access_token == "ya29.access"
        assert creds.token_uri == "https://oauth2.googleapis.com/token"

    def test_roundtrip_serialization(self) -> None:
        creds = StoredCredentials(
            access_token="ya29.access",
            refresh_token="1//refresh",
            client_id="client-id",
            client_secret="client-secret",
            expiry=datetime(2026, 3, 30, 12, 0, 0, tzinfo=UTC),
            user_info=GoogleUserInfo(email="alice@example.com", name="Alice"),
        )
        json_str = creds.model_dump_json()
        restored = StoredCredentials.model_validate_json(json_str)
        assert restored.user_info.email == "alice@example.com"
        assert restored.access_token == "ya29.access"

    def test_optional_refresh_token(self) -> None:
        creds = StoredCredentials(
            access_token="ya29.access",
            client_id="cid",
            client_secret="csec",
            user_info=GoogleUserInfo(email="a@b.com", name="A"),
        )
        assert creds.refresh_token is None
        assert creds.expiry is None


class TestOAuthConfig:
    def test_defaults(self) -> None:
        config = OAuthConfig(client_id="cid", client_secret="csec")
        assert len(config.scopes) == 3
        assert "openid" in config.scopes

    def test_custom_scopes(self) -> None:
        config = OAuthConfig(
            client_id="cid", client_secret="csec", scopes=["openid"]
        )
        assert config.scopes == ["openid"]
