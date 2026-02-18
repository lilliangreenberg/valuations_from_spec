"""CLI command implementations for the Portfolio Company Monitoring System."""

from __future__ import annotations

import json
from typing import Any

import click

from src.models.config import Config
from src.services.database import Database
from src.utils.logger import configure_logging


def _get_config() -> Config:
    """Load configuration from .env file."""
    return Config()  # type: ignore[call-arg]


def _get_db(config: Config) -> Database:
    """Initialize database with schema."""
    db = Database(db_path=config.database_path)
    db.init_db()
    return db


def _print_summary(title: str, stats: dict[str, Any]) -> None:
    """Print a formatted summary of batch operation results."""
    click.echo(f"\n[SUCCESS] {title}")
    for key, value in stats.items():
        if key == "errors" and isinstance(value, list):
            if value:
                click.echo(f"  Errors ({len(value)}):")
                for error in value[:10]:
                    click.echo(f"    - {error}")
                if len(value) > 10:
                    click.echo(f"    ... and {len(value) - 10} more")
        elif key != "results":
            click.echo(f"  {key}: {value}")


# --- Feature 001: Data Extraction & Snapshots ---


@click.command()
def extract_companies() -> None:
    """Extract companies from Airtable and store locally."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.repositories.company_repository import CompanyRepository
    from src.services.airtable_client import AirtableClient
    from src.services.extractor import CompanyExtractor

    airtable = AirtableClient(config.airtable_api_key, config.airtable_base_id)
    company_repo = CompanyRepository(db)
    extractor = CompanyExtractor(airtable, company_repo)

    click.echo("[INFO] Extracting companies from Airtable...")
    result = extractor.extract_companies()
    _print_summary("Company extraction complete", result)
    db.close()


@click.command()
@click.option("--use-batch-api", is_flag=True, help="Use Firecrawl batch API (8x faster)")
@click.option("--batch-size", default=20, type=int, help="URLs per batch (max 1000)")
@click.option("--timeout", default=300, type=int, help="Timeout per batch in seconds")
def capture_snapshots(use_batch_api: bool, batch_size: int, timeout: int) -> None:
    """Capture website snapshots for all companies."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository
    from src.repositories.company_repository import CompanyRepository
    from src.services.firecrawl_client import FirecrawlClient

    firecrawl = FirecrawlClient(config.firecrawl_api_key)
    snapshot_repo = SnapshotRepository(db)
    company_repo = CompanyRepository(db)

    if use_batch_api:
        from src.services.batch_snapshot_manager import BatchSnapshotManager

        manager = BatchSnapshotManager(firecrawl, snapshot_repo, company_repo)
        click.echo(f"[INFO] Capturing snapshots using batch API (batch size: {batch_size})...")
        result = manager.capture_batch_snapshots(batch_size=batch_size, timeout=timeout)
    else:
        from src.services.snapshot_manager import SnapshotManager

        manager = SnapshotManager(firecrawl, snapshot_repo, company_repo)  # type: ignore[assignment]
        click.echo("[INFO] Capturing snapshots sequentially...")
        result = manager.capture_all_snapshots()

    _print_summary("Snapshot capture complete", result)
    db.close()


# --- Feature 002: Change Detection & Status Analysis ---


