"""LLM prompt templates for significance classification and company verification.

Prompts use explicit classification criteria and few-shot examples for consistency.
Tool use (structured outputs) enforces response format at the API level.
"""

from __future__ import annotations

# --- Shared Classification Criteria ---

_CLASSIFICATION_CRITERIA = (
    "CLASSIFICATION RULES (apply in order):\n\n"
    "SIGNIFICANT (positive): funding round, new product/feature launch, market/geo expansion,"
    " major partnership (named), IPO/public listing, enterprise customer win (named),"
    " pricing page added, API/developer docs added, SOC2/compliance certification, hiring surge\n"
    "SIGNIFICANT (negative): shutdown/winding down notice, being acquired (loss of independence),"
    " domain -> 404/parked/redirect, site content dramatically shrinks (full site to single page),"
    " layoffs/RIF, office closure, CEO/founder/C-suite departure, leadership/team page removed,"
    " careers page removed, legal action/regulatory/SEC, product line discontinued,"
    " brand replaced by acquirer\n"
    "SIGNIFICANT (neutral): rebrand without acquisition, pivot to new market, merger with peer\n"
    "INSIGNIFICANT: CSS/styling/layout, copyright year, navigation/menu, marketing copy refresh,"
    " testimonials/case studies, blog post listings, job posting count,"
    " analytics/meta tags/cookies, team photo updates, event dates\n"
    "UNCERTAIN: potentially significant signal but content too"
    " truncated/ambiguous to confirm\n\n"
    "Defaults: significant vs insignificant -> insignificant."
    " significant vs uncertain -> uncertain.\n"
    "Never classify routine marketing language as significant."
)

_FALSE_POSITIVE_RULES = (
    "FALSE POSITIVE RULES:\n"
    "- Keywords matching the company's own name or domain are NOT signals\n"
    "- 'talent acquisition' or 'customer acquisition' != company acquisition\n"
    "- 'funding opportunities' or 'funding sources' != funding round\n"
    "- Navigation/footer changes containing business terms are NOT signals\n"
    "- Marketing language that sounds significant but is routine is NOT significant"
)

# --- Few-Shot Examples ---

_FEW_SHOT_EXAMPLES = (
    "EXAMPLES:\n\n"
    'Example 1 -- Insignificant (routine update):\n'
    'Company "Acme Labs" (acmelabs.io). Copyright year 2025->2026, nav text changes, team photo'
    " swap. Magnitude: minor. Keywords: none.\n"
    "Result: classification=insignificant, sentiment=neutral, confidence=0.95,"
    ' reasoning="Copyright year and photo swap are routine maintenance.",'
    " company_status=operational,"
    ' status_reason="Active website maintenance indicates normal operations."\n\n'
    'Example 2 -- Significant negative (acquisition):\n'
    'Company "DataSync" (datasync.com). Content: "DataSync has been acquired by Snowflake.'
    ' Our team will be joining Snowflake..." Magnitude: major. Keywords: acquired, acquisition.\n'
    "Result: classification=significant, sentiment=negative, confidence=0.95,"
    ' reasoning="Explicit acquisition by Snowflake means DataSync is no longer independent.",'
    " validated_keywords=[acquired, acquisition], company_status=likely_closed,"
    ' status_reason="DataSync acquired by Snowflake per homepage announcement."\n\n'
    'Example 3 -- Insignificant (false positive keywords):\n'
    'Company "Recall AI" (recall.ai). Product updates: "recall your meetings instantly",'
    ' "talent acquisition teams love our product". Magnitude: moderate.'
    " Keywords: recall, talent acquisition.\n"
    "Result: classification=insignificant, sentiment=neutral, confidence=0.90,"
    " reasoning=\"'Recall' is the company name, 'talent acquisition' describes their customers.\","
    " false_positives=[recall, talent acquisition], company_status=operational,"
    ' status_reason="Product updates indicate active development."'
)

