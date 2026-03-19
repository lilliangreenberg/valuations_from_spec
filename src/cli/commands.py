"""CLI command implementations for the Portfolio Company Monitoring System."""

from __future__ import annotations

import getpass
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import click

from src.core.report_builder import (
    build_capture_snapshots_report,
    build_capture_social_snapshots_report,
    build_detect_changes_report,
    build_detect_social_changes_report,
    build_discover_social_media_report,
    build_extract_leadership_report,
    build_search_news_report,
)
from src.models.config import Config
from src.services.database import Database
from src.utils.logger import configure_logging
from src.utils.report_writer import write_report


def _get_config() -> Config:
    """Load configuration from .env file."""
    return Config()  # type: ignore[call-arg]


def _get_db(config: Config) -> Database:
    """Initialize database with schema."""
    db = Database(db_path=config.database_path)
    db.init_db()
    return db


def _get_operator() -> str:
    """Get the current operator's username for audit attribution."""
    return getpass.getuser()


def _get_manually_closed_ids(db: Database, operator: str) -> set[int]:
    """Get company IDs that have been manually set to likely_closed.

    These companies are excluded from batch operations by default.
    """
    from src.domains.monitoring.repositories.company_status_repository import (
        CompanyStatusRepository,
    )

    status_repo = CompanyStatusRepository(db, operator)
    closed_ids = status_repo.get_manually_closed_company_ids()
    if closed_ids:
        click.echo(f"[INFO] Excluding {len(closed_ids)} manually-closed companies")
    return closed_ids


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

    operator = _get_operator()
    airtable = AirtableClient(config.airtable_api_key, config.airtable_base_id)
    company_repo = CompanyRepository(db, operator)
    extractor = CompanyExtractor(airtable, company_repo)

    click.echo("[INFO] Extracting companies from Airtable...")
    result = extractor.extract_companies()
    _print_summary("Company extraction complete", result)
    db.close()


@click.command()
def import_urls() -> None:
    """Import social media and blog URLs from Airtable."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.discovery.repositories.social_media_link_repository import (
        SocialMediaLinkRepository,
    )
    from src.repositories.company_repository import CompanyRepository
    from src.services.airtable_client import AirtableClient
    from src.services.extractor import CompanyExtractor

    operator = _get_operator()
    airtable = AirtableClient(config.airtable_api_key, config.airtable_base_id)
    company_repo = CompanyRepository(db, operator)
    social_link_repo = SocialMediaLinkRepository(db, operator)
    extractor = CompanyExtractor(airtable, company_repo)

    click.echo("[INFO] Importing social media and blog URLs from Airtable...")
    result = extractor.import_social_urls(social_link_repo)
    _print_summary("URL import complete", result)
    db.close()


@click.command()
@click.option("--use-batch-api", is_flag=True, help="Use Firecrawl batch API (8x faster)")
@click.option("--batch-size", default=20, type=int, help="URLs per batch (max 1000)")
@click.option("--timeout", default=300, type=int, help="Timeout per batch in seconds")
@click.option("--company-id", default=None, type=int, help="Capture snapshot for a single company")
@click.option(
    "--skip-if-snapshot-since",
    default=None,
    type=str,
    help="Skip companies that already have a snapshot on or after this date (YYYY-MM-DD)",
)
@click.option(
    "--include-manually-closed",
    is_flag=True,
    default=False,
    help="Include companies manually set to likely_closed (excluded by default)",
)
def capture_snapshots(
    use_batch_api: bool,
    batch_size: int,
    timeout: int,
    company_id: int | None,
    skip_if_snapshot_since: str | None,
    include_manually_closed: bool,
) -> None:
    """Capture website snapshots for all companies."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.discovery.repositories.social_media_link_repository import (
        SocialMediaLinkRepository,
    )
    from src.domains.discovery.services.branding_logo_processor import BrandingLogoProcessor
    from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository
    from src.repositories.company_repository import CompanyRepository
    from src.services.firecrawl_client import FirecrawlClient

    operator = _get_operator()
    firecrawl = FirecrawlClient(config.firecrawl_api_key)
    snapshot_repo = SnapshotRepository(db, operator)
    company_repo = CompanyRepository(db, operator)
    logo_repo = SocialMediaLinkRepository(db, operator)
    logo_processor = BrandingLogoProcessor(logo_repo)

    # Build exclusion set from manually-closed companies and --skip-if-snapshot-since
    exclude_ids: set[int] | None = None
    if not include_manually_closed and company_id is None:
        closed_ids = _get_manually_closed_ids(db, operator)
        if closed_ids:
            exclude_ids = closed_ids

    if skip_if_snapshot_since:
        since_ids = snapshot_repo.get_company_ids_with_snapshot_since(skip_if_snapshot_since)
        skip_count = len(since_ids)
        click.echo(
            f"[INFO] Skipping {skip_count} companies with snapshots since {skip_if_snapshot_since}"
        )
        exclude_ids = exclude_ids | since_ids if exclude_ids else since_ids

    if company_id is not None:
        from src.services.snapshot_manager import SnapshotManager

        manager = SnapshotManager(firecrawl, snapshot_repo, company_repo)  # type: ignore[assignment]
        click.echo(f"[INFO] Capturing snapshot for company {company_id}...")
        try:
            result = manager.capture_snapshot_for_company(company_id)
        except ValueError as exc:
            click.echo(f"[ERROR] {exc}")
            db.close()
            raise SystemExit(1) from exc
    elif use_batch_api:
        from src.services.batch_snapshot_manager import BatchSnapshotManager

        manager = BatchSnapshotManager(
            firecrawl,
            snapshot_repo,
            company_repo,
            logo_processor=logo_processor,
        )
        click.echo(f"[INFO] Capturing snapshots using batch API (batch size: {batch_size})...")
        result = manager.capture_batch_snapshots(
            batch_size=batch_size, timeout=timeout, exclude_company_ids=exclude_ids
        )
    else:
        from src.services.snapshot_manager import SnapshotManager

        manager = SnapshotManager(
            firecrawl,
            snapshot_repo,
            company_repo,
            logo_processor=logo_processor,
        )  # type: ignore[assignment]
        click.echo("[INFO] Capturing snapshots sequentially...")
        result = manager.capture_all_snapshots(exclude_company_ids=exclude_ids)

    _print_summary("Snapshot capture complete", result)

    report_config: dict[str, Any] = {
        "mode": "batch" if use_batch_api else "sequential",
        "batch_size": batch_size if use_batch_api else None,
        "limit": company_id,
    }
    report = build_capture_snapshots_report(result, report_config)
    report_path = write_report(report)
    click.echo(f"  Report written to: {report_path}")

    db.close()