@click.command()
@click.option("--batch-size", default=50, type=int, help="Companies per batch")
@click.option(
    "--output-format",
    default="summary",
    type=click.Choice(["summary", "detailed", "json"]),
    help="Output format",
)
def detect_changes(batch_size: int, output_format: str) -> None:
    """Detect content changes between snapshots with significance analysis."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.monitoring.repositories.change_record_repository import (
        ChangeRecordRepository,
    )
    from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository
    from src.domains.monitoring.services.change_detector import ChangeDetector
    from src.repositories.company_repository import CompanyRepository

    snapshot_repo = SnapshotRepository(db)
    change_repo = ChangeRecordRepository(db)
    company_repo = CompanyRepository(db)
    detector = ChangeDetector(snapshot_repo, change_repo, company_repo)

    click.echo("[INFO] Detecting changes...")
    result = detector.detect_all_changes()

    if output_format == "json":
        click.echo(json.dumps(result, indent=2))
    else:
        _print_summary("Change detection complete", result)
    db.close()


@click.command()
@click.option("--batch-size", default=50, type=int, help="Companies per batch")
@click.option("--confidence-threshold", default=0.7, type=float, help="Min confidence 0.0-1.0")
@click.option(
    "--output-format",
    default="summary",
    type=click.Choice(["summary", "detailed", "json"]),
    help="Output format",
)
def analyze_status(batch_size: int, confidence_threshold: float, output_format: str) -> None:
    """Analyze company operational status from snapshots."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.monitoring.repositories.company_status_repository import (
        CompanyStatusRepository,
    )
    from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository
    from src.domains.monitoring.services.status_analyzer import StatusAnalyzer
    from src.repositories.company_repository import CompanyRepository

    snapshot_repo = SnapshotRepository(db)
    status_repo = CompanyStatusRepository(db)
    company_repo = CompanyRepository(db)
    analyzer = StatusAnalyzer(snapshot_repo, status_repo, company_repo)

    click.echo("[INFO] Analyzing company statuses...")
    result = analyzer.analyze_all_statuses()

    if output_format == "json":
        click.echo(json.dumps(result, indent=2))
    else:
        _print_summary("Status analysis complete", result)
    db.close()


@click.command()
@click.option("--batch-size", default=100, type=int, help="Records per batch")
@click.option("--dry-run", is_flag=True, help="Preview without updating")
def backfill_significance(batch_size: int, dry_run: bool) -> None:
    """Backfill significance analysis for existing change records."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.monitoring.repositories.change_record_repository import (
        ChangeRecordRepository,
    )
    from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository
    from src.domains.monitoring.services.significance_analyzer import SignificanceAnalyzer

    change_repo = ChangeRecordRepository(db)
    snapshot_repo = SnapshotRepository(db)

    llm_client = None
    if config.llm_validation_enabled and config.anthropic_api_key:
        from src.services.llm_client import LLMClient

        llm_client = LLMClient(config.anthropic_api_key, config.llm_model)

    analyzer = SignificanceAnalyzer(
        change_repo,
        snapshot_repo,
        llm_client=llm_client,
        llm_enabled=config.llm_validation_enabled,
    )

    mode = "DRY RUN" if dry_run else "backfilling"
    click.echo(f"[INFO] {mode} significance analysis...")
    result = analyzer.backfill_significance(dry_run=dry_run)
    _print_summary("Significance backfill complete", result)
    db.close()


@click.command()
@click.option("--days", default=180, type=int, help="Look back N days")
@click.option("--sentiment", default=None, type=str, help="Filter by sentiment")
@click.option("--min-confidence", default=0.5, type=float, help="Min confidence threshold")
def list_significant_changes(days: int, sentiment: str | None, min_confidence: float) -> None:
    """List significant changes detected."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.monitoring.repositories.change_record_repository import (
        ChangeRecordRepository,
    )

    change_repo = ChangeRecordRepository(db)
    records = change_repo.get_significant_changes(
        days=days, sentiment=sentiment, min_confidence=min_confidence
    )

    if not records:
        click.echo("[INFO] No significant changes found.")
    else:
        click.echo(f"[INFO] Found {len(records)} significant changes:\n")
        for record in records:
            click.echo(
                f"  {record.get('company_name', 'Unknown')} | "
                f"{record.get('significance_sentiment', 'N/A')} | "
                f"confidence: {record.get('significance_confidence', 0):.2f} | "
                f"{record.get('detected_at', '')[:10]}"
            )
            keywords = record.get("matched_keywords", [])
            if keywords:
                click.echo(f"    Keywords: {', '.join(keywords[:5])}")
    db.close()


