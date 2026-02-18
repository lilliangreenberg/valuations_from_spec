"""Company logo model for extracted logos with perceptual hashing."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from datetime import datetime


class ExtractionLocation(StrEnum):
    """Where the logo was extracted from on the webpage."""

    TOP_LEFT = "top_left"
    HEADER = "header"
    NAV = "nav"
    FAVICON = "favicon"
    OG_IMAGE = "og_image"


class CompanyLogo(BaseModel):
    """Represents an extracted company logo with perceptual hash for comparison."""

    model_config = ConfigDict(strict=True)

    id: int | None = None
    company_id: int
    image_data: str
    image_format: str
    perceptual_hash: str
    source_url: str
    extraction_location: ExtractionLocation
    width: int | None = None
    height: int | None = None
    extracted_at: datetime