# --- Feature 002: Change Detection & Status Analysis ---


@click.command()
@click.option("--batch-size", default=50, type=int, help="Companies per batch")
@click.option("--limit", default=None, type=int, help="Max companies to process")
@click.option(
    "--company-id",
    "company_ids",
    multiple=True,
    type=int,
    help="Process specific company ID(s). Repeatable. Overrides --limit.",
)
@click.option(
    "--output-format",
    default="summary",
    type=click.Choice(["summary", "detailed", "json"]),
    help="Output format",
)
@click.option("--include-social", is_flag=True, help="Enrich LLM with social media context")
@click.option(
    "--include-manually-closed",
    is_flag=True,
    default=False,
    help="Include companies manually set to likely_closed (excluded by default)",
)
def detect_changes(
    batch_size: int,
    limit: int | None,
    company_ids: tuple[int, ...],
    output_format: str,
    include_social: bool,
    include_manually_closed: bool,
) -> None:
    """Detect content changes between snapshots with significance analysis."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.monitoring.repositories.change_record_repository import (
        ChangeRecordRepository,
    )
    from src.domains.monitoring.repositories.company_status_repository import (
        CompanyStatusRepository,
    )
    from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository
    from src.domains.monitoring.services.change_detector import ChangeDetector
    from src.repositories.company_repository import CompanyRepository

    operator = _get_operator()
    snapshot_repo = SnapshotRepository(db, operator)
    change_repo = ChangeRecordRepository(db, operator)
    company_repo = CompanyRepository(db, operator)
    status_repo = CompanyStatusRepository(db, operator)

    llm_client = None
    if config.llm_validation_enabled and config.anthropic_api_key:
        from src.services.llm_client import LLMClient

        llm_client = LLMClient(config.anthropic_api_key, config.llm_model)

    social_snapshot_repo = None
    if include_social:
        from src.domains.monitoring.repositories.social_snapshot_repository import (
            SocialSnapshotRepository,
        )

        social_snapshot_repo = SocialSnapshotRepository(db, operator)

    detector = ChangeDetector(
        snapshot_repo,
        change_repo,
        company_repo,
        llm_client=llm_client,
        llm_enabled=bool(llm_client),
        social_snapshot_repo=social_snapshot_repo,
        status_repo=status_repo,
    )

    exclude_ids: set[int] | None = None
    if not include_manually_closed and not company_ids:
        exclude_ids = _get_manually_closed_ids(db, operator) or None

    click.echo("[INFO] Detecting changes...")
    result = detector.detect_all_changes(
        limit=limit,
        company_ids=list(company_ids) if company_ids else None,
        exclude_company_ids=exclude_ids,
    )

    if output_format == "json":
        click.echo(json.dumps(result, indent=2))
    else:
        _print_summary("Change detection complete", result)
        _print_status_changes(result.get("report_details", {}).get("status_changes", []))

    report_config: dict[str, Any] = {
        "include_social": include_social,
        "llm_enabled": bool(llm_client),
        "llm_model": config.llm_model if llm_client else None,
        "limit": limit,
    }
    report = build_detect_changes_report(result, report_config)
    report_path = write_report(report)
    click.echo(f"  Report written to: {report_path}")

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
@click.option("--include-social", is_flag=True, help="Include social media signals in analysis")
def analyze_status(
    batch_size: int, confidence_threshold: float, output_format: str, include_social: bool
) -> None:
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

    operator = _get_operator()
    snapshot_repo = SnapshotRepository(db, operator)
    status_repo = CompanyStatusRepository(db, operator)
    company_repo = CompanyRepository(db, operator)

    social_snapshot_repo = None
    if include_social:
        from src.domains.monitoring.repositories.social_snapshot_repository import (
            SocialSnapshotRepository,
        )

        social_snapshot_repo = SocialSnapshotRepository(db, operator)
        click.echo("[INFO] Including social media signals in status analysis...")

    analyzer = StatusAnalyzer(
        snapshot_repo, status_repo, company_repo, social_snapshot_repo=social_snapshot_repo
    )

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
    from src.repositories.company_repository import CompanyRepository

    operator = _get_operator()
    change_repo = ChangeRecordRepository(db, operator)
    snapshot_repo = SnapshotRepository(db, operator)
    company_repo = CompanyRepository(db, operator)

    llm_client = None
    if config.llm_validation_enabled and config.anthropic_api_key:
        from src.services.llm_client import LLMClient

        llm_client = LLMClient(config.anthropic_api_key, config.llm_model)

    analyzer = SignificanceAnalyzer(
        change_repo,
        snapshot_repo,
        company_repo,
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

    operator = _get_operator()
    change_repo = ChangeRecordRepository(db, operator)
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
            homepage_url = record.get("homepage_url", "")
            if homepage_url:
                click.echo(f"    URL: {homepage_url}")
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

    operator = _get_operator()
    change_repo = ChangeRecordRepository(db, operator)
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
            homepage_url = record.get("homepage_url", "")
            if homepage_url:
                click.echo(f"    URL: {homepage_url}")
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

    operator = _get_operator()
    company_repo = CompanyRepository(db, operator)
    change_repo = ChangeRecordRepository(db, operator)
    news_repo = NewsArticleRepository(db, operator)

    company = company_repo.get_company_by_name(company_name)
    if not company:
        click.echo(f"[ERROR] Company '{company_name}' not found.")
        db.close()
        return

    click.echo(f"\n[INFO] Change history for: {company['name']}")
    click.echo(f"  Homepage: {company.get('homepage_url', 'N/A')}\n")

    from src.domains.monitoring.repositories.social_change_record_repository import (
        SocialChangeRecordRepository,
    )

    records = change_repo.get_changes_for_company(company["id"])
    social_change_repo = SocialChangeRecordRepository(db, operator)
    social_changes = social_change_repo.get_changes_for_company(company["id"])

    # Build unified list of (detected_at, display_line) for chronological display
    unified: list[tuple[str, str]] = []

    for record in records:
        changed = "CHANGED" if record["has_changed"] else "no change"
        sig = record.get("significance_classification", "N/A")
        sentiment = record.get("significance_sentiment", "N/A")
        detected_at = record.get("detected_at", "")
        line = (
            f"  [HOMEPAGE] {detected_at[:10]} | {changed} | "
            f"{record['change_magnitude']} | "
            f"significance: {sig} ({sentiment})"
        )
        unified.append((detected_at, line))

    for sc in social_changes:
        changed = "CHANGED" if sc["has_changed"] else "no change"
        sig = sc.get("significance_classification", "N/A")
        sentiment = sc.get("significance_sentiment", "N/A")
        source_type = sc.get("source_type", "unknown").upper()
        detected_at = sc.get("detected_at", "")
        line = (
            f"  [{source_type}] {detected_at[:10]} | {changed} | "
            f"{sc['change_magnitude']} | "
            f"significance: {sig} ({sentiment})"
        )
        unified.append((detected_at, line))

    if not unified:
        click.echo("  No changes recorded.")
    else:
        # Sort by detected_at descending (most recent first)
        unified.sort(key=lambda x: x[0], reverse=True)
        for _ts, line in unified:
            click.echo(line)

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

    operator = _get_operator()
    status_repo = CompanyStatusRepository(db, operator)
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
@click.option("--company-id", type=int, default=None, help="Company ID")
@click.option("--company-name", type=str, default=None, help="Company name")
@click.option("--notes", type=str, required=True, help="Analyst notes to set (use '' to clear)")
def set_company_notes(company_id: int | None, company_name: str | None, notes: str) -> None:
    """Set analyst notes for a company to guide LLM classification."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.repositories.company_repository import CompanyRepository

    operator = _get_operator()
    repo = CompanyRepository(db, operator)
    company: dict[str, Any] | None = None

    if company_id is not None:
        company = repo.get_company_by_id(company_id)
    elif company_name is not None:
        company = repo.get_company_by_name(company_name)
    else:
        click.echo("[ERROR] Provide --company-id or --company-name.")
        db.close()
        return

    if not company:
        click.echo("[ERROR] Company not found.")
        db.close()
        return

    notes_value: str | None = notes.strip() or None
    repo.update_notes(company["id"], notes_value)
    if notes_value:
        click.echo(f"[SUCCESS] Notes set for '{company['name']}':\n  {notes_value}")
    else:
        click.echo(f"[SUCCESS] Notes cleared for '{company['name']}'.")
    db.close()


