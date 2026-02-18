"""MCP batch request/response bridge (stub)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MCPBatchRequest:
    """Batch request for MCP processing."""

    urls: list[str] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPBatchResponse:
    """Batch response from MCP processing."""

    results: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    total: int = 0
    completed: int = 0
