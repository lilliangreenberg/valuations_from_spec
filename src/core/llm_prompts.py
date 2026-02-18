"""LLM prompt templates for significance validation and company verification."""

from __future__ import annotations

SIGNIFICANCE_VALIDATION_SYSTEM_PROMPT = (
    "You are analyzing website content changes for a venture capital portfolio"
    " monitoring system.\n"
    "Your task is to validate whether detected changes are genuinely significant"
    " for business monitoring purposes.\n\n"
    "Respond with a JSON object containing:\n"
    '- classification: "significant", "insignificant", or "uncertain"\n'
    '- sentiment: "positive", "negative", "neutral", or "mixed"\n'
    "- confidence: float between 0.0 and 1.0\n"
    "- reasoning: brief explanation of your classification\n"
    "- validated_keywords: list of keywords you confirm are relevant\n"
    "- false_positives: list of keywords that are false positives"
)

SIGNIFICANCE_VALIDATION_USER_TEMPLATE = (
    "Analyze this content change:\n\n"
    "Content excerpt:\n{content_excerpt}\n\n"
    "Detected keywords: {keywords}\n"
    "Detected categories: {categories}\n"
    "Initial classification: {initial_classification}\n"
    "Change magnitude: {magnitude}\n\n"
    "Validate whether this change is genuinely significant for a VC portfolio"
    " monitoring system.\n"
    "Respond with JSON only."
)


NEWS_SIGNIFICANCE_SYSTEM_PROMPT = (
    "You are analyzing news articles for a venture capital portfolio monitoring"
    " system.\n"
    "Determine if the article represents a significant business event.\n\n"
    "Respond with a JSON object containing:\n"
    '- classification: "significant", "insignificant", or "uncertain"\n'
    '- sentiment: "positive", "negative", "neutral", or "mixed"\n'
    "- confidence: float between 0.0 and 1.0\n"
    "- reasoning: brief explanation\n"
    "- validated_keywords: list of confirmed relevant keywords\n"
    "- false_positives: list of false positive keywords"
)

NEWS_SIGNIFICANCE_USER_TEMPLATE = (
    "Analyze this news article:\n\n"
    "Title: {title}\n"
    "Source: {source}\n"
    "Content: {content}\n\n"
    "Detected keywords: {keywords}\n"
    "Company: {company_name}\n\n"
    "Is this article significant for VC portfolio monitoring?"
    " Respond with JSON only."
)


COMPANY_VERIFICATION_SYSTEM_PROMPT = (
    "You are verifying whether a news article is about a specific company.\n"
    "The company may have a common name, so careful verification is needed.\n\n"
    "Respond with a JSON object containing:\n"
    "- is_match: boolean - whether the article is about this specific company\n"
    "- confidence: float between 0.0 and 1.0\n"
    "- reasoning: brief explanation of your determination"
)

COMPANY_VERIFICATION_USER_TEMPLATE = (
    'Is this article about the company "{company_name}"?\n\n'
    "Company homepage: {company_url}\n"
    "Article title: {article_title}\n"
    "Article source: {article_source}\n"
    "Article snippet: {article_snippet}\n\n"
    "Consider: Could this article be about a different entity with a similar"
    " name?\n"
    "Respond with JSON only."
)


def build_significance_validation_prompt(
    content_excerpt: str,
    keywords: list[str],
    categories: list[str],
    initial_classification: str,
    magnitude: str,
) -> tuple[str, str]:
    """Build system and user prompts for significance validation.

    Returns (system_prompt, user_prompt).
    """
    user_prompt = SIGNIFICANCE_VALIDATION_USER_TEMPLATE.format(
        content_excerpt=content_excerpt[:2000],
        keywords=", ".join(keywords),
        categories=", ".join(categories),
        initial_classification=initial_classification,
        magnitude=magnitude,
    )
    return SIGNIFICANCE_VALIDATION_SYSTEM_PROMPT, user_prompt


def build_news_significance_prompt(
    title: str,
    source: str,
    content: str,
    keywords: list[str],
    company_name: str,
) -> tuple[str, str]:
    """Build prompts for news significance validation."""
    user_prompt = NEWS_SIGNIFICANCE_USER_TEMPLATE.format(
        title=title,
        source=source,
        content=content[:2000],
        keywords=", ".join(keywords),
        company_name=company_name,
    )
    return NEWS_SIGNIFICANCE_SYSTEM_PROMPT, user_prompt


def build_company_verification_prompt(
    company_name: str,
    company_url: str,
    article_title: str,
    article_source: str,
    article_snippet: str,
) -> tuple[str, str]:
    """Build prompts for company identity verification."""
    user_prompt = COMPANY_VERIFICATION_USER_TEMPLATE.format(
        company_name=company_name,
        company_url=company_url,
        article_title=article_title,
        article_source=article_source,
        article_snippet=article_snippet[:1000],
    )
    return COMPANY_VERIFICATION_SYSTEM_PROMPT, user_prompt
