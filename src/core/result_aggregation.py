"""Batch result aggregation functions."""

from __future__ import annotations

from typing import Any


def aggregate_batch_results(
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate multiple batch result dicts into a summary.

    Each result dict has: processed, successful, failed, skipped, errors.
    """
    total_processed = 0
    total_successful = 0
    total_failed = 0
    total_skipped = 0
    all_errors: list[str] = []

    for result in results:
        total_processed += result.get("processed", 0)
        total_successful += result.get("successful", 0)
        total_failed += result.get("failed", 0)
        total_skipped += result.get("skipped", 0)
        all_errors.extend(result.get("errors", []))

    return {
        "processed": total_processed,
        "successful": total_successful,
        "failed": total_failed,
        "skipped": total_skipped,
        "errors": all_errors,
    }


def format_batch_summary(stats: dict[str, Any]) -> str:
    """Format batch statistics as a human-readable summary string."""
    lines = [
        f"[SUMMARY] Processed: {stats.get('processed', 0)}",
        f"  Successful: {stats.get('successful', 0)}",
        f"  Failed: {stats.get('failed', 0)}",
        f"  Skipped: {stats.get('skipped', 0)}",
    ]

    errors = stats.get("errors", [])
    if errors:
        lines.append(f"  Errors ({len(errors)}):")
        for error in errors[:10]:
            lines.append(f"    - {error}")
        if len(errors) > 10:
            lines.append(f"    ... and {len(errors) - 10} more")

    return "\n".join(lines)
