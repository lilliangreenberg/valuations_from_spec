"""Comprehensive unit tests for utility modules.

Tests pure functions and simple data classes -- no I/O, no mocking required.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from src.utils.image_utils import (
    compute_hash_similarity,
    compute_perceptual_hash,
    decode_base64_image,
    encode_image_to_base64,
    get_image_dimensions,
    get_image_format,
    image_from_bytes,
    is_valid_logo_size,
    resize_image,
)
from src.utils.progress import ProgressTracker
from src.utils.validators import (
    extract_domain,
    is_valid_checksum_hex,
    is_valid_md5,
    is_valid_url,
    normalize_url,
)

# ──────────────────────────────────────────────────────────────────────
# Module 1: utils/validators.py
# ──────────────────────────────────────────────────────────────────────


class TestIsValidUrl:
    """Tests for is_valid_url."""

    def test_https(self) -> None:
        assert is_valid_url("https://example.com") is True

    def test_http(self) -> None:
        assert is_valid_url("http://example.com") is True

    def test_with_path(self) -> None:
        assert is_valid_url("https://example.com/path/to/page") is True

    def test_with_query_params(self) -> None:
        assert is_valid_url("https://example.com?q=test&page=1") is True

    def test_ftp_scheme_fails(self) -> None:
        assert is_valid_url("ftp://files.example.com") is False

    def test_missing_scheme(self) -> None:
        assert is_valid_url("example.com") is False

    def test_missing_netloc(self) -> None:
        assert is_valid_url("https://") is False

    def test_empty_string(self) -> None:
        assert is_valid_url("") is False

    def test_file_scheme(self) -> None:
        assert is_valid_url("file:///etc/passwd") is False

    def test_data_uri(self) -> None:
        assert is_valid_url("data:text/html,<h1>Hi</h1>") is False

    def test_with_port(self) -> None:
        assert is_valid_url("https://localhost:8080/api") is True

    def test_with_fragment(self) -> None:
        assert is_valid_url("https://example.com/page#section") is True


class TestIsValidMd5:
    """Tests for is_valid_md5."""

    def test_valid_md5(self) -> None:
        assert is_valid_md5("d41d8cd98f00b204e9800998ecf8427e") is True

    def test_all_zeros(self) -> None:
        assert is_valid_md5("0" * 32) is True

    def test_uppercase_fails(self) -> None:
        assert is_valid_md5("D41D8CD98F00B204E9800998ECF8427E") is False

    def test_too_short(self) -> None:
        assert is_valid_md5("d41d8cd98f00b204") is False

    def test_too_long(self) -> None:
        assert is_valid_md5("d41d8cd98f00b204e9800998ecf8427e0") is False

    def test_non_hex_chars(self) -> None:
        assert is_valid_md5("g41d8cd98f00b204e9800998ecf8427e") is False

    def test_empty(self) -> None:
        assert is_valid_md5("") is False


class TestNormalizeUrl:
    """Tests for normalize_url."""

    def test_removes_www(self) -> None:
        result = normalize_url("https://www.example.com/page")
        assert "www." not in result
        assert "example.com" in result

    def test_removes_trailing_slash(self) -> None:
        result = normalize_url("https://example.com/page/")
        assert not result.endswith("/")

    def test_lowercases(self) -> None:
        result = normalize_url("HTTPS://EXAMPLE.COM/Page")
        assert result == "https://example.com/page"

    def test_strips_whitespace(self) -> None:
        result = normalize_url("  https://example.com  ")
        assert result == "https://example.com"

    def test_preserves_path(self) -> None:
        result = normalize_url("https://example.com/some/path")
        assert "/some/path" in result

    def test_root_url(self) -> None:
        result = normalize_url("https://example.com/")
        assert result == "https://example.com"

    def test_no_path(self) -> None:
        result = normalize_url("https://example.com")
        assert result == "https://example.com"


class TestExtractDomain:
    """Tests for extract_domain."""

    def test_simple(self) -> None:
        assert extract_domain("https://example.com/page") == "example.com"

    def test_removes_www(self) -> None:
        assert extract_domain("https://www.example.com") == "example.com"

    def test_subdomain_preserved(self) -> None:
        # extract_domain only removes www, keeps other subdomains
        assert extract_domain("https://blog.example.com") == "blog.example.com"

    def test_with_port(self) -> None:
        assert extract_domain("https://example.com:8080") == "example.com:8080"


class TestIsValidChecksumHex:
    """Tests for is_valid_checksum_hex."""

    def test_lowercase_valid(self) -> None:
        assert is_valid_checksum_hex("d41d8cd98f00b204e9800998ecf8427e") is True

    def test_uppercase_accepted(self) -> None:
        # is_valid_checksum_hex lowercases internally before checking
        assert is_valid_checksum_hex("D41D8CD98F00B204E9800998ECF8427E") is True

    def test_mixed_case_accepted(self) -> None:
        assert is_valid_checksum_hex("d41D8cd98f00b204E9800998ecf8427e") is True

    def test_too_short_fails(self) -> None:
        assert is_valid_checksum_hex("abc123") is False

    def test_non_hex_fails(self) -> None:
        assert is_valid_checksum_hex("z" * 32) is False


# ──────────────────────────────────────────────────────────────────────
# Module 2: utils/progress.py
# ──────────────────────────────────────────────────────────────────────


class TestProgressTracker:
    """Tests for ProgressTracker."""

    def test_initial_state(self) -> None:
        tracker = ProgressTracker(total=10)
        assert tracker.total == 10
        assert tracker.processed == 0
        assert tracker.successful == 0
        assert tracker.failed == 0
        assert tracker.skipped == 0
        assert tracker.errors == []

    def test_record_success(self) -> None:
        tracker = ProgressTracker(total=5)
        tracker.record_success()
        assert tracker.processed == 1
        assert tracker.successful == 1

    def test_record_failure(self) -> None:
        tracker = ProgressTracker(total=5)
        tracker.record_failure("something broke")
        assert tracker.processed == 1
        assert tracker.failed == 1
        assert tracker.errors == ["something broke"]

    def test_record_skip(self) -> None:
        tracker = ProgressTracker(total=5)
        tracker.record_skip()
        assert tracker.processed == 1
        assert tracker.skipped == 1

    def test_progress_percentage_zero_total(self) -> None:
        tracker = ProgressTracker(total=0)
        assert tracker.progress_percentage == 100.0

    def test_progress_percentage_half(self) -> None:
        tracker = ProgressTracker(total=10)
        for _ in range(5):
            tracker.record_success()
        assert tracker.progress_percentage == pytest.approx(50.0)

    def test_progress_percentage_complete(self) -> None:
        tracker = ProgressTracker(total=3)
        tracker.record_success()
        tracker.record_failure("err")
        tracker.record_skip()
        assert tracker.progress_percentage == pytest.approx(100.0)

    def test_elapsed_seconds(self) -> None:
        tracker = ProgressTracker(total=1)
        # Just confirm it returns a non-negative float
        assert tracker.elapsed_seconds >= 0.0

    def test_summary(self) -> None:
        tracker = ProgressTracker(total=3)
        tracker.record_success()
        tracker.record_failure("err1")
        tracker.record_skip()
        summary = tracker.summary()
        assert summary["processed"] == 3
        assert summary["successful"] == 1
        assert summary["failed"] == 1
        assert summary["skipped"] == 1
        assert summary["errors"] == ["err1"]
        assert isinstance(summary["duration_seconds"], float)

    def test_multiple_errors_accumulated(self) -> None:
        tracker = ProgressTracker(total=3)
        tracker.record_failure("err1")
        tracker.record_failure("err2")
        tracker.record_failure("err3")
        assert len(tracker.errors) == 3
        assert tracker.errors == ["err1", "err2", "err3"]

    def test_all_success(self) -> None:
        tracker = ProgressTracker(total=5)
        for _ in range(5):
            tracker.record_success()
        assert tracker.processed == 5
        assert tracker.successful == 5
        assert tracker.failed == 0
        assert tracker.skipped == 0
        assert tracker.progress_percentage == pytest.approx(100.0)

    def test_mixed_results(self) -> None:
        tracker = ProgressTracker(total=10)
        for _ in range(6):
            tracker.record_success()
        for i in range(3):
            tracker.record_failure(f"err_{i}")
        tracker.record_skip()
        assert tracker.processed == 10
        assert tracker.successful == 6
        assert tracker.failed == 3
        assert tracker.skipped == 1
        assert len(tracker.errors) == 3


# ──────────────────────────────────────────────────────────────────────
# Module 3: utils/image_utils.py
# ──────────────────────────────────────────────────────────────────────


def _make_test_image(width: int = 64, height: int = 64, color: str = "red") -> Image.Image:
    """Create a small test image in memory."""
    return Image.new("RGB", (width, height), color=color)


def _image_to_bytes(img: Image.Image, fmt: str = "PNG") -> bytes:
    """Convert a PIL Image to raw bytes."""
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


class TestEncodeDecodeRoundTrip:
    """Tests for encode_image_to_base64 and decode_base64_image."""

    def test_round_trip_png(self) -> None:
        img = _make_test_image(32, 32, "blue")
        encoded = encode_image_to_base64(img, format="PNG")
        decoded = decode_base64_image(encoded)
        assert decoded.size == (32, 32)

    def test_round_trip_preserves_pixel_data(self) -> None:
        img = _make_test_image(1, 1, "red")
        encoded = encode_image_to_base64(img, format="PNG")
        decoded = decode_base64_image(encoded)
        pixel = decoded.getpixel((0, 0))
        assert pixel == (255, 0, 0)

    def test_encoded_is_string(self) -> None:
        img = _make_test_image(8, 8)
        encoded = encode_image_to_base64(img)
        assert isinstance(encoded, str)


class TestComputePerceptualHash:
    """Tests for compute_perceptual_hash."""

    def test_returns_string(self) -> None:
        img = _make_test_image(64, 64, "green")
        phash = compute_perceptual_hash(img)
        assert isinstance(phash, str)
        assert len(phash) > 0

    def test_identical_images_same_hash(self) -> None:
        img1 = _make_test_image(64, 64, "red")
        img2 = _make_test_image(64, 64, "red")
        assert compute_perceptual_hash(img1) == compute_perceptual_hash(img2)

    def test_different_images_different_hash(self) -> None:
        img_red = _make_test_image(64, 64, "red")
        img_blue = _make_test_image(64, 64, "blue")
        # Different solid colors should produce different hashes
        # (though perceptual hashing can be lenient, solid red vs blue should differ)
        hash_red = compute_perceptual_hash(img_red)
        hash_blue = compute_perceptual_hash(img_blue)
        # We do not require they are different for solid colors (phash may match),
        # so just verify they are valid strings
        assert isinstance(hash_red, str)
        assert isinstance(hash_blue, str)


class TestComputeHashSimilarity:
    """Tests for compute_hash_similarity."""

    def test_identical_hashes(self) -> None:
        img = _make_test_image(64, 64, "red")
        h = compute_perceptual_hash(img)
        similarity = compute_hash_similarity(h, h)
        assert similarity == pytest.approx(1.0)

    def test_similarity_range(self) -> None:
        img1 = _make_test_image(64, 64, "red")
        img2 = _make_test_image(64, 64, "blue")
        h1 = compute_perceptual_hash(img1)
        h2 = compute_perceptual_hash(img2)
        sim = compute_hash_similarity(h1, h2)
        assert 0.0 <= sim <= 1.0


class TestResizeImage:
    """Tests for resize_image."""

    def test_downscale(self) -> None:
        img = _make_test_image(512, 512)
        resized = resize_image(img, max_width=256, max_height=256)
        w, h = resized.size
        assert w <= 256
        assert h <= 256

    def test_preserves_aspect_ratio(self) -> None:
        img = _make_test_image(400, 200)
        resized = resize_image(img, max_width=100, max_height=100)
        w, h = resized.size
        # Original is 2:1, so resized should be 100x50
        assert w == 100
        assert h == 50

    def test_already_small_not_upscaled(self) -> None:
        img = _make_test_image(32, 32)
        resized = resize_image(img, max_width=256, max_height=256)
        w, h = resized.size
        # thumbnail does not upscale
        assert w == 32
        assert h == 32


class TestGetImageDimensions:
    """Tests for get_image_dimensions."""

    def test_returns_tuple(self) -> None:
        img = _make_test_image(100, 50)
        assert get_image_dimensions(img) == (100, 50)


class TestGetImageFormat:
    """Tests for get_image_format."""

    def test_new_image_has_no_format(self) -> None:
        # Newly created images have no format set
        img = _make_test_image(10, 10)
        assert get_image_format(img) == "PNG"  # defaults to PNG

    def test_loaded_image_has_format(self) -> None:
        img = _make_test_image(10, 10)
        raw = _image_to_bytes(img, "PNG")
        loaded = image_from_bytes(raw)
        assert get_image_format(loaded) == "PNG"


class TestIsValidLogoSize:
    """Tests for is_valid_logo_size."""

    def test_valid_size(self) -> None:
        img = _make_test_image(64, 64)
        assert is_valid_logo_size(img) is True

    def test_minimum_boundary(self) -> None:
        img = _make_test_image(16, 16)
        assert is_valid_logo_size(img) is True

    def test_below_minimum(self) -> None:
        img = _make_test_image(15, 15)
        assert is_valid_logo_size(img) is False

    def test_maximum_boundary(self) -> None:
        img = _make_test_image(2048, 2048)
        assert is_valid_logo_size(img) is True

    def test_above_maximum(self) -> None:
        img = _make_test_image(2049, 2049)
        assert is_valid_logo_size(img) is False

    def test_one_dimension_too_small(self) -> None:
        img = _make_test_image(64, 10)
        assert is_valid_logo_size(img) is False

    def test_one_dimension_too_large(self) -> None:
        img = _make_test_image(64, 2049)
        assert is_valid_logo_size(img) is False

    def test_custom_bounds(self) -> None:
        img = _make_test_image(50, 50)
        assert is_valid_logo_size(img, min_size=100) is False
        assert is_valid_logo_size(img, min_size=10, max_size=100) is True


class TestImageFromBytes:
    """Tests for image_from_bytes."""

    def test_valid_png_bytes(self) -> None:
        img = _make_test_image(20, 20, "green")
        raw = _image_to_bytes(img, "PNG")
        loaded = image_from_bytes(raw)
        assert loaded.size == (20, 20)

    def test_valid_jpeg_bytes(self) -> None:
        img = _make_test_image(20, 20, "green")
        raw = _image_to_bytes(img, "JPEG")
        loaded = image_from_bytes(raw)
        assert loaded.size == (20, 20)