# --- Change Significance Classification ---

SIGNIFICANCE_CLASSIFICATION_SYSTEM_PROMPT = (
    "You analyze website content changes for a VC portfolio monitoring system.\n"
    "Classify whether changes represent genuinely significant business events.\n\n"
    "You receive: content excerpt, change magnitude, keyword hints from an automated scanner.\n"
    "Keywords are hints only -- they may be false positives.\n\n"
    + _CLASSIFICATION_CRITERIA
    + "\n\n"
    + _FALSE_POSITIVE_RULES
    + "\n\n"
    + _FEW_SHOT_EXAMPLES
)

SIGNIFICANCE_CLASSIFICATION_USER_TEMPLATE = (
    "Company: {company_name}\n"
    "Homepage: {homepage_url}\n\n"
    "Content excerpt (changed/added text):\n{content_excerpt}\n\n"
    "Change magnitude: {magnitude}\n\n"
    "Keyword hints: {keywords}\n"
    "Categories: {categories}"
)


def build_significance_classification_prompt(
    content_excerpt: str,
    keywords: list[str],
    categories: list[str],
    magnitude: str,
    company_name: str,
    homepage_url: str,
) -> tuple[str, str]:
    """Build system and user prompts for significance classification.

    Returns (system_prompt, user_prompt).
    """
    user_prompt = SIGNIFICANCE_CLASSIFICATION_USER_TEMPLATE.format(
        content_excerpt=content_excerpt[:2000],
        keywords=", ".join(keywords) if keywords else "none detected",
        categories=", ".join(categories) if categories else "none",
        magnitude=magnitude,
        company_name=company_name,
        homepage_url=homepage_url,
    )
    return SIGNIFICANCE_CLASSIFICATION_SYSTEM_PROMPT, user_prompt


# --- Baseline Classification ---

BASELINE_CLASSIFICATION_SYSTEM_PROMPT = (
    "You analyze a company's website content for a VC portfolio monitoring system.\n"
    "This is a BASELINE analysis of full website content captured for the first time.\n"
    "Identify pre-existing signals about company health and operational status.\n\n"
    + _CLASSIFICATION_CRITERIA
    + "\n\n"
    + _FALSE_POSITIVE_RULES
)

BASELINE_CLASSIFICATION_USER_TEMPLATE = (
    "Company: {company_name}\n"
    "Homepage: {homepage_url}\n\n"
    "Website content excerpt:\n{content_excerpt}\n\n"
    "Keyword hints: {keywords}\n"
    "Categories: {categories}\n\n"
    "Identify any pre-existing signals (positive or negative) about operational health."
)


def build_baseline_classification_prompt(
    content_excerpt: str,
    keywords: list[str],
    categories: list[str],
    company_name: str,
    homepage_url: str,
) -> tuple[str, str]:
    """Build prompts for baseline significance classification.

    Returns (system_prompt, user_prompt).
    """
    user_prompt = BASELINE_CLASSIFICATION_USER_TEMPLATE.format(
        content_excerpt=content_excerpt[:2000],
        keywords=", ".join(keywords) if keywords else "none detected",
        categories=", ".join(categories) if categories else "none",
        company_name=company_name,
        homepage_url=homepage_url,
    )
    return BASELINE_CLASSIFICATION_SYSTEM_PROMPT, user_prompt


# --- News Significance Classification ---

NEWS_CLASSIFICATION_SYSTEM_PROMPT = (
    "You analyze news articles for a VC portfolio monitoring system.\n"
    "Determine if a news article represents a significant business event.\n\n"
    + _CLASSIFICATION_CRITERIA
    + "\n\n"
    + _FALSE_POSITIVE_RULES
)

NEWS_CLASSIFICATION_USER_TEMPLATE = (
    "Company: {company_name}\n"
    "Title: {title}\n"
    "Source: {source}\n"
    "Content: {content}\n\n"
    "Keyword hints: {keywords}\n\n"
    "Is this article a significant business event for {company_name}?"
)


