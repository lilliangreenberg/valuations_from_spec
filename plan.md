# Social Media Content Monitoring - Implementation Plan

## Goal
Periodically scrape Medium and blog pages (skip Twitter/LinkedIn per user decision), detect changes over time, and enrich the existing significance analysis + status analysis with social media content signals. A 1-year posting inactivity threshold becomes a negative health signal.

---

## Phase 1: Database & Models

### 1a. New table: `social_media_snapshots`

Add to `src/services/database.py` `init_db()`, following the exact pattern of the `snapshots` table:

```sql
CREATE TABLE IF NOT EXISTS social_media_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    source_url TEXT NOT NULL,          -- the Medium/blog URL being scraped
    source_type TEXT NOT NULL,         -- 'medium' or 'blog'
    content_markdown TEXT,
    content_html TEXT,
    status_code INTEGER,
    captured_at TEXT NOT NULL,
    error_message TEXT,
    content_checksum TEXT,             -- MD5, 32-char hex, lowercase
    latest_post_date TEXT,             -- ISO 8601, extracted from content
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    UNIQUE(company_id, source_url)     -- one active snapshot row per URL per company
);
CREATE INDEX IF NOT EXISTS idx_social_snapshots_company_id ON social_media_snapshots(company_id);
CREATE INDEX IF NOT EXISTS idx_social_snapshots_source_type ON social_media_snapshots(source_type);
```

**Why a separate table instead of reusing `snapshots`:** The `snapshots` table is tightly coupled to homepage URLs throughout the codebase -- `SnapshotRepository`, `ChangeDetector`, `BatchSnapshotManager`, `StatusAnalyzer`, and `show-changes` CLI all assume one snapshot stream per company (homepage). A separate table avoids a discriminator column that would require modifying every existing query.

**Why UNIQUE(company_id, source_url) instead of just storing history:** Social media snapshots are compared snapshot-to-snapshot like homepage snapshots. On each capture run, the old row is kept for diff comparison, then a new row is inserted. The unique constraint prevents accidental double-capture in the same run. For history, we keep old snapshots by removing the unique constraint -- actually, let me reconsider: we need history for change detection. The pattern should match `snapshots`: **no unique constraint on (company_id, source_url)**, just accumulate rows over time, and query the latest 2 for diffing.

**Revised:**
```sql
CREATE TABLE IF NOT EXISTS social_media_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL,         -- 'medium' or 'blog'
    content_markdown TEXT,
    content_html TEXT,
    status_code INTEGER,
    captured_at TEXT NOT NULL,
    error_message TEXT,
    content_checksum TEXT,
    latest_post_date TEXT,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);
```

This matches the `snapshots` table pattern exactly (no unique constraint, accumulate history).

### 1b. New table: `social_media_change_records`

A separate change records table to avoid modifying every existing `change_records` query:

```sql
CREATE TABLE IF NOT EXISTS social_media_change_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    snapshot_id_old INTEGER NOT NULL,
    snapshot_id_new INTEGER NOT NULL,
    checksum_old TEXT NOT NULL,
    checksum_new TEXT NOT NULL,
    has_changed INTEGER NOT NULL,
    change_magnitude TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    significance_classification TEXT,
    significance_sentiment TEXT,
    significance_confidence REAL,
    matched_keywords TEXT,             -- JSON
    matched_categories TEXT,           -- JSON
    significance_notes TEXT,
    evidence_snippets TEXT,            -- JSON
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id_old) REFERENCES social_media_snapshots(id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id_new) REFERENCES social_media_snapshots(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sm_change_records_company_id ON social_media_change_records(company_id);
```

**Why separate from `change_records`:** The existing `change_records` has FK references to `snapshots(id)`. Social media change records reference `social_media_snapshots(id)`. Mixing them would require nullable FKs or a discriminator, complicating all existing queries. The separate table keeps blast radius zero on existing features.

---

## Phase 2: Pure Functions (Core)

All new pure functions go in `src/domains/monitoring/core/social_content_analysis.py`.

### 2a. `extract_latest_post_date(markdown: str) -> str | None`

Extracts the most recent post/article date from scraped blog/Medium content.

**Strategy (ordered by reliability):**
1. ISO 8601 dates: `\d{4}-\d{2}-\d{2}`
2. Common blog formats: "January 15, 2025", "Jan 15, 2025", "15 Jan 2025"
3. Relative dates: "3 days ago", "2 weeks ago" (convert to absolute using a reference date parameter)
4. Return the **most recent** valid date found, or `None` if no dates detected.