@click.command()
@click.option("--limit", default=50, type=int, help="Max records to display")
def list_uncertain_changes(limit: int) -> None:
    """List changes classified as UNCERTAIN requiring manual review."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.monitoring.repositories.change_record_repository import (
        ChangeRecordRepository,
    )

    change_repo = ChangeRecordRepository(db)
    records = change_repo.get_uncertain_changes(limit=limit)

    if not records:
        click.echo("[INFO] No uncertain changes found.")
    else:
        click.echo(f"[INFO] Found {len(records)} uncertain changes:\n")
        for record in records:
            click.echo(
                f"  {record.get('company_name', 'Unknown')} | "
                f"confidence: {record.get('significance_confidence', 0):.2f} | "
                f"{record.get('detected_at', '')[:10]}"
            )
            notes = record.get("significance_notes", "")
            if notes:
                click.echo(f"    Notes: {notes}")
    db.close()


@click.command()
@click.argument("company_name")
def show_changes(company_name: str) -> None:
    """Display change history for a company, including related news."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.monitoring.repositories.change_record_repository import (
        ChangeRecordRepository,
    )
    from src.domains.news.repositories.news_article_repository import NewsArticleRepository
    from src.repositories.company_repository import CompanyRepository

    company_repo = CompanyRepository(db)
    change_repo = ChangeRecordRepository(db)
    news_repo = NewsArticleRepository(db)

    company = company_repo.get_company_by_name(company_name)
    if not company:
        click.echo(f"[ERROR] Company '{company_name}' not found.")
        db.close()
        return

    click.echo(f"\n[INFO] Change history for: {company['name']}")
    click.echo(f"  Homepage: {company.get('homepage_url', 'N/A')}\n")

    records = change_repo.get_changes_for_company(company["id"])
    if not records:
        click.echo("  No changes recorded.")
    else:
        for record in records:
            changed = "CHANGED" if record["has_changed"] else "no change"
            sig = record.get("significance_classification", "N/A")
            sentiment = record.get("significance_sentiment", "N/A")
            click.echo(
                f"  {record['detected_at'][:10]} | {changed} | "
                f"{record['change_magnitude']} | "
                f"significance: {sig} ({sentiment})"
            )

    # Show related news
    articles = news_repo.get_news_articles(company["id"], limit=10)
    if articles:
        click.echo(f"\n  Related News ({len(articles)} articles):")
        for article in articles:
            sig = article.get("significance_classification", "N/A")
            click.echo(
                f"    {article.get('published_at', '')[:10]} | "
                f"{article.get('title', 'Untitled')[:60]} | "
                f"{article.get('source', '')} | "
                f"significance: {sig}"
            )
    db.close()


@click.command()
@click.argument("company_name")
def show_status(company_name: str) -> None:
    """Display current status for a company."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.monitoring.repositories.company_status_repository import (
        CompanyStatusRepository,
    )

    status_repo = CompanyStatusRepository(db)
    status = status_repo.get_status_by_company_name(company_name)

    if not status:
        click.echo(f"[ERROR] No status found for '{company_name}'.")
        db.close()
        return

    click.echo(f"\n[INFO] Status for: {company_name}")
    click.echo(f"  Status: {status['status']}")
    click.echo(f"  Confidence: {status['confidence']:.2f}")
    click.echo(f"  Last Checked: {status['last_checked'][:10]}")

    indicators = status.get("indicators", [])
    if indicators:
        click.echo("  Indicators:")
        for ind in indicators:
            if isinstance(ind, dict):
                click.echo(f"    - {ind.get('type')}: {ind.get('value')} ({ind.get('signal')})")
    db.close()


@click.command()
@click.option("--days", default=180, type=int, help="Look back N days")
def list_active(days: int) -> None:
    """List companies with recent changes."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    rows = db.fetchall(
        """SELECT DISTINCT c.name, c.homepage_url, cr.detected_at
           FROM companies c
           JOIN change_records cr ON c.id = cr.company_id
           WHERE cr.has_changed = 1
           AND cr.detected_at >= datetime('now', ?)
           ORDER BY cr.detected_at DESC""",
        (f"-{days} days",),
    )

    if not rows:
        click.echo(f"[INFO] No companies with changes in the last {days} days.")
    else:
        click.echo(f"[INFO] Companies with changes in the last {days} days:\n")
        for row in rows:
            click.echo(f"  {row['name']} | last change: {row['detected_at'][:10]}")
    db.close()


