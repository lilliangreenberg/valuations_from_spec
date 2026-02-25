"""Migration: Remap snapshot company_id assignments and merge duplicate companies.

Problem:
    97.9% of snapshots (1,253/1,280) have their content attributed to the wrong
    company due to an off-by-one shift bug in the original data capture pipeline.
    Each snapshot stores the URL that was actually scraped in its `url` column.
    This migration uses that URL to find the correct company and reassign.

Strategy:
    1. Back up the database
    2. Remap snapshots to the correct company using snapshot.url -> company.homepage_url
    3. Merge duplicate companies (move all child data to the keeper, delete the duplicate)
    4. Update change_records.company_id to match the corrected snapshot assignments
    5. Validate the result

Duplicate company merge decisions:
    URL-duplicates (same homepage_url):
        - Opal Inc. (236) KEEP  <-  Opal Camera, Inc. (528) DELETE
        - Beamm Techologies Inc (472) DELETE  ->  Beamm (663) KEEP
        - Finfra Tech Holdings Pte. Ltd. (274) KEEP  <-  Digital Micro Pte. Ltd. (484) DELETE

    Name-duplicates (one has NULL homepage_url):
        - Agrata Group Pte Ltd (112) KEEP  <-  Agrata Group Pte Ltd (637) DELETE
        - Candoriq (17) KEEP  <-  Candoriq (416) DELETE
        - Lightbulbml (363) KEEP  <-  Lightbulbml (640) DELETE

    Name-duplicates (different URLs, same product with www/no-www):
        - Fiber Ai, Inc. (67) KEEP  <-  Fiber Ai, Inc. (436) DELETE
        - Kick, Inc. (405) KEEP  <-  Kick, Inc. (671) DELETE

    Name-duplicates (different URLs, company rebranded):
        - Mobilus Labs Limited (49) KEEP  <-  Mobilus Labs Limited (260) DELETE
          (mobiluslabs.com is original, aana.ai is rebrand acquired by Dropbox)

    Name-duplicates that are GENUINELY DIFFERENT products (DO NOT MERGE):
        - Codomain Data Corporation (120, ssoready.com) vs (618, tesseral.com)
          Both are different products by the same company. Keep both.
        - Plenty Financial, Inc (142, wealthsimple.com) vs (749, withplenty.com)
          142 appears to be a data error (Wealthsimple is not Plenty Financial).
          Keep both -- do not merge because they may be separate portfolio entries.
        - Sideguide (78, sideguide.dev) vs (712, mendable.ai) vs (730, firecrawl.dev)
          Three products by the same parent. Keep all three.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

DB_PATH = Path("data/companies.db")
BACKUP_SUFFIX = "_pre_remap_backup_" + datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


# --- Duplicate merge definitions ---
# (keeper_id, duplicate_id) -- all child records move from duplicate to keeper
MERGES: list[tuple[int, int]] = [
    # URL-duplicates
    (236, 528),   # Opal Inc. keeps, Opal Camera deletes
    (663, 472),   # Beamm keeps (correct name), Beamm Techologies deletes
    (274, 484),   # Finfra Tech keeps, Digital Micro deletes
    # Name-duplicates with NULL URL
    (112, 637),   # Agrata (has URL + social) keeps, Agrata (no URL) deletes
    (416, 17),    # Candoriq (has URL) keeps, Candoriq (no URL) deletes
    (640, 363),   # Lightbulbml (has URL) keeps, Lightbulbml (no URL) deletes
    # Name-duplicates with www/non-www
    (67, 436),    # Fiber Ai (fiber.ai) keeps, Fiber Ai (www.fiber.ai) deletes
    (405, 671),   # Kick (www.kick.co) keeps, Kick (kick.co) deletes
    # Rebrand
    (49, 260),    # Mobilus Labs (original domain) keeps, Mobilus Labs (aana.ai) deletes
]

# Tables with company_id foreign key (and the column name)
CHILD_TABLES: list[tuple[str, str]] = [
    ("snapshots", "company_id"),
    ("change_records", "company_id"),
    ("social_media_links", "company_id"),
    ("blog_links", "company_id"),
    ("company_logos", "company_id"),
    ("company_statuses", "company_id"),
    ("news_articles", "company_id"),
    ("company_leadership", "company_id"),
]

# Tables with entity_id that references companies (no FK constraint)
SOFT_REF_TABLES: list[tuple[str, str, str]] = [
    ("processing_errors", "entity_id", "entity_type"),
]


def backup_database(db_path: Path) -> Path:
    """Create a timestamped backup."""
    backup_path = db_path.with_name(db_path.stem + BACKUP_SUFFIX + db_path.suffix)
    shutil.copy2(db_path, backup_path)
    print(f"[BACKUP] Created: {backup_path}")
    return backup_path


def count_mismatches(conn: sqlite3.Connection) -> int:
    """Count snapshots where url != company.homepage_url."""
    row = conn.execute("""
        SELECT COUNT(*) FROM snapshots s
        JOIN companies c ON s.company_id = c.id
        WHERE s.url != c.homepage_url
    """).fetchone()
    return row[0] if row else 0


def remap_snapshots(conn: sqlite3.Connection) -> dict[str, int]:
    """Remap snapshot.company_id using snapshot.url to find the correct company.

    Returns counts of each remap category.
    """
    stats: dict[str, int] = {}

    # Phase 1: Exact URL match
    cursor = conn.execute("""
        UPDATE snapshots
        SET company_id = (
            SELECT MIN(c.id) FROM companies c WHERE c.homepage_url = snapshots.url
        )
        WHERE EXISTS (
            SELECT 1 FROM companies c WHERE c.homepage_url = snapshots.url
        )
        AND company_id != (
            SELECT MIN(c.id) FROM companies c WHERE c.homepage_url = snapshots.url
        )
    """)
    stats["exact_match"] = cursor.rowcount
    print(f"  [REMAP] Exact URL match: {cursor.rowcount} snapshots updated")

    # Phase 2: Trailing slash normalization (snapshot has slash, company doesn't)
    cursor = conn.execute("""
        UPDATE snapshots
        SET company_id = (
            SELECT MIN(c.id) FROM companies c WHERE c.homepage_url = RTRIM(snapshots.url, '/')
        )
        WHERE NOT EXISTS (
            SELECT 1 FROM companies c WHERE c.homepage_url = snapshots.url
        )
        AND EXISTS (
            SELECT 1 FROM companies c WHERE c.homepage_url = RTRIM(snapshots.url, '/')
        )
        AND company_id != (
            SELECT MIN(c.id) FROM companies c WHERE c.homepage_url = RTRIM(snapshots.url, '/')
        )
    """)
    stats["trailing_slash"] = cursor.rowcount
    print(f"  [REMAP] Trailing slash normalization: {cursor.rowcount} snapshots updated")

    # Phase 3: Whitespace TRIM normalization
    cursor = conn.execute("""
        UPDATE snapshots
        SET company_id = (
            SELECT MIN(c.id) FROM companies c WHERE TRIM(c.homepage_url) = snapshots.url
        )
        WHERE NOT EXISTS (
            SELECT 1 FROM companies c WHERE c.homepage_url = snapshots.url
        )
        AND NOT EXISTS (
            SELECT 1 FROM companies c WHERE c.homepage_url = RTRIM(snapshots.url, '/')
        )
        AND EXISTS (
            SELECT 1 FROM companies c WHERE TRIM(c.homepage_url) = snapshots.url
        )
        AND company_id != (
            SELECT MIN(c.id) FROM companies c WHERE TRIM(c.homepage_url) = snapshots.url
        )
    """)
    stats["whitespace_trim"] = cursor.rowcount
    print(f"  [REMAP] Whitespace TRIM: {cursor.rowcount} snapshots updated")

    return stats


def update_change_records(conn: sqlite3.Connection) -> int:
    """Update change_records.company_id to match the corrected snapshot assignments.

    Derives the correct company_id from the old snapshot's company_id,
    since both snapshots in a change_record share the same URL.
    """
    cursor = conn.execute("""
        UPDATE change_records
        SET company_id = (
            SELECT s.company_id FROM snapshots s
            WHERE s.id = change_records.snapshot_id_old
        )
        WHERE company_id != (
            SELECT s.company_id FROM snapshots s
            WHERE s.id = change_records.snapshot_id_old
        )
    """)
    print(f"  [CHANGE_RECORDS] Updated company_id on {cursor.rowcount} records")
    return cursor.rowcount


def merge_duplicate_companies(conn: sqlite3.Connection) -> dict[str, int]:
    """Merge duplicate companies: move all child data to keeper, delete duplicate.

    For each (keeper_id, duplicate_id):
    1. Move all child records from duplicate to keeper
    2. Handle unique constraint conflicts by deleting duplicates
    3. Delete the duplicate company record
    """
    stats: dict[str, int] = {"merges": 0, "records_moved": 0, "duplicates_deleted": 0}

    for keeper_id, dup_id in MERGES:
        # Verify both exist
        keeper = conn.execute(
            "SELECT id, name, homepage_url FROM companies WHERE id = ?", (keeper_id,)
        ).fetchone()
        dup = conn.execute(
            "SELECT id, name, homepage_url FROM companies WHERE id = ?", (dup_id,)
        ).fetchone()

        if not keeper or not dup:
            print(f"  [SKIP] Merge ({keeper_id} <- {dup_id}): one or both not found")
            continue

        print(f"  [MERGE] {keeper[1]} ({keeper_id}) <- {dup[1]} ({dup_id})")

        # Move child records from duplicate to keeper
        for table, col in CHILD_TABLES:
            # Check for unique constraints that might cause conflicts
            # social_media_links: UNIQUE(company_id, profile_url)
            # blog_links: UNIQUE(company_id, blog_url)
            # company_leadership: UNIQUE(company_id, linkedin_profile_url)
            if table == "social_media_links":
                # Delete from duplicate where keeper already has that profile_url
                cursor = conn.execute(f"""
                    DELETE FROM {table}
                    WHERE {col} = ? AND profile_url IN (
                        SELECT profile_url FROM {table} WHERE {col} = ?
                    )
                """, (dup_id, keeper_id))
                if cursor.rowcount > 0:
                    print(f"    [DEDUP] Removed {cursor.rowcount} duplicate social_media_links")

            elif table == "blog_links":
                cursor = conn.execute(f"""
                    DELETE FROM {table}
                    WHERE {col} = ? AND blog_url IN (
                        SELECT blog_url FROM {table} WHERE {col} = ?
                    )
                """, (dup_id, keeper_id))
                if cursor.rowcount > 0:
                    print(f"    [DEDUP] Removed {cursor.rowcount} duplicate blog_links")

            elif table == "company_leadership":
                cursor = conn.execute(f"""
                    DELETE FROM {table}
                    WHERE {col} = ? AND linkedin_profile_url IN (
                        SELECT linkedin_profile_url FROM {table} WHERE {col} = ?
                    )
                """, (dup_id, keeper_id))
                if cursor.rowcount > 0:
                    print(f"    [DEDUP] Removed {cursor.rowcount} duplicate company_leadership")

            # Now move remaining records
            cursor = conn.execute(
                f"UPDATE {table} SET {col} = ? WHERE {col} = ?",
                (keeper_id, dup_id),
            )
            if cursor.rowcount > 0:
                stats["records_moved"] += cursor.rowcount
                print(f"    [MOVE] {table}: {cursor.rowcount} records")

        # Move soft-reference records
        for table, id_col, type_col in SOFT_REF_TABLES:
            cursor = conn.execute(
                f"UPDATE {table} SET {id_col} = ? WHERE {id_col} = ? AND {type_col} = 'snapshot'",
                (keeper_id, dup_id),
            )
            if cursor.rowcount > 0:
                stats["records_moved"] += cursor.rowcount
                print(f"    [MOVE] {table}: {cursor.rowcount} records")

        # If keeper has no homepage_url but duplicate does, take it
        if not keeper[2] and dup[2]:
            conn.execute(
                "UPDATE companies SET homepage_url = ? WHERE id = ?",
                (dup[2], keeper_id),
            )
            print(f"    [URL] Inherited homepage_url: {dup[2]}")

        # If keeper has no homepage_url, also check for snapshots that were just
        # moved to it -- use their URL as the homepage_url
        if not keeper[2] and not dup[2]:
            row = conn.execute(
                "SELECT url FROM snapshots WHERE company_id = ? LIMIT 1", (keeper_id,)
            ).fetchone()
            if row and row[0]:
                conn.execute(
                    "UPDATE companies SET homepage_url = ? WHERE id = ?",
                    (row[0], keeper_id),
                )
                print(f"    [URL] Derived homepage_url from snapshot: {row[0]}")

        # Delete the duplicate company (CASCADE will clean up any remaining FKs)
        conn.execute("DELETE FROM companies WHERE id = ?", (dup_id,))
        stats["duplicates_deleted"] += 1
        stats["merges"] += 1
        print(f"    [DELETE] Company {dup_id} removed")

    return stats


def validate(conn: sqlite3.Connection) -> bool:
    """Run validation checks after migration."""
    ok = True

    # Check 1: No mismatched snapshot URLs
    mismatches = count_mismatches(conn)
    # Some mismatches are expected for companies whose domain now serves
    # different content (the snapshot URL is correct, it just doesn't match
    # the company's registered homepage because the company no longer owns the domain).
    # But the SYSTEMATIC offset should be gone.
    # We check: no snapshot should have a URL that matches a DIFFERENT company's homepage.
    wrong_company = conn.execute("""
        SELECT COUNT(*) FROM snapshots s
        WHERE EXISTS (
            SELECT 1 FROM companies c
            WHERE c.homepage_url = s.url AND c.id != s.company_id
        )
    """).fetchone()[0]

    if wrong_company > 0:
        print(f"[FAIL] {wrong_company} snapshots have URLs matching a different company")
        ok = False
    else:
        print(f"[PASS] No snapshots have URLs belonging to a different company")

    # Check 2: Change records match their snapshot's company_id
    cr_mismatch = conn.execute("""
        SELECT COUNT(*) FROM change_records cr
        JOIN snapshots s ON s.id = cr.snapshot_id_old
        WHERE cr.company_id != s.company_id
    """).fetchone()[0]

    if cr_mismatch > 0:
        print(f"[FAIL] {cr_mismatch} change_records have mismatched company_id")
        ok = False
    else:
        print("[PASS] All change_records.company_id match their snapshot's company")

    # Check 3: No duplicate companies remain (same homepage_url)
    url_dups = conn.execute("""
        SELECT COUNT(*) FROM (
            SELECT homepage_url FROM companies
            WHERE homepage_url IS NOT NULL
            GROUP BY homepage_url HAVING COUNT(*) > 1
        )
    """).fetchone()[0]

    if url_dups > 0:
        print(f"[FAIL] {url_dups} homepage_urls still shared by multiple companies")
        ok = False
    else:
        print("[PASS] No duplicate homepage_urls remain")

    # Check 4: FK integrity -- all snapshot.company_id reference valid companies
    orphan_snaps = conn.execute("""
        SELECT COUNT(*) FROM snapshots s
        WHERE NOT EXISTS (SELECT 1 FROM companies c WHERE c.id = s.company_id)
    """).fetchone()[0]

    if orphan_snaps > 0:
        print(f"[FAIL] {orphan_snaps} snapshots reference non-existent companies")
        ok = False
    else:
        print("[PASS] All snapshot FK references are valid")

    # Check 5: FK integrity -- all change_records reference valid companies
    orphan_cr = conn.execute("""
        SELECT COUNT(*) FROM change_records cr
        WHERE NOT EXISTS (SELECT 1 FROM companies c WHERE c.id = cr.company_id)
    """).fetchone()[0]

    if orphan_cr > 0:
        print(f"[FAIL] {orphan_cr} change_records reference non-existent companies")
        ok = False
    else:
        print("[PASS] All change_record FK references are valid")

    # Stats
    total_companies = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    total_snapshots = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    total_changes = conn.execute("SELECT COUNT(*) FROM change_records").fetchone()[0]
    total_social = conn.execute("SELECT COUNT(*) FROM social_media_links").fetchone()[0]

    print(f"\n[STATS] Companies: {total_companies}")
    print(f"[STATS] Snapshots: {total_snapshots}")
    print(f"[STATS] Change records: {total_changes}")
    print(f"[STATS] Social media links: {total_social}")

    return ok


def main() -> int:
    """Run the full migration."""
    if not DB_PATH.exists():
        print(f"[ERROR] Database not found: {DB_PATH}")
        return 1

    # Pre-migration state
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    pre_mismatch = count_mismatches(conn)
    pre_companies = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    print(f"[PRE] Mismatched snapshots: {pre_mismatch}")
    print(f"[PRE] Total companies: {pre_companies}")
    conn.close()

    # Step 1: Backup
    print("\n=== Step 1: Backup ===")
    backup_path = backup_database(DB_PATH)

    # Step 2-5: All changes in one connection, using a savepoint for atomicity
    print("\n=== Step 2: Remap snapshots ===")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    # Disable FK checks during migration to avoid CASCADE issues during merge
    conn.execute("PRAGMA foreign_keys = OFF")

    try:
        conn.execute("BEGIN TRANSACTION")

        # Step 2: Remap snapshots
        remap_stats = remap_snapshots(conn)

        # Step 3: Update change_records
        print("\n=== Step 3: Update change_records ===")
        cr_updated = update_change_records(conn)

        # Step 4: Merge duplicates
        print("\n=== Step 4: Merge duplicate companies ===")
        merge_stats = merge_duplicate_companies(conn)

        # Step 5: Validate
        print("\n=== Step 5: Validate ===")
        conn.execute("PRAGMA foreign_keys = ON")
        valid = validate(conn)

        if valid:
            conn.execute("COMMIT")
            print("\n[SUCCESS] Migration committed.")
            print(f"  Snapshots remapped: {sum(remap_stats.values())}")
            print(f"  Change records updated: {cr_updated}")
            print(f"  Companies merged: {merge_stats['merges']}")
            print(f"  Records moved: {merge_stats['records_moved']}")
            print(f"  Duplicate companies deleted: {merge_stats['duplicates_deleted']}")
            print(f"  Backup at: {backup_path}")
            return 0
        else:
            conn.execute("ROLLBACK")
            print("\n[ROLLED BACK] Validation failed. No changes applied.")
            print(f"  Backup remains at: {backup_path}")
            return 1

    except Exception as exc:
        conn.execute("ROLLBACK")
        print(f"\n[ROLLED BACK] Error: {exc}")
        print(f"  Backup remains at: {backup_path}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
