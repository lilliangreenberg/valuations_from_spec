"""Content checksum computation."""

from __future__ import annotations

import hashlib


def compute_content_checksum(content: str) -> str:
    """Compute MD5 hex digest of content string.

    Returns lowercase 32-character hex string.
    """
    return hashlib.md5(content.encode("utf-8")).hexdigest()
