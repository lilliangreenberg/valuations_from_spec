"""Comparison tests: Kagi Search vs Firecrawl Search for news monitoring.

These tests hit real APIs -- they require KAGI_API_KEY and FIRECRAWL_API_KEY
environment variables (loaded from .env).

Run with:
    uv run pytest tests/integration/test_search_comparison.py -v -s
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import pytest
import structlog
from dotenv import load_dotenv
from firecrawl import Firecrawl

from src.domains.news.services.kagi_client import KagiClient

logger = structlog.get_logger(__name__)

load_dotenv()

KAGI_API_KEY = os.getenv("KAGI_API_KEY", "")
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY", "")

requires_kagi = pytest.mark.skipif(not KAGI_API_KEY, reason="KAGI_API_KEY not set")
requires_firecrawl = pytest.mark.skipif(not FIRECRAWL_API_KEY, reason="FIRECRAWL_API_KEY not set")
requires_both = pytest.mark.skipif(
    not KAGI_API_KEY or not FIRECRAWL_API_KEY,
    reason="Both KAGI_API_KEY and FIRECRAWL_API_KEY required",
)

# Test companies: mix of distinctive and ambiguous names
TEST_COMPANIES: list[dict[str, str]] = [
    {"name": "Arch0 Inc", "domain": "arch0.com"},
    {"name": "Wand Technologies Inc.", "domain": "wand.app"},
    {"name": "Odeko Inc.", "domain": "odeko.com"},
    {"name": "PartyKit, Inc.", "domain": "partykit.io"},
]


def _extract_domain(url: str) -> str:
    """Extract domain from URL, stripping www."""
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def _normalize_firecrawl_news(
    results: list[Any],
) -> list[dict[str, Any]]:
    """Normalize Firecrawl SearchResultNews objects to dicts matching Kagi format."""
    articles: list[dict[str, Any]] = []
    for item in results:
        url = getattr(item, "url", None) or ""
        if not url:
            continue
        source = _extract_domain(url)
        title = getattr(item, "title", None) or ""
        snippet = getattr(item, "snippet", None) or ""
        date = getattr(item, "date", None) or datetime.now(tz=UTC).isoformat()

        articles.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "published": date,
                "source": source,
            }
        )
    return articles


def _normalize_firecrawl_web(
    results: list[Any],
) -> list[dict[str, Any]]:
    """Normalize Firecrawl SearchResultWeb objects to dicts matching Kagi format."""
    articles: list[dict[str, Any]] = []
    for item in results:
        url = getattr(item, "url", None) or ""
        if not url:
            continue
        source = _extract_domain(url)
        title = getattr(item, "title", None) or ""
        description = getattr(item, "description", None) or ""

        articles.append(
            {
                "title": title,
                "url": url,
                "snippet": description,
                "published": datetime.now(tz=UTC).isoformat(),
                "source": source,
            }
        )
    return articles


# ──────────────────────────────────────────────────────────────────────
# Individual API capability tests
# ──────────────────────────────────────────────────────────────────────


class TestKagiSearchCapabilities:
    """Verify Kagi search returns usable results for portfolio companies."""

    @requires_kagi
    @pytest.mark.parametrize("company", TEST_COMPANIES, ids=lambda c: c["name"])
    def test_returns_results_for_company(self, company: dict[str, str]) -> None:
        kagi = KagiClient(KAGI_API_KEY)
        articles = kagi.search(query=company["name"], limit=10)
        assert isinstance(articles, list)
        # Kagi should find something for each company
        print(f"  Kagi: {len(articles)} results for '{company['name']}'")

    @requires_kagi
    def test_date_filtering(self) -> None:
        kagi = KagiClient(KAGI_API_KEY)
        now = datetime.now(tz=UTC)
        after = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        before = now.strftime("%Y-%m-%d")
        articles = kagi.search(
            query="Odeko Inc.",
            after_date=after,
            before_date=before,
            limit=10,
        )
        assert isinstance(articles, list)
        print(f"  Kagi date-filtered: {len(articles)} results")

    @requires_kagi
    def test_result_fields_present(self) -> None:
        kagi = KagiClient(KAGI_API_KEY)
        articles = kagi.search(query="Odeko Inc.", limit=5)
        if articles:
            article = articles[0]
            assert "title" in article
            assert "url" in article
            assert "snippet" in article
            assert "published" in article
            assert "source" in article
            assert article["url"].startswith("http")


class TestFirecrawlSearchCapabilities:
    """Verify Firecrawl search returns usable results for portfolio companies."""

    @requires_firecrawl
    @pytest.mark.parametrize("company", TEST_COMPANIES, ids=lambda c: c["name"])
    def test_news_source_returns_results(self, company: dict[str, str]) -> None:
        fc = Firecrawl(api_key=FIRECRAWL_API_KEY)
        result = fc.search(
            query=company["name"],
            sources=["news"],
            limit=10,
        )
        news = result.news or []
        print(f"  Firecrawl news: {len(news)} results for '{company['name']}'")

    @requires_firecrawl
    @pytest.mark.parametrize("company", TEST_COMPANIES, ids=lambda c: c["name"])
    def test_web_source_returns_results(self, company: dict[str, str]) -> None:
        fc = Firecrawl(api_key=FIRECRAWL_API_KEY)
        result = fc.search(
            query=company["name"],
            sources=["web"],
            limit=10,
        )
        web = result.web or []
        print(f"  Firecrawl web: {len(web)} results for '{company['name']}'")

    @requires_firecrawl
    def test_combined_sources(self) -> None:
        fc = Firecrawl(api_key=FIRECRAWL_API_KEY)
        result = fc.search(
            query="Odeko Inc.",
            sources=["web", "news"],
            limit=10,
        )
        web_count = len(result.web or [])
        news_count = len(result.news or [])
        print(f"  Firecrawl combined: {web_count} web + {news_count} news")
        assert web_count + news_count > 0

    @requires_firecrawl
    def test_time_based_filtering(self) -> None:
        fc = Firecrawl(api_key=FIRECRAWL_API_KEY)
        result = fc.search(
            query="Odeko Inc.",
            sources=["news"],
            limit=10,
            tbs="qdr:m",  # past month
        )
        news = result.news or []
        print(f"  Firecrawl time-filtered (past month): {len(news)} results")

    @requires_firecrawl
    def test_custom_date_range(self) -> None:
        fc = Firecrawl(api_key=FIRECRAWL_API_KEY)
        now = datetime.now(tz=UTC)
        after = now - timedelta(days=90)
        tbs = f"cdr:1,cd_min:{after.strftime('%m/%d/%Y')},cd_max:{now.strftime('%m/%d/%Y')}"
        result = fc.search(
            query="Odeko Inc.",
            sources=["news"],
            limit=10,
            tbs=tbs,
        )
        news = result.news or []
        print(f"  Firecrawl custom date range (90d): {len(news)} results")

    @requires_firecrawl
    def test_news_result_fields(self) -> None:
        fc = Firecrawl(api_key=FIRECRAWL_API_KEY)
        result = fc.search(
            query="Odeko Inc.",
            sources=["news"],
            limit=5,
        )
        news = result.news or []
        if news:
            item = news[0]
            print(
                f"  Fields present: title={item.title is not None}, "
                f"url={item.url is not None}, snippet={item.snippet is not None}, "
                f"date={item.date is not None}"
            )
            assert item.url is not None


# ──────────────────────────────────────────────────────────────────────
# Head-to-head comparison tests
# ──────────────────────────────────────────────────────────────────────


class TestSearchComparison:
    """Side-by-side comparison of Kagi and Firecrawl search results."""

    @requires_both
    @pytest.mark.parametrize("company", TEST_COMPANIES, ids=lambda c: c["name"])
    def test_result_count_comparison(self, company: dict[str, str]) -> None:
        """Compare how many results each API returns per company."""
        kagi = KagiClient(KAGI_API_KEY)
        fc = Firecrawl(api_key=FIRECRAWL_API_KEY)

        kagi_articles = kagi.search(query=company["name"], limit=20)

        fc_result = fc.search(
            query=company["name"],
            sources=["news"],
            limit=20,
        )
        fc_news = _normalize_firecrawl_news(fc_result.news or [])

        fc_web_result = fc.search(
            query=company["name"],
            sources=["web"],
            limit=20,
        )
        fc_web = _normalize_firecrawl_web(fc_web_result.web or [])

        print(f"\n  [{company['name']}]")
        print(f"    Kagi:           {len(kagi_articles)} results")
        print(f"    Firecrawl news: {len(fc_news)} results")
        print(f"    Firecrawl web:  {len(fc_web)} results")

    @requires_both
    @pytest.mark.parametrize("company", TEST_COMPANIES, ids=lambda c: c["name"])
    def test_relevance_comparison(self, company: dict[str, str]) -> None:
        """Compare relevance: how many results mention the company name."""
        kagi = KagiClient(KAGI_API_KEY)
        fc = Firecrawl(api_key=FIRECRAWL_API_KEY)

        name_lower = company["name"].lower().rstrip(".")
        # Also check without suffixes like "Inc", "Inc."
        name_core = name_lower.replace(" inc", "").replace(",", "").strip()

        kagi_articles = kagi.search(query=company["name"], limit=20)
        fc_result = fc.search(
            query=company["name"],
            sources=["news"],
            limit=20,
        )
        fc_articles = _normalize_firecrawl_news(fc_result.news or [])

        def count_relevant(articles: list[dict[str, Any]]) -> int:
            relevant = 0
            for a in articles:
                text = (a.get("title", "") + " " + a.get("snippet", "")).lower()
                if name_core in text or name_lower in text:
                    relevant += 1
            return relevant

        kagi_relevant = count_relevant(kagi_articles)
        fc_relevant = count_relevant(fc_articles)

        kagi_pct = (kagi_relevant / len(kagi_articles) * 100) if kagi_articles else 0
        fc_pct = (fc_relevant / len(fc_articles) * 100) if fc_articles else 0

        print(f"\n  [{company['name']}] Relevance (name in title/snippet):")
        print(f"    Kagi:           {kagi_relevant}/{len(kagi_articles)} ({kagi_pct:.0f}%)")
        print(f"    Firecrawl news: {fc_relevant}/{len(fc_articles)} ({fc_pct:.0f}%)")

    @requires_both
    @pytest.mark.parametrize("company", TEST_COMPANIES, ids=lambda c: c["name"])
    def test_domain_coverage_comparison(self, company: dict[str, str]) -> None:
        """Compare how many results include the company's own domain."""
        kagi = KagiClient(KAGI_API_KEY)
        fc = Firecrawl(api_key=FIRECRAWL_API_KEY)

        domain = company["domain"]

        kagi_articles = kagi.search(query=company["name"], limit=20)
        fc_result = fc.search(
            query=company["name"],
            sources=["news"],
            limit=20,
        )
        fc_articles = _normalize_firecrawl_news(fc_result.news or [])

        def count_domain_mentions(articles: list[dict[str, Any]]) -> int:
            count = 0
            for a in articles:
                text = (a.get("url", "") + " " + a.get("snippet", "")).lower()
                if domain in text:
                    count += 1
            return count

        kagi_domain = count_domain_mentions(kagi_articles)
        fc_domain = count_domain_mentions(fc_articles)

        print(f"\n  [{company['name']}] Domain mentions ({domain}):")
        print(f"    Kagi:           {kagi_domain}/{len(kagi_articles)}")
        print(f"    Firecrawl news: {fc_domain}/{len(fc_articles)}")

    @requires_both
    @pytest.mark.parametrize("company", TEST_COMPANIES, ids=lambda c: c["name"])
    def test_snippet_quality_comparison(self, company: dict[str, str]) -> None:
        """Compare snippet lengths and presence across APIs."""
        kagi = KagiClient(KAGI_API_KEY)
        fc = Firecrawl(api_key=FIRECRAWL_API_KEY)

        kagi_articles = kagi.search(query=company["name"], limit=10)
        fc_result = fc.search(
            query=company["name"],
            sources=["news"],
            limit=10,
        )
        fc_articles = _normalize_firecrawl_news(fc_result.news or [])

        def snippet_stats(articles: list[dict[str, Any]]) -> dict[str, Any]:
            snippets = [a.get("snippet", "") for a in articles]
            non_empty = [s for s in snippets if s.strip()]
            lengths = [len(s) for s in non_empty]
            return {
                "total": len(articles),
                "with_snippet": len(non_empty),
                "avg_length": sum(lengths) / len(lengths) if lengths else 0,
                "min_length": min(lengths) if lengths else 0,
                "max_length": max(lengths) if lengths else 0,
            }

        kagi_stats = snippet_stats(kagi_articles)
        fc_stats = snippet_stats(fc_articles)

        print(f"\n  [{company['name']}] Snippet quality:")
        print(
            f"    Kagi:           {kagi_stats['with_snippet']}/{kagi_stats['total']} "
            f"have snippets, avg {kagi_stats['avg_length']:.0f} chars "
            f"(range {kagi_stats['min_length']}-{kagi_stats['max_length']})"
        )
        print(
            f"    Firecrawl news: {fc_stats['with_snippet']}/{fc_stats['total']} "
            f"have snippets, avg {fc_stats['avg_length']:.0f} chars "
            f"(range {fc_stats['min_length']}-{fc_stats['max_length']})"
        )

    @requires_both
    @pytest.mark.parametrize("company", TEST_COMPANIES, ids=lambda c: c["name"])
    def test_url_overlap(self, company: dict[str, str]) -> None:
        """Check how many URLs are returned by both APIs."""
        kagi = KagiClient(KAGI_API_KEY)
        fc = Firecrawl(api_key=FIRECRAWL_API_KEY)

        kagi_articles = kagi.search(query=company["name"], limit=20)
        fc_result = fc.search(
            query=company["name"],
            sources=["news"],
            limit=20,
        )
        fc_articles = _normalize_firecrawl_news(fc_result.news or [])

        kagi_urls = {a["url"].rstrip("/").lower() for a in kagi_articles}
        fc_urls = {a["url"].rstrip("/").lower() for a in fc_articles}

        overlap = kagi_urls & fc_urls
        kagi_only = kagi_urls - fc_urls
        fc_only = fc_urls - kagi_urls

        print(f"\n  [{company['name']}] URL overlap:")
        print(f"    Shared:          {len(overlap)}")
        print(f"    Kagi only:       {len(kagi_only)}")
        print(f"    Firecrawl only:  {len(fc_only)}")

    @requires_both
    @pytest.mark.parametrize("company", TEST_COMPANIES, ids=lambda c: c["name"])
    def test_source_diversity(self, company: dict[str, str]) -> None:
        """Compare diversity of news sources returned."""
        kagi = KagiClient(KAGI_API_KEY)
        fc = Firecrawl(api_key=FIRECRAWL_API_KEY)

        kagi_articles = kagi.search(query=company["name"], limit=20)
        fc_result = fc.search(
            query=company["name"],
            sources=["news"],
            limit=20,
        )
        fc_articles = _normalize_firecrawl_news(fc_result.news or [])

        kagi_sources = {a.get("source", "") for a in kagi_articles}
        fc_sources = {a.get("source", "") for a in fc_articles}

        print(f"\n  [{company['name']}] Source diversity:")
        print(f"    Kagi:           {len(kagi_sources)} unique sources: {sorted(kagi_sources)[:8]}")
        print(f"    Firecrawl news: {len(fc_sources)} unique sources: {sorted(fc_sources)[:8]}")


