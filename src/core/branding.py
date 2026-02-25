"""Pure functions for extracting logo information from Firecrawl branding data.

Extracts the best logo URL from a BrandingProfile returned by Firecrawl's
branding format, applying third-party URL filtering. No I/O.
"""

from __future__ import annotations

from typing import Any

# Third-party URL patterns to reject. Kept in sync with logo_service.py.
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


def _is_third_party_url(url: str) -> bool:
    """Check if a URL matches known third-party logo patterns."""
    url_lower = url.lower()
    return any(pattern in url_lower for pattern in _SKIP_URL_PATTERNS)


def extract_branding_logo_url(branding: Any) -> str | None:
    """Extract the best logo URL from a Firecrawl BrandingProfile.

    Priority:
      1. branding.logo (primary logo URL -- most reliable)
      2. branding.images["logo"] (images dict, logo key)
      3. branding.images["og_image"] (fallback)
      4. branding.images["favicon"] (lowest priority)

    Returns the URL string or None if no valid logo found.
    Rejects known third-party URLs.
    """
    if branding is None:
        return None

    # Priority 1: branding.logo (top-level attribute)
    logo_url = _try_string_attr(branding, "logo")
    if logo_url and not _is_third_party_url(logo_url):
        return logo_url

    # Priority 2-4: branding.images dict
    images = getattr(branding, "images", None)
    if images is None and isinstance(branding, dict):
        images = branding.get("images")

    if isinstance(images, dict):
        for key in ("logo", "og_image", "favicon"):
            url = images.get(key)
            if isinstance(url, str) and url.strip() and not _is_third_party_url(url):
                return url

    return None


def _try_string_attr(obj: Any, attr: str) -> str | None:
    """Try to get a non-empty string attribute from an object or dict."""
    value = getattr(obj, attr, None)
    if value is None and isinstance(obj, dict):
        value = obj.get(attr)
    if isinstance(value, str) and value.strip():
        return value
    return None