@click.command()
@click.option("--company-id", type=int, default=None, help="Company ID")
@click.option("--company-name", type=str, default=None, help="Company name")
def get_company_notes(company_id: int | None, company_name: str | None) -> None:
    """Show the current analyst notes for a company."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.repositories.company_repository import CompanyRepository

    operator = _get_operator()
    repo = CompanyRepository(db, operator)
    company: dict[str, Any] | None = None

    if company_id is not None:
        company = repo.get_company_by_id(company_id)
    elif company_name is not None:
        company = repo.get_company_by_name(company_name)
    else:
        click.echo("[ERROR] Provide --company-id or --company-name.")
        db.close()
        return

    if not company:
        click.echo("[ERROR] Company not found.")
        db.close()
        return

    notes = company.get("notes")
    if notes:
        click.echo(f"[INFO] Notes for '{company['name']}':\n  {notes}")
    else:
        click.echo(f"[INFO] No notes set for '{company['name']}'.")
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
            click.echo(f"    URL: {row['homepage_url']}")
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
            click.echo(f"    URL: {row['homepage_url']}")
    db.close()


# --- Feature 003: Social Media Discovery ---


@click.command()
@click.option("--company-id", default=None, type=int, help="Look up by company ID")
@click.option("--company-name", default=None, type=str, help="Look up by company name")
def show_social_links(company_id: int | None, company_name: str | None) -> None:
    """Display discovered social media links and blogs for a company."""
    if not company_id and not company_name:
        click.echo("[ERROR] Provide --company-id or --company-name.")
        return

    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.discovery.repositories.social_media_link_repository import (
        SocialMediaLinkRepository,
    )
    from src.repositories.company_repository import CompanyRepository

    operator = _get_operator()
    company_repo = CompanyRepository(db, operator)

    if company_name:
        company = company_repo.get_company_by_name(company_name)
        if not company:
            click.echo(f"[ERROR] Company not found: {company_name}")
            db.close()
            return
        company_id = company["id"]
        resolved_name = company["name"]
        homepage_url = company.get("homepage_url", "")
    else:
        company = company_repo.get_company_by_id(company_id)  # type: ignore[arg-type]
        if not company:
            click.echo(f"[ERROR] Company not found: ID {company_id}")
            db.close()
            return
        resolved_name = company["name"]
        homepage_url = company.get("homepage_url", "")

    link_repo = SocialMediaLinkRepository(db, operator)
    links = link_repo.get_links_for_company(company_id)  # type: ignore[arg-type]
    blogs = link_repo.get_blogs_for_company(company_id)  # type: ignore[arg-type]

    click.echo(f"\n  {resolved_name}")
    if homepage_url:
        click.echo(f"  {homepage_url}\n")

    if links:
        click.echo(f"  Social media links ({len(links)}):")
        for link in links:
            platform = link.get("platform", "unknown")
            url = link.get("profile_url", "")
            acct_type = link.get("account_type") or ""
            status = link.get("verification_status", "")
            parts = [f"    [{platform:<10s}] {url}"]
            if acct_type:
                parts.append(f"type={acct_type}")
            if status and status != "unverified":
                parts.append(f"status={status}")
            click.echo("  ".join(parts))
    else:
        click.echo("  Social media links: none found")

    if blogs:
        click.echo(f"\n  Blog links ({len(blogs)}):")
        for blog in blogs:
            blog_type = blog.get("blog_type", "unknown")
            url = blog.get("blog_url", "")
            click.echo(f"    [{blog_type:<10s}] {url}")

    click.echo()
    db.close()


@click.command()
@click.option("--batch-size", default=50, type=int, help="Homepages per batch")
@click.option("--limit", default=None, type=int, help="Process first N companies")
@click.option("--company-id", default=None, type=int, help="Single company ID")
@click.option(
    "--skip-ceo-search",
    is_flag=True,
    default=False,
    help="Skip CEO LinkedIn discovery after social media discovery",
)
@click.option(
    "--include-manually-closed",
    is_flag=True,
    default=False,
    help="Include companies manually set to likely_closed (excluded by default)",
)
def discover_social_media(
    batch_size: int,
    limit: int | None,
    company_id: int | None,
    skip_ceo_search: bool,
    include_manually_closed: bool,
) -> None:
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

    operator = _get_operator()
    firecrawl = FirecrawlClient(config.firecrawl_api_key)
    social_repo = SocialMediaLinkRepository(db, operator)
    company_repo = CompanyRepository(db, operator)
    discovery = SocialMediaDiscovery(firecrawl, social_repo, company_repo)

    exclude_ids: set[int] | None = None
    if not include_manually_closed and company_id is None:
        exclude_ids = _get_manually_closed_ids(db, operator) or None

    click.echo("[INFO] Discovering social media links...")
    result = discovery.discover_all(
        batch_size=batch_size,
        limit=limit,
        company_id=company_id,
        exclude_company_ids=exclude_ids,
    )
    _print_summary("Social media discovery complete", result)

    # Chain CEO LinkedIn discovery (opt-out via --skip-ceo-search)
    if not skip_ceo_search and config.kagi_api_key:
        click.echo("\n[INFO] Running CEO LinkedIn discovery...")
        ceo_discovery = _build_ceo_linkedin_discovery(
            db, config, operator, social_repo, company_repo
        )
        ceo_result = ceo_discovery.discover_all(limit=limit, exclude_company_ids=exclude_ids)
        _print_summary("CEO LinkedIn discovery complete", ceo_result)

    report_config: dict[str, Any] = {
        "batch_size": batch_size,
        "limit": limit,
        "company_id": company_id,
    }
    report = build_discover_social_media_report(result, report_config)
    report_path = write_report(report)
    click.echo(f"  Report written to: {report_path}")

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

    operator = _get_operator()
    firecrawl = FirecrawlClient(config.firecrawl_api_key)
    social_repo = SocialMediaLinkRepository(db, operator)
    company_repo = CompanyRepository(db, operator)
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

    operator = _get_operator()
    firecrawl = FirecrawlClient(config.firecrawl_api_key)
    social_repo = SocialMediaLinkRepository(db, operator)
    company_repo = CompanyRepository(db, operator)
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


# --- Logo Refresh ---


@click.command()
@click.option("--force", is_flag=True, help="Refresh all logos regardless of staleness")
@click.option("--staleness-days", default=90, type=int, help="Refresh logos older than N days")
@click.option("--limit", default=None, type=int, help="Process first N companies")
@click.option("--batch-size", default=50, type=int, help="URLs per Firecrawl batch")
@click.option("--timeout", default=300, type=int, help="Timeout per batch in seconds")
def refresh_logos(
    force: bool,
    staleness_days: int,
    limit: int | None,
    batch_size: int,
    timeout: int,
) -> None:
    """Refresh company logos using Firecrawl branding data.

    By default, only refreshes logos that are missing or older than --staleness-days.
    Use --force to refresh all logos.
    """
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.discovery.repositories.social_media_link_repository import (
        SocialMediaLinkRepository,
    )
    from src.domains.discovery.services.branding_logo_processor import BrandingLogoProcessor
    from src.repositories.company_repository import CompanyRepository
    from src.services.firecrawl_client import FirecrawlClient
    from src.utils.progress import ProgressTracker

    operator = _get_operator()
    firecrawl = FirecrawlClient(config.firecrawl_api_key)
    company_repo = CompanyRepository(db, operator)
    logo_repo = SocialMediaLinkRepository(db, operator)
    logo_processor = BrandingLogoProcessor(logo_repo)

    companies = company_repo.get_companies_with_homepage()
    if limit:
        companies = companies[:limit]

    # Determine which companies need logo refresh
    companies_to_process = _filter_companies_for_logo_refresh(
        logo_repo,
        companies,
        force=force,
        staleness_days=staleness_days,
    )

    if not companies_to_process:
        click.echo("[INFO] No companies need logo refresh.")
        db.close()
        return

    click.echo(
        f"[INFO] Refreshing logos for {len(companies_to_process)} companies "
        f"(batch size: {batch_size})..."
    )

    tracker = ProgressTracker(total=len(companies_to_process))

    # Build URL -> company_id mapping
    url_to_company: dict[str, int] = {}
    urls: list[str] = []
    for company in companies_to_process:
        url = company["homepage_url"]
        url_to_company[url] = company["id"]
        urls.append(url)

    # Scrape homepages with branding format using batch API
    for i in range(0, len(urls), batch_size):
        batch_urls = urls[i : i + batch_size]
        try:
            result = firecrawl.batch_capture_snapshots(batch_urls, timeout=timeout)
            if result["success"]:
                for doc in result.get("documents", []):
                    doc_url = doc.get("url", "")
                    company_id = url_to_company.get(doc_url)
                    if company_id is None:
                        for orig_url, cid in url_to_company.items():
                            if doc_url and orig_url in doc_url:
                                company_id = cid
                                break
                    if company_id is not None:
                        branding = doc.get("branding")
                        if branding:
                            stored = logo_processor.process_branding_logo(
                                company_id,
                                branding,
                            )
                            if stored:
                                tracker.record_success()
                            else:
                                tracker.record_failure(
                                    f"No valid logo for company {company_id}",
                                )
                        else:
                            tracker.record_failure(f"No branding data for {doc_url}")
                    else:
                        tracker.record_failure(f"No company match for URL: {doc_url}")
            else:
                for _url in batch_urls:
                    tracker.record_failure(
                        f"Batch failed: {result.get('errors', [])}",
                    )
        except Exception as exc:
            for _url in batch_urls:
                tracker.record_failure(str(exc))

        tracker.log_progress(every_n=1)

    _print_summary("Logo refresh complete", tracker.summary())
    db.close()


def _filter_companies_for_logo_refresh(
    logo_repo: Any,
    companies: list[dict[str, Any]],
    *,
    force: bool,
    staleness_days: int,
) -> list[dict[str, Any]]:
    """Filter companies that need logo refresh based on staleness threshold."""
    if force:
        return companies

    cutoff = (datetime.now(tz=UTC) - timedelta(days=staleness_days)).isoformat()
    result: list[dict[str, Any]] = []
    for company in companies:
        logo = logo_repo.get_company_logo(company["id"])
        if logo is None:
            # No logo at all
            result.append(company)
        elif logo.get("extracted_at", "") < cutoff:
            # Logo is stale
            result.append(company)
    return result


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

    operator = _get_operator()
    kagi = KagiClient(config.kagi_api_key)
    news_repo = NewsArticleRepository(db, operator)
    company_repo = CompanyRepository(db, operator)
    snapshot_repo = SnapshotRepository(db, operator)

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
@click.option("--max-workers", default=5, type=int, help="Parallel workers for Kagi API calls")
@click.option(
    "--include-manually-closed",
    is_flag=True,
    default=False,
    help="Include companies manually set to likely_closed (excluded by default)",
)
def search_news_all(limit: int | None, max_workers: int, include_manually_closed: bool) -> None:
    """Search news for all companies with parallel Kagi API calls."""
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

    operator = _get_operator()
    kagi = KagiClient(config.kagi_api_key)
    news_repo = NewsArticleRepository(db, operator)
    company_repo = CompanyRepository(db, operator)
    snapshot_repo = SnapshotRepository(db, operator)

    llm_client = None
    if config.llm_validation_enabled and config.anthropic_api_key:
        from src.services.llm_client import LLMClient

        llm_client = LLMClient(config.anthropic_api_key, config.llm_model)

    manager = NewsMonitorManager(kagi, news_repo, company_repo, snapshot_repo, llm_client)

    exclude_ids: set[int] | None = None
    if not include_manually_closed:
        exclude_ids = _get_manually_closed_ids(db, operator) or None

    click.echo(f"[INFO] Searching news for all companies ({max_workers} workers)...")
    result = manager.search_all_companies(
        limit=limit,
        max_workers=max_workers,
        exclude_company_ids=exclude_ids,
    )
    _print_summary("News search complete", result)

    report_config: dict[str, Any] = {
        "limit": limit,
        "max_workers": max_workers,
    }
    report = build_search_news_report(result, report_config)
    report_path = write_report(report)
    click.echo(f"  Report written to: {report_path}")

    db.close()


# --- Feature 005: LinkedIn Leadership Extraction ---


@click.command()
@click.option("--company-id", required=True, type=int, help="Company ID")
@click.option("--headless", is_flag=True, help="Run browser in headless mode")
@click.option(
    "--profile-dir",
    default=None,
    type=str,
    help="Playwright browser profile directory",
)
def extract_leadership(company_id: int, headless: bool, profile_dir: str | None) -> None:
    """Extract leadership profiles from LinkedIn for a single company."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.discovery.repositories.social_media_link_repository import (
        SocialMediaLinkRepository,
    )
    from src.domains.leadership.repositories.leadership_repository import (
        LeadershipRepository,
    )
    from src.domains.leadership.services.leadership_manager import LeadershipManager
    from src.domains.leadership.services.linkedin_browser import LinkedInBrowser
    from src.repositories.company_repository import CompanyRepository

    operator = _get_operator()
    browser_headless = headless or config.linkedin_headless
    browser_profile = profile_dir or config.linkedin_profile_dir

    browser = LinkedInBrowser(headless=browser_headless, profile_dir=browser_profile)
    leadership_repo = LeadershipRepository(db, operator)
    social_repo = SocialMediaLinkRepository(db, operator)
    company_repo = CompanyRepository(db, operator)

    # Set up Kagi fallback
    search_service = _build_leadership_search(config)

    manager = LeadershipManager(
        linkedin_browser=browser,
        leadership_search=search_service,
        leadership_repo=leadership_repo,
        social_link_repo=social_repo,
        company_repo=company_repo,
    )

    click.echo(f"[INFO] Extracting leadership for company {company_id}...")
    result = manager.extract_company_leadership(company_id)

    if result.get("error"):
        click.echo(f"[ERROR] {result['error']}")
    else:
        _print_summary("Leadership extraction complete", result)
        _print_leadership_changes(result.get("leadership_changes", []))
    db.close()


