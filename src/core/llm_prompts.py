"""LLM prompt templates for significance classification and company verification.

Prompts are designed so the LLM acts as the PRIMARY classifier, not a validator.
Keyword matches from the automated scanner are passed as hints/context, but the
LLM makes its own independent determination without being anchored by the keyword
system's conclusion.
"""

from __future__ import annotations

# --- Change Significance Classification ---

SIGNIFICANCE_CLASSIFICATION_SYSTEM_PROMPT = (
    "You are analyzing website content changes for a venture capital portfolio"
    " monitoring system.\n"
    "Your task is to independently classify whether detected changes represent"
    " genuinely significant business events.\n\n"
    "You will receive a content excerpt showing what changed, the magnitude of"
    " the change, and keyword hints from an automated scanner. The keyword hints"
    " may contain false positives or miss important context. Use them as starting"
    " points for your analysis, but make your own independent judgment.\n\n"
    "IMPORTANT: You will be told the company's name and homepage URL. If a keyword\n"
    "match is simply the company's own name or a word derived from it, that is a\n"
    "false positive -- not a real signal. For example, a company called 'Recall'\n"
    "appearing on recall.ai will trigger 'recall' as a product_failures keyword,\n"
    "but that is just the company name, not a product recall event.\n\n"
    "Common false positives to watch for:\n"
    "- Keywords that match the company's own name or domain\n"
    "- 'talent acquisition' or 'customer acquisition' (not company acquisition)\n"
    "- 'funding opportunities' or 'funding sources' (not a funding round)\n"
    "- Navigation menu or footer changes containing business terms\n"
    "- Marketing language that sounds significant but is routine\n"
    "- Copyright year updates, CSS changes, analytics tracking\n\n"
    "Respond with a JSON object containing:\n"
    '- classification: "significant", "insignificant", or "uncertain"\n'
    '- sentiment: "positive", "negative", "neutral", or "mixed"\n'
    "- confidence: float between 0.0 and 1.0\n"
    "- reasoning: (REQUIRED) 1-3 sentences explaining WHY you classified this way."
    " What specific evidence drove your decision? If insignificant, explain what"
    " the keywords actually refer to in context.\n"
    "- validated_keywords: list of keyword hints you confirm are relevant\n"
    "- false_positives: list of keyword hints that are false positives"
)

SIGNIFICANCE_CLASSIFICATION_USER_TEMPLATE = (
    "Analyze this website content change for business significance:\n\n"
    "Company: {company_name}\n"
    "Homepage: {homepage_url}\n\n"
    "Content excerpt (changed/added text):\n{content_excerpt}\n\n"
    "Change magnitude: {magnitude}\n\n"
    "Keyword hints from automated scanner:\n"
    "  Detected terms: {keywords}\n"
    "  Categories: {categories}\n\n"
    "Classify this change independently. The keyword hints may be false positives.\n"
    "Respond with JSON only."
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

    Keywords and categories are passed as hints, not as the answer.
    Company name and URL are included so the LLM can identify false positives
    where keyword matches are just the company's own name.

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
    "You are analyzing a company's website content for a venture capital portfolio"
    " monitoring system.\n"
    "This is a BASELINE analysis of the company's full website content, captured"
    " for the first time. Your task is to identify any pre-existing signals about"
    " the company's health and operational status.\n\n"
    "Look for indicators such as:\n"
    "- Company is operational and active (product pages, recent updates, hiring)\n"
    "- Company has been acquired ('now part of X', 'acquired by X')\n"
    "- Company has shut down or is winding down\n"
    "- Recent funding announcements still on the homepage\n"
    "- Signs of financial distress or legal issues\n"
    "- Product launches or growth indicators\n\n"
    "You will receive keyword hints from an automated scanner. These may contain"
    " false positives -- use them as starting points but make your own judgment.\n\n"
    "IMPORTANT: You will be told the company's name and homepage URL. If a keyword\n"
    "match is simply the company's own name or a word derived from it, that is a\n"
    "false positive -- not a real signal.\n\n"
    "Respond with a JSON object containing:\n"
    '- classification: "significant", "insignificant", or "uncertain"\n'
    '- sentiment: "positive", "negative", "neutral", or "mixed"\n'
    "- confidence: float between 0.0 and 1.0\n"
    "- reasoning: (REQUIRED) 1-3 sentences explaining WHY you classified this way."
    " What specific evidence did you find about the company's operational status?"
    " If insignificant, explain why the keyword hints are not meaningful.\n"
    "- validated_keywords: list of keyword hints you confirm are relevant\n"
    "- false_positives: list of keyword hints that are false positives"
)

