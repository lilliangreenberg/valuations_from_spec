"""Application configuration model using pydantic-settings."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    """Application configuration loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    airtable_api_key: str
    airtable_base_id: str
    firecrawl_api_key: str
    database_path: str = "data/companies.db"
    log_level: str = "INFO"
    max_retry_attempts: int = 2
    anthropic_api_key: str | None = None
    llm_model: str = "claude-haiku-4-5-20251001"
    llm_validation_enabled: bool = False
    kagi_api_key: str | None = None

    @field_validator("airtable_api_key")
    @classmethod
    def validate_airtable_api_key(cls, value: str) -> str:
        """Airtable API key must be non-empty."""
        if not value.strip():
            msg = "airtable_api_key must not be empty"
            raise ValueError(msg)
        return value

    @field_validator("airtable_base_id")
    @classmethod
    def validate_airtable_base_id(cls, value: str) -> str:
        """Airtable base ID must match the expected pattern."""
        if not re.fullmatch(r"app[a-zA-Z0-9]+", value):
            msg = "airtable_base_id must match pattern ^app[a-zA-Z0-9]+$"
            raise ValueError(msg)
        return value

    @field_validator("firecrawl_api_key")
    @classmethod
    def validate_firecrawl_api_key(cls, value: str) -> str:
        """Firecrawl API key must be non-empty."""
        if not value.strip():
            msg = "firecrawl_api_key must not be empty"
            raise ValueError(msg)
        return value

    @field_validator("database_path")
    @classmethod
    def validate_database_path(cls, value: str) -> str:
        """Ensure parent directory exists, creating it if necessary."""
        parent = Path(value).parent
        parent.mkdir(parents=True, exist_ok=True)
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        """Log level must be a valid Python logging level."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper_value = value.upper()
        if upper_value not in valid_levels:
            msg = f"log_level must be one of {', '.join(sorted(valid_levels))}"
            raise ValueError(msg)
        return upper_value

    @field_validator("max_retry_attempts")
    @classmethod
    def validate_max_retry_attempts(cls, value: int) -> int:
        """Max retry attempts must be between 0 and 5."""
        if value < 0 or value > 5:
            msg = "max_retry_attempts must be between 0 and 5"
            raise ValueError(msg)
        return value