@click.command()
@click.option("--limit", default=None, type=int, help="Process first N companies")
@click.option("--headless", is_flag=True, help="Run browser in headless mode")
@click.option(
    "--profile-dir",
    default=None,
    type=str,
    help="Playwright browser profile directory",
)
@click.option(
    "--max-workers",
    default=1,
    type=int,
    help="Parallel workers (default 1 for Playwright safety; increase for Kagi-only mode)",
)
@click.option(
    "--include-manually-closed",
    is_flag=True,
    default=False,
    help="Include companies manually set to likely_closed (excluded by default)",
)
def extract_leadership_all(
    limit: int | None,
    headless: bool,
    profile_dir: str | None,
    max_workers: int,
    include_manually_closed: bool,
) -> None:
    """Extract leadership profiles for all companies."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.discovery.repositories.social_media_link_repository import (
        SocialMediaLinkRepository,
    )
    from src.domains.leadership.repositories.leadership_repository import (
        LeadershipRepository,
    )
    from src.domains.leadership.services.leadership_manager import LeadershipManager
    from src.domains.leadership.services.linkedin_browser import LinkedInBrowser
    from src.repositories.company_repository import CompanyRepository

    operator = _get_operator()
    browser_headless = headless or config.linkedin_headless
    browser_profile = profile_dir or config.linkedin_profile_dir

    browser = LinkedInBrowser(headless=browser_headless, profile_dir=browser_profile)
    leadership_repo = LeadershipRepository(db, operator)
    social_repo = SocialMediaLinkRepository(db, operator)
    company_repo = CompanyRepository(db, operator)

    search_service = _build_leadership_search(config)

    manager = LeadershipManager(
        linkedin_browser=browser,
        leadership_search=search_service,
        leadership_repo=leadership_repo,
        social_link_repo=social_repo,
        company_repo=company_repo,
    )

    exclude_ids: set[int] | None = None
    if not include_manually_closed:
        exclude_ids = _get_manually_closed_ids(db, operator) or None

    click.echo(f"[INFO] Extracting leadership for all companies ({max_workers} workers)...")
    result = manager.extract_all_leadership(
        limit=limit,
        max_workers=max_workers,
        exclude_company_ids=exclude_ids,
    )
    _print_summary("Leadership extraction complete", result)

    critical = result.get("critical_changes", [])
    if critical:
        click.echo(f"\n[CRITICAL] {len(critical)} critical leadership change(s):")
        for change in critical:
            click.echo(
                f"  {change.get('company_name', 'Unknown')} | "
                f"{change.get('change_type', '')} | "
                f"{change.get('person_name', '')} ({change.get('title', '')})"
            )

    report_config: dict[str, Any] = {
        "limit": limit,
        "max_workers": max_workers,
        "headless": headless,
    }
    report = build_extract_leadership_report(result, report_config)
    report_path = write_report(report)
    click.echo(f"  Report written to: {report_path}")

    db.close()


@click.command()
@click.option("--limit", default=None, type=int, help="Process first N companies")
@click.option("--headless", is_flag=True, help="Run browser in headless mode")
@click.option(
    "--profile-dir",
    default=None,
    type=str,
    help="Playwright browser profile directory",
)
def check_leadership_changes(
    limit: int | None,
    headless: bool,
    profile_dir: str | None,
) -> None:
    """Re-extract leadership and report changes only."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.discovery.repositories.social_media_link_repository import (
        SocialMediaLinkRepository,
    )
    from src.domains.leadership.repositories.leadership_repository import (
        LeadershipRepository,
    )
    from src.domains.leadership.services.leadership_manager import LeadershipManager
    from src.domains.leadership.services.linkedin_browser import LinkedInBrowser
    from src.repositories.company_repository import CompanyRepository

    operator = _get_operator()
    browser_headless = headless or config.linkedin_headless
    browser_profile = profile_dir or config.linkedin_profile_dir

    browser = LinkedInBrowser(headless=browser_headless, profile_dir=browser_profile)
    leadership_repo = LeadershipRepository(db, operator)
    social_repo = SocialMediaLinkRepository(db, operator)
    company_repo = CompanyRepository(db, operator)

    search_service = _build_leadership_search(config)

    manager = LeadershipManager(
        linkedin_browser=browser,
        leadership_search=search_service,
        leadership_repo=leadership_repo,
        social_link_repo=social_repo,
        company_repo=company_repo,
    )

    click.echo("[INFO] Checking for leadership changes...")
    result = manager.extract_all_leadership(limit=limit)

    critical = result.get("critical_changes", [])
    if critical:
        click.echo(f"\n[CRITICAL] {len(critical)} critical leadership change(s):")
        for change in critical:
            click.echo(
                f"  {change.get('company_name', 'Unknown')} | "
                f"{change.get('change_type', '')} | "
                f"{change.get('person_name', '')} ({change.get('title', '')})"
            )
    else:
        click.echo("[INFO] No critical leadership changes detected.")

    _print_summary("Leadership change check complete", result)
    db.close()