# ──────────────────────────────────────────────────────────────────────
# Verification pipeline compatibility test
# ──────────────────────────────────────────────────────────────────────


class TestVerificationPipelineCompatibility:
    """Test that Firecrawl search results work with existing verification logic."""

    @requires_firecrawl
    def test_firecrawl_results_have_verification_fields(self) -> None:
        """Firecrawl news results must provide the fields the verification
        pipeline needs: title, url, snippet (for context matching)."""
        fc = Firecrawl(api_key=FIRECRAWL_API_KEY)
        result = fc.search(
            query="Odeko Inc.",
            sources=["news"],
            limit=5,
        )
        articles = _normalize_firecrawl_news(result.news or [])
        assert len(articles) > 0, "Firecrawl returned no news results"

        for article in articles:
            assert "title" in article, "Missing title field"
            assert "url" in article, "Missing url field"
            assert "snippet" in article, "Missing snippet field"
            assert "published" in article, "Missing published field"
            assert "source" in article, "Missing source field"
            assert article["url"].startswith("http"), f"Invalid URL: {article['url']}"

    @requires_firecrawl
    def test_firecrawl_results_pass_context_check(self) -> None:
        """Verify that Firecrawl snippets contain enough context for
        check_name_in_context to work."""
        from src.domains.news.core.verification_logic import check_name_in_context

        fc = Firecrawl(api_key=FIRECRAWL_API_KEY)
        result = fc.search(
            query="Odeko Inc.",
            sources=["news"],
            limit=10,
        )
        articles = _normalize_firecrawl_news(result.news or [])

        context_matches = 0
        for article in articles:
            if check_name_in_context(article["snippet"], "Odeko Inc."):
                context_matches += 1

        print(f"\n  Firecrawl context matches: {context_matches}/{len(articles)}")

    @requires_both
    def test_verification_pass_rate_comparison(self) -> None:
        """Compare how many results from each API would pass verification
        using context + domain signals only (no LLM)."""
        from src.domains.news.core.verification_logic import (
            calculate_weighted_confidence,
            check_domain_in_content,
            check_domain_match,
            check_name_in_context,
            extract_domain_from_url,
            is_article_verified,
        )

        company_name = "Odeko Inc."
        company_url = "https://odeko.com/"
        company_domain = extract_domain_from_url(company_url)

        kagi = KagiClient(KAGI_API_KEY)
        fc = Firecrawl(api_key=FIRECRAWL_API_KEY)

        kagi_articles = kagi.search(query=company_name, limit=20)
        fc_result = fc.search(
            query=company_name,
            sources=["news"],
            limit=20,
        )
        fc_articles = _normalize_firecrawl_news(fc_result.news or [])

        def evaluate_articles(
            articles: list[dict[str, Any]],
        ) -> dict[str, int]:
            passed = 0
            domain_hits = 0
            context_hits = 0
            for article in articles:
                signals: dict[str, float] = {}
                domain_matched = check_domain_match(article["url"], company_domain)
                if not domain_matched:
                    domain_matched = check_domain_in_content(
                        article.get("snippet", ""), company_domain
                    )
                signals["domain"] = 1.0 if domain_matched else 0.0
                if domain_matched:
                    domain_hits += 1

                context_matched = check_name_in_context(article.get("snippet", ""), company_name)
                signals["context"] = 1.0 if context_matched else 0.0
                if context_matched:
                    context_hits += 1

                confidence = calculate_weighted_confidence(signals)
                if is_article_verified(confidence):
                    passed += 1

            return {
                "total": len(articles),
                "domain_hits": domain_hits,
                "context_hits": context_hits,
                "passed": passed,
            }

        kagi_eval = evaluate_articles(kagi_articles)
        fc_eval = evaluate_articles(fc_articles)

        print(f"\n  [Odeko Inc.] Verification pass rate (no LLM):")
        print(
            f"    Kagi:           {kagi_eval['passed']}/{kagi_eval['total']} passed "
            f"(domain: {kagi_eval['domain_hits']}, context: {kagi_eval['context_hits']})"
        )
        print(
            f"    Firecrawl news: {fc_eval['passed']}/{fc_eval['total']} passed "
            f"(domain: {fc_eval['domain_hits']}, context: {fc_eval['context_hits']})"
        )


# ──────────────────────────────────────────────────────────────────────
# Date field reliability test
# ──────────────────────────────────────────────────────────────────────


class TestDateFieldReliability:
    """Compare date/published field availability and quality."""

    @requires_both
    def test_date_field_presence(self) -> None:
        """Check how many results from each API include a date."""
        kagi = KagiClient(KAGI_API_KEY)
        fc = Firecrawl(api_key=FIRECRAWL_API_KEY)

        kagi_articles = kagi.search(query="Odeko Inc.", limit=20)
        fc_result = fc.search(
            query="Odeko Inc.",
            sources=["news"],
            limit=20,
        )

        # Kagi: check if published dates look real (not just now())
        kagi_with_date = 0
        for a in kagi_articles:
            pub = a.get("published", "")
            if pub and "T" in pub:
                kagi_with_date += 1

        # Firecrawl: check raw date field on SearchResultNews
        fc_with_date = 0
        for item in fc_result.news or []:
            if getattr(item, "date", None):
                fc_with_date += 1

        print(f"\n  [Odeko Inc.] Date field presence:")
        print(f"    Kagi:           {kagi_with_date}/{len(kagi_articles)} have dates")
        print(f"    Firecrawl news: {fc_with_date}/{len(fc_result.news or [])} have dates")
