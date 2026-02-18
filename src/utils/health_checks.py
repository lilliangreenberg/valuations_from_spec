"""API health check utilities."""

from __future__ import annotations

import requests

from src.utils.logger import get_logger

logger = get_logger(__name__)


def check_firecrawl_health(api_key: str, timeout: int = 10) -> bool:
    """Check if Firecrawl API is reachable and authenticated."""
    try:
        response = requests.get(
            "https://api.firecrawl.dev/v1/health",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        return response.status_code == 200
    except requests.RequestException as exc:
        logger.warning("firecrawl_health_check_failed", error=str(exc))
        return False


def check_airtable_health(api_key: str, base_id: str, timeout: int = 10) -> bool:
    """Check if Airtable API is reachable and authenticated."""
    try:
        response = requests.get(
            f"https://api.airtable.com/v0/{base_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        return response.status_code in (200, 404)
    except requests.RequestException as exc:
        logger.warning("airtable_health_check_failed", error=str(exc))
        return False


def check_kagi_health(api_key: str, timeout: int = 10) -> bool:
    """Check if Kagi API is reachable and authenticated."""
    try:
        response = requests.get(
            "https://kagi.com/api/v0/search",
            headers={"Authorization": f"Bot {api_key}"},
            params={"q": "test", "limit": "1"},
            timeout=timeout,
        )
        return response.status_code in (200, 401)
    except requests.RequestException as exc:
        logger.warning("kagi_health_check_failed", error=str(exc))
        return False