@click.command()
@click.option("--limit", default=None, type=int, help="Process first N companies")
@click.option("--dry-run", is_flag=True, help="Preview without updating")
def analyze_baseline(limit: int | None, dry_run: bool) -> None:
    """Run baseline signal analysis on company snapshots.

    Computes one-time baseline signals for companies that haven't been analyzed yet.
    Baselines capture pre-existing positive/negative signals from the full page content.
    """
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository
    from src.domains.monitoring.services.baseline_analyzer import BaselineAnalyzer
    from src.repositories.company_repository import CompanyRepository

    operator = _get_operator()
    snapshot_repo = SnapshotRepository(db, operator)
    company_repo = CompanyRepository(db, operator)

    llm_client = None
    if config.llm_validation_enabled and config.anthropic_api_key:
        from src.services.llm_client import LLMClient

        llm_client = LLMClient(config.anthropic_api_key, config.llm_model)

    analyzer = BaselineAnalyzer(
        snapshot_repo,
        company_repo,
        llm_client=llm_client,
        llm_enabled=bool(llm_client),
    )

    mode = "DRY RUN" if dry_run else "analyzing"
    click.echo(f"[INFO] {mode} baseline signals...")
    result = analyzer.backfill_baselines(limit=limit, dry_run=dry_run)
    _print_summary("Baseline analysis complete", result)
    db.close()


