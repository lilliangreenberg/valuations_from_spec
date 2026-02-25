"""Logo extraction and comparison service.

Extracts the primary company logo from HTML content using a multi-strategy
priority cascade. Strategies are ordered from highest to lowest confidence:

  0. JSON-LD schema.org Organization logo (authoritative self-declaration)
  1. Header/nav image linked to homepage (universal company logo placement)
  2. First img with "logo" in class/id/alt, excluding third-party sections
  3. Favicon / apple-touch-icon (always company-owned, low resolution)
  4. og:image (often a marketing banner -- lowest priority)
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Third-party logo filtering
# ---------------------------------------------------------------------------

# URL patterns for logos that should never be collected.
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

# Text patterns near images that indicate a third-party logo section.
# If any of these appear in a parent container, the image is likely a
# partner/investor/client logo -- not the company's own.
_THIRD_PARTY_SECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"backed\s+by",
        r"funded\s+by",
        r"our\s+investors?",
        r"our\s+backers?",
        r"trusted\s+by",
        r"used\s+by",
        r"loved\s+by",
        r"our\s+customers?",
        r"our\s+clients?",
        r"as\s+seen\s+in",
        r"featured\s+in",
        r"in\s+the\s+press",
        r"in\s+the\s+news",
        r"our\s+partners?",
        r"strategic\s+partners?",
        r"technology\s+partners?",
        r"integration\s*s?\b",
        r"works\s+with",
        r"compatible\s+with",
        r"awards?\s+(?:&|and)\s+recognition",
        r"certifications?",
    ]
]

# CSS class/id patterns that indicate a logo grid (partner/client logos).
_LOGO_GRID_CLASS_PATTERNS: list[str] = [
    "partner-logo",
    "client-logo",
    "investor-logo",
    "customer-logo",
    "logo-grid",
    "logo-slider",
    "logo-carousel",
    "logo-strip",
    "logo-wall",
    "social-proof",
    "trust-badge",
    "trust-logo",
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


def _is_inside_third_party_section(tag: Any) -> bool:
    """Check if an HTML tag is inside a section that contains third-party logos.

    Walks up the DOM tree looking for parent containers whose text content
    or class/id attributes suggest a partner/investor/client logo section.
    Stops after 5 levels to avoid scanning the entire document.
    """
    parent = tag.parent
    levels_checked = 0
    while parent and parent.name and levels_checked < 5:
        # Check class and id attributes for logo grid patterns
        parent_classes = " ".join(parent.get("class", [])).lower()
        parent_id = (parent.get("id") or "").lower()
        combined_attrs = parent_classes + " " + parent_id

        if any(p in combined_attrs for p in _LOGO_GRID_CLASS_PATTERNS):
            return True

        # Check the direct text of this container (not deeply nested text)
        # for third-party section headings
        direct_text = ""
        for child in parent.children:
            if hasattr(child, "name") and child.name in (
                "h1", "h2", "h3", "h4", "h5", "h6", "p", "span", "div",
            ):
                direct_text += " " + child.get_text(strip=True)

        if direct_text and any(
            pat.search(direct_text) for pat in _THIRD_PARTY_SECTION_PATTERNS
        ):
            return True

        parent = parent.parent
        levels_checked += 1

    return False


def _is_homepage_link(anchor: Any, base_url: str) -> bool:
    """Check if an anchor tag links to the site's homepage."""
    href = anchor.get("href", "")
    if not href or not isinstance(href, str):
        return False

    # Direct homepage references
    if href in ("/", "#", ""):
        return True

    # Parse the base URL to get the domain
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.lower().lstrip("www.")

    # Check if the href points to the same domain root
    parsed_href = urlparse(href)
    if parsed_href.netloc:
        href_domain = parsed_href.netloc.lower().lstrip("www.")
        href_path = parsed_href.path.rstrip("/")
        if href_domain == base_domain and href_path in ("", "/"):
            return True

    return False


