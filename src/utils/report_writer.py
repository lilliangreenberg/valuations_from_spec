"""Report writer utility for writing structured JSON reports to disk.

Writes command reports to docs/reports/ with timestamped filenames.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Default report output directory (relative to project root)
_DEFAULT_REPORTS_DIR = "docs/reports"


def write_report(
    report: dict[str, Any],
    reports_dir: str | Path | None = None,
) -> Path:
    """Write a report dict to a JSON file in the reports directory.

    Filename format: {command}_{timestamp}.json
    e.g. capture-snapshots_2026-03-10T14-32-18Z.json

    Args:
        report: The report dict to serialize.
        reports_dir: Override for the output directory. Defaults to docs/reports/.

    Returns:
        Path to the written file.
    """
    output_dir = Path(reports_dir) if reports_dir else Path(_DEFAULT_REPORTS_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    command = report.get("command", "unknown")
    timestamp = report.get("timestamp", "unknown")
    # Replace colons in timestamp for filesystem compatibility
    safe_timestamp = timestamp.replace(":", "-")
    filename = f"{command}_{safe_timestamp}.json"

    filepath = output_dir / filename

    filepath.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    logger.info(
        "report_written",
        command=command,
        path=str(filepath),
    )

    return filepath