@click.command()
@click.option("--days", default=180, type=int, help="Look back N days")
def list_inactive(days: int) -> None:
    """List companies without recent changes."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    rows = db.fetchall(
        """SELECT c.name, c.homepage_url
           FROM companies c
           WHERE c.id NOT IN (
               SELECT DISTINCT company_id FROM change_records
               WHERE has_changed = 1
               AND detected_at >= datetime('now', ?)
           )
           ORDER BY c.name""",
        (f"-{days} days",),
    )

    if not rows:
        click.echo(f"[INFO] All companies have changes in the last {days} days.")
    else:
        click.echo(f"[INFO] Companies without changes in the last {days} days:\n")
        for row in rows:
            click.echo(f"  {row['name']}")
    db.close()


# --- Feature 003: Social Media Discovery ---


@click.command()
@click.option("--batch-size", default=50, type=int, help="Homepages per batch")
@click.option("--limit", default=None, type=int, help="Process first N companies")
@click.option("--company-id", default=None, type=int, help="Single company ID")
def discover_social_media(batch_size: int, limit: int | None, company_id: int | None) -> None:
    """Discover social media links from company homepages."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.discovery.repositories.social_media_link_repository import (
        SocialMediaLinkRepository,
    )
    from src.domains.discovery.services.social_media_discovery import SocialMediaDiscovery
    from src.repositories.company_repository import CompanyRepository
    from src.services.firecrawl_client import FirecrawlClient

    firecrawl = FirecrawlClient(config.firecrawl_api_key)
    social_repo = SocialMediaLinkRepository(db)
    company_repo = CompanyRepository(db)
    discovery = SocialMediaDiscovery(firecrawl, social_repo, company_repo)

    click.echo("[INFO] Discovering social media links...")
    result = discovery.discover_all(batch_size=batch_size, limit=limit, company_id=company_id)
    _print_summary("Social media discovery complete", result)
    db.close()


@click.command()
@click.option("--company-id", required=True, type=int, help="Company ID to crawl")
@click.option("--max-depth", default=3, type=int, help="Maximum crawl depth")
@click.option("--max-pages", default=50, type=int, help="Maximum pages to crawl")
@click.option("--include-subdomains/--no-subdomains", default=True, help="Include subdomains")
def discover_social_full_site(
    company_id: int, max_depth: int, max_pages: int, include_subdomains: bool
) -> None:
    """Discover social media via full-site crawl for a single company."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.discovery.repositories.social_media_link_repository import (
        SocialMediaLinkRepository,
    )
    from src.domains.discovery.services.full_site_social_discovery import (
        FullSiteSocialDiscovery,
    )
    from src.repositories.company_repository import CompanyRepository
    from src.services.firecrawl_client import FirecrawlClient

    firecrawl = FirecrawlClient(config.firecrawl_api_key)
    social_repo = SocialMediaLinkRepository(db)
    company_repo = CompanyRepository(db)
    discovery = FullSiteSocialDiscovery(firecrawl, social_repo, company_repo)

    click.echo(f"[INFO] Running full-site discovery for company {company_id}...")
    result = discovery.discover_for_company(
        company_id,
        max_depth=max_depth,
        max_pages=max_pages,
        include_subdomains=include_subdomains,
    )
    _print_summary("Full-site discovery complete", result)
    db.close()


@click.command()
@click.option("--company-ids", default=None, type=str, help="Comma-separated company IDs")
@click.option("--limit", default=None, type=int, help="Process first N companies")
@click.option("--batch-size", default=10, type=int, help="Companies per commit batch")
@click.option("--max-workers", default=5, type=int, help="Parallel workers")
@click.option("--scraping-parallelism", default=10, type=int, help="Page scraping parallelism")
def discover_social_batch(
    company_ids: str | None,
    limit: int | None,
    batch_size: int,
    max_workers: int,
    scraping_parallelism: int,
) -> None:
    """Advanced batch discovery with parallel full-site crawls."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.discovery.repositories.social_media_link_repository import (
        SocialMediaLinkRepository,
    )
    from src.domains.discovery.services.batch_social_discovery import BatchSocialDiscovery
    from src.domains.discovery.services.full_site_social_discovery import (
        FullSiteSocialDiscovery,
    )
    from src.repositories.company_repository import CompanyRepository
    from src.services.firecrawl_client import FirecrawlClient

    firecrawl = FirecrawlClient(config.firecrawl_api_key)
    social_repo = SocialMediaLinkRepository(db)
    company_repo = CompanyRepository(db)
    full_site = FullSiteSocialDiscovery(firecrawl, social_repo, company_repo)
    batch_discovery = BatchSocialDiscovery(full_site)

    if company_ids:
        ids = [int(x.strip()) for x in company_ids.split(",")]
    else:
        companies = company_repo.get_companies_with_homepage()
        if limit:
            companies = companies[:limit]
        ids = [c["id"] for c in companies]

    click.echo(f"[INFO] Batch discovery for {len(ids)} companies (workers: {max_workers})...")
    result = batch_discovery.discover_batch(ids, max_workers=max_workers)
    _print_summary("Batch discovery complete", result)
    db.close()