**Signature:**
```python
def extract_latest_post_date(
    markdown: str,
    reference_date: datetime | None = None,
) -> datetime | None:
```

Pure function. `reference_date` defaults to `datetime.now(UTC)` at the call site (in the service layer), not inside the pure function itself.

### 2b. `check_posting_inactivity(latest_post_date: datetime | None, threshold_days: int = 365, reference_date: datetime) -> tuple[bool, int | None]`

Returns `(is_inactive, days_since_last_post)`.
- If `latest_post_date is None`: returns `(True, None)` -- no dates found is treated as inactive
- If days since last post > threshold_days: returns `(True, days_since_last_post)`
- Otherwise: returns `(False, days_since_last_post)`

### 2c. `prepare_social_context(social_snapshots: list[dict], max_chars: int = 2000) -> str`

Aggregates social media content into a formatted string for LLM consumption. This is the bridge between social media data and the existing LLM prompt system.

```python
def prepare_social_context(
    social_snapshots: list[dict],
    inactivity_results: list[tuple[str, bool, int | None]],  # (source_url, is_inactive, days)
    max_chars: int = 2000,
) -> str:
```

Output format:
```
--- Social Media Activity ---
Source: https://medium.com/@company (medium)
Last post: 2025-08-15 (198 days ago)
Status: ACTIVE
Content excerpt: [first N chars of markdown, proportionally split across sources]

Source: https://company.com/blog (blog)
Last post: None detected
Status: INACTIVE (no posting date found)
Content excerpt: [...]
---
```

Character budget is split proportionally across sources, capped at `max_chars`.

### 2d. `SOCIAL_MEDIA_EXCLUDED_CATEGORIES`

A new frozenset in `significance_analysis.py`, analogous to `HOMEPAGE_EXCLUDED_CATEGORIES`. Per user requirement, social media self-reports are treated the same as homepage self-reports:

```python
SOCIAL_MEDIA_EXCLUDED_CATEGORIES: frozenset[str] = HOMEPAGE_EXCLUDED_CATEGORIES
```

This is an explicit alias, not a copy, so if the homepage exclusions change, social media follows. The user said "these posts should also ignore keyword terms that are ignored for homepage scraping, as self reports are unlikely."

---

## Phase 3: Repository

New file: `src/domains/monitoring/repositories/social_snapshot_repository.py`

### `SocialSnapshotRepository`

Mirrors `SnapshotRepository` patterns exactly:

```python
class SocialSnapshotRepository:
    def __init__(self, db: Database) -> None

    def store_snapshot(self, data: dict) -> int
    def get_latest_snapshots(self, company_id: int, source_url: str, limit: int = 2) -> list[dict]
    def get_all_sources_for_company(self, company_id: int) -> list[dict]
    def get_companies_with_multiple_snapshots(self) -> list[tuple[int, str]]
        # Returns (company_id, source_url) pairs with 2+ snapshots
```

### `SocialChangeRecordRepository`

Mirrors `ChangeRecordRepository`:

```python
class SocialChangeRecordRepository:
    def __init__(self, db: Database) -> None

    def store_change_record(self, data: dict) -> int
    def get_changes_for_company(self, company_id: int) -> list[dict]
    def get_significant_changes(self, days: int = 180, ...) -> list[dict]
```

---

## Phase 4: Service - Social Snapshot Capture

New file: `src/domains/monitoring/services/social_snapshot_manager.py`

### `SocialSnapshotManager`

**Responsibilities:**
1. Collect scrapable URLs: query `social_media_links` for platform='medium' + query `blog_links`
2. Batch-scrape via existing `FirecrawlClient.batch_capture_snapshots()`
3. For each result: compute checksum, extract `latest_post_date`, store snapshot
4. Track progress with `ProgressTracker`

```python
class SocialSnapshotManager:
    def __init__(
        self,
        social_snapshot_repo: SocialSnapshotRepository,
        social_link_repo: SocialMediaLinkRepository,
        company_repo: CompanyRepository,
        firecrawl_client: FirecrawlClient,
    ) -> None

    def collect_social_urls(self, company_id: int | None = None) -> list[dict]:
        """Get Medium + blog URLs from existing discovery data.
        Returns list of {company_id, source_url, source_type}."""

    def capture_social_snapshots(
        self,
        batch_size: int = 50,
        limit: int | None = None,
        company_id: int | None = None,
    ) -> dict[str, Any]:
        """Batch-capture social media snapshots.
        Uses FirecrawlClient.batch_capture_snapshots() for cost efficiency."""
```

