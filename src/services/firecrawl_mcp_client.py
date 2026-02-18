"""Firecrawl MCP client stub (not implemented)."""

from __future__ import annotations

from typing import Any


class FirecrawlMCPClient:
    """MCP-based Firecrawl client (stub - raises NotImplementedError)."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def capture_snapshot(self, url: str) -> dict[str, Any]:
        raise NotImplementedError("MCP client not implemented")

    def batch_capture_snapshots(self, urls: list[str], **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("MCP client not implemented")
