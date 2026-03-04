"""Extract logos from latest snapshot HTML for all companies.

Reads each company's most recent snapshot content_html, extracts the
primary logo URL, downloads the image, computes a perceptual hash,
and stores the result in the company_logos table.
"""

from __future__ import annotations

import io
import sqlite3
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from PIL import Image

# Add project root to path
sys.path.insert(0, str(__file__).rsplit("/scripts", 1)[0])

from src.domains.discovery.services.logo_service import LogoService
from src.utils.image_utils import (
    compute_perceptual_hash,
    encode_image_to_base64,
    get_image_dimensions,
    is_valid_logo_size,
    resize_image,
)

DB_PATH = "data/companies.db"
REQUEST_TIMEOUT = 15
# Delay between HTTP requests to avoid hammering servers
REQUEST_DELAY = 0.3

# URL patterns for logos that should never be collected.
# Third-party logos that appear on many portfolio company pages.
SKIP_URL_PATTERNS = [
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

# Known third-party perceptual hashes to skip.
SKIP_PERCEPTUAL_HASHES = {
    # YC logo variants
    "9993666c4c9b93b2",
    "f86a629598637378",
    "fcc171079c3c8d71",
    "f8d963079c3c8c71",
    # Blank/corrupt images (all zeros)
    "0000000000000000",
}


def is_third_party_logo_url(url: str) -> bool:
    """Check if a URL matches known third-party logo patterns."""
    url_lower = url.lower()
    return any(pattern in url_lower for pattern in SKIP_URL_PATTERNS)


def resolve_logo_url(source_url: str, base_url: str) -> str:
    """Resolve a potentially relative logo URL to an absolute URL."""
    if source_url.startswith(("http://", "https://", "//")):
        if source_url.startswith("//"):
            return "https:" + source_url
        return source_url
    return urljoin(base_url, source_url)


def download_image(url: str) -> Image.Image | None:
    """Download an image from a URL. Returns PIL Image or None on failure."""
    try:
        resp = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (compatible; LogoExtractor/1.0)"},
        )
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "image" not in content_type and "svg" not in content_type:
            return None
        return Image.open(io.BytesIO(resp.content))
    except Exception:
        return None


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    logo_service = LogoService()

    # Get latest snapshot with HTML for each company
    rows = conn.execute("""
        SELECT s.company_id, c.name, c.homepage_url, s.content_html, s.url as snapshot_url
        FROM snapshots s
        JOIN companies c ON s.company_id = c.id
        WHERE s.content_html IS NOT NULL
          AND LENGTH(s.content_html) > 200
          AND s.id = (
              SELECT s2.id FROM snapshots s2
              WHERE s2.company_id = s.company_id
                AND s2.content_html IS NOT NULL
              ORDER BY s2.captured_at DESC
              LIMIT 1
          )
        ORDER BY s.company_id
    """).fetchall()

    print(f"Found {len(rows)} companies with HTML snapshots")

    extracted = 0
    downloaded = 0
    stored = 0
    failed_extract = 0
    failed_download = 0
    failed_size = 0
    skipped_investor = 0

    for i, row in enumerate(rows):
        company_id = row["company_id"]
        name = row["name"]
        homepage_url = row["homepage_url"]
        html = row["content_html"]
        snapshot_url = row["snapshot_url"] or homepage_url

        # Extract logo URL from HTML
        result = logo_service.extract_logo_from_html(html, snapshot_url)
        if result is None:
            failed_extract += 1
            continue

        extracted += 1
        source_url = resolve_logo_url(result["source_url"], snapshot_url)
        extraction_location = result["extraction_location"]

        # Skip known investor/accelerator logos by URL
        if is_third_party_logo_url(source_url):
            skipped_investor += 1
            continue

        # Download image
        image = download_image(source_url)
        if image is None:
            failed_download += 1
            if (i + 1) % 100 == 0:
                print(f"  Progress: {i + 1}/{len(rows)} processed, {stored} stored")
            continue

        downloaded += 1

        # Validate size
        if not is_valid_logo_size(image):
            failed_size += 1
            continue

        # Process: resize, hash, encode
        resized = resize_image(image.copy())
        try:
            phash = compute_perceptual_hash(resized)
        except Exception:
            failed_size += 1
            continue

        # Skip known investor/accelerator logos by perceptual hash
        if phash in SKIP_PERCEPTUAL_HASHES:
            skipped_investor += 1
            continue

        width, height = get_image_dimensions(image)

        # Convert to PNG for storage
        try:
            image_base64 = encode_image_to_base64(resized, format="PNG")
            image_data = image_base64.encode("utf-8")
        except Exception:
            # Some images (CMYK, P mode) need conversion
            try:
                converted = resized.convert("RGBA")
                image_base64 = encode_image_to_base64(converted, format="PNG")
                image_data = image_base64.encode("utf-8")
            except Exception:
                failed_size += 1
                continue

        # Store in database
        now = datetime.now(tz=timezone.utc).isoformat()
        try:
            conn.execute(
                """INSERT INTO company_logos
                   (company_id, image_data, image_format, perceptual_hash,
                    source_url, extraction_location, width, height, extracted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    company_id,
                    image_data,
                    "PNG",
                    phash,
                    source_url,
                    extraction_location,
                    width,
                    height,
                    now,
                ),
            )
            conn.commit()
            stored += 1
        except Exception as exc:
            if "UNIQUE constraint" in str(exc):
                pass  # Already exists
            else:
                print(f"  [ERROR] {name} (id={company_id}): {exc}")

        if (i + 1) % 100 == 0:
            print(f"  Progress: {i + 1}/{len(rows)} processed, {stored} stored")

        time.sleep(REQUEST_DELAY)

    print()
    print("=== Logo Extraction Summary ===")
    print(f"Companies with HTML snapshots: {len(rows)}")
    print(f"Logo URL extracted from HTML:  {extracted}")
    print(f"  - No logo found in HTML:     {failed_extract}")
    print(f"  - Skipped third-party logos:    {skipped_investor}")
    print(f"Image downloaded successfully: {downloaded}")
    print(f"  - Download failed:           {failed_download}")
    print(f"Stored in database:           {stored}")
    print(f"  - Invalid size/format:       {failed_size}")

    # Verify
    total = conn.execute("SELECT COUNT(*) FROM company_logos").fetchone()[0]
    print(f"\nTotal logos in company_logos table: {total}")

    conn.close()


if __name__ == "__main__":
    main()