**Key detail:** The existing `FirecrawlClient` already enforces `only_main_content=False` globally (hardcoded at module level). Social snapshots inherit this invariant automatically.

---

## Phase 5: Service - Social Change Detection

New file: `src/domains/monitoring/services/social_change_detector.py`

### `SocialChangeDetector`

Reuses existing pure functions from `monitoring/core/`:
- `detect_content_change()` for checksum + similarity comparison
- `extract_content_diff()` for diff extraction
- `analyze_content_significance()` with `exclude_categories=SOCIAL_MEDIA_EXCLUDED_CATEGORIES`

```python
class SocialChangeDetector:
    def __init__(
        self,
        social_snapshot_repo: SocialSnapshotRepository,
        social_change_record_repo: SocialChangeRecordRepository,
        company_repo: CompanyRepository,
        llm_client: LLMClient | None = None,
        llm_enabled: bool = False,
    ) -> None

    def detect_all_changes(self, limit: int | None = None) -> dict[str, Any]:
        """Detect changes across all social media sources.
        Pattern mirrors ChangeDetector.detect_all_changes() exactly."""
```

The flow:
1. `social_snapshot_repo.get_companies_with_multiple_snapshots()` returns `(company_id, source_url)` pairs
2. For each pair, get latest 2 snapshots
3. `detect_content_change()` on checksums + content
4. If changed: `extract_content_diff()` then `analyze_content_significance()` with social exclusions
5. If LLM enabled: `llm_client.classify_significance()` as primary classifier
6. Store in `social_media_change_records`

---

## Phase 6: Enrich Existing Analysis

This is the core integration -- making social media data flow into existing health assessments.

### 6a. New LLM prompt: `build_enriched_significance_prompt()`

Add to `src/core/llm_prompts.py`:

```python
ENRICHED_SIGNIFICANCE_SYSTEM_PROMPT = (
    "You are analyzing website content changes for a venture capital portfolio "
    "monitoring system.\n"
    "You will receive BOTH the homepage change data AND social media activity "
    "data. Use all available signals to make your assessment.\n\n"
    "Social media signals to consider:\n"
    "- Recent blog/Medium posts about product updates, funding, or growth = positive\n"
    "- Blog/Medium going inactive (no posts in 1+ year) = negative signal\n"
    "- No social media presence at all = neutral (not all companies blog)\n"
    "- Content of recent posts: what are they writing about?\n\n"
    "[... rest follows existing SIGNIFICANCE_CLASSIFICATION_SYSTEM_PROMPT pattern ...]"
)

ENRICHED_SIGNIFICANCE_USER_TEMPLATE = (
    "Analyze this website content change for business significance:\n\n"
    "Company: {company_name}\n"
    "Homepage: {homepage_url}\n\n"
    "Content excerpt (changed/added text):\n{content_excerpt}\n\n"
    "Change magnitude: {magnitude}\n\n"
    "Social media context:\n{social_context}\n\n"
    "Keyword hints from automated scanner:\n"
    "  Detected terms: {keywords}\n"
    "  Categories: {categories}\n\n"
    "Classify this change independently using ALL available signals.\n"
    "Respond with JSON only."
)
```

### 6b. Extend `LLMClient.classify_significance()`

Add an optional `social_context: str = ""` parameter. When non-empty, use the enriched prompt template instead of the basic one. This is backwards-compatible -- existing callers pass no social context and get the same behavior.

### 6c. Enrich `ChangeDetector.detect_all_changes()`

Inject `SocialSnapshotRepository` as an optional dependency:

```python
def __init__(self, ..., social_snapshot_repo: SocialSnapshotRepository | None = None):
```

In the detection loop, after computing the homepage diff but before calling the LLM:
1. If `social_snapshot_repo` is provided, fetch latest social snapshots for this company
2. Run `check_posting_inactivity()` on each
3. Call `prepare_social_context()` to build the context string
4. Pass `social_context` to `llm_client.classify_significance()`

When `social_snapshot_repo is None`, behavior is identical to current (zero blast radius on existing callers).

### 6d. Enrich `StatusAnalyzer.analyze_all_statuses()`

