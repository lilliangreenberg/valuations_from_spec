"""Service for downloading and storing logos from Firecrawl branding data.

Designed to be called from SnapshotManager / BatchSnapshotManager
after a snapshot is captured, when branding data is available
and the company has no existing logo.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import requests
import structlog

from src.core.branding import extract_branding_logo_url
from src.utils.image_utils import (
    compute_perceptual_hash,
    encode_image_to_base64,
    get_image_dimensions,
    image_from_bytes,
    is_valid_logo_size,
    resize_image,
)

if TYPE_CHECKING:
    from src.domains.discovery.repositories.social_media_link_repository import (
        SocialMediaLinkRepository,
    )

logger = structlog.get_logger(__name__)

# Known third-party perceptual hashes to reject.
_SKIP_PERCEPTUAL_HASHES: set[str] = {
    # YC logo variants
    "9993666c4c9b93b2",
    "f86a629598637378",
    "fcc171079c3c8d71",
    "f8d963079c3c8c71",
    # Blank/corrupt images (all zeros)
    "0000000000000000",
}

_REQUEST_TIMEOUT = 15
_USER_AGENT = "Mozilla/5.0 (compatible; LogoExtractor/1.0)"


class BrandingLogoProcessor:
    """Downloads branding logos and stores them in the company_logos table.

    All download/processing failures are logged and swallowed -- they never
    affect snapshot capture success/failure.
    """

    def __init__(self, logo_repo: SocialMediaLinkRepository) -> None:
        self.logo_repo = logo_repo

    def company_has_logo(self, company_id: int) -> bool:
        """Check if a company already has a stored logo."""
        return self.logo_repo.get_company_logo(company_id) is not None

    def process_branding_logo(
        self,
        company_id: int,
        branding: Any,
    ) -> bool:
        """Extract, download, and store a logo from branding data.

        Returns True if a logo was stored, False otherwise.
        """
        logo_url = extract_branding_logo_url(branding)
        if not logo_url:
            logger.debug("no_branding_logo_url", company_id=company_id)
            return False

        return self._download_and_store(company_id, logo_url)

    def _download_and_store(self, company_id: int, logo_url: str) -> bool:
        """Download image from URL, compute hash, store in database."""
        try:
            response = requests.get(
                logo_url,
                timeout=_REQUEST_TIMEOUT,
                headers={"User-Agent": _USER_AGENT},
            )
            response.raise_for_status()
        except Exception as exc:
            logger.warning(
                "branding_logo_download_failed",
                company_id=company_id,
                url=logo_url,
                error=str(exc),
            )
            return False

        content_type = response.headers.get("Content-Type", "")
        if "image" not in content_type and "svg" not in content_type:
            logger.debug(
                "branding_logo_not_image",
                company_id=company_id,
                url=logo_url,
                content_type=content_type,
            )
            return False

        try:
            image = image_from_bytes(response.content)

            if not is_valid_logo_size(image):
                logger.debug(
                    "branding_logo_invalid_size",
                    company_id=company_id,
                    size=image.size,
                )
                return False

            width, height = get_image_dimensions(image)
            resized = resize_image(image.copy(), max_width=256, max_height=256)
            phash = compute_perceptual_hash(resized)

            # Reject known third-party logos by perceptual hash
            if phash in _SKIP_PERCEPTUAL_HASHES:
                logger.debug(
                    "branding_logo_third_party_hash",
                    company_id=company_id,
                    phash=phash,
                )
                return False

            # Encode as PNG for storage
            try:
                image_base64 = encode_image_to_base64(resized, format="PNG")
            except Exception:
                # Some images (CMYK, P mode) need conversion
                converted = resized.convert("RGBA")
                image_base64 = encode_image_to_base64(converted, format="PNG")

            self.logo_repo.store_company_logo(
                {
                    "company_id": company_id,
                    "image_data": image_base64.encode("utf-8"),
                    "image_format": "PNG",
                    "perceptual_hash": phash,
                    "source_url": logo_url,
                    "extraction_location": "branding",
                    "width": width,
                    "height": height,
                    "extracted_at": datetime.now(tz=UTC).isoformat(),
                }
            )

            logger.info(
                "branding_logo_stored",
                company_id=company_id,
                source_url=logo_url,
                phash=phash,
            )
            return True

        except Exception as exc:
            logger.warning(
                "branding_logo_processing_failed",
                company_id=company_id,
                url=logo_url,
                error=str(exc),
            )
            return False