BASELINE_CLASSIFICATION_USER_TEMPLATE = (
    "Analyze this company's website content for pre-existing health signals:\n\n"
    "Company: {company_name}\n"
    "Homepage: {homepage_url}\n\n"
    "Website content excerpt:\n{content_excerpt}\n\n"
    "Keyword hints from automated scanner:\n"
    "  Detected terms: {keywords}\n"
    "  Categories: {categories}\n\n"
    "Determine if this company shows any significant pre-existing signals"
    " (positive or negative) about its operational health.\n"
    "Respond with JSON only."
)


def build_baseline_classification_prompt(
    content_excerpt: str,
    keywords: list[str],
    categories: list[str],
    company_name: str,
    homepage_url: str,
) -> tuple[str, str]:
    """Build prompts for baseline significance classification.

    Baseline analysis examines full website content (not a diff) to detect
    pre-existing signals about company health. Company name and URL are
    included so the LLM can identify false positives from the company's
    own name.

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
    "You are analyzing news articles for a venture capital portfolio monitoring"
    " system.\n"
    "Your task is to independently determine if a news article represents a"
    " significant business event for the specified company.\n\n"
    "You will receive keyword hints from an automated scanner. These may contain"
    " false positives -- use them as starting points but classify independently.\n\n"
    "Respond with a JSON object containing:\n"
    '- classification: "significant", "insignificant", or "uncertain"\n'
    '- sentiment: "positive", "negative", "neutral", or "mixed"\n'
    "- confidence: float between 0.0 and 1.0\n"
    "- reasoning: (REQUIRED) 1-3 sentences explaining WHY you classified this way."
    " What makes this article significant or not for the company?\n"
    "- validated_keywords: list of confirmed relevant keywords\n"
    "- false_positives: list of false positive keywords"
)

NEWS_CLASSIFICATION_USER_TEMPLATE = (
    "Analyze this news article for business significance:\n\n"
    "Company: {company_name}\n"
    "Title: {title}\n"
    "Source: {source}\n"
    "Content: {content}\n\n"
    "Keyword hints from automated scanner: {keywords}\n\n"
    "Is this article a significant business event for {company_name}?\n"
    "Respond with JSON only."
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


# --- Company Verification (unchanged) ---

COMPANY_VERIFICATION_SYSTEM_PROMPT = (
    "You are verifying whether a news article is about a specific company.\n"
    "The company may have a common name, so careful verification is needed.\n\n"
    "You will receive a description of what the company does, extracted from their\n"
    "homepage. Use this to determine if the article is about THIS specific company\n"
    "or a DIFFERENT entity with a similar name.\n\n"
    "Pay close attention to:\n"
    "- Does the article describe the same product/service as the company description?\n"
    "- Does the article reference a different domain or website than the company's?\n"
    "- Are there any indicators this is a different company (different industry,\n"
    "  different location, different product)?\n\n"
    "Respond with a JSON object containing:\n"
    "- is_match: boolean - whether the article is about this specific company\n"
    "- confidence: float between 0.0 and 1.0\n"
    "- reasoning: brief explanation of your determination"
)

COMPANY_VERIFICATION_USER_TEMPLATE = (
    'Is this article about the company "{company_name}"?\n\n'
    "Company homepage: {company_url}\n"
    "Company description: {company_description}\n\n"
    "Article title: {article_title}\n"
    "Article source: {article_source}\n"
    "Article snippet: {article_snippet}\n\n"
    "Consider: Could this article be about a different entity with a similar"
    " name? Compare the article content against the company description above.\n"
    "Respond with JSON only."
)


def build_company_verification_prompt(
    company_name: str,
    company_url: str,
    article_title: str,
    article_source: str,
    article_snippet: str,
    company_description: str = "",
) -> tuple[str, str]:
    """Build prompts for company identity verification.

    The company_description provides context about what the company does,
    extracted from their homepage snapshot, to help the LLM disambiguate
    companies with similar names.
    """
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

STATUS_AWARE_SIGNIFICANCE_SYSTEM_PROMPT = (
    "You are analyzing website content changes for a venture capital portfolio"
    " monitoring system.\n"
    "Your task is to independently classify whether detected changes represent"
    " genuinely significant business events, AND to determine the company's"
    " current operational status.\n\n"
    "You will receive a content excerpt showing what changed, the magnitude of"
    " the change, and keyword hints from an automated scanner. The keyword hints"
    " may contain false positives or miss important context. Use them as starting"
    " points for your analysis, but make your own independent judgment.\n\n"
    "IMPORTANT: You will be told the company's name and homepage URL. If a keyword\n"
    "match is simply the company's own name or a word derived from it, that is a\n"
    "false positive -- not a real signal.\n\n"
    "Common false positives to watch for:\n"
    "- Keywords that match the company's own name or domain\n"
    "- 'talent acquisition' or 'customer acquisition' (not company acquisition)\n"
    "- 'funding opportunities' or 'funding sources' (not a funding round)\n"
    "- Navigation menu or footer changes containing business terms\n"
    "- Marketing language that sounds significant but is routine\n"
    "- Copyright year updates, CSS changes, analytics tracking\n\n"
    "For company_status, assess based on all available evidence in the diff:\n"
    "- operational: company appears to be actively running (product updates, hiring,"
    " recent activity, normal business content)\n"
    "- likely_closed: clear evidence of shutdown, acquisition, or cessation"
    " (shutdown notices, acquisition announcements, domain parked/redirected,"
    " 'we are winding down' language)\n"
    "- uncertain: insufficient evidence to determine status confidently\n\n"
    "Default to 'operational' unless there is clear evidence otherwise.\n\n"
    "Respond with a JSON object containing:\n"
    '- classification: "significant", "insignificant", or "uncertain"\n'
    '- sentiment: "positive", "negative", "neutral", or "mixed"\n'
    "- confidence: float between 0.0 and 1.0\n"
    "- reasoning: (REQUIRED) 1-3 sentences explaining WHY you classified this way."
    " What specific evidence drove your decision?\n"
    "- validated_keywords: list of keyword hints you confirm are relevant\n"
    "- false_positives: list of keyword hints that are false positives\n"
    '- company_status: "operational", "likely_closed", or "uncertain"\n'
    "- status_reason: (REQUIRED) exactly one sentence explaining your company_status"
    " determination. Be specific and factual. This is shown directly to users."
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

    Like build_significance_classification_prompt but also elicits company_status
    and status_reason fields from the LLM.

    When company_notes is provided, it is appended to the user prompt as analyst
    context to help the LLM handle unusual or edge-case companies.

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
            f"\n\nAnalyst notes about this company:\n{company_notes.strip()}\n\n"
            "Take these notes into account when making your classification"
            " and status determination."
        )
    return STATUS_AWARE_SIGNIFICANCE_SYSTEM_PROMPT, user_prompt


# --- Enriched Significance Classification (with Social Media Context) ---

ENRICHED_SIGNIFICANCE_SYSTEM_PROMPT = (
    "You are analyzing website content changes for a venture capital portfolio"
    " monitoring system.\n"
    "You will receive BOTH the homepage change data AND social media activity"
    " data. Use all available signals to make your assessment.\n\n"
    "Social media signals to consider:\n"
    "- Recent blog/Medium posts about product updates, funding, or growth = positive\n"
    "- Blog/Medium going inactive (no posts in 1+ year) = negative signal\n"
    "- No social media presence at all = neutral (not all companies blog)\n"
    "- Content of recent posts: what are they writing about?\n\n"
    "You will receive keyword hints from an automated scanner. These may contain"
    " false positives -- use them as starting points but classify independently.\n\n"
    "IMPORTANT: You will be told the company's name and homepage URL. If a keyword\n"
    "match is simply the company's own name or a word derived from it, that is a\n"
    "false positive -- not a real signal.\n\n"
    "Common false positives to watch for:\n"
    "- Keywords that match the company's own name or domain\n"
    "- 'talent acquisition' or 'customer acquisition' (not company acquisition)\n"
    "- Navigation menu or footer changes containing business terms\n"
    "- Marketing language that sounds significant but is routine\n\n"
    "Respond with a JSON object containing:\n"
    '- classification: "significant", "insignificant", or "uncertain"\n'
    '- sentiment: "positive", "negative", "neutral", or "mixed"\n'
    "- confidence: float between 0.0 and 1.0\n"
    "- reasoning: (REQUIRED) 1-3 sentences explaining WHY you classified this way."
    " Reference BOTH homepage and social media signals in your reasoning.\n"
    "- validated_keywords: list of keyword hints you confirm are relevant\n"
    "- false_positives: list of keyword hints that are false positives"
)

ENRICHED_SIGNIFICANCE_USER_TEMPLATE = (
    "Analyze this website content change for business significance:\n\n"
    "Company: {company_name}\n"
    "Homepage: {homepage_url}\n\n"
    "Content excerpt (changed/added text):\n{content_excerpt}\n\n"
    "Change magnitude: {magnitude}\n\n"
    "Social media context:\n{social_context}\n\n"
    "Keyword hints from automated scanner:\n"
    "  Detected terms: {keywords}\n"
    "  Categories: {categories}\n\n"
    "Classify this change independently using ALL available signals.\n"
    "Respond with JSON only."
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

    Uses the enriched prompt template that includes social media activity data.

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
    "You are analyzing website content changes for a venture capital portfolio"
    " monitoring system.\n"
    "You will receive BOTH the homepage change data AND social media activity"
    " data. Use all available signals to make your assessment.\n\n"
    "Social media signals to consider:\n"
    "- Recent blog/Medium posts about product updates, funding, or growth = positive\n"
    "- Blog/Medium going inactive (no posts in 1+ year) = negative signal\n"
    "- No social media presence at all = neutral (not all companies blog)\n"
    "- Content of recent posts: what are they writing about?\n\n"
    "You will receive keyword hints from an automated scanner. These may contain"
    " false positives -- use them as starting points but classify independently.\n\n"
    "IMPORTANT: You will be told the company's name and homepage URL. If a keyword\n"
    "match is simply the company's own name or a word derived from it, that is a\n"
    "false positive -- not a real signal.\n\n"
    "Common false positives to watch for:\n"
    "- Keywords that match the company's own name or domain\n"
    "- 'talent acquisition' or 'customer acquisition' (not company acquisition)\n"
    "- Navigation menu or footer changes containing business terms\n"
    "- Marketing language that sounds significant but is routine\n\n"
    "For company_status, assess based on ALL available evidence (homepage diff,"
    " social media signals, LinkedIn verification, and current status):\n"
    "- operational: company appears to be actively running\n"
    "- likely_closed: clear evidence of shutdown, acquisition, or cessation\n"
    "- uncertain: insufficient evidence to determine status confidently\n\n"
    "IMPORTANT: You may be given the company's current status and confidence.\n"
    "Minor or insignificant website changes should NOT flip a company's status.\n"
    "Only change the status if there is clear, strong evidence in the diff content\n"
    "that contradicts the current status. Default to maintaining the current status\n"
    "unless the evidence is compelling.\n\n"
    "Respond with a JSON object containing:\n"
    '- classification: "significant", "insignificant", or "uncertain"\n'
    '- sentiment: "positive", "negative", "neutral", or "mixed"\n'
    "- confidence: float between 0.0 and 1.0\n"
    "- reasoning: (REQUIRED) 1-3 sentences explaining WHY you classified this way."
    " Reference BOTH homepage and social media signals in your reasoning.\n"
    "- validated_keywords: list of keyword hints you confirm are relevant\n"
    "- false_positives: list of keyword hints that are false positives\n"
    '- company_status: "operational", "likely_closed", or "uncertain"\n'
    "- status_reason: (REQUIRED) exactly one sentence explaining your company_status"
    " determination. Be specific and factual. This is shown directly to users."
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

    Like build_enriched_significance_prompt but also elicits company_status
    and status_reason fields from the LLM.

    When company_notes is provided, it is appended to the user prompt as analyst
    context to help the LLM handle unusual or edge-case companies.

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
            f"\n\nAnalyst notes about this company:\n{company_notes.strip()}\n\n"
            "Take these notes into account when making your classification"
            " and status determination."
        )
    return STATUS_AWARE_ENRICHED_SYSTEM_PROMPT, user_prompt
