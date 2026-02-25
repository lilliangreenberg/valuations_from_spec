"""Logo extraction and comparison service."""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# URL patterns for logos that should never be collected.
# These are third-party logos that appear on many portfolio company pages
# but do not belong to the company itself.
_SKIP_URL_PATTERNS: list[str] = [
    # Y Combinator
    "ycombinator",
    "y-combinator",
    "yc-logo",
    "yclogo",
    "yc.png",
    "yc.svg",
    "yc.jpg",
    "/yc_",
    # Social media platforms
    "tiktok-common.",
    "ttwstatic.com",
    # Google
    "google-logo",
    "google-rating",
    # Generic SaaS favicons (shared across many sites, not company-specific)
    "calendly.com/assets/favicon",
    "hsappstatic.net",
    # Platform error/default pages
    "wix-public/",
    "error-pages/logo",
]

# Alt-text patterns that indicate a third-party logo, not the company's own.
_SKIP_ALT_PATTERNS: list[str] = [
    "google review",
    "google rating",
    "app store",
    "google play",
    "play store",
    "tiktok",
]


def _is_third_party_logo(url: str, alt: str = "") -> bool:
    """Check if a URL or alt text indicates a third-party logo."""
    url_lower = url.lower()
    alt_lower = alt.lower()
    if any(pattern in url_lower for pattern in _SKIP_URL_PATTERNS):
        return True
    if any(pattern in alt_lower for pattern in _SKIP_ALT_PATTERNS):
        return True
    return False


class LogoService:
    """Extracts and compares company logos."""

    def extract_logo_from_html(self, html: str, base_url: str) -> dict[str, Any] | None:
        """Extract the primary logo from HTML content.

        Looks for common logo patterns in HTML.
        Skips known third-party logos (investors, social media, generic favicons).
        Returns dict with source_url and extraction_location, or None.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # Strategy 1: og:image meta tag
        og_image = soup.find("meta", attrs={"property": "og:image"})
        if og_image:
            content = og_image.get("content", "")
            if isinstance(content, str) and content and not _is_third_party_logo(content):
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
                and not _is_third_party_logo(src, alt)
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
                if isinstance(href, str) and href and not _is_third_party_logo(href):
                    return {
                        "source_url": href,
                        "extraction_location": "favicon",
                    }

        return None
