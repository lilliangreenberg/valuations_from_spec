"""Website URL mapping and grouping utilities."""

from __future__ import annotations

from urllib.parse import urlparse


def extract_base_domain(url: str) -> str:
    """Extract the base domain from a URL, removing subdomains."""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    parts = netloc.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return netloc


def is_same_domain(url1: str, url2: str) -> bool:
    """Check if two URLs belong to the same domain."""
    return extract_base_domain(url1) == extract_base_domain(url2)


def is_subdomain_of(url: str, base_domain: str) -> bool:
    """Check if a URL is a subdomain of the given base domain."""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    base = base_domain.lower()
    return netloc.endswith(f".{base}") or netloc == base


def group_urls_by_domain(urls: list[str]) -> dict[str, list[str]]:
    """Group a list of URLs by their base domain."""
    groups: dict[str, list[str]] = {}
    for url in urls:
        domain = extract_base_domain(url)
        if domain not in groups:
            groups[domain] = []
        groups[domain].append(url)
    return groups