class LogoService:
    """Extracts the primary company logo from HTML content.

    Uses a multi-strategy priority cascade, from highest to lowest confidence.
    Each strategy filters out known third-party logos and images inside
    partner/investor/client sections.
    """

    def extract_logo_from_html(self, html: str, base_url: str) -> dict[str, Any] | None:
        """Extract the primary logo from HTML content.

        Strategies (in priority order):
          0. JSON-LD schema.org Organization logo
          1. Header/nav image linked to homepage
          2. First img with 'logo' in class/id/alt (outside third-party sections)
          3. Favicon / apple-touch-icon
          4. og:image (lowest priority -- often a banner, not a logo)

        Returns dict with source_url and extraction_location, or None.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        # Strategy 0: JSON-LD schema.org Organization logo
        result = self._try_jsonld_logo(soup)
        if result:
            return result

        # Strategy 1: Header/nav image linked to homepage
        result = self._try_header_nav_logo(soup, base_url)
        if result:
            return result

        # Strategy 2: First img with "logo" in class/id/alt
        # (outside third-party sections)
        result = self._try_logo_keyword_img(soup)
        if result:
            return result

        # Strategy 3: Favicon / apple-touch-icon
        result = self._try_favicon(soup)
        if result:
            return result

        # Strategy 4: og:image (lowest priority)
        result = self._try_og_image(soup)
        if result:
            return result

        return None

    def _try_jsonld_logo(self, soup: Any) -> dict[str, Any] | None:
        """Strategy 0: Extract logo from JSON-LD schema.org Organization markup.

        This is the highest-confidence signal. A site declaring its own
        Organization logo in structured data is an authoritative first-party
        declaration.
        """
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                raw = script.string
                if not raw:
                    continue
                data = json.loads(raw)
                logo_url = self._extract_logo_from_jsonld(data)
                if logo_url and not _is_third_party_logo(logo_url):
                    return {
                        "source_url": logo_url,
                        "extraction_location": "jsonld",
                    }
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        return None

    def _extract_logo_from_jsonld(self, data: Any) -> str | None:
        """Recursively search JSON-LD data for an Organization logo."""
        if isinstance(data, dict):
            schema_type = data.get("@type", "")
            # Handle both string and list @type
            type_values = schema_type if isinstance(schema_type, list) else [schema_type]

            if any(t in ("Organization", "Corporation", "LocalBusiness")
                   for t in type_values):
                logo = data.get("logo")
                if isinstance(logo, str) and logo:
                    return logo
                if isinstance(logo, dict):
                    url = logo.get("url") or logo.get("contentUrl")
                    if isinstance(url, str) and url:
                        return url

            # Recurse into nested structures
            for value in data.values():
                result = self._extract_logo_from_jsonld(value)
                if result:
                    return result

        elif isinstance(data, list):
            for item in data:
                result = self._extract_logo_from_jsonld(item)
                if result:
                    return result

        return None

    def _try_header_nav_logo(
        self, soup: Any, base_url: str,
    ) -> dict[str, Any] | None:
        """Strategy 1: Find an image in header/nav linked to the homepage.

        The company's own logo is almost universally placed in the <header>
        or <nav>, wrapped in an <a> linking to '/'. This is the most reliable
        structural signal.
        """
        for container_tag in ("header", "nav"):
            for container in soup.find_all(container_tag):
                # Look for <a href="/"> containing an <img>
                for anchor in container.find_all("a"):
                    if not _is_homepage_link(anchor, base_url):
                        continue
                    img = anchor.find("img")
                    if img:
                        src = img.get("src", "")
                        alt = (img.get("alt") or "").lower()
                        if isinstance(src, str) and src and not _is_third_party_logo(src, alt):
                            return {
                                "source_url": src,
                                "extraction_location": "header",
                            }

                # Fallback: any img in header/nav with "logo" in attributes
                for img in container.find_all("img"):
                    src = img.get("src", "")
                    alt = (img.get("alt") or "").lower()
                    classes = " ".join(img.get("class", [])).lower()
                    img_id = (img.get("id") or "").lower()
                    combined = alt + " " + classes + " " + img_id

                    if (
                        any(kw in combined for kw in ("logo", "brand", "site-logo"))
                        and isinstance(src, str)
                        and src
                        and not _is_third_party_logo(src, alt)
                    ):
                        return {
                            "source_url": src,
                            "extraction_location": "header",
                        }

        return None

    def _try_logo_keyword_img(self, soup: Any) -> dict[str, Any] | None:
        """Strategy 2: First img with 'logo' in class/id/alt, outside third-party sections.

        Searches the entire DOM but rejects images inside containers that
        look like partner/investor/client logo sections.
        """
        for tag in soup.find_all("img"):
            src = tag.get("src", "")
            alt = (tag.get("alt") or "").lower()
            classes = " ".join(tag.get("class", [])).lower()
            img_id = (tag.get("id") or "").lower()
            combined = alt + " " + classes + " " + img_id

            if not (
                any(kw in combined for kw in ("logo", "brand", "site-logo"))
                and isinstance(src, str)
                and src
            ):
                continue

            if _is_third_party_logo(src, alt):
                continue

            if _is_inside_third_party_section(tag):
                continue

            return {
                "source_url": src,
                "extraction_location": "body",
            }

        return None

    def _try_favicon(self, soup: Any) -> dict[str, Any] | None:
        """Strategy 3: Favicon or apple-touch-icon.

        Always company-owned, always site-specific. Lower resolution than a
        full logo but reliable as a brand signal.
        """
        # Prefer apple-touch-icon (larger, 180x180) over favicon (16x16)
        for link_tag in soup.find_all("link", rel=True):
            rels = link_tag.get("rel", [])
            if isinstance(rels, list) and any("apple-touch-icon" in r.lower() for r in rels):
                href = link_tag.get("href", "")
                if isinstance(href, str) and href and not _is_third_party_logo(href):
                    return {
                        "source_url": href,
                        "extraction_location": "favicon",
                    }

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

    def _try_og_image(self, soup: Any) -> dict[str, Any] | None:
        """Strategy 4: Open Graph image (lowest priority).

        og:image is the image shown when the page is shared on social media.
        For homepages this is often the company logo, but for content pages
        it is frequently a marketing banner or article image. Demoted to
        last resort.
        """
        og_image = soup.find("meta", attrs={"property": "og:image"})
        if og_image:
            content = og_image.get("content", "")
            if isinstance(content, str) and content and not _is_third_party_logo(content):
                return {
                    "source_url": content,
                    "extraction_location": "og_image",
                }
        return None
