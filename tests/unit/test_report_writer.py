"""Unit tests for report writer utility."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.utils.report_writer import write_report

if TYPE_CHECKING:
    from pathlib import Path


class TestWriteReport:
    """Tests for write_report."""

    def test_writes_valid_json(self, tmp_path: Path) -> None:
        report = {
            "command": "capture-snapshots",
            "timestamp": "2026-03-10T14:32:18Z",
            "summary": {"processed": 10},
        }

        filepath = write_report(report, reports_dir=tmp_path)

        assert filepath.exists()
        content = json.loads(filepath.read_text(encoding="utf-8"))
        assert content["command"] == "capture-snapshots"
        assert content["summary"]["processed"] == 10

    def test_filename_format(self, tmp_path: Path) -> None:
        report = {
            "command": "detect-changes",
            "timestamp": "2026-03-10T14:45:03Z",
        }

        filepath = write_report(report, reports_dir=tmp_path)

        assert filepath.name == "detect-changes_2026-03-10T14-45-03Z.json"

    def test_creates_directory(self, tmp_path: Path) -> None:
        nested_dir = tmp_path / "nested" / "reports"
        report = {"command": "test", "timestamp": "2026-01-01T00:00:00Z"}

        filepath = write_report(report, reports_dir=nested_dir)

        assert filepath.exists()
        assert nested_dir.exists()

    def test_handles_unicode(self, tmp_path: Path) -> None:
        report = {
            "command": "test",
            "timestamp": "2026-01-01T00:00:00Z",
            "data": {"name": "Acme GmbH"},
        }

        filepath = write_report(report, reports_dir=tmp_path)

        content = filepath.read_text(encoding="utf-8")
        assert "Acme GmbH" in content  # Not escaped
