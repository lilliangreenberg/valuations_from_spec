"""Image processing utilities for logo extraction and comparison."""

from __future__ import annotations

import base64
import io

import imagehash
from PIL import Image


def decode_base64_image(data: str) -> Image.Image:
    """Decode a base64-encoded image string to a PIL Image."""
    image_bytes = base64.b64decode(data)
    return Image.open(io.BytesIO(image_bytes))


def encode_image_to_base64(image: Image.Image, format: str = "PNG") -> str:
    """Encode a PIL Image to a base64 string."""
    buffer = io.BytesIO()
    image.save(buffer, format=format)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def compute_perceptual_hash(image: Image.Image) -> str:
    """Compute perceptual hash (pHash) for an image."""
    return str(imagehash.phash(image))


def compute_hash_similarity(hash1: str, hash2: str) -> float:
    """Compute similarity between two perceptual hashes.

    Returns a float between 0.0 (completely different) and 1.0 (identical).
    """
    h1 = imagehash.hex_to_hash(hash1)
    h2 = imagehash.hex_to_hash(hash2)
    max_distance = len(h1.hash.flatten())
    hamming_distance = h1 - h2
    return 1.0 - (hamming_distance / max_distance)


def resize_image(image: Image.Image, max_width: int = 256, max_height: int = 256) -> Image.Image:
    """Resize image to fit within max dimensions while preserving aspect ratio."""
    image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    return image


def get_image_dimensions(image: Image.Image) -> tuple[int, int]:
    """Get width and height of an image."""
    return image.size


def get_image_format(image: Image.Image) -> str:
    """Get the format of an image (PNG, JPEG, etc.)."""
    return image.format or "PNG"


def is_valid_logo_size(image: Image.Image, min_size: int = 16, max_size: int = 2048) -> bool:
    """Check if image dimensions are reasonable for a logo."""
    width, height = image.size
    return min_size <= width <= max_size and min_size <= height <= max_size


def image_from_bytes(data: bytes) -> Image.Image:
    """Create a PIL Image from raw bytes."""
    return Image.open(io.BytesIO(data))