Same pattern: optional `social_snapshot_repo` dependency. When present:
1. Fetch latest social snapshot per source for the company
2. Check inactivity (1-year threshold)
3. Add inactivity indicators to the status analysis:
   - `("social_media_inactive", "medium", SignalType.NEGATIVE)` if Medium is inactive
   - `("social_media_inactive", "blog", SignalType.NEGATIVE)` if blog is inactive
   - `("social_media_active", "medium", SignalType.POSITIVE)` if recent posts found

These indicators feed into the existing `analyze_snapshot_status()` scoring system.

### 6e. Enrich `show-changes` CLI output

When displaying change history, also show social media change records inline (interleaved by date), marked with `[MEDIUM]` or `[BLOG]` prefixes.

---

## Phase 7: CLI Commands

Add to `src/cli/commands.py`:

### `capture-social-snapshots`
```
uv run airtable-extractor capture-social-snapshots
uv run airtable-extractor capture-social-snapshots --batch-size 100
uv run airtable-extractor capture-social-snapshots --company-id 42
uv run airtable-extractor capture-social-snapshots --limit 10
```

### `detect-social-changes`
```
uv run airtable-extractor detect-social-changes
uv run airtable-extractor detect-social-changes --limit 10
```

### `--include-social` flag on existing commands
```
uv run airtable-extractor detect-changes --include-social    # enriches LLM with social context
uv run airtable-extractor analyze-status --include-social    # adds inactivity signals
```

---

## Phase 8: Testing

Following the existing test structure (1277 tests across unit/contract/integration):

### Unit tests (`tests/unit/test_social_content_analysis.py`)
- `extract_latest_post_date()`: ISO dates, "Month Day, Year", relative dates, no dates, mixed formats
- `check_posting_inactivity()`: active, inactive, None date, edge cases at exactly 365 days
- `prepare_social_context()`: single source, multiple sources, character truncation, empty list
- `SOCIAL_MEDIA_EXCLUDED_CATEGORIES`: equals `HOMEPAGE_EXCLUDED_CATEGORIES`

### Contract tests (`tests/contract/`)
- `SocialSnapshotRepository`: store, retrieve latest 2, get companies with multiple snapshots
- `SocialChangeRecordRepository`: store, retrieve by company, filter by significance
- `SocialSnapshotManager`: mock Firecrawl, verify batch calls, verify URL collection

### Integration tests (`tests/integration/`)
- End-to-end: capture social snapshots -> detect changes -> verify enriched LLM context
- `--include-social` flag: verify social context flows through to LLM call
- Inactivity detection: company with old blog posts -> negative status indicator

**Estimated test count:** ~40-50 new tests.

---

## Implementation Order

1. **Phase 1** (Database): Tables + migration in `init_db()`
2. **Phase 2** (Core): Pure functions -- fully testable with unit tests before anything else
3. **Phase 3** (Repository): CRUD -- testable with contract tests against temp SQLite
4. **Phase 4** (Capture service): `SocialSnapshotManager` -- can run independently
5. **Phase 5** (Change detection): `SocialChangeDetector` -- can run independently
6. **Phase 6** (Integration): Enrich existing `ChangeDetector`, `StatusAnalyzer`, LLM prompts
7. **Phase 7** (CLI): Wire up commands
8. **Phase 8** (Tests): Tests written alongside each phase (TDD), final integration tests last

---

## Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Domain placement | `domains/monitoring/` | This is periodic content tracking, not URL discovery |
| Separate tables | Yes, for both snapshots and change records | Zero blast radius on existing queries and FKs |
| Category exclusions | Same as homepage (`HOMEPAGE_EXCLUDED_CATEGORIES`) | User confirmed: social self-reports are equally unlikely |
| Inactivity threshold | 365 days, configurable | User specified 1 year |
| LLM enrichment | Optional `social_context` param on existing method | Backwards-compatible, zero blast radius |
| Date extraction | Multi-format regex with fallback chain | Blogs/Medium have inconsistent date formats |
| Scraping | Reuse `FirecrawlClient.batch_capture_snapshots()` | Cost-efficient, inherits `only_main_content=False` |
| Twitter/LinkedIn | Skipped entirely | User decision -- unreliable scraping |
| No dates found | Treated as inactive | Conservative assumption per user preference |

---

## Performance Estimates

- Medium URLs in `social_media_links`: ~50-100 (subset of 761 companies)
- Blog URLs in `blog_links`: ~200-300
- Total URLs per run: ~250-400
- Batch scraping at 50/batch: 5-8 batches, ~5-10 minutes
- Additional LLM tokens per company (social context): ~500-1000 tokens
- Change detection: < 2 minutes (reuses existing pure functions)
