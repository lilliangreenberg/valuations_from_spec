"""Unit tests for the LLM short-circuit in change_detector."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.domains.monitoring.services.change_detector import _should_skip_llm


@dataclass
class _FakeSig:
    classification: str
    confidence: float
    matched_categories: list[str] = field(default_factory=list)


class TestShouldSkipLLM:
    def test_insignificant_minor_high_confidence_skips(self) -> None:
        sig = _FakeSig(classification="insignificant", confidence=0.9)
        assert _should_skip_llm(sig, "minor") is True

    def test_insignificant_minor_low_confidence_does_not_skip(self) -> None:
        sig = _FakeSig(classification="insignificant", confidence=0.6)
        assert _should_skip_llm(sig, "minor") is False

    def test_insignificant_major_does_not_skip(self) -> None:
        """Major-magnitude changes always deserve LLM scrutiny."""
        sig = _FakeSig(classification="insignificant", confidence=0.95)
        assert _should_skip_llm(sig, "major") is False

    def test_significant_high_confidence_decisive_category_skips(self) -> None:
        sig = _FakeSig(
            classification="significant",
            confidence=0.92,
            matched_categories=["closure"],
        )
        assert _should_skip_llm(sig, "major") is True

    def test_significant_high_confidence_vague_category_does_not_skip(self) -> None:
        sig = _FakeSig(
            classification="significant",
            confidence=0.92,
            matched_categories=["misc"],
        )
        assert _should_skip_llm(sig, "major") is False

    def test_significant_low_confidence_does_not_skip(self) -> None:
        sig = _FakeSig(
            classification="significant",
            confidence=0.70,
            matched_categories=["funding"],
        )
        assert _should_skip_llm(sig, "major") is False

    def test_uncertain_never_skips(self) -> None:
        sig = _FakeSig(classification="uncertain", confidence=0.99)
        assert _should_skip_llm(sig, "minor") is False
