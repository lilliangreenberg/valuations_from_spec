"""Shared test fixtures for the Portfolio Company Monitoring System."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from src.services.database import Database

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> str:
    """Provide a temporary database file path."""
    return str(tmp_path / "test.db")


@pytest.fixture
def db(tmp_db_path: str) -> Database:
    """Provide an initialized temporary database."""
    database = Database(db_path=tmp_db_path)
    database.init_db()
    return database


@pytest.fixture
def db_with_company(db: Database) -> tuple[Database, int]:
    """Provide a database with a single test company inserted. Returns (db, company_id)."""
    now = datetime.now(UTC).isoformat()
    cursor = db.execute(
        """INSERT INTO companies
           (name, homepage_url, source_sheet, flagged_for_review, created_at, updated_at)
           VALUES (?, ?, ?, 0, ?, ?)""",
        ("Test Corp", "https://testcorp.com", "Online Presence", now, now),
    )
    db.connection.commit()
    company_id = cursor.lastrowid or 0
    return db, company_id


@pytest.fixture
def sample_company_data() -> dict[str, Any]:
    """Sample company data for testing."""
    return {
        "name": "Acme Corp",
        "homepage_url": "https://acme.com",
        "source_sheet": "Online Presence",
    }


@pytest.fixture
def sample_snapshot_data() -> dict[str, Any]:
    """Sample snapshot data for testing."""
    return {
        "company_id": 1,
        "url": "https://acme.com",
        "content_markdown": "# Acme Corp\n\nWelcome to Acme Corp.",
        "content_html": "<h1>Acme Corp</h1><p>Welcome to Acme Corp.</p>",
        "status_code": 200,
        "captured_at": datetime.now(UTC).isoformat(),
        "has_paywall": False,
        "has_auth_required": False,
        "error_message": None,
        "content_checksum": "d41d8cd98f00b204e9800998ecf8427e",
        "http_last_modified": None,
        "capture_metadata": None,
    }


@pytest.fixture
def sample_html_with_social_links() -> str:
    """HTML content with social media links in various locations."""
    return """<!DOCTYPE html>
<html>
<head>
    <meta property="og:url" content="https://acme.com">
    <meta name="twitter:site" content="@acmecorp">
    <script type="application/ld+json">
    {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "Acme Corp",
        "sameAs": [
            "https://www.linkedin.com/company/acme-corp",
            "https://github.com/acme-corp"
        ]
    }
    </script>
</head>
<body>
    <header>
        <nav>
            <a href="https://acme.com">Home</a>
        </nav>
    </header>
    <main>
        <h1>Welcome to Acme Corp</h1>
        <p>We build things. Check us on <a href="https://www.youtube.com/@acmecorp">YouTube</a>.</p>
    </main>
    <footer>
        <a href="https://twitter.com/acmecorp">Twitter</a>
        <a href="https://www.facebook.com/acmecorp">Facebook</a>
        <a href="https://www.instagram.com/acmecorp">Instagram</a>
        <a href="https://blog.acme.com/2024/01/hello">Blog</a>
        <a aria-label="LinkedIn" href="https://linkedin.com/company/acme">LinkedIn</a>
        <p>Copyright 2025 Acme Corp. All rights reserved.</p>
    </footer>
</body>
</html>"""


@pytest.fixture
def sample_markdown_with_links() -> str:
    """Markdown content with social media links."""
    return """# Acme Corp

Welcome to Acme Corp. We build amazing things.

Follow us on [Twitter](https://twitter.com/acmecorp) and [LinkedIn](https://linkedin.com/company/acme-corp).

Check out our [GitHub](https://github.com/acme-corp) for open source projects.

Visit https://www.youtube.com/@acmecorp for video content.
"""
