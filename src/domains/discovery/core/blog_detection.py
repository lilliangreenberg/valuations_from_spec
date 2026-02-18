"""Blog URL detection and classification."""

from __future__ import annotations

import re
from enum import StrEnum
from urllib.parse import urlparse


class BlogType(StrEnum):
    COMPANY_BLOG = "company_blog"
    MEDIUM = "medium"
    SUBSTACK = "substack"
    GHOST = "ghost"
    WORDPRESS = "wordpress"
    OTHER = "other"


# Blog subdomain patterns
BLOG_SUBDOMAIN_PATTERNS: list[str] = ["blog.", "news.", "updates.", "press."]

# Blog path patterns
BLOG_PATH_PATTERNS: list[str] = ["/blog", "/news", "/updates", "/press", "/articles"]

# Platform-specific patterns
BLOG_PLATFORM_PATTERNS: dict[BlogType, re.Pattern[str]] = {
    BlogType.MEDIUM: re.compile(r"(medium\.com/@|\.medium\.com)", re.IGNORECASE),
    BlogType.SUBSTACK: re.compile(r"\.substack\.com", re.IGNORECASE),
    BlogType.GHOST: re.compile(r"\.ghost\.io", re.IGNORECASE),
    BlogType.WORDPRESS: re.compile(r"(\.wordpress\.com|/wp-content/)", re.IGNORECASE),
}


def detect_blog_url(url: str) -> tuple[bool, BlogType | None]:
    """Detect if a URL is a blog and classify its type.

    Returns (is_blog, blog_type).
    """
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path.lower()

    # Check platform-specific patterns first
    for blog_type, pattern in BLOG_PLATFORM_PATTERNS.items():
        if pattern.search(url):
            return True, blog_type

    # Check subdomain patterns
    for subdomain in BLOG_SUBDOMAIN_PATTERNS:
        if netloc.startswith(subdomain):
            return True, BlogType.COMPANY_BLOG

    # Check path patterns
    for blog_path in BLOG_PATH_PATTERNS:
        if path.startswith(blog_path):
            return True, BlogType.COMPANY_BLOG

    return False, None


def normalize_blog_url(url: str) -> str:
    """Normalize a blog URL to its hub/root level.

    Examples:
    - blog.example.com/2024/01/post -> blog.example.com
    - example.com/blog/category/post -> example.com/blog
    - company.substack.com/p/article -> company.substack.com
    """
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()

    # For subdomain blogs (blog.example.com, company.substack.com, etc.)
    for subdomain in BLOG_SUBDOMAIN_PATTERNS:
        if netloc.startswith(subdomain):
            return f"{parsed.scheme}://{netloc}"

    # For platform blogs
    if ".substack.com" in netloc or ".medium.com" in netloc or ".ghost.io" in netloc:
        return f"{parsed.scheme}://{netloc}"

    # For medium.com/@handle
    if "medium.com" in netloc:
        path_parts = [p for p in parsed.path.split("/") if p]
        if path_parts and path_parts[0].startswith("@"):
            return f"{parsed.scheme}://{netloc}/{path_parts[0]}"

    # For path-based blogs (/blog, /news, etc.)
    path = parsed.path.lower()
    for blog_path in BLOG_PATH_PATTERNS:
        if path.startswith(blog_path):
            return f"{parsed.scheme}://{netloc}{blog_path}"

    return url