def build_news_classification_prompt(
    title: str,
    source: str,
    content: str,
    keywords: list[str],
    company_name: str,
) -> tuple[str, str]:
    """Build prompts for news significance classification.

    Returns (system_prompt, user_prompt).
    """
    user_prompt = NEWS_CLASSIFICATION_USER_TEMPLATE.format(
        title=title,
        source=source,
        content=content[:2000],
        keywords=", ".join(keywords) if keywords else "none detected",
        company_name=company_name,
    )
    return NEWS_CLASSIFICATION_SYSTEM_PROMPT, user_prompt


# --- Company Verification ---

COMPANY_VERIFICATION_SYSTEM_PROMPT = (
    "You verify whether a news article is about a specific company.\n"
    "The company may have a common name, so careful verification is needed.\n\n"
    "You receive a description of the company from their homepage.\n"
    "Determine if the article is about THIS company or a DIFFERENT entity.\n\n"
    "Check: same product/service? Same domain? Different industry/location/product?"
)

COMPANY_VERIFICATION_USER_TEMPLATE = (
    'Is this article about "{company_name}"?\n\n'
    "Company homepage: {company_url}\n"
    "Company description: {company_description}\n\n"
    "Article title: {article_title}\n"
    "Article source: {article_source}\n"
    "Article snippet: {article_snippet}"
)


def build_company_verification_prompt(
    company_name: str,
    company_url: str,
    article_title: str,
    article_source: str,
    article_snippet: str,
    company_description: str = "",
) -> tuple[str, str]:
    """Build prompts for company identity verification."""
    user_prompt = COMPANY_VERIFICATION_USER_TEMPLATE.format(
        company_name=company_name,
        company_url=company_url,
        company_description=company_description or "No description available.",
        article_title=article_title,
        article_source=article_source,
        article_snippet=article_snippet[:1000],
    )
    return COMPANY_VERIFICATION_SYSTEM_PROMPT, user_prompt


# --- Status-Aware Significance Classification ---

_STATUS_RULES = (
    "STATUS DETERMINATION:\n"
    "- operational: active website with product/hiring/business content\n"
    "- likely_closed: shutdown notice, acquired, domain parked/404/redirect,"
    " 'winding down' language\n"
    "- uncertain: insufficient evidence\n\n"
    "Default to operational. Only change status with clear, strong evidence.\n"
    "Minor or insignificant website changes should NOT flip status."
)

STATUS_AWARE_SIGNIFICANCE_SYSTEM_PROMPT = (
    "You analyze website content changes for a VC portfolio monitoring system.\n"
    "Classify change significance AND determine the company's operational status.\n\n"
    + _CLASSIFICATION_CRITERIA
    + "\n\n"
    + _FALSE_POSITIVE_RULES
    + "\n\n"
    + _STATUS_RULES
    + "\n\n"
    + _FEW_SHOT_EXAMPLES
)


def build_status_aware_significance_prompt(
    content_excerpt: str,
    keywords: list[str],
    categories: list[str],
    magnitude: str,
    company_name: str,
    homepage_url: str,
    company_notes: str = "",
) -> tuple[str, str]:
    """Build prompts for status-aware significance classification.

    Returns (system_prompt, user_prompt).
    """
    user_prompt = SIGNIFICANCE_CLASSIFICATION_USER_TEMPLATE.format(
        content_excerpt=content_excerpt[:2000],
        keywords=", ".join(keywords) if keywords else "none detected",
        categories=", ".join(categories) if categories else "none",
        magnitude=magnitude,
        company_name=company_name,
        homepage_url=homepage_url,
    )
    if company_notes.strip():
        user_prompt += (
            f"\n\nAnalyst notes:\n{company_notes.strip()}\n"
            "Take these notes into account for classification and status."
        )
    return STATUS_AWARE_SIGNIFICANCE_SYSTEM_PROMPT, user_prompt