# --- Feature 004: News Monitoring ---


@click.command()
@click.option("--company-name", default=None, type=str, help="Company name to search")
@click.option("--company-id", default=None, type=int, help="Company ID to search")
def search_news(company_name: str | None, company_id: int | None) -> None:
    """Search news for a single company."""
    if not company_name and not company_id:
        click.echo("[ERROR] Either --company-name or --company-id is required.")
        return

    config = _get_config()
    configure_logging(config.log_level)

    if not config.kagi_api_key:
        click.echo("[ERROR] KAGI_API_KEY not set in .env file.")
        return

    db = _get_db(config)

    from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository
    from src.domains.news.repositories.news_article_repository import NewsArticleRepository
    from src.domains.news.services.kagi_client import KagiClient
    from src.domains.news.services.news_monitor_manager import NewsMonitorManager
    from src.repositories.company_repository import CompanyRepository

    kagi = KagiClient(config.kagi_api_key)
    news_repo = NewsArticleRepository(db)
    company_repo = CompanyRepository(db)
    snapshot_repo = SnapshotRepository(db)

    llm_client = None
    if config.llm_validation_enabled and config.anthropic_api_key:
        from src.services.llm_client import LLMClient

        llm_client = LLMClient(config.anthropic_api_key, config.llm_model)

    manager = NewsMonitorManager(kagi, news_repo, company_repo, snapshot_repo, llm_client)

    click.echo("[INFO] Searching news...")
    result = manager.search_company_news(company_id=company_id, company_name=company_name)

    if result.get("error"):
        click.echo(f"[ERROR] {result['error']}")
    else:
        _print_summary("News search complete", result)
    db.close()


@click.command()
@click.option("--limit", default=None, type=int, help="Process first N companies")
def search_news_all(limit: int | None) -> None:
    """Search news for all companies."""
    config = _get_config()
    configure_logging(config.log_level)

    if not config.kagi_api_key:
        click.echo("[ERROR] KAGI_API_KEY not set in .env file.")
        return

    db = _get_db(config)

    from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository
    from src.domains.news.repositories.news_article_repository import NewsArticleRepository
    from src.domains.news.services.kagi_client import KagiClient
    from src.domains.news.services.news_monitor_manager import NewsMonitorManager
    from src.repositories.company_repository import CompanyRepository

    kagi = KagiClient(config.kagi_api_key)
    news_repo = NewsArticleRepository(db)
    company_repo = CompanyRepository(db)
    snapshot_repo = SnapshotRepository(db)

    llm_client = None
    if config.llm_validation_enabled and config.anthropic_api_key:
        from src.services.llm_client import LLMClient

        llm_client = LLMClient(config.anthropic_api_key, config.llm_model)

    manager = NewsMonitorManager(kagi, news_repo, company_repo, snapshot_repo, llm_client)

    click.echo("[INFO] Searching news for all companies...")
    result = manager.search_all_companies(limit=limit)
    _print_summary("News search complete", result)
    db.close()
