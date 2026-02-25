"""CLI entry point for the Portfolio Company Monitoring System."""

from __future__ import annotations

import click

from src.cli.commands import (
    analyze_baseline,
    analyze_status,
    backfill_significance,
    capture_snapshots,
    check_leadership_changes,
    detect_changes,
    discover_social_batch,
    discover_social_full_site,
    discover_social_media,
    extract_companies,
    extract_leadership,
    extract_leadership_all,
    import_urls,
    list_active,
    list_inactive,
    list_significant_changes,
    list_uncertain_changes,
    refresh_logos,
    search_news,
    search_news_all,
    show_changes,
    show_status,
)


@click.group()
def cli() -> None:
    """Portfolio Company Monitoring System."""


cli.add_command(extract_companies)
cli.add_command(import_urls)
cli.add_command(capture_snapshots)
cli.add_command(detect_changes)
cli.add_command(analyze_status)
cli.add_command(discover_social_media)
cli.add_command(discover_social_full_site)
cli.add_command(discover_social_batch)
cli.add_command(backfill_significance)
cli.add_command(list_significant_changes)
cli.add_command(list_uncertain_changes)
cli.add_command(search_news)
cli.add_command(search_news_all)
cli.add_command(show_changes)
cli.add_command(show_status)
cli.add_command(list_active)
cli.add_command(list_inactive)
cli.add_command(extract_leadership)
cli.add_command(extract_leadership_all)
cli.add_command(check_leadership_changes)
cli.add_command(analyze_baseline)
cli.add_command(refresh_logos)
