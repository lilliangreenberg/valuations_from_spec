"""Detect HTML regions for link location classification."""

from __future__ import annotations

from enum import StrEnum

from bs4 import BeautifulSoup, Tag


class HTMLRegion(StrEnum):
    FOOTER = "footer"
    HEADER = "header"
    NAV = "nav"
    ASIDE = "aside"
    MAIN = "main"
    UNKNOWN = "unknown"


def detect_link_region(html: str, link_url: str) -> HTMLRegion:
    """Detect which HTML region a link URL is located in.

    Walks up the DOM tree from the link to find the nearest semantic container.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Find the <a> tag with this URL
    link_tag = soup.find("a", href=link_url)
    if link_tag is None:
        return HTMLRegion.UNKNOWN

    return _find_region_for_tag(link_tag)


def _find_region_for_tag(tag: Tag) -> HTMLRegion:
    """Walk up DOM tree to find semantic region."""
    current = tag.parent
    while current and isinstance(current, Tag):
        tag_name = current.name.lower()

        tag_region = {
            "footer": HTMLRegion.FOOTER,
            "header": HTMLRegion.HEADER,
            "nav": HTMLRegion.NAV,
            "aside": HTMLRegion.ASIDE,
            "main": HTMLRegion.MAIN,
        }.get(tag_name)
        if tag_region is not None:
            return tag_region

        # Check for role attributes
        role = (current.get("role") or "").lower()
        role_region = {
            "contentinfo": HTMLRegion.FOOTER,
            "banner": HTMLRegion.HEADER,
            "navigation": HTMLRegion.NAV,
            "complementary": HTMLRegion.ASIDE,
            "main": HTMLRegion.MAIN,
        }.get(role)
        if role_region is not None:
            return role_region

        # Check for common class/id patterns
        classes = " ".join(current.get("class", [])).lower()
        element_id = (current.get("id") or "").lower()
        combined = f"{classes} {element_id}"

        if any(kw in combined for kw in ("footer", "foot", "bottom-bar")):
            return HTMLRegion.FOOTER
        elif any(kw in combined for kw in ("header", "head", "top-bar", "topbar")):
            return HTMLRegion.HEADER
        elif any(kw in combined for kw in ("nav", "navigation", "menu")):
            return HTMLRegion.NAV
        elif any(kw in combined for kw in ("sidebar", "aside")):
            return HTMLRegion.ASIDE

        current = current.parent

    return HTMLRegion.UNKNOWN
