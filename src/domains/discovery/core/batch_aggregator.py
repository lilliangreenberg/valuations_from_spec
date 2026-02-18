"""Batch discovery result aggregation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BatchDiscoveryStats:
    """Statistics for a batch discovery operation."""

    total_companies: int = 0
    processed: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    total_links_found: int = 0
    total_blogs_found: int = 0
    total_logos_extracted: int = 0
    errors: list[str] = field(default_factory=list)
    platform_counts: dict[str, int] = field(default_factory=dict)

    def record_company_result(
        self,
        links_count: int,
        blogs_count: int,
        logo_extracted: bool,
        platforms: list[str],
    ) -> None:
        """Record results for a single company."""
        self.processed += 1
        self.successful += 1
        self.total_links_found += links_count
        self.total_blogs_found += blogs_count
        if logo_extracted:
            self.total_logos_extracted += 1
        for platform in platforms:
            self.platform_counts[platform] = self.platform_counts.get(platform, 0) + 1

    def record_failure(self, company_name: str, error: str) -> None:
        """Record a failed company."""
        self.processed += 1
        self.failed += 1
        self.errors.append(f"{company_name}: {error}")

    def record_skip(self) -> None:
        """Record a skipped company."""
        self.processed += 1
        self.skipped += 1

    def summary(self) -> dict[str, object]:
        """Return summary dict."""
        return {
            "total_companies": self.total_companies,
            "processed": self.processed,
            "successful": self.successful,
            "failed": self.failed,
            "skipped": self.skipped,
            "total_links_found": self.total_links_found,
            "total_blogs_found": self.total_blogs_found,
            "total_logos_extracted": self.total_logos_extracted,
            "platform_counts": self.platform_counts,
            "errors": self.errors,
        }
