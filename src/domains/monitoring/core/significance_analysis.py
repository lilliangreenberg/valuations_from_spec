"""Keyword-based significance analysis for content changes and news articles."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- Keyword Dictionaries ---

POSITIVE_KEYWORDS: dict[str, list[str]] = {
    "funding_investment": [
        "funding",
        "raised",
        "series a",
        "series b",
        "series c",
        "series d",
        "series e",
        "venture capital",
        "seed round",
        "valuation",
        "unicorn",
        "pre-seed",
        "funding round",
        "investment round",
        "capital raise",
        "angel round",
    ],
    "product_launch": [
        "launched",
        "new product",
        "beta release",
        "general availability",
        "rollout",
        "product launch",
        "new feature",
        "release",
        "public beta",
        "early access",
    ],
    "growth_success": [
        "revenue growth",
        "profitable",
        "milestone",
        "arr",
        "mrr",
        "doubled",
        "tripled",
        "record revenue",
        "growth rate",
        "user growth",
    ],
    "partnerships": [
        "partnership",
        "strategic alliance",
        "joint venture",
        "signed deal",
        "collaboration",
        "partner",
        "teaming up",
    ],
    "expansion": [
        "expansion",
        "new office",
        "international",
        "hiring",
        "scale up",
        "new market",
        "global expansion",
        "opened office",
        "expanding team",
    ],
    "recognition": [
        "award",
        "winner",
        "top 10",
        "best of",
        "innovation award",
        "recognized",
        "honored",
        "named to",
        "included in",
    ],
    "ipo_exit": [
        "ipo",
        "going public",
        "filed s-1",
        "direct listing",
        "nasdaq",
        "nyse",
        "stock exchange",
        "public offering",
        "spac",
    ],
}

NEGATIVE_KEYWORDS: dict[str, list[str]] = {
    "closure": [
        "shut down",
        "closed down",
        "ceased operations",
        "discontinued",
        "winding down",
        "shutting down",
        "closing",
        "going out of business",
        "no longer operating",
    ],
    "layoffs_downsizing": [
        "layoffs",
        "downsizing",
        "workforce reduction",
        "job cuts",
        "restructuring",
        "furlough",
        "laid off",
        "headcount reduction",
        "rif",
        "reduction in force",
    ],
    "financial_distress": [
        "bankruptcy",
        "insolvent",
        "chapter 11",
        "cash crunch",
        "debt crisis",
        "defaulted",
        "financial difficulties",
        "creditors",
        "liquidation",
    ],
    "legal_issues": [
        "lawsuit",
        "litigation",
        "investigation",
        "settlement",
        "fine",
        "penalty",
        "sued",
        "regulatory action",
        "compliance violation",
        "subpoena",
    ],
    "security_breach": [
        "data breach",
        "hacked",
        "cyberattack",
        "ransomware",
        "vulnerability",
        "security incident",
        "compromised",
        "unauthorized access",
    ],
    "acquisition": [
        "acquired by",
        "merged with",
        "sold to",
        "bought by",
        "takeover",
        "acquisition",
        "merger",
        "buyout",
    ],
    "leadership_changes": [
        "ceo resigned",
        "founder left",
        "stepping down",
        "ousted",
        "leadership change",
        "executive departure",
        "cto left",
    ],
    "product_failures": [
        "recall",
        "discontinued product",
        "defect",
        "safety issue",
        "product failure",
        "pulled from market",
    ],
    "market_exit": [
        "exiting market",
        "pulling out",
        "retreat",
        "abandoned",
        "market withdrawal",
        "leaving market",
    ],
}

INSIGNIFICANT_PATTERNS: dict[str, list[str]] = {
    "css_styling": [
        "font-family",
        "background-color",
        "margin:",
        "padding:",
        ".css",
        "border-radius",
        "text-align",
        "font-size",
    ],
    "copyright_year": [
        "(c)",
        "copyright",
        "all rights reserved",
    ],
    "tracking_analytics": [
        "google-analytics",
        "gtag",
        "tracking",
        "pixel",
        "analytics",
        "hotjar",
        "mixpanel",
    ],
}

# False positive phrases that look like keywords but are not
FALSE_POSITIVE_PHRASES: list[str] = [
    "talent acquisition",
    "customer acquisition",
    "data acquisition",
    "funding opportunities",
    "funding sources",
    "self-funded",
]

# Negation words that precede keywords
NEGATION_WORDS: list[str] = [
    "no",
    "not",
    "never",
    "without",
    "lacks",
    "none",
]

# Negation suffix patterns that follow keywords (e.g., "funding status: none")
NEGATION_SUFFIX_PATTERNS: list[str] = [
    "status: none",
    "date: n/a",
    "status:none",
    "date:n/a",
]


@dataclass
class KeywordMatchResult:
    """Result of a keyword match in content."""

    keyword: str
    category: str
    position: int
    context_before: str
    context_after: str
    is_negated: bool = False
    is_false_positive: bool = False


@dataclass
class SignificanceResult:
    """Result of significance analysis."""

    classification: str  # "significant", "insignificant", "uncertain"
    sentiment: str  # "positive", "negative", "neutral", "mixed"
    confidence: float  # 0.0-1.0
    matched_keywords: list[str] = field(default_factory=list)
    matched_categories: list[str] = field(default_factory=list)
    notes: str | None = None
    evidence_snippets: list[str] = field(default_factory=list)


def find_keyword_matches(
    content: str,
    keywords: dict[str, list[str]],
) -> list[KeywordMatchResult]:
    """Find all keyword matches in content.

    Returns list of KeywordMatchResult with context.
    """
    content_lower = content.lower()
    matches: list[KeywordMatchResult] = []

    for category, terms in keywords.items():
        for keyword in terms:
            # Use word boundary matching to avoid partial matches
            pattern = re.compile(r"\b" + re.escape(keyword) + r"\b", re.IGNORECASE)
            for match in pattern.finditer(content_lower):
                position = match.start()
                context_start = max(0, position - 50)
                context_end = min(len(content), match.end() + 50)
                context_before = content[context_start:position].strip()[:50]
                context_after = content[match.end() : context_end].strip()[:50]

                matches.append(
                    KeywordMatchResult(
                        keyword=keyword,
                        category=category,
                        position=position,
                        context_before=context_before,
                        context_after=context_after,
                    )
                )

    return matches


def detect_negation(matches: list[KeywordMatchResult], content: str) -> list[KeywordMatchResult]:
    """Check if keyword matches are preceded by negation words or followed by negation suffixes.

    Prefix negation: "no funding", "not acquired", "without partnership"
    Suffix negation: "funding status: none", "funding date: N/A"

    Negation reduces confidence by 20%.
    """
    content_lower = content.lower()
    for match in matches:
        # Check prefix negation: negation words in the 20 chars before the keyword
        start = max(0, match.position - 20)
        prefix = content_lower[start : match.position].strip()
        for neg_word in NEGATION_WORDS:
            if prefix.endswith(neg_word) or f" {neg_word} " in f" {prefix} ":
                match.is_negated = True
                break

        # Check suffix negation: patterns in the 30 chars after the keyword
        if not match.is_negated:
            keyword_end = match.position + len(match.keyword)
            suffix_end = min(len(content_lower), keyword_end + 30)
            suffix = content_lower[keyword_end:suffix_end].strip()
            for suffix_pattern in NEGATION_SUFFIX_PATTERNS:
                if suffix.startswith(suffix_pattern):
                    match.is_negated = True
                    break
    return matches


def detect_false_positives(
    matches: list[KeywordMatchResult], content: str
) -> list[KeywordMatchResult]:
    """Check if keyword matches are actually false positive phrases.

    False positives reduce confidence by 30%.
    """
    content_lower = content.lower()
    for match in matches:
        for fp_phrase in FALSE_POSITIVE_PHRASES:
            # Check if the keyword is part of a known false positive phrase
            fp_start = content_lower.find(fp_phrase)
            if fp_start != -1:
                fp_end = fp_start + len(fp_phrase)
                if fp_start <= match.position < fp_end:
                    match.is_false_positive = True
                    break
    return matches


def _determine_sentiment(positive_count: int, negative_count: int) -> str:
    """Determine sentiment from keyword counts.

    - 2+ positive AND 2+ negative -> mixed
    - 2+ negative only -> negative
    - 2+ positive only -> positive
    - < 2 total -> neutral
    """
    if positive_count >= 2 and negative_count >= 2:
        return "mixed"
    if negative_count >= 2:
        return "negative"
    if positive_count >= 2:
        return "positive"
    return "neutral"


def classify_significance(
    positive_matches: list[KeywordMatchResult],
    negative_matches: list[KeywordMatchResult],
    insignificant_matches: list[KeywordMatchResult],
    magnitude: str = "minor",
) -> SignificanceResult:
    """Classify significance based on keyword matches and change magnitude.

    Classification rules:
    1. Only insignificant patterns + minor magnitude -> INSIGNIFICANT (85%)
    2. 2+ negative keywords -> SIGNIFICANT (80-95%)
    3. 2+ positive keywords -> SIGNIFICANT (80-90%)
    4. 1 keyword + major magnitude -> SIGNIFICANT (70%)
    5a. 1 keyword + minor magnitude -> UNCERTAIN (50%)
    5b. 1 keyword + moderate magnitude -> UNCERTAIN (60%)
    6. No keywords -> INSIGNIFICANT (75%)
    """
    # Filter out negated and false positive matches for counting
    effective_positive = [
        m for m in positive_matches if not m.is_negated and not m.is_false_positive
    ]
    effective_negative = [
        m for m in negative_matches if not m.is_negated and not m.is_false_positive
    ]

    all_keywords = [m.keyword for m in effective_positive + effective_negative]
    all_categories = list({m.category for m in effective_positive + effective_negative})
    evidence = [
        m.context_before + " [" + m.keyword + "] " + m.context_after
        for m in effective_positive + effective_negative
    ]

    # Rule 1: Only insignificant patterns
    if (
        insignificant_matches
        and not effective_positive
        and not effective_negative
        and magnitude == "minor"
    ):
        return SignificanceResult(
            classification="insignificant",
            sentiment="neutral",
            confidence=0.85,
            matched_keywords=[m.keyword for m in insignificant_matches],
            matched_categories=[m.category for m in insignificant_matches],
            notes="Only insignificant patterns detected with minor changes",
        )

    # Calculate base confidence with adjustments
    negated_count = sum(1 for m in positive_matches + negative_matches if m.is_negated)
    false_positive_count = sum(
        1 for m in positive_matches + negative_matches if m.is_false_positive
    )

    confidence_reduction = (negated_count * 0.20) + (false_positive_count * 0.30)

    # Rule 2: 2+ negative keywords
    if len(effective_negative) >= 2:
        base_confidence = 0.80 + min(0.15, len(effective_negative) * 0.05)
        return SignificanceResult(
            classification="significant",
            sentiment=_determine_sentiment(len(effective_positive), len(effective_negative)),
            confidence=max(0.0, base_confidence - confidence_reduction),
            matched_keywords=all_keywords,
            matched_categories=all_categories,
            notes=(
                f"Multiple negative signals detected ({len(effective_negative)} negative keywords)"
            ),
            evidence_snippets=evidence,
        )

    # Rule 3: 2+ positive keywords
    if len(effective_positive) >= 2:
        base_confidence = 0.80 + min(0.10, len(effective_positive) * 0.05)
        return SignificanceResult(
            classification="significant",
            sentiment=_determine_sentiment(len(effective_positive), len(effective_negative)),
            confidence=max(0.0, base_confidence - confidence_reduction),
            matched_keywords=all_keywords,
            matched_categories=all_categories,
            notes=(
                f"Multiple positive signals detected ({len(effective_positive)} positive keywords)"
            ),
            evidence_snippets=evidence,
        )

    # Rule 4 & 5: 1 keyword with magnitude
    total_effective = len(effective_positive) + len(effective_negative)
    if total_effective == 1:
        if magnitude == "major":
            return SignificanceResult(
                classification="significant",
                sentiment=_determine_sentiment(len(effective_positive), len(effective_negative)),
                confidence=max(0.0, 0.70 - confidence_reduction),
                matched_keywords=all_keywords,
                matched_categories=all_categories,
                notes="Single keyword with major content change",
                evidence_snippets=evidence,
            )
        elif magnitude == "minor":
            return SignificanceResult(
                classification="uncertain",
                sentiment=_determine_sentiment(len(effective_positive), len(effective_negative)),
                confidence=max(0.0, 0.50 - confidence_reduction),
                matched_keywords=all_keywords,
                matched_categories=all_categories,
                notes="Single keyword with minor content change",
                evidence_snippets=evidence,
            )
        else:
            # moderate magnitude with 1 keyword
            return SignificanceResult(
                classification="uncertain",
                sentiment=_determine_sentiment(len(effective_positive), len(effective_negative)),
                confidence=max(0.0, 0.60 - confidence_reduction),
                matched_keywords=all_keywords,
                matched_categories=all_categories,
                notes="Single keyword with moderate content change",
                evidence_snippets=evidence,
            )

    # Rule 6: No keywords
    return SignificanceResult(
        classification="insignificant",
        sentiment="neutral",
        confidence=0.75,
        notes="No significant keywords detected",
    )


def analyze_content_significance(
    content: str,
    magnitude: str = "minor",
) -> SignificanceResult:
    """Full significance analysis pipeline for content.

    1. Find keyword matches (positive, negative, insignificant)
    2. Detect negation
    3. Detect false positives
    4. Classify significance
    """
    positive_matches = find_keyword_matches(content, POSITIVE_KEYWORDS)
    negative_matches = find_keyword_matches(content, NEGATIVE_KEYWORDS)
    insignificant_matches = find_keyword_matches(content, INSIGNIFICANT_PATTERNS)

    # Apply negation and false positive detection
    positive_matches = detect_negation(positive_matches, content)
    negative_matches = detect_negation(negative_matches, content)
    positive_matches = detect_false_positives(positive_matches, content)
    negative_matches = detect_false_positives(negative_matches, content)

    return classify_significance(
        positive_matches, negative_matches, insignificant_matches, magnitude
    )
