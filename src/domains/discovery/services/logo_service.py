"""Logo extraction and comparison service."""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class LogoService:
    """Extracts and compares company logos."""

    def extract_logo_from_html(self, html: str, base_url: str) -> dict[str, Any] | None:
        """Extract the primary logo from HTML content.

        Looks for common logo patterns in HTML.
        Returns dict with image data or None.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # Strategy 1: og:image meta tag
        og_image = soup.find("meta", attrs={"property": "og:image"})
        if og_image:
            content = og_image.get("content", "")
            if isinstance(content, str) and content:
                return {
                    "source_url": content,
                    "extraction_location": "og_image",
                }

        # Strategy 2: Logo in header/nav with common patterns
        for tag in soup.find_all("img"):
            src = tag.get("src", "")
            alt = (tag.get("alt") or "").lower()
            classes = " ".join(tag.get("class", [])).lower()

            if (
                any(kw in alt + classes for kw in ("logo", "brand", "site-logo"))
                and isinstance(src, str)
                and src
            ):
                return {
                    "source_url": src,
                    "extraction_location": "header",
                }

        # Strategy 3: Favicon
        for link_tag in soup.find_all("link", rel=True):
            rels = link_tag.get("rel", [])
            if isinstance(rels, list) and any("icon" in r.lower() for r in rels):
                href = link_tag.get("href", "")
                if isinstance(href, str) and href:
                    return {
                        "source_url": href,
                        "extraction_location": "favicon",
                    }

        return None