# --- Enriched Significance Classification (with Social Media Context) ---

_SOCIAL_SIGNALS = (
    "SOCIAL MEDIA SIGNALS:\n"
    "- Recent blog/Medium posts about product/funding/growth = positive\n"
    "- Blog/Medium inactive 1+ year = negative signal\n"
    "- No social presence = neutral (not all companies blog)\n"
    "Reference BOTH homepage and social signals in reasoning."
)

ENRICHED_SIGNIFICANCE_SYSTEM_PROMPT = (
    "You analyze website content changes for a VC portfolio monitoring system.\n"
    "You receive homepage change data AND social media activity data.\n\n"
    + _CLASSIFICATION_CRITERIA
    + "\n\n"
    + _FALSE_POSITIVE_RULES
    + "\n\n"
    + _SOCIAL_SIGNALS
    + "\n\n"
    + _FEW_SHOT_EXAMPLES
)

ENRICHED_SIGNIFICANCE_USER_TEMPLATE = (
    "Company: {company_name}\n"
    "Homepage: {homepage_url}\n\n"
    "Content excerpt (changed/added text):\n{content_excerpt}\n\n"
    "Change magnitude: {magnitude}\n\n"
    "Social media context:\n{social_context}\n\n"
    "Keyword hints: {keywords}\n"
    "Categories: {categories}"
)


def build_enriched_significance_prompt(
    content_excerpt: str,
    keywords: list[str],
    categories: list[str],
    magnitude: str,
    company_name: str,
    homepage_url: str,
    social_context: str,
) -> tuple[str, str]:
    """Build prompts for enriched significance classification with social context.

    Returns (system_prompt, user_prompt).
    """
    user_prompt = ENRICHED_SIGNIFICANCE_USER_TEMPLATE.format(
        content_excerpt=content_excerpt[:2000],
        keywords=", ".join(keywords) if keywords else "none detected",
        categories=", ".join(categories) if categories else "none",
        magnitude=magnitude,
        company_name=company_name,
        homepage_url=homepage_url,
        social_context=social_context,
    )
    return ENRICHED_SIGNIFICANCE_SYSTEM_PROMPT, user_prompt


# --- Status-Aware Enriched Significance Classification ---

STATUS_AWARE_ENRICHED_SYSTEM_PROMPT = (
    "You analyze website content changes for a VC portfolio monitoring system.\n"
    "You receive homepage change data AND social media activity data.\n"
    "Classify change significance AND determine operational status.\n\n"
    + _CLASSIFICATION_CRITERIA
    + "\n\n"
    + _FALSE_POSITIVE_RULES
    + "\n\n"
    + _SOCIAL_SIGNALS
    + "\n\n"
    + _STATUS_RULES
    + "\n\n"
    + _FEW_SHOT_EXAMPLES
)


def build_status_aware_enriched_prompt(
    content_excerpt: str,
    keywords: list[str],
    categories: list[str],
    magnitude: str,
    company_name: str,
    homepage_url: str,
    social_context: str,
    company_notes: str = "",
) -> tuple[str, str]:
    """Build prompts for status-aware enriched significance classification.

    Returns (system_prompt, user_prompt).
    """
    user_prompt = ENRICHED_SIGNIFICANCE_USER_TEMPLATE.format(
        content_excerpt=content_excerpt[:2000],
        keywords=", ".join(keywords) if keywords else "none detected",
        categories=", ".join(categories) if categories else "none",
        magnitude=magnitude,
        company_name=company_name,
        homepage_url=homepage_url,
        social_context=social_context,
    )
    if company_notes.strip():
        user_prompt += (
            f"\n\nAnalyst notes:\n{company_notes.strip()}\n"
            "Take these notes into account for classification and status."
        )
    return STATUS_AWARE_ENRICHED_SYSTEM_PROMPT, user_prompt