# --- Feature 006: Social Media Content Monitoring ---


@click.command()
@click.option("--batch-size", default=50, type=int, help="URLs per Firecrawl batch")
@click.option("--limit", default=None, type=int, help="Max URLs to capture")
@click.option("--company-id", default=None, type=int, help="Single company ID")
@click.option(
    "--include-manually-closed",
    is_flag=True,
    default=False,
    help="Include companies manually set to likely_closed (excluded by default)",
)
def capture_social_snapshots(
    batch_size: int,
    limit: int | None,
    company_id: int | None,
    include_manually_closed: bool,
) -> None:
    """Capture snapshots of Medium and blog pages for social media monitoring."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.discovery.repositories.social_media_link_repository import (
        SocialMediaLinkRepository,
    )
    from src.domains.monitoring.repositories.social_snapshot_repository import (
        SocialSnapshotRepository,
    )
    from src.domains.monitoring.services.social_snapshot_manager import (
        SocialSnapshotManager,
    )
    from src.repositories.company_repository import CompanyRepository
    from src.services.firecrawl_client import FirecrawlClient

    operator = _get_operator()
    social_snapshot_repo = SocialSnapshotRepository(db, operator)
    social_link_repo = SocialMediaLinkRepository(db, operator)
    company_repo = CompanyRepository(db, operator)
    firecrawl = FirecrawlClient(config.firecrawl_api_key)

    manager = SocialSnapshotManager(social_snapshot_repo, social_link_repo, company_repo, firecrawl)

    exclude_ids: set[int] | None = None
    if not include_manually_closed and company_id is None:
        exclude_ids = _get_manually_closed_ids(db, operator) or None

    click.echo("[INFO] Capturing social media snapshots...")
    result = manager.capture_social_snapshots(
        batch_size=batch_size,
        limit=limit,
        company_id=company_id,
        exclude_company_ids=exclude_ids,
    )
    _print_summary("Social snapshot capture complete", result)

    report_config: dict[str, Any] = {
        "batch_size": batch_size,
        "limit": limit,
        "company_id": company_id,
    }
    report = build_capture_social_snapshots_report(result, report_config)
    report_path = write_report(report)
    click.echo(f"  Report written to: {report_path}")

    db.close()


@click.command()
@click.option("--limit", default=None, type=int, help="Max source pairs to process")
@click.option(
    "--include-manually-closed",
    is_flag=True,
    default=False,
    help="Include companies manually set to likely_closed (excluded by default)",
)
def detect_social_changes(limit: int | None, include_manually_closed: bool) -> None:
    """Detect content changes in social media snapshots."""
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    from src.domains.monitoring.repositories.social_change_record_repository import (
        SocialChangeRecordRepository,
    )
    from src.domains.monitoring.repositories.social_snapshot_repository import (
        SocialSnapshotRepository,
    )
    from src.domains.monitoring.services.social_change_detector import (
        SocialChangeDetector,
    )
    from src.repositories.company_repository import CompanyRepository

    operator = _get_operator()
    social_snapshot_repo = SocialSnapshotRepository(db, operator)
    social_change_repo = SocialChangeRecordRepository(db, operator)
    company_repo = CompanyRepository(db, operator)

    llm_client = None
    if config.llm_validation_enabled and config.anthropic_api_key:
        from src.services.llm_client import LLMClient

        llm_client = LLMClient(config.anthropic_api_key, config.llm_model)

    detector = SocialChangeDetector(
        social_snapshot_repo,
        social_change_repo,
        company_repo,
        llm_client=llm_client,
        llm_enabled=bool(llm_client),
    )

    exclude_ids: set[int] | None = None
    if not include_manually_closed:
        exclude_ids = _get_manually_closed_ids(db, operator) or None

    click.echo("[INFO] Detecting social media changes...")
    result = detector.detect_all_changes(limit=limit, exclude_company_ids=exclude_ids)
    _print_summary("Social change detection complete", result)

    report_config: dict[str, Any] = {
        "limit": limit,
    }
    report = build_detect_social_changes_report(result, report_config)
    report_path = write_report(report)
    click.echo(f"  Report written to: {report_path}")

    db.close()


def _build_leadership_search(config: Config) -> Any:
    """Build the LeadershipSearch service with Kagi client."""
    from src.domains.leadership.services.leadership_search import LeadershipSearch

    if config.kagi_api_key:
        from src.domains.news.services.kagi_client import KagiClient

        kagi = KagiClient(config.kagi_api_key)
        return LeadershipSearch(kagi)

    # Return a stub that produces empty results if no Kagi key
    class _StubSearch:
        def search_leadership(self, company_name: str) -> list[dict[str, str]]:
            return []

        def search_ceo_linkedin(
            self, company_name: str, person_name: str | None = None
        ) -> list[dict[str, str]]:
            return []

    return _StubSearch()


@click.command()
@click.option("--host", default="127.0.0.1", type=str, help="Host to bind to")
@click.option("--port", default=8000, type=int, help="Port to bind to")
@click.option("--no-browser", is_flag=True, help="Do not open browser on start")
def dashboard(host: str, port: int, no_browser: bool) -> None:
    """Launch the web dashboard."""
    import os
    import threading
    import webbrowser

    import uvicorn

    from src.domains.dashboard.app import create_app

    database_path = os.environ.get("DATABASE_PATH", "data/companies.db")
    log_level = os.environ.get("LOG_LEVEL", "INFO")
    configure_logging(log_level)

    app = create_app(database_path=database_path)

    if not no_browser:

        def open_browser() -> None:
            import time

            time.sleep(1.5)
            webbrowser.open(f"http://{host}:{port}")

        threading.Thread(target=open_browser, daemon=True).start()

    click.echo(f"[INFO] Dashboard running at http://{host}:{port}")
    click.echo("[INFO] Press Ctrl+C to stop.")
    uvicorn.run(app, host=host, port=port, log_level="warning")


def _print_status_changes(status_changes: list[dict[str, Any]]) -> None:
    """Print companies whose status changed during detect-changes."""
    if not status_changes:
        return

    click.echo("\n  Status Changes:")
    for entry in status_changes:
        prev = entry.get("previous_status", "unknown")
        new = entry.get("new_status", "unknown")
        name = entry.get("name", "")
        reason = entry.get("status_reason", "")
        reason_str = f" -- {reason}" if reason else ""
        click.echo(f"    {name}: {prev} -> {new}{reason_str}")


def _print_leadership_changes(changes: list[dict[str, Any]]) -> None:
    """Print leadership changes."""
    if not changes:
        return

    click.echo("\n  Leadership Changes:")
    for change in changes:
        severity = change.get("severity", "")
        prefix = "[CRITICAL]" if severity == "critical" else "[NOTE]"
        click.echo(
            f"    {prefix} {change.get('change_type', '')} | "
            f"{change.get('person_name', '')} ({change.get('title', '')})"
        )


def _build_ceo_linkedin_discovery(
    db: Database,
    config: Config,
    operator: str,
    social_repo: Any = None,
    company_repo: Any = None,
) -> Any:
    """Build the CeoLinkedinDiscovery service with all dependencies."""
    from src.domains.discovery.repositories.social_media_link_repository import (
        SocialMediaLinkRepository,
    )
    from src.domains.leadership.repositories.leadership_mention_repository import (
        LeadershipMentionRepository,
    )
    from src.domains.leadership.repositories.leadership_repository import (
        LeadershipRepository,
    )
    from src.domains.leadership.services.ceo_linkedin_discovery import (
        CeoLinkedinDiscovery,
    )
    from src.domains.monitoring.repositories.snapshot_repository import (
        SnapshotRepository,
    )
    from src.repositories.company_repository import CompanyRepository

    search_service = _build_leadership_search(config)
    leadership_repo = LeadershipRepository(db, operator)
    mention_repo = LeadershipMentionRepository(db, operator)
    snapshot_repo = SnapshotRepository(db, operator)
    if social_repo is None:
        social_repo = SocialMediaLinkRepository(db, operator)
    if company_repo is None:
        company_repo = CompanyRepository(db, operator)

    return CeoLinkedinDiscovery(
        leadership_search=search_service,
        leadership_repo=leadership_repo,
        leadership_mention_repo=mention_repo,
        snapshot_repo=snapshot_repo,
        social_link_repo=social_repo,
        company_repo=company_repo,
    )


@click.command()
@click.option("--company-id", default=None, type=int, help="Single company ID")
@click.option("--limit", default=None, type=int, help="Process first N companies")
@click.option("--max-workers", default=5, type=int, help="Parallel Kagi workers")
@click.option("--ceo-name", default=None, type=str, help="Known CEO name for targeted search")
@click.option("--dry-run", is_flag=True, help="Show what would be done without writing to DB")
@click.option(
    "--include-manually-closed",
    is_flag=True,
    default=False,
    help="Include companies manually set to likely_closed (excluded by default)",
)
def discover_ceo_linkedin(
    company_id: int | None,
    limit: int | None,
    max_workers: int,
    ceo_name: str | None,
    dry_run: bool,
    include_manually_closed: bool,
) -> None:
    """Discover CEO/founder LinkedIn profiles via Kagi search.

    Extracts CEO/founder names from website snapshots, then searches Kagi
    for their LinkedIn profiles. Results are stored in company_leadership
    and social_media_links tables.

    Can be run standalone or is automatically chained after discover-social-media
    (opt-out via --skip-ceo-search on that command).
    """
    config = _get_config()
    configure_logging(config.log_level)
    db = _get_db(config)

    operator = _get_operator()
    ceo_discovery = _build_ceo_linkedin_discovery(db, config, operator)

    mode = "[DRY RUN] " if dry_run else ""
    if company_id is not None:
        click.echo(f"{mode}[INFO] Discovering CEO LinkedIn for company {company_id}...")
        result = ceo_discovery.discover_for_company(company_id, ceo_name=ceo_name, dry_run=dry_run)
        if result.get("error"):
            click.echo(f"[ERROR] {result['error']}")
        else:
            _print_summary("CEO LinkedIn discovery complete", result)
    else:
        exclude_ids: set[int] | None = None
        if not include_manually_closed:
            exclude_ids = _get_manually_closed_ids(db, operator) or None

        click.echo(f"{mode}[INFO] Discovering CEO LinkedIn for all companies...")
        result = ceo_discovery.discover_all(
            limit=limit,
            max_workers=max_workers,
            dry_run=dry_run,
            exclude_company_ids=exclude_ids,
        )
        _print_summary("CEO LinkedIn discovery complete", result)

    db.close()
