"""Real Firecrawl MCP client stub (not implemented)."""

from __future__ import annotations

from typing import Any


class RealFirecrawlMCPClient:
    """Real MCP-based Firecrawl client (stub - raises NotImplementedError)."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def discover_social_media(self, url: str) -> dict[str, Any]:
        raise NotImplementedError("Real MCP client not implemented")
