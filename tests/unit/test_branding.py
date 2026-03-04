"""Unit tests for branding logo URL extraction (pure functions, no I/O)."""

from __future__ import annotations

from types import SimpleNamespace

from src.core.branding import extract_branding_logo_url


class TestExtractBrandingLogoUrl:
    """Tests for extract_branding_logo_url pure function."""

    def test_extracts_from_logo_field(self) -> None:
        """Primary logo URL from branding.logo is returned."""
        branding = SimpleNamespace(logo="https://acme.com/logo.png", images=None)
        assert extract_branding_logo_url(branding) == "https://acme.com/logo.png"

    def test_extracts_from_images_logo(self) -> None:
        """Falls back to branding.images['logo'] when branding.logo is None."""
        branding = SimpleNamespace(
            logo=None,
            images={"logo": "https://acme.com/images/logo.svg"},
        )
        assert extract_branding_logo_url(branding) == "https://acme.com/images/logo.svg"

    def test_extracts_from_images_og_image(self) -> None:
        """Falls back to branding.images['og_image'] when logo keys are absent."""
        branding = SimpleNamespace(
            logo=None,
            images={"og_image": "https://acme.com/og.png"},
        )
        assert extract_branding_logo_url(branding) == "https://acme.com/og.png"

    def test_extracts_from_images_favicon(self) -> None:
        """Falls back to branding.images['favicon'] as lowest priority."""
        branding = SimpleNamespace(
            logo=None,
            images={"favicon": "https://acme.com/favicon.ico"},
        )
        assert extract_branding_logo_url(branding) == "https://acme.com/favicon.ico"

    def test_logo_field_beats_images_dict(self) -> None:
        """branding.logo takes priority over branding.images."""
        branding = SimpleNamespace(
            logo="https://acme.com/primary-logo.png",
            images={"logo": "https://acme.com/secondary-logo.png"},
        )
        assert extract_branding_logo_url(branding) == "https://acme.com/primary-logo.png"

    def test_images_logo_beats_og_image(self) -> None:
        """images['logo'] takes priority over images['og_image']."""
        branding = SimpleNamespace(
            logo=None,
            images={
                "logo": "https://acme.com/logo.png",
                "og_image": "https://acme.com/og.png",
                "favicon": "https://acme.com/fav.ico",
            },
        )
        assert extract_branding_logo_url(branding) == "https://acme.com/logo.png"

    def test_returns_none_for_none_input(self) -> None:
        """None branding returns None."""
        assert extract_branding_logo_url(None) is None

    def test_returns_none_for_empty_branding(self) -> None:
        """Branding with no logo or images returns None."""
        branding = SimpleNamespace(logo=None, images=None)
        assert extract_branding_logo_url(branding) is None

    def test_returns_none_for_all_none_images(self) -> None:
        """Branding with all-None image values returns None."""
        branding = SimpleNamespace(
            logo=None,
            images={"logo": None, "og_image": None, "favicon": None},
        )
        assert extract_branding_logo_url(branding) is None

    def test_rejects_yc_logo_url(self) -> None:
        """Y Combinator logo URLs are rejected."""
        branding = SimpleNamespace(
            logo="https://cdn.ycombinator.com/logo.png",
            images=None,
        )
        assert extract_branding_logo_url(branding) is None

    def test_rejects_yc_in_images(self) -> None:
        """YC URLs in images dict are also rejected."""
        branding = SimpleNamespace(
            logo=None,
            images={"logo": "https://assets.site.com/yc-logo.svg"},
        )
        assert extract_branding_logo_url(branding) is None

    def test_rejects_tiktok_logo(self) -> None:
        """TikTok platform logos are rejected."""
        branding = SimpleNamespace(
            logo="https://tiktok-common.example.com/logo.png",
            images=None,
        )
        assert extract_branding_logo_url(branding) is None

    def test_rejects_google_logo(self) -> None:
        """Google logos are rejected."""
        branding = SimpleNamespace(
            logo="https://cdn.site.com/google-logo.svg",
            images=None,
        )
        assert extract_branding_logo_url(branding) is None

    def test_rejects_calendly_favicon(self) -> None:
        """Calendly generic favicons are rejected."""
        branding = SimpleNamespace(
            logo="https://calendly.com/assets/favicon/icon.png",
            images=None,
        )
        assert extract_branding_logo_url(branding) is None

    def test_skips_empty_string_logo(self) -> None:
        """Empty string logo field is treated as absent."""
        branding = SimpleNamespace(logo="", images=None)
        assert extract_branding_logo_url(branding) is None

    def test_skips_whitespace_only_logo(self) -> None:
        """Whitespace-only logo field is treated as absent."""
        branding = SimpleNamespace(logo="  ", images=None)
        assert extract_branding_logo_url(branding) is None

    def test_skips_empty_string_in_images(self) -> None:
        """Empty string in images dict is skipped."""
        branding = SimpleNamespace(
            logo=None,
            images={"logo": "", "og_image": "https://acme.com/og.png"},
        )
        assert extract_branding_logo_url(branding) == "https://acme.com/og.png"

    def test_falls_through_rejected_to_valid(self) -> None:
        """If primary URL is rejected, falls through to valid alternative."""
        branding = SimpleNamespace(
            logo="https://cdn.ycombinator.com/yc.png",
            images={"logo": "https://acme.com/real-logo.png"},
        )
        assert extract_branding_logo_url(branding) == "https://acme.com/real-logo.png"

    def test_works_with_dict_input(self) -> None:
        """Also works with plain dict branding (not just objects)."""
        branding = {
            "logo": "https://acme.com/dict-logo.png",
            "images": {"logo": "https://acme.com/images-logo.png"},
        }
        assert extract_branding_logo_url(branding) == "https://acme.com/dict-logo.png"

    def test_dict_fallback_to_images(self) -> None:
        """Dict branding falls back to images when logo is missing."""
        branding = {
            "images": {"logo": "https://acme.com/from-images.png"},
        }
        assert extract_branding_logo_url(branding) == "https://acme.com/from-images.png"

    def test_empty_images_dict(self) -> None:
        """Empty images dict returns None."""
        branding = SimpleNamespace(logo=None, images={})
        assert extract_branding_logo_url(branding) is None
