"""Cross-domain aggregation queries for dashboard views."""

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from src.services.database import Database

logger = structlog.get_logger(__name__)


class QueryService:
    """Aggregation queries spanning multiple tables for dashboard views."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get_overview_stats(self) -> dict[str, Any]:
        """Summary statistics for the overview page."""
        row = self.db.fetchone("""
            SELECT
                (SELECT COUNT(*) FROM companies) as total_companies,
                (SELECT COUNT(*) FROM companies WHERE homepage_url IS NOT NULL)
                    as companies_with_homepage,
                (SELECT COUNT(*) FROM snapshots) as total_snapshots,
                (SELECT MAX(captured_at) FROM snapshots) as last_scan_date,
                (SELECT COUNT(*) FROM change_records
                 WHERE has_changed = 1
                 AND detected_at >= datetime('now', '-30 days')) as recent_changes,
                (SELECT COUNT(*) FROM change_records
                 WHERE significance_classification = 'significant'
                 AND detected_at >= datetime('now', '-30 days')) as significant_changes,
                (SELECT COUNT(*) FROM social_media_links) as total_social_links,
                (SELECT COUNT(*) FROM news_articles) as total_news,
                (SELECT COUNT(*) FROM company_leadership WHERE is_current = 1)
                    as total_leadership
        """)

        stats: dict[str, Any] = dict(row) if row else {}

        # Status breakdown
        status_rows = self.db.fetchall("""
            SELECT cs.status, COUNT(DISTINCT cs.company_id) as count
            FROM company_statuses cs
            INNER JOIN (
                SELECT company_id, MAX(last_checked) as max_checked
                FROM company_statuses
                GROUP BY company_id
            ) latest ON cs.company_id = latest.company_id
                AND cs.last_checked = latest.max_checked
            GROUP BY cs.status
        """)
        stats["status_counts"] = {row["status"]: row["count"] for row in status_rows}

        return stats

    def get_activity_feed(self, limit: int = 30, offset: int = 0) -> list[dict[str, Any]]:
        """Recent activity across all domains, merged and sorted by date."""
        rows = self.db.fetchall(
            """
            SELECT * FROM (
                SELECT
                    'change' as event_type,
                    cr.detected_at as event_date,
                    c.name as company_name,
                    c.id as company_id,
                    cr.significance_classification as classification,
                    cr.significance_sentiment as sentiment,
                    cr.change_magnitude as magnitude,
                    cr.matched_keywords as detail_json,
                    NULL as title
                FROM change_records cr
                JOIN companies c ON cr.company_id = c.id
                WHERE cr.has_changed = 1
                AND cr.significance_classification = 'significant'

                UNION ALL

                SELECT
                    'news' as event_type,
                    na.published_at as event_date,
                    c.name as company_name,
                    c.id as company_id,
                    na.significance_classification as classification,
                    na.significance_sentiment as sentiment,
                    NULL as magnitude,
                    na.matched_keywords as detail_json,
                    na.title as title
                FROM news_articles na
                JOIN companies c ON na.company_id = c.id

                UNION ALL

                SELECT
                    'leadership' as event_type,
                    cl.discovered_at as event_date,
                    c.name as company_name,
                    c.id as company_id,
                    NULL as classification,
                    NULL as sentiment,
                    NULL as magnitude,
                    NULL as detail_json,
                    cl.person_name || ' - ' || cl.title as title
                FROM company_leadership cl
                JOIN companies c ON cl.company_id = c.id
                WHERE cl.is_current = 1
            )
            ORDER BY event_date DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )

        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            if item.get("detail_json"):
                try:
                    item["keywords"] = json.loads(item["detail_json"])
                except (json.JSONDecodeError, TypeError):
                    item["keywords"] = []
            else:
                item["keywords"] = []
            del item["detail_json"]
            result.append(item)

        return result

    def get_company_summary(self, company_id: int) -> dict[str, Any] | None:
        """Full company detail with data from all domains."""
        company_row = self.db.fetchone("SELECT * FROM companies WHERE id = ?", (company_id,))
        if not company_row:
            return None

        company = dict(company_row)

        # Latest status
        status_row = self.db.fetchone(
            """SELECT * FROM company_statuses
               WHERE company_id = ?
               ORDER BY id DESC LIMIT 1""",
            (company_id,),
        )
        company["status"] = dict(status_row) if status_row else None

        # Recent changes
        change_rows = self.db.fetchall(
            """SELECT * FROM change_records
               WHERE company_id = ?
               ORDER BY detected_at DESC LIMIT 20""",
            (company_id,),
        )
        company["changes"] = [self._deserialize_json_fields(dict(r)) for r in change_rows]

        # Social media links
        social_rows = self.db.fetchall(
            """SELECT * FROM social_media_links
               WHERE company_id = ?
               ORDER BY platform""",
            (company_id,),
        )
        company["social_links"] = [dict(r) for r in social_rows]

        # News articles
        news_rows = self.db.fetchall(
            """SELECT * FROM news_articles
               WHERE company_id = ?
               ORDER BY published_at DESC LIMIT 20""",
            (company_id,),
        )
        company["news"] = [self._deserialize_json_fields(dict(r)) for r in news_rows]

        # Current leadership
        leader_rows = self.db.fetchall(
            """SELECT * FROM company_leadership
               WHERE company_id = ?
               ORDER BY is_current DESC, title""",
            (company_id,),
        )
        company["leadership"] = [dict(r) for r in leader_rows]

        # Latest snapshot metadata
        snap_row = self.db.fetchone(
            """SELECT id, captured_at, content_checksum, has_paywall,
                      has_auth_required, status_code, error_message,
                      baseline_classification, baseline_sentiment
               FROM snapshots
               WHERE company_id = ?
               ORDER BY captured_at DESC LIMIT 1""",
            (company_id,),
        )
        company["latest_snapshot"] = dict(snap_row) if snap_row else None

        # Snapshot count
        count_row = self.db.fetchone(
            "SELECT COUNT(*) as cnt FROM snapshots WHERE company_id = ?",
            (company_id,),
        )
        company["snapshot_count"] = count_row["cnt"] if count_row else 0

        return company

    def get_companies_list(
        self,
        search: str | None = None,
        status_filter: str | None = None,
        source_sheet_filter: str | None = None,
        has_changes: bool | None = None,
        flagged: bool | None = None,
        freshness: str | None = None,
        manual_override: str | None = None,
        sort_by: str = "name",
        sort_order: str = "asc",
        page: int = 1,
        per_page: int = 50,
    ) -> dict[str, Any]:
        """Paginated, filterable, sortable company list."""
        allowed_sorts = {
            "name": "c.name",
            "status": "COALESCE(cs.status, 'unknown')",
            "last_change": "last_change_date",
            "social_count": "social_count",
            "news_count": "news_count",
        }
        order_col = allowed_sorts.get(sort_by, "c.name")
        order_dir = "DESC" if sort_order == "desc" else "ASC"

        # Build WHERE clauses
        conditions: list[str] = []
        params: list[Any] = []

        if search:
            conditions.append("c.name LIKE ?")
            params.append(f"%{search}%")

        if status_filter:
            conditions.append("cs.status = ?")
            params.append(status_filter)

        if source_sheet_filter:
            conditions.append("c.source_sheet = ?")
            params.append(source_sheet_filter)

        if flagged is True:
            conditions.append("c.flagged_for_review = 1")
        elif flagged is False:
            conditions.append("c.flagged_for_review = 0")

        if has_changes is True:
            conditions.append("last_change_date IS NOT NULL")
        elif has_changes is False:
            conditions.append("last_change_date IS NULL")

        not_manually_closed = (
            "(cs.status IS NULL OR NOT (cs.status = 'likely_closed' AND cs.is_manual_override = 1))"
        )
        freshness_thresholds = {
            "fresh": (f"ls.last_snapshot >= datetime('now', '-7 days') AND {not_manually_closed}"),
            "recent": (
                "ls.last_snapshot >= datetime('now', '-30 days') "
                f"AND ls.last_snapshot < datetime('now', '-7 days') AND {not_manually_closed}"
            ),
            "stale": (
                "ls.last_snapshot >= datetime('now', '-90 days') "
                f"AND ls.last_snapshot < datetime('now', '-30 days') AND {not_manually_closed}"
            ),
            "very_stale": (
                f"ls.last_snapshot < datetime('now', '-90 days') AND {not_manually_closed}"
            ),
            "never": f"ls.last_snapshot IS NULL AND {not_manually_closed}",
            "manually_closed": ("cs.status = 'likely_closed' AND cs.is_manual_override = 1"),
        }
        if freshness and freshness in freshness_thresholds:
            conditions.append(freshness_thresholds[freshness])

        if manual_override == "yes":
            conditions.append("cs.is_manual_override = 1")
        elif manual_override == "no":
            conditions.append("COALESCE(cs.is_manual_override, 0) = 0")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Count total
        count_sql = f"""
            SELECT COUNT(*) as cnt FROM (
                SELECT c.id
                FROM companies c
                LEFT JOIN (
                    SELECT company_id, status, is_manual_override
                    FROM company_statuses
                    WHERE id IN (
                        SELECT MAX(id) FROM company_statuses GROUP BY company_id
                    )
                ) cs ON c.id = cs.company_id
                LEFT JOIN (
                    SELECT company_id, MAX(detected_at) as last_change_date
                    FROM change_records WHERE has_changed = 1
                    GROUP BY company_id
                ) lc ON c.id = lc.company_id
                LEFT JOIN (
                    SELECT company_id, MAX(captured_at) as last_snapshot
                    FROM snapshots
                    GROUP BY company_id
                ) ls ON c.id = ls.company_id
                WHERE {where_clause}
            )
        """
        count_row = self.db.fetchone(count_sql, tuple(params))
        total = count_row["cnt"] if count_row else 0
        total_pages = max(1, math.ceil(total / per_page))
        offset = (page - 1) * per_page

        # Fetch page
        data_sql = f"""
            SELECT
                c.id, c.name, c.homepage_url, c.source_sheet,
                c.flagged_for_review, c.flag_reason,
                COALESCE(cs.status, 'unknown') as status,
                COALESCE(cs.is_manual_override, 0) as is_manual_override,
                lc.last_change_date,
                ls.last_snapshot,
                COALESCE(sc.social_count, 0) as social_count,
                COALESCE(nc.news_count, 0) as news_count
            FROM companies c
            LEFT JOIN (
                SELECT company_id, status, is_manual_override
                FROM company_statuses
                WHERE id IN (
                    SELECT MAX(id) FROM company_statuses GROUP BY company_id
                )
            ) cs ON c.id = cs.company_id
            LEFT JOIN (
                SELECT company_id, MAX(detected_at) as last_change_date
                FROM change_records WHERE has_changed = 1
                GROUP BY company_id
            ) lc ON c.id = lc.company_id
            LEFT JOIN (
                SELECT company_id, MAX(captured_at) as last_snapshot
                FROM snapshots
                GROUP BY company_id
            ) ls ON c.id = ls.company_id
            LEFT JOIN (
                SELECT company_id, COUNT(*) as social_count
                FROM social_media_links
                GROUP BY company_id
            ) sc ON c.id = sc.company_id
            LEFT JOIN (
                SELECT company_id, COUNT(*) as news_count
                FROM news_articles
                GROUP BY company_id
            ) nc ON c.id = nc.company_id
            WHERE {where_clause}
            ORDER BY {order_col} {order_dir}
            LIMIT ? OFFSET ?
        """
        data_params = [*params, per_page, offset]
        rows = self.db.fetchall(data_sql, tuple(data_params))

        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }

    def get_source_sheets(self) -> list[str]:
        """Distinct source_sheet values for filter dropdowns."""
        rows = self.db.fetchall("SELECT DISTINCT source_sheet FROM companies ORDER BY source_sheet")
        return [row["source_sheet"] for row in rows]

    def get_changes_filtered(
        self,
        classification: str | None = None,
        sentiment: str | None = None,
        min_confidence: float = 0.0,
        days: int = 180,
        page: int = 1,
        per_page: int = 50,
    ) -> dict[str, Any]:
        """Paginated changes view grouped by company.

        Returns company groups with nested change records instead of
        a flat list. Total reflects distinct companies with changes.
        """
        conditions: list[str] = [
            "cr.has_changed = 1",
            "cr.detected_at >= datetime('now', ?)",
        ]
        params: list[Any] = [f"-{days} days"]

        if classification:
            conditions.append("cr.significance_classification = ?")
            params.append(classification)

        if sentiment:
            conditions.append("cr.significance_sentiment = ?")
            params.append(sentiment)

        if min_confidence > 0:
            conditions.append("COALESCE(cr.significance_confidence, 0) >= ?")
            params.append(min_confidence)

        where_clause = " AND ".join(conditions)

        # Count distinct companies with matching changes
        count_row = self.db.fetchone(
            "SELECT COUNT(DISTINCT cr.company_id) as cnt "
            f"FROM change_records cr WHERE {where_clause}",
            tuple(params),
        )
        total = count_row["cnt"] if count_row else 0
        total_pages = max(1, math.ceil(total / per_page))
        offset = (page - 1) * per_page

        # Fetch paginated company groups
        company_rows = self.db.fetchall(
            f"""SELECT cr.company_id, c.name as company_name, c.notes as company_notes,
                       COALESCE(cs.status, 'unknown') as company_status,
                       COALESCE(cs.is_manual_override, 0) as company_status_manual,
                       MAX(cr.detected_at) as latest_change,
                       COUNT(*) as change_count
                FROM change_records cr
                JOIN companies c ON cr.company_id = c.id
                LEFT JOIN (
                    SELECT company_id, status, is_manual_override
                    FROM company_statuses
                    WHERE id IN (SELECT MAX(id) FROM company_statuses GROUP BY company_id)
                ) cs ON c.id = cs.company_id
                WHERE {where_clause}
                GROUP BY cr.company_id
                ORDER BY latest_change DESC
                LIMIT ? OFFSET ?""",
            (*params, per_page, offset),
        )

        if not company_rows:
            return {
                "items": [],
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": total_pages,
            }

        # Fetch all change records for these companies
        company_ids = [r["company_id"] for r in company_rows]
        placeholders = ",".join("?" * len(company_ids))
        change_rows = self.db.fetchall(
            f"""SELECT cr.*
                FROM change_records cr
                WHERE cr.company_id IN ({placeholders}) AND {where_clause}
                ORDER BY cr.detected_at DESC""",
            (*company_ids, *params),
        )

        # Group changes by company_id
        changes_by_company: dict[int, list[dict[str, Any]]] = {}
        for row in change_rows:
            cid = row["company_id"]
            if cid not in changes_by_company:
                changes_by_company[cid] = []
            changes_by_company[cid].append(self._deserialize_json_fields(dict(row)))

        # Build grouped result
        items: list[dict[str, Any]] = []
        for company in company_rows:
            cid = company["company_id"]
            items.append(
                {
                    "company_id": cid,
                    "company_name": company["company_name"],
                    "company_notes": company["company_notes"],
                    "company_status": company["company_status"],
                    "company_status_manual": company["company_status_manual"],
                    "latest_change": company["latest_change"],
                    "change_count": company["change_count"],
                    "changes": changes_by_company.get(cid, []),
                }
            )

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }

    def get_news_filtered(
        self,
        classification: str | None = None,
        sentiment: str | None = None,
        days: int = 180,
        page: int = 1,
        per_page: int = 50,
    ) -> dict[str, Any]:
        """Paginated news view with filters."""
        conditions: list[str] = ["na.published_at >= datetime('now', ?)"]
        params: list[Any] = [f"-{days} days"]

        if classification:
            conditions.append("na.significance_classification = ?")
            params.append(classification)

        if sentiment:
            conditions.append("na.significance_sentiment = ?")
            params.append(sentiment)

        where_clause = " AND ".join(conditions)

        count_row = self.db.fetchone(
            f"SELECT COUNT(*) as cnt FROM news_articles na WHERE {where_clause}",
            tuple(params),
        )
        total = count_row["cnt"] if count_row else 0
        total_pages = max(1, math.ceil(total / per_page))
        offset = (page - 1) * per_page

        rows = self.db.fetchall(
            f"""SELECT na.*, c.name as company_name
                FROM news_articles na
                JOIN companies c ON na.company_id = c.id
                WHERE {where_clause}
                ORDER BY na.published_at DESC
                LIMIT ? OFFSET ?""",
            (*params, per_page, offset),
        )

        return {
            "items": [self._deserialize_json_fields(dict(r)) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }

    def get_leadership_overview(
        self,
        current_only: bool = True,
        page: int = 1,
        per_page: int = 50,
    ) -> dict[str, Any]:
        """Paginated leadership view."""
        current_filter = "AND cl.is_current = 1" if current_only else ""

        count_row = self.db.fetchone(
            f"SELECT COUNT(*) as cnt FROM company_leadership cl WHERE 1=1 {current_filter}"
        )
        total = count_row["cnt"] if count_row else 0
        total_pages = max(1, math.ceil(total / per_page))
        offset = (page - 1) * per_page

        rows = self.db.fetchall(
            f"""SELECT cl.*, c.name as company_name,
                    ls.captured_at as last_snapshot_at,
                    ls.vision_data_json as latest_vision_data
                FROM company_leadership cl
                JOIN companies c ON cl.company_id = c.id
                LEFT JOIN (
                    SELECT linkedin_url, company_id, captured_at, vision_data_json,
                        ROW_NUMBER() OVER (
                            PARTITION BY linkedin_url ORDER BY captured_at DESC
                        ) as rn
                    FROM linkedin_snapshots
                    WHERE url_type = 'person'
                ) ls ON ls.linkedin_url = cl.linkedin_profile_url
                    AND ls.company_id = cl.company_id AND ls.rn = 1
                WHERE 1=1 {current_filter}
                ORDER BY c.name, cl.title
                LIMIT ? OFFSET ?""",
            (per_page, offset),
        )

        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        }

    # -- Widget-specific query methods --

    def get_changes_since_last_scan(self) -> dict[str, Any]:
        """Data for the 'Changes Since Last Check' widget.

        Finds the two most recent distinct scan dates and counts changes
        detected since the previous scan.
        """
        # Get the two most recent distinct captured_at dates
        date_rows = self.db.fetchall("""
            SELECT DISTINCT DATE(captured_at) as scan_date
            FROM snapshots
            ORDER BY scan_date DESC
            LIMIT 2
        """)

        if len(date_rows) < 2:
            return {
                "total_changes": 0,
                "scan_date": date_rows[0]["scan_date"] if date_rows else None,
                "by_magnitude": {"minor": 0, "moderate": 0, "major": 0},
                "by_significance": {"significant": 0, "insignificant": 0, "uncertain": 0},
            }

        current_scan = date_rows[0]["scan_date"]
        previous_scan = date_rows[1]["scan_date"]

        # Count distinct COMPANIES with changes (not individual records)
        total_row = self.db.fetchone(
            """SELECT COUNT(DISTINCT company_id) as cnt FROM change_records
               WHERE has_changed = 1 AND DATE(detected_at) >= ?""",
            (previous_scan,),
        )
        total_companies_changed = total_row["cnt"] if total_row else 0

        # Breakdown by magnitude (distinct companies per magnitude)
        # Use the highest magnitude per company (major > moderate > minor)
        mag_rows = self.db.fetchall(
            """SELECT mag, COUNT(*) as cnt FROM (
                   SELECT company_id,
                       CASE
                           WHEN SUM(
                               CASE WHEN LOWER(change_magnitude) = 'major' THEN 1 ELSE 0 END
                           ) > 0 THEN 'major'
                           WHEN SUM(
                               CASE WHEN LOWER(change_magnitude) = 'moderate' THEN 1 ELSE 0 END
                           ) > 0 THEN 'moderate'
                           ELSE 'minor'
                       END as mag
                   FROM change_records
                   WHERE has_changed = 1 AND DATE(detected_at) >= ?
                   GROUP BY company_id
               )
               GROUP BY mag""",
            (previous_scan,),
        )
        by_magnitude = {"minor": 0, "moderate": 0, "major": 0}
        for row in mag_rows:
            if row["mag"] in by_magnitude:
                by_magnitude[row["mag"]] = row["cnt"]

        # Breakdown by significance (distinct companies, highest severity wins)
        sig_rows = self.db.fetchall(
            """SELECT sig, COUNT(*) as cnt FROM (
                   SELECT company_id,
                       CASE
                           WHEN SUM(CASE WHEN LOWER(significance_classification) = 'significant'
                                    THEN 1 ELSE 0 END) > 0
                               THEN 'significant'
                           WHEN SUM(CASE WHEN LOWER(significance_classification) = 'uncertain'
                                    THEN 1 ELSE 0 END) > 0
                               THEN 'uncertain'
                           ELSE 'insignificant'
                       END as sig
                   FROM change_records
                   WHERE has_changed = 1 AND DATE(detected_at) >= ?
                   GROUP BY company_id
               )
               GROUP BY sig""",
            (previous_scan,),
        )
        by_significance = {"significant": 0, "insignificant": 0, "uncertain": 0}
        for row in sig_rows:
            if row["sig"] in by_significance:
                by_significance[row["sig"]] = row["cnt"]

        return {
            "total_changes": total_companies_changed,
            "scan_date": current_scan,
            "by_magnitude": by_magnitude,
            "by_significance": by_significance,
        }

    def get_alerts_summary(self, days: int = 30) -> dict[str, Any]:
        """Data for the 'Alerts Needing Attention' widget."""
        # Significant + negative changes
        neg_row = self.db.fetchone(
            """SELECT COUNT(*) as cnt FROM change_records
               WHERE significance_classification = 'significant'
               AND significance_sentiment = 'negative'
               AND detected_at >= datetime('now', ?)""",
            (f"-{days} days",),
        )
        negative_significant_count = neg_row["cnt"] if neg_row else 0

        # Uncertain changes needing review
        unc_row = self.db.fetchone(
            """SELECT COUNT(*) as cnt FROM change_records
               WHERE significance_classification = 'uncertain'
               AND detected_at >= datetime('now', ?)""",
            (f"-{days} days",),
        )
        uncertain_count = unc_row["cnt"] if unc_row else 0

        # Flagged companies
        flagged_rows = self.db.fetchall(
            """SELECT id, name, flag_reason
               FROM companies
               WHERE flagged_for_review = 1
               ORDER BY name
               LIMIT 5"""
        )
        flagged_companies = [dict(r) for r in flagged_rows]

        total_alerts = negative_significant_count + uncertain_count + len(flagged_companies)

        return {
            "negative_significant_count": negative_significant_count,
            "uncertain_count": uncertain_count,
            "flagged_companies": flagged_companies,
            "total_alerts": total_alerts,
        }

    def get_trending_data(self, weeks: int = 12) -> dict[str, Any]:
        """Data for the 'Investment Trending Graph' widget.

        Returns weekly time series data for the last N weeks.
        """
        labels: list[str] = []
        significant_changes: list[int] = []
        news_articles: list[int] = []
        leadership_discoveries: list[int] = []

        for week_offset in range(weeks - 1, -1, -1):
            start_days = week_offset * 7
            end_days = start_days - 7
            start_param = f"-{start_days} days" if start_days > 0 else "+0 days"
            end_param = f"-{end_days} days" if end_days > 0 else "+0 days"

            # Week label
            label_row = self.db.fetchone("SELECT DATE('now', ?) as d", (start_param,))
            label_date = label_row["d"] if label_row else ""
            # Format as "Mon DD" for readability
            labels.append(label_date[5:] if label_date else "")

            # Significant changes this week
            cr_row = self.db.fetchone(
                """SELECT COUNT(*) as cnt FROM change_records
                   WHERE has_changed = 1
                   AND significance_classification = 'significant'
                   AND detected_at >= datetime('now', ?)
                   AND detected_at < datetime('now', ?)""",
                (start_param, end_param) if end_days > 0 else (start_param, "+1 day"),
            )
            significant_changes.append(cr_row["cnt"] if cr_row else 0)

            # News articles this week
            na_row = self.db.fetchone(
                """SELECT COUNT(*) as cnt FROM news_articles
                   WHERE published_at >= datetime('now', ?)
                   AND published_at < datetime('now', ?)""",
                (start_param, end_param) if end_days > 0 else (start_param, "+1 day"),
            )
            news_articles.append(na_row["cnt"] if na_row else 0)

            # Leadership discoveries this week
            cl_row = self.db.fetchone(
                """SELECT COUNT(*) as cnt FROM company_leadership
                   WHERE discovered_at >= datetime('now', ?)
                   AND discovered_at < datetime('now', ?)""",
                (start_param, end_param) if end_days > 0 else (start_param, "+1 day"),
            )
            leadership_discoveries.append(cl_row["cnt"] if cl_row else 0)

        return {
            "labels": labels,
            "significant_changes": significant_changes,
            "news_articles": news_articles,
            "leadership_discoveries": leadership_discoveries,
        }

    def get_snapshot_freshness(self) -> dict[str, Any]:
        """Data for the 'Snapshot Freshness' widget.

        Classifies each company by how recently it was last scanned.
        Companies manually marked as likely_closed are separated into
        their own tier instead of inflating the regular freshness counts.
        """
        rows = self.db.fetchall("""
            SELECT
                c.id, c.name,
                ls.last_snapshot,
                CASE
                    WHEN cs.status = 'likely_closed' AND cs.is_manual_override = 1
                        THEN 'manually_closed'
                    WHEN ls.last_snapshot IS NULL THEN 'never'
                    WHEN ls.last_snapshot >= datetime('now', '-7 days') THEN 'fresh'
                    WHEN ls.last_snapshot >= datetime('now', '-30 days') THEN 'recent'
                    WHEN ls.last_snapshot >= datetime('now', '-90 days') THEN 'stale'
                    ELSE 'very_stale'
                END as tier
            FROM companies c
            LEFT JOIN (
                SELECT company_id, MAX(captured_at) as last_snapshot
                FROM snapshots
                GROUP BY company_id
            ) ls ON c.id = ls.company_id
            LEFT JOIN (
                SELECT company_id, status, is_manual_override
                FROM company_statuses
                WHERE id IN (
                    SELECT MAX(id) FROM company_statuses GROUP BY company_id
                )
            ) cs ON c.id = cs.company_id
            ORDER BY c.name
        """)

        summary: dict[str, int] = {
            "fresh": 0,
            "recent": 0,
            "stale": 0,
            "very_stale": 0,
            "never_scanned": 0,
            "manually_closed": 0,
        }
        companies_by_tier: dict[str, list[dict[str, Any]]] = {
            "fresh": [],
            "recent": [],
            "stale": [],
            "very_stale": [],
            "never_scanned": [],
            "manually_closed": [],
        }

        for row in rows:
            tier = row["tier"]
            tier_key = "never_scanned" if tier == "never" else tier
            summary[tier_key] = summary.get(tier_key, 0) + 1
            companies_by_tier[tier_key].append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "last_snapshot": row["last_snapshot"],
                }
            )

        return {
            "summary": summary,
            "companies_by_tier": companies_by_tier,
        }

    def get_company_health_grid(self) -> list[dict[str, Any]]:
        """Data for the 'Company Health Grid' widget.

        Returns all companies with their latest status for grid display.
        """
        rows = self.db.fetchall("""
            SELECT
                c.id, c.name,
                COALESCE(cs.status, 'unknown') as status,
                COALESCE(cs.is_manual_override, 0) as is_manual_override,
                cs.confidence,
                cs.indicators,
                cs.status_reason
            FROM companies c
            LEFT JOIN (
                SELECT company_id, status, is_manual_override, confidence,
                       indicators, status_reason
                FROM company_statuses
                WHERE id IN (
                    SELECT MAX(id) FROM company_statuses GROUP BY company_id
                )
            ) cs ON c.id = cs.company_id
            ORDER BY c.name
        """)
        result = []
        for r in rows:
            d = dict(r)
            if d.get("indicators"):
                try:
                    d["indicators"] = json.loads(d["indicators"])
                except (json.JSONDecodeError, TypeError):
                    d["indicators"] = []
            else:
                d["indicators"] = []
            result.append(d)
        return result

    def get_status_news_contradictions(
        self, days: int = 30, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Companies marked operational despite recent significant-negative news.

        The highest-value "risk blindness" query -- catches portfolio
        companies where status analysis hasn't caught up to clear warning
        signals in the news.
        """
        rows = self.db.fetchall(
            """SELECT
                   c.id as company_id,
                   c.name as company_name,
                   c.homepage_url as homepage_url,
                   cs.status as status,
                   cs.confidence as status_confidence,
                   cs.last_checked as status_last_checked,
                   na.title as news_title,
                   na.source as news_source,
                   na.content_url as news_url,
                   na.published_at as news_published_at,
                   na.significance_confidence as news_confidence,
                   na.matched_categories as news_categories
               FROM companies c
               INNER JOIN (
                   SELECT company_id, MAX(id) as max_id
                   FROM company_statuses
                   GROUP BY company_id
               ) latest ON latest.company_id = c.id
               JOIN company_statuses cs ON cs.id = latest.max_id
               JOIN news_articles na ON na.company_id = c.id
               WHERE cs.status = 'operational'
                 AND na.significance_classification = 'significant'
                 AND na.significance_sentiment = 'negative'
                 AND na.published_at >= datetime('now', ?)
               ORDER BY na.published_at DESC
               LIMIT ?""",
            (f"-{days} days", limit),
        )
        results: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            raw_cats = data.get("news_categories") or "[]"
            try:
                data["news_categories"] = json.loads(raw_cats) if raw_cats else []
            except (json.JSONDecodeError, TypeError):
                data["news_categories"] = []
            results.append(data)
        return results

    def get_recent_leadership_departures(
        self, days: int = 90, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Recent critical leadership changes across the portfolio.

        Powers the "Leadership Alerts" dashboard widget. Critical severity
        means CEO / founder / CTO / COO departures.
        """
        rows = self.db.fetchall(
            """SELECT lc.*, c.name AS company_name, c.homepage_url AS homepage_url
               FROM leadership_changes lc
               JOIN companies c ON lc.company_id = c.id
               WHERE lc.severity = 'critical'
                 AND lc.detected_at >= datetime('now', ?)
               ORDER BY lc.detected_at DESC
               LIMIT ?""",
            (f"-{days} days", limit),
        )
        return [dict(row) for row in rows]

    def get_news_sentiment_trend(self, company_id: int, months: int = 12) -> list[dict[str, Any]]:
        """Per-month positive vs negative news counts for one company.

        Feeds a small sparkline on the company detail page and enables
        downstream sentiment-flip detection.
        """
        rows = self.db.fetchall(
            """SELECT
                   strftime('%Y-%m', published_at) AS month,
                   SUM(CASE WHEN significance_sentiment = 'positive' THEN 1 ELSE 0 END)
                       AS positive,
                   SUM(CASE WHEN significance_sentiment = 'negative' THEN 1 ELSE 0 END)
                       AS negative,
                   COUNT(*) AS total
               FROM news_articles
               WHERE company_id = ?
                 AND significance_classification = 'significant'
                 AND published_at >= datetime('now', ?)
               GROUP BY month
               ORDER BY month""",
            (company_id, f"-{months * 30} days"),
        )
        return [dict(row) for row in rows]

    def get_change_frequency_anomalies(
        self, days: int = 90, baseline_days: int = 365
    ) -> list[dict[str, Any]]:
        """Companies with an unusual change-detection rate in the recent window.

        Compares the rate of detected changes in the last `days` days
        against the per-company baseline over the last `baseline_days`
        days. Surfaces both spikes (rebrand / migration) and drops
        (site frozen / abandoned).
        """
        rows = self.db.fetchall(
            """SELECT
                   c.id AS company_id,
                   c.name AS company_name,
                   recent.cnt AS recent_count,
                   baseline.cnt AS baseline_count
               FROM companies c
               LEFT JOIN (
                   SELECT company_id, COUNT(*) AS cnt
                   FROM change_records
                   WHERE has_changed = 1
                     AND detected_at >= datetime('now', ?)
                   GROUP BY company_id
               ) recent ON recent.company_id = c.id
               LEFT JOIN (
                   SELECT company_id, COUNT(*) AS cnt
                   FROM change_records
                   WHERE has_changed = 1
                     AND detected_at >= datetime('now', ?)
                   GROUP BY company_id
               ) baseline ON baseline.company_id = c.id
               WHERE baseline.cnt IS NOT NULL AND baseline.cnt > 0""",
            (f"-{days} days", f"-{baseline_days} days"),
        )

        anomalies: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            recent = float(data.get("recent_count") or 0)
            baseline = float(data.get("baseline_count") or 0)
            if baseline <= 0:
                continue
            # Scale both rates to the same window length for comparison.
            expected = baseline * (days / baseline_days)
            if expected <= 0:
                continue
            ratio = recent / expected
            # Flag spikes (> 2x expected) and droughts (< 0.1x expected)
            if ratio >= 2.0 or ratio <= 0.1:
                data["expected_count"] = round(expected, 2)
                data["ratio"] = round(ratio, 2)
                data["direction"] = "spike" if ratio >= 2.0 else "drought"
                anomalies.append(data)

        anomalies.sort(
            key=lambda d: abs((d.get("ratio") or 1.0) - 1.0),
            reverse=True,
        )
        return anomalies

    def _deserialize_json_fields(self, data: dict[str, Any]) -> dict[str, Any]:
        """Deserialize JSON string fields to Python objects."""
        for field in (
            "matched_keywords",
            "matched_categories",
            "evidence_snippets",
            "match_evidence",
            "indicators",
        ):
            if data.get(field) and isinstance(data[field], str):
                try:
                    data[field] = json.loads(data[field])
                except (json.JSONDecodeError, TypeError):
                    data[field] = []
        return data
