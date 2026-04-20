"""Company status analysis service.

Collects signals from multiple sources (snapshot content, social media
activity, news articles, leadership change events) and hands them to the
pure determine_status rules engine. A veto path allows definitive news
events (e.g., confirmed bankruptcy or shutdown) to force LIKELY_CLOSED
regardless of other signals.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from src.core.data_access import parse_datetime
from src.domains.monitoring.core.social_content_analysis import (
    check_posting_inactivity,
)
from src.domains.monitoring.core.status_rules import (
    CompanyStatusType,
    SignalType,
    analyze_snapshot_status,
    calculate_confidence,
    determine_status,
)
from src.utils.progress import ProgressTracker

if TYPE_CHECKING:
    from src.domains.leadership.repositories.leadership_change_repository import (
        LeadershipChangeRepository,
    )
    from src.domains.monitoring.repositories.company_status_repository import (
        CompanyStatusRepository,
    )
    from src.domains.monitoring.repositories.snapshot_repository import SnapshotRepository
    from src.domains.monitoring.repositories.social_snapshot_repository import (
        SocialSnapshotRepository,
    )
    from src.domains.news.repositories.news_article_repository import (
        NewsArticleRepository,
    )
    from src.repositories.company_repository import CompanyRepository

logger = structlog.get_logger(__name__)


# News keyword categories that justify a status veto to LIKELY_CLOSED
# when present in a significant-negative article with high confidence.
# Drawn from NEGATIVE_KEYWORDS in significance_analysis.py.
_NEWS_VETO_CATEGORIES: frozenset[str] = frozenset(
    {
        "closure",
        "financial_distress",
        "acquisition",
    }
)

# Minimum confidence on a significant-negative news article required to
# trigger the veto path. Lower confidence articles still contribute as
# normal negative indicators but do not veto the weighted decision.
_NEWS_VETO_MIN_CONFIDENCE: float = 0.75

# Lookback windows for news and leadership signals.
_NEWS_LOOKBACK_DAYS: int = 90
_LEADERSHIP_LOOKBACK_DAYS: int = 90


class StatusAnalyzer:
    """Orchestrates company status analysis from multiple signal sources."""

    def __init__(
        self,
        snapshot_repo: SnapshotRepository,
        status_repo: CompanyStatusRepository,
        company_repo: CompanyRepository,
        social_snapshot_repo: SocialSnapshotRepository | None = None,
        news_repo: NewsArticleRepository | None = None,
        leadership_change_repo: LeadershipChangeRepository | None = None,
    ) -> None:
        self.snapshot_repo = snapshot_repo
        self.status_repo = status_repo
        self.company_repo = company_repo
        self.social_snapshot_repo = social_snapshot_repo
        self.news_repo = news_repo
        self.leadership_change_repo = leadership_change_repo

    # ------------------------------------------------------------------
    # Indicator collectors
    # ------------------------------------------------------------------

    def _collect_social_indicators(self, company_id: int) -> list[tuple[str, str, SignalType]]:
        """Social media inactivity signals."""
        if self.social_snapshot_repo is None:
            return []

        social_snapshots = self.social_snapshot_repo.get_all_sources_for_company(company_id)
        if not social_snapshots:
            return []

        now = datetime.now(UTC)
        indicators: list[tuple[str, str, SignalType]] = []

        for snap in social_snapshots:
            source_type = snap.get("source_type", "unknown")
            post_date = parse_datetime(snap.get("latest_post_date"))

            is_inactive, days = check_posting_inactivity(post_date, reference_date=now)

            if is_inactive:
                value = (
                    f"{days} days since last post" if days is not None else "no posting date found"
                )
                indicators.append(
                    ("social_media_inactive", f"{source_type}: {value}", SignalType.NEGATIVE)
                )
            else:
                value = f"{days} days since last post" if days is not None else "active"
                indicators.append(
                    ("social_media_active", f"{source_type}: {value}", SignalType.POSITIVE)
                )

        return indicators

    def _fetch_news_for_company(
        self,
        company_id: int,
        cache: dict[int, list[dict[str, Any]]] | None,
    ) -> list[dict[str, Any]]:
        """Look up news for a company, preferring a pre-fetched cache."""
        if cache is not None:
            return cache.get(company_id, [])
        if self.news_repo is None:
            return []
        try:
            return self.news_repo.get_recent_significant_news_for_company(
                company_id=company_id,
                days=_NEWS_LOOKBACK_DAYS,
            )
        except Exception as exc:
            logger.warning("news_query_failed", company_id=company_id, error=str(exc))
            return []

    def _collect_news_indicators(
        self,
        company_id: int,
        news_cache: dict[int, list[dict[str, Any]]] | None = None,
    ) -> list[tuple[str, str, SignalType]]:
        """Recent significant news signals.

        Every significant-negative article contributes a NEGATIVE indicator.
        Every significant-positive article contributes a POSITIVE indicator.
        Mixed/neutral sentiment is ignored here (neither helps nor hurts).
        """
        if self.news_repo is None and news_cache is None:
            return []

        articles = self._fetch_news_for_company(company_id, news_cache)

        indicators: list[tuple[str, str, SignalType]] = []
        for article in articles:
            sentiment = article.get("significance_sentiment") or ""
            title = (article.get("title") or "")[:120]
            source = article.get("source") or "unknown"
            value = f"{source}: {title}"

            if sentiment == "negative":
                indicators.append(("news_negative", value, SignalType.NEGATIVE))
            elif sentiment == "positive":
                indicators.append(("news_positive", value, SignalType.POSITIVE))

        return indicators

    def _check_news_veto(
        self,
        company_id: int,
        news_cache: dict[int, list[dict[str, Any]]] | None = None,
    ) -> tuple[CompanyStatusType | None, str | None]:
        """Return a forced status when a definitive closure event is found.

        A veto fires when a single significant-negative news article exists
        in the lookback window with (a) confidence >= _NEWS_VETO_MIN_CONFIDENCE
        AND (b) at least one matched category in _NEWS_VETO_CATEGORIES.

        Returns (forced_status, reason) or (None, None) if no veto applies.
        """
        if self.news_repo is None and news_cache is None:
            return None, None

        articles = self._fetch_news_for_company(company_id, news_cache)

        for article in articles:
            if (article.get("significance_sentiment") or "") != "negative":
                continue
            confidence = float(article.get("significance_confidence") or 0.0)
            if confidence < _NEWS_VETO_MIN_CONFIDENCE:
                continue

            categories = article.get("matched_categories") or []
            if not isinstance(categories, list):
                categories = []
            matched_veto = set(categories) & _NEWS_VETO_CATEGORIES
            if not matched_veto:
                continue

            title = (article.get("title") or "")[:120]
            source = article.get("source") or "unknown"
            reason = (
                f"news_veto: {source} -- {title} "
                f"[{', '.join(sorted(matched_veto))}, conf={confidence:.2f}]"
            )
            return CompanyStatusType.LIKELY_CLOSED, reason

        return None, None

    def _collect_leadership_indicators(
        self,
        company_id: int,
        leadership_cache: dict[int, list[dict[str, Any]]] | None = None,
    ) -> list[tuple[str, str, SignalType]]:
        """Recent leadership change signals from the event log.

        Critical-severity departures (CEO/founder/CTO/COO) become NEGATIVE
        indicators. New CEO arrivals become POSITIVE. Other notable changes
        contribute no signal because they are too ambiguous.
        """
        if self.leadership_change_repo is None and leadership_cache is None:
            return []

        if leadership_cache is not None:
            events = leadership_cache.get(company_id, [])
        else:
            try:
                events = self.leadership_change_repo.get_changes_for_company(  # type: ignore[union-attr]
                    company_id=company_id,
                    limit=50,
                )
            except Exception as exc:
                logger.warning(
                    "leadership_indicators_query_failed",
                    company_id=company_id,
                    error=str(exc),
                )
                return []

        cutoff = datetime.now(UTC).timestamp() - (_LEADERSHIP_LOOKBACK_DAYS * 86400)
        indicators: list[tuple[str, str, SignalType]] = []

        for event in events:
            detected_at = parse_datetime(event.get("detected_at"))
            if detected_at is None or detected_at.timestamp() < cutoff:
                continue

            change_type = str(event.get("change_type") or "")
            severity = str(event.get("severity") or "")
            person = str(event.get("person_name") or "Unknown")
            title = str(event.get("title") or "")
            value = f"{change_type}: {person} ({title})"

            if severity == "critical" and change_type.endswith("_departure"):
                indicators.append(("leadership_departure", value, SignalType.NEGATIVE))
            elif change_type == "new_ceo":
                indicators.append(("leadership_new_ceo", value, SignalType.POSITIVE))

        return indicators

    def _collect_error_pattern_indicators(
        self, company_id: int
    ) -> list[tuple[str, str, SignalType]]:
        """Persistent snapshot capture failures.

        Looks at the last 5 snapshots. If at least 3 of them have an
        error_message, emits a NEGATIVE signal -- the site is likely
        broken, redirected, or behind auth the scraper can't clear.
        A single flaky snapshot is ignored; this only fires on
        patterns of persistent failure.
        """
        try:
            recent = self.snapshot_repo.get_latest_snapshots(company_id, limit=5)
        except Exception:
            return []

        if len(recent) < 3:
            return []

        errored = [s for s in recent if (s.get("error_message") or "").strip()]
        if len(errored) < 3:
            return []

        # Summarize the most recent error so the UI can show why.
        latest_error = (errored[0].get("error_message") or "")[:120]
        value = f"{len(errored)}/{len(recent)} recent snapshots failed: {latest_error}"
        return [("error_pattern", value, SignalType.NEGATIVE)]

    def _collect_baseline_drift_indicators(
        self, company_id: int
    ) -> list[tuple[str, str, SignalType]]:
        """Sentiment drift between the first-ever snapshot and the latest.

        If the original baseline classification was positive-significant
        and the latest content-level significance has flipped to negative,
        flag it as a NEUTRAL context indicator (not strongly negative,
        because the drift could be market cycle or a single event).
        """
        try:
            oldest = self.snapshot_repo.get_latest_snapshots(company_id, limit=50)
        except Exception:
            return []

        if len(oldest) < 2:
            return []

        baseline = oldest[-1]  # oldest in the window
        latest = oldest[0]

        base_sentiment = (baseline.get("baseline_sentiment") or "").strip()
        if not base_sentiment or base_sentiment == "neutral":
            return []

        # Use latest snapshot's baseline sentiment as the comparison point
        # when available; otherwise no drift can be computed.
        latest_sentiment = (latest.get("baseline_sentiment") or "").strip()
        if not latest_sentiment or latest_sentiment == base_sentiment:
            return []

        if base_sentiment == "positive" and latest_sentiment == "negative":
            return [
                (
                    "baseline_drift",
                    "sentiment flipped positive -> negative since first snapshot",
                    SignalType.NEUTRAL,
                )
            ]
        return []

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def _resolve_previous_status(self, company_id: int) -> CompanyStatusType | None:
        """Look up the company's latest stored status for preservation logic."""
        prev = self.status_repo.get_latest_status(company_id)
        if not prev or prev.get("is_manual_override"):
            return None
        raw = prev.get("status")
        if raw in {s.value for s in CompanyStatusType}:
            return CompanyStatusType(raw)
        return None

    def _serialize_indicators(
        self, indicators: list[tuple[str, str, SignalType]]
    ) -> list[dict[str, str]]:
        return [{"type": ind[0], "value": ind[1], "signal": ind[2].value} for ind in indicators]

    def analyze_all_statuses(self) -> dict[str, Any]:
        """Analyze status for all companies with snapshots.

        Returns summary stats.
        """
        companies = self.company_repo.get_all_companies()
        tracker = ProgressTracker(total=len(companies))

        # --- Batch-fetch per-source data once at the start of the run
        # to avoid N+1 queries across hundreds of companies. ---
        news_cache: dict[int, list[dict[str, Any]]] | None = None
        if self.news_repo is not None:
            try:
                news_cache = self.news_repo.get_recent_significant_news_by_company(
                    days=_NEWS_LOOKBACK_DAYS,
                )
            except Exception as exc:
                logger.warning("news_batch_fetch_failed", error=str(exc))
                news_cache = {}

        leadership_cache: dict[int, list[dict[str, Any]]] | None = None
        if self.leadership_change_repo is not None:
            try:
                leadership_cache = self.leadership_change_repo.get_recent_changes_by_company(
                    days=_LEADERSHIP_LOOKBACK_DAYS,
                )
            except Exception as exc:
                logger.warning("leadership_batch_fetch_failed", error=str(exc))
                leadership_cache = {}

        for company in companies:
            company_id = company["id"]
            try:
                if self.status_repo.has_manual_override(company_id):
                    logger.info(
                        "status_analysis_skipped_manual_override",
                        company_id=company_id,
                        company_name=company.get("name", ""),
                    )
                    tracker.record_skip()
                    continue

                snapshots = self.snapshot_repo.get_latest_snapshots(company_id, limit=1)
                if not snapshots:
                    tracker.record_skip()
                    continue

                snapshot = snapshots[0]
                content = snapshot.get("content_markdown") or ""
                if not content:
                    tracker.record_skip()
                    continue

                http_last_modified = parse_datetime(snapshot.get("http_last_modified"))
                previous_status = self._resolve_previous_status(company_id)

                # --- Indicator collection (modular sources) ---
                snapshot_status, snapshot_confidence, snapshot_indicators = analyze_snapshot_status(
                    content, http_last_modified, previous_status
                )

                indicators: list[tuple[str, str, SignalType]] = list(snapshot_indicators)
                indicators += self._collect_social_indicators(company_id)
                indicators += self._collect_news_indicators(company_id, news_cache)
                indicators += self._collect_leadership_indicators(company_id, leadership_cache)
                indicators += self._collect_error_pattern_indicators(company_id)
                indicators += self._collect_baseline_drift_indicators(company_id)

                now = datetime.now(UTC).isoformat()

                # --- Veto path: a definitive closure signal from news
                # overrides the weighted calculation. ---
                forced_status, veto_reason = self._check_news_veto(company_id, news_cache)
                if forced_status is not None:
                    logger.warning(
                        "status_vetoed_by_news",
                        company_id=company_id,
                        forced_status=forced_status.value,
                        reason=veto_reason,
                    )
                    self.status_repo.store_status(
                        {
                            "company_id": company_id,
                            "status": forced_status.value,
                            "confidence": 0.95,
                            "indicators": self._serialize_indicators(indicators),
                            "last_checked": now,
                            "http_last_modified": snapshot.get("http_last_modified"),
                            "status_reason": veto_reason,
                        }
                    )
                    tracker.record_success()
                    tracker.log_progress(every_n=10)
                    continue

                # --- Normal weighted decision ---
                confidence = calculate_confidence(indicators)
                status = determine_status(confidence, indicators, previous_status)

                # Fall back to snapshot-only confidence when no extra
                # indicators were collected, so behavior matches the
                # single-source path exactly.
                if len(indicators) == len(snapshot_indicators):
                    status = snapshot_status
                    confidence = snapshot_confidence

                self.status_repo.store_status(
                    {
                        "company_id": company_id,
                        "status": status.value,
                        "confidence": confidence,
                        "indicators": self._serialize_indicators(indicators),
                        "last_checked": now,
                        "http_last_modified": snapshot.get("http_last_modified"),
                    }
                )

                tracker.record_success()
            except Exception as exc:
                logger.error(
                    "status_analysis_failed",
                    company_id=company_id,
                    error=str(exc),
                )
                tracker.record_failure(f"Company {company_id}: {exc}")

            tracker.log_progress(every_n=10)

        return tracker.summary()
