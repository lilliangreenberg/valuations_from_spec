# Portfolio Company Monitoring System - Development Guidelines

Reference guide for development. See TECHNICAL_SPEC.md for complete specification.
Last updated: 2026-02-18

## CRITICAL: Session Startup Requirements

**BEFORE MAKING ANY CODE CHANGES**, verify API versions per constitutional requirement:

### [CRITICAL] Firecrawl Configuration

**`only_main_content` MUST ALWAYS BE SET TO `False`**

This is hardcoded in `src/services/firecrawl_client.py:51` and must NEVER be changed to `True` or removed.

**Why this matters**:
- Social media links are located in footer/header content (90%+ of cases)
- Default `True` excludes this content, causing 127% fewer links to be detected
- With `False`: 75 links found across 21 companies
- With `True` (default): 33 links found across 9 companies

**Never modify this setting. It must remain `only_main_content=False` permanently.**

### CRITICAL: Always ask when confused
**WHENEVER YOU ARE CONFUSED OR UNSURE HOW TO PROCEED: Stop work and ask the user for input.**

---

1. **Airtable API**: Check https://airtable.com/developers/web/api/introduction
   - Current: REST API (no explicit version number in docs)
   - Library: pyairtable 3.2.0 (VERIFIED: Latest stable, up to date)
   - Changelog: https://github.com/gtalarico/pyairtable/releases

2. **Firecrawl API**: Check https://docs.firecrawl.dev/
   - Current: v2
   - Library: firecrawl-py 4.5.0 (VERIFIED: Latest stable, up to date)
   - Migration Status: COMPLETED (2025-10-30)
   - API Compatibility: Confirmed - scrape() method returns Document object with markdown, html, metadata, warning
   - Changelog: https://github.com/mendableai/firecrawl/releases

3. **All Python Dependencies**: Updated to latest versions (2025-10-31)
   - pydantic: 2.11.9 -> 2.12.3
   - structlog: 25.4.0 -> 25.5.0
   - python-dotenv: 1.1.1 -> 1.2.1
   - ruff: 0.13.2 -> 0.14.3
   - All other dependencies verified at latest versions
   - Migrated from deprecated json_encoders to field_serializer (Pydantic v2)

4. Update this file with new versions and verification date if changes found

**Last API Version Check**: 2025-10-31
**Critical Findings**: All libraries updated to latest versions. Fixed Pydantic v2 deprecation warnings by migrating from json_encoders to field_serializer.

**Last Test Cleanup**: 2026-02-13
**Test Status**: 1277 passing, 0 failing, 0 errors (100% pass rate)
**Tests Removed**: 370 deprecated/broken tests (MCP full-site discovery + outdated API contracts)

## Active Technologies
- Python 3.12 + pyairtable (Airtable API client), firecrawl-py (Firecrawl API client), pydantic (data validation), python-dotenv (configuration), structlog (logging) (001-you-are-developing)
- Python 3.12 (existing codebase) (002-website-change-detection)
- SQLite (existing `data/companies.db`) (002-website-change-detection)
- Python 3.12 + PIL/Pillow (image processing), imagehash (perceptual hashing) (003-the-program-needs)
- Playwright (headed browser for LinkedIn scraping) (005-leadership-extraction)

## Architecture

**Design:** Functional Core / Imperative Shell (FC/IS)
- Pure functions for all business logic (no I/O in core/)
- I/O operations isolated in services/
- SOLID principles enforced
- Full type hints with mypy strict mode

**Dependency Flow:**
```
CLI (Click) -> Services (I/O) -> Core (Pure functions) -> Models (Pydantic)
```

**Critical Rule:** core/ modules MUST NOT import from services/

## Project Structure
```
src/
  cli/                       # Click command definitions
  core/                      # Functional core (pure functions, NO I/O)
    advanced_extraction.py
    data_access.py
    duplicate_resolver.py
    link_aggregator.py
    llm_prompts.py
    result_aggregation.py
    social_account_extractor.py
    transformers.py
    validators.py
    website_mapper.py
  domains/                   # Domain-driven design (bounded contexts)
    discovery/               # Social Media Discovery domain
      core/                  # Pure functions for discovery
      repositories/          # Data access for social links
      services/              # Discovery orchestration services
    monitoring/              # Website Monitoring domain
      core/                  # Change detection logic
      repositories/          # Snapshot and change data access
      services/              # Monitoring orchestration
    news/                    # News Monitoring domain
      core/                  # Verification logic
      repositories/          # News article data access
      services/              # News search and analysis
    leadership/              # Leadership Extraction domain
      core/                  # Title detection, profile parsing, change detection
      repositories/          # Leadership data access
      services/              # LinkedIn browser, Kagi search, orchestrator
  models/                    # Pydantic models (shared)
  repositories/              # Shared repositories (Company)
  services/                  # Imperative shell (I/O operations)
    airtable_client.py
    batch_snapshot_manager.py
    database.py
    firecrawl_client.py
    llm_client.py
    snapshot_manager.py
  utils/                     # Utility functions
tests/
  unit/                      # Pure function tests (no I/O, no mocking)
  contract/                  # Service boundary tests (mocked APIs)
  integration/               # End-to-end workflow tests
docs/                        # Documentation
```

See TECHNICAL_SPEC.md Section 2 for complete architecture details.

## Database Schema

**Database:** SQLite at `data/companies.db`

**Core Tables:**
- `companies` - Portfolio companies with homepage URLs
- `snapshots` - Website content snapshots (markdown + HTML)
- `change_records` - Detected changes with significance analysis
- `company_statuses` - Operational status (operational/likely_closed/uncertain)
- `social_media_links` - Discovered social media profiles (12 platforms)
- `blog_links` - Discovered blog URLs
- `company_logos` - Extracted logos with perceptual hashes
- `news_articles` - News mentions with verification and significance
- `company_leadership` - Leadership profiles (CEO, CTO, founders) from LinkedIn
- `processing_errors` - Failed operations for debugging

**Key Constraints:**
- UNIQUE(name, homepage_url) on companies
- UNIQUE(company_id, profile_url) on social_media_links
- UNIQUE(content_url) on news_articles (globally unique)
- UNIQUE(company_id, linkedin_profile_url) on company_leadership
- Foreign keys with ON DELETE CASCADE for referential integrity

See TECHNICAL_SPEC.md Section 5 for complete schema details.

## Data Models

**Core Models (Pydantic with strict validation):**
- `Company` - Company metadata (name, homepage_url, source_sheet)
- `Snapshot` - Website content (markdown, HTML, checksum, HTTP headers)
- `ChangeRecord` - Content changes (magnitude, significance, sentiment)
- `CompanyStatus` - Operational status (status, confidence, indicators)
- `SocialMediaLink` - Social media profiles (platform, verification, account type)
- `NewsArticle` - News mentions (title, URL, verification, significance)
- `CompanyLeadership` - Leadership profiles (name, title, LinkedIn URL, discovery method)

**Enums:**
- `ChangeMagnitude`: MINOR (<10%), MODERATE (10-50%), MAJOR (>50%)
- `SignificanceClassification`: SIGNIFICANT, INSIGNIFICANT, UNCERTAIN
- `SignificanceSentiment`: POSITIVE, NEGATIVE, NEUTRAL, MIXED
- `Platform`: LINKEDIN, TWITTER, YOUTUBE, GITHUB, BLUESKY, etc. (12 platforms + BLOG)
- `VerificationStatus`: LOGO_MATCHED, UNVERIFIED, MANUALLY_REVIEWED, FLAGGED
- `LeadershipDiscoveryMethod`: PLAYWRIGHT_SCRAPE, KAGI_SEARCH
- `LeadershipChangeType`: CEO_DEPARTURE, FOUNDER_DEPARTURE, CTO_DEPARTURE, etc.

See TECHNICAL_SPEC.md Section 4 for complete model specifications.

## Significance Analysis System

**Purpose:** Classifies changes and news as SIGNIFICANT, INSIGNIFICANT, or UNCERTAIN

**Keyword Categories:**
- **Positive (7 categories, 60+ terms):** funding, product launch, growth, partnerships, expansion, recognition, IPO/exit
- **Negative (9 categories, 60+ terms):** closure, layoffs, financial distress, legal issues, security breach, acquisition, leadership changes
- **Insignificant (3 categories):** CSS styling, copyright year changes, tracking/analytics

**Classification Rules:**
1. Only insignificant patterns + minor magnitude -> INSIGNIFICANT (85% confidence)
2. 2+ negative keywords -> SIGNIFICANT (80-95% confidence)
3. 2+ positive keywords -> SIGNIFICANT (80-90% confidence)
4. 1 keyword + major magnitude -> SIGNIFICANT (70% confidence)
5. 1 keyword + minor magnitude -> UNCERTAIN (50% confidence)
6. No keywords -> INSIGNIFICANT (75% confidence)

**Sentiment:** POSITIVE, NEGATIVE, MIXED (both), NEUTRAL

**Advanced Features:**
- Negation detection: "no funding", "not acquired" (reduces confidence by 20%)
- False positive detection: "talent acquisition", "customer acquisition" (reduces by 30%)
- Optional LLM validation via Claude (when LLM_VALIDATION_ENABLED=true)

**Shared Across:**
- Website change detection (Feature 002)
- News article analysis (Feature 004)

See TECHNICAL_SPEC.md Section 10 for complete keyword dictionaries and logic.

## Configuration

**Required Environment Variables (in .env):**
```bash
AIRTABLE_API_KEY=pat.xxxxx              # Airtable personal access token
AIRTABLE_BASE_ID=appXXXXXXXXXXXXXX      # Airtable base ID
FIRECRAWL_API_KEY=fc-xxxxx              # Firecrawl API key
DATABASE_PATH=data/companies.db         # SQLite database path (default)
```

**Optional Environment Variables:**
```bash
LOG_LEVEL=INFO                          # DEBUG, INFO, WARNING, ERROR
MAX_RETRY_ATTEMPTS=2                    # 0-5 (default: 2)
ANTHROPIC_API_KEY=sk-xxxxx              # For LLM significance validation
LLM_MODEL=claude-haiku-4-5-20251001     # LLM model ID (default: Haiku 4.5)
LLM_VALIDATION_ENABLED=false            # Enable LLM validation (default: false)
KAGI_API_KEY=xxxxx                      # For news monitoring (Feature 004)
LINKEDIN_HEADLESS=false                 # Run LinkedIn browser headless (default: false)
LINKEDIN_PROFILE_DIR=data/linkedin_profile  # Persistent browser profile (default)
```

**External API Versions:**
- Airtable API: REST API (no version number)
- Firecrawl API: v2
- Kagi Search API: v0
- Anthropic API: Latest (claude-haiku-4-5-20251001 default)

See TECHNICAL_SPEC.md Section 3 and 12 for complete configuration and API contract details.

## Commands

### Feature 001: Data Extraction & Snapshots
```bash
uv run airtable-extractor extract-companies                     # Extract from Airtable
uv run airtable-extractor capture-snapshots                     # Sequential snapshot capture (slower)
uv run airtable-extractor capture-snapshots --use-batch-api     # Batch API capture (approximately 8x faster)
uv run airtable-extractor capture-snapshots --use-batch-api --batch-size 50  # Custom batch size
```

### Feature 002: Change Detection & Status Analysis
```bash
# Change detection with automatic significance analysis
uv run airtable-extractor detect-changes           # Detect content changes with significance analysis

# Significance analysis commands
uv run airtable-extractor backfill-significance    # Backfill significance for existing records
uv run airtable-extractor backfill-significance --dry-run  # Preview without updating
uv run airtable-extractor list-significant-changes --days 180  # List significant changes
uv run airtable-extractor list-significant-changes --sentiment positive  # Filter by sentiment
uv run airtable-extractor list-uncertain-changes   # Changes requiring manual review

# Status analysis
uv run airtable-extractor analyze-status           # Analyze company status
uv run airtable-extractor show-changes <company>   # View change history with significance
uv run airtable-extractor show-status <company>    # View status details
uv run airtable-extractor list-active --days 180   # Companies with recent changes
uv run airtable-extractor list-inactive --days 180 # Companies without changes
```

### Feature 003: Social Media Discovery
```bash
# Homepage-only approach with batch scraping (COST-OPTIMIZED, DEFAULT)
# Uses Firecrawl batch API to scrape multiple homepages in batches (50-100 URLs at once)
# for significant cost savings vs. individual scraping
uv run airtable-extractor discover-social-media                    # Process all companies
uv run airtable-extractor discover-social-media --batch-size 100   # Custom batch size
uv run airtable-extractor discover-social-media --limit 10         # Process first 10
uv run airtable-extractor discover-social-media --company-id <id>  # Single company (bypasses batching)

# Full-site approach (finds more links across entire website, slower)
uv run airtable-extractor discover-social-full-site --company-id <id>

# Advanced batch discovery (full-site crawl with parallel processing)
uv run airtable-extractor discover-social-batch --limit 50 --max-workers 10
```

**Cost Optimization:** The default `discover-social-media` command now uses Firecrawl's batch API
to scrape multiple homepages in a single API call (default: 50 URLs per batch, max: 1000).
This provides significant cost savings compared to individual scraping, especially when processing
large numbers of companies. Recommended batch size: 50-100 for optimal cost/speed balance.

### Feature 004: News Monitoring with Kagi Search
```bash
# Single company news search
uv run airtable-extractor search-news --company-name "Modal Labs"
uv run airtable-extractor search-news --company-id 42

# Batch search all companies
uv run airtable-extractor search-news-all
uv run airtable-extractor search-news-all --limit 10

# View news in change history (integrated into existing command)
uv run airtable-extractor show-changes "Modal Labs"  # Now includes related news
```

**Configuration Required:**
Add to `.env`:
```bash
KAGI_API_KEY=your-kagi-api-key-here
```

**Documentation:** See [docs/kagi_api_integration.md](docs/kagi_api_integration.md) for full details.

### Feature 005: LinkedIn Leadership Extraction
```bash
# Single company leadership extraction
uv run airtable-extractor extract-leadership --company-id 42
uv run airtable-extractor extract-leadership --company-id 42 --headless

# Batch extract all companies
uv run airtable-extractor extract-leadership-all
uv run airtable-extractor extract-leadership-all --limit 10

# Check leadership changes (re-extract and report changes)
uv run airtable-extractor check-leadership-changes
uv run airtable-extractor check-leadership-changes --limit 10
```

**First Run Setup:**
1. Run `uv run playwright install chromium` to install the browser
2. Run `uv run airtable-extractor extract-leadership --company-id <id>` -- a browser window opens
3. Log into LinkedIn manually in the browser window
4. Session cookies are saved to `data/linkedin_profile/` and reused on subsequent runs

**Leadership Change Detection:**
- CEO/Founder/CTO/COO departures flagged as CRITICAL (confidence 0.95)
- Other executive departures flagged as NOTABLE (confidence 0.80)
- Integrated into existing significance analysis system
- Changes logged at WARNING level with structured context

### Testing & Quality
```bash
uv run pytest                                      # Run all tests (1277 tests)
uv run pytest --cov=src --cov-report=term-missing # With coverage
uv run ruff check .                                # Run linting
uv run ruff format .                               # Format code
uv run mypy src/ --strict                          # Type checking
```

**Test Structure:**
- `tests/unit/` - Pure function tests (no I/O, fast)
- `tests/contract/` - Service boundary tests (mocked APIs, temp DB)
- `tests/integration/` - End-to-end workflow tests

See TECHNICAL_SPEC.md Section 14 for complete testing strategy.

## Error Handling & Retry Logic

**Retry Strategy:**
- Max attempts: 2 (default), configurable via MAX_RETRY_ATTEMPTS
- Exponential backoff: 2s, 4s, 8s, 10s (max)
- Retries on: ConnectionError, TimeoutError, HTTP 429/500/502/503/504
- No retry on: HTTP 401 (auth failure), validation errors

**Batch Error Isolation:**
- Individual failures do not abort batch operations
- Errors accumulated and reported in summary
- All errors logged via structlog with context

**Error Categories:**
- Transient Network: Retry with backoff
- Rate Limiting: Retry with longer backoff (HTTP 429)
- Auth Failure: Fail immediately (HTTP 401)
- Data Validation: Log and skip record
- API Error: Log and skip operation (HTTP 5xx)

See TECHNICAL_SPEC.md Section 13 for complete error handling specification.

## Code Style
Python 3.12: Follow standard conventions

**CRITICAL**: DO NOT USE EMOJIS anywhere in code, comments, documentation, commit messages, or any project artifacts. Use text-based markers instead (e.g., [NOTE], [WARNING], [COMPLETED]). This is a constitutional requirement (Principle VI).

## Critical Constraints & Invariants

**System Invariants:**
1. **CRITICAL: `only_main_content=False` in ALL Firecrawl calls** - This is NON-NEGOTIABLE
   - Hardcoded in `src/services/firecrawl_client.py:51`
   - Social media links are in headers/footers (90%+ of cases)
   - With False: 75 links across 21 companies
   - With True: 33 links across 9 companies (127% fewer links)

2. **Unique constraints enforce data integrity:**
   - companies(name, homepage_url) - No duplicate companies
   - social_media_links(company_id, profile_url) - No duplicate links per company
   - news_articles(content_url) - No duplicate articles globally
   - blog_links(company_id, blog_url) - No duplicate blogs per company

3. **Checksums:** Always lowercase hex MD5 strings (32 chars)

4. **Datetimes:** ISO 8601 strings in SQLite, Python datetime with UTC timezone

5. **Foreign Keys:** ON DELETE CASCADE for referential integrity

**Performance Characteristics:**
- 761 company snapshots: Sequential ~2 hours, Batch API ~16 minutes (8x faster)
- Social media discovery: Sequential ~3 hours, Batch ~45 minutes
- Change detection: ~5 minutes
- News search (all companies): ~30 minutes

**Known Limitations:**
- MCP Integration: FirecrawlMCPClient/RealFirecrawlMCPClient raise NotImplementedError
- No Scheduled Execution: CLI-only, no cron/scheduler integration
- No URL Shortener Resolution: t.co, bit.ly links not expanded
- Single-threaded CLI: Parallelism handled by APIs or ThreadPoolExecutor
- SQLite Single-Writer: One writer at a time, concurrent writes will fail

See TECHNICAL_SPEC.md Section 16 for complete constraints and invariants.

## Recent Changes
- LinkedIn Leadership Extraction (2026-02-18): COMPLETED - Extract CEO/founder profiles from LinkedIn
  - Full TDD implementation with 101 new tests (76 unit, 16 contract, 9 integration)
  - Headed Playwright browser with persistent session for LinkedIn scraping
  - Kagi search fallback when LinkedIn blocks access
  - Leadership change detection: CEO/Founder/CTO/COO departures flagged as CRITICAL
  - CompanyLeadership Pydantic model with LeadershipDiscoveryMethod enum
  - Added company_leadership table with UNIQUE(company_id, linkedin_profile_url)
  - Pure functions: title detection (25+ titles with seniority ranking), profile parsing, change detection
  - LeadershipRepository CRUD with upsert, mark_not_current for departed leaders
  - LinkedInBrowser: persistent context, auth wall detection, manual login wait
  - LeadershipSearch: Kagi fallback with CEO/founder/CTO queries
  - LeadershipManager orchestrator: Playwright-first with Kagi fallback
  - Extended significance analysis with 18 leadership change keywords
  - CLI commands: extract-leadership, extract-leadership-all, check-leadership-changes
  - Feature Status: PRODUCTION READY (requires `uv run playwright install chromium`)
- News Monitoring with Kagi Search (2026-02-11): COMPLETED - Track news articles about portfolio companies
  - Full TDD implementation with 28 new tests (11 unit, 6 contract, 11 integration)
  - Created NewsArticle model with significance and verification fields
  - Added news_articles table with foreign keys and indexes
  - Implemented KagiClient with full API integration (requests library)
  - Multi-signal company verification: logo (30%), domain (30%), name context (15%), LLM (25%)
  - Reuses existing significance analysis system (keywords + LLM validation)
  - Extended LLMClient with validate_news_significance() and verify_company_identity()
  - Database CRUD methods: store_news_article, get_news_articles, check_duplicate_news_url
  - NewsMonitorManager orchestrates: search -> verify -> analyze -> store
  - CLI commands: search-news, search-news-all (batch processing)
  - Integration with show-changes command displays related news articles
  - Date range calculation: between snapshots or fallback to 90 days
  - Comprehensive documentation in docs/kagi_api_integration.md
  - Feature Status: PRODUCTION READY (requires KAGI_API_KEY in .env)
- Website Change Significance Classification (2026-02-09): COMPLETED - Automated business significance analysis
  - Created significance_analysis.py with 150+ keywords across 16 categories
  - Added SignificanceAnalyzer service for keyword-based classification
  - Integrated automatic significance analysis into detect-changes workflow
  - Extended ChangeRecord model with 6 new significance fields
  - Database migration adds significance columns to change_records table
  - Three-tier classification: SIGNIFICANT / INSIGNIFICANT / UNCERTAIN
  - Sentiment analysis: POSITIVE / NEGATIVE / MIXED / NEUTRAL
  - Confidence scoring (0.0-1.0) with negation and false positive detection
  - New CLI commands: backfill-significance, list-significant-changes, list-uncertain-changes
  - Comprehensive unit tests (37 tests, all passing)
  - Full documentation in docs/significance_keywords.md
  - Feature Status: PRODUCTION READY
- Batch Snapshot Capture (2026-02-09): Added high-performance batch processing using Firecrawl batch API
  - New BatchSnapshotManager service for parallel snapshot capture (approximately 8x faster)
  - Extended FirecrawlClient with batch_capture_snapshots() method
  - Added --use-batch-api flag to capture-snapshots CLI command
  - Batch size configurable (default: 20, max: 1000 URLs per batch)
  - Preserves critical only_main_content=False setting in batch operations
  - Full integration test coverage (8 test scenarios)
  - Reduces 761 company processing from approximately 2 hours to approximately 16 minutes
- 003-the-program-needs (2025-11-05): COMPLETED all 38/38 tasks for social media discovery
  - Added 2 missing contract tests (discovery service, database extensions)
  - Completed 4 integration test suites (discovery, logo extraction, Airtable sync, batch processing)
  - Created image utility module with 9 pure functions for logo processing
  - Added comprehensive platform patterns documentation for 12 platforms
  - Created quickstart validation guide with 7 scenarios
  - Implemented full batch processing with parallel execution support
  - Added BatchSocialDiscovery service for 25-50 company parallelization
  - Fixed linting issues and formatted all code with ruff
  - Updated dependencies to latest versions (2025-10-31)
  - Fixed Pydantic v2 deprecation warnings
  - Feature Status: PRODUCTION READY
- 002-website-change-detection: Added Python 3.12 (existing codebase)
- 001-you-are-developing: Added Python 3.12 + pyairtable (Airtable API client), firecrawl-py (Firecrawl API client), pydantic (data validation), python-dotenv (configuration), structlog (logging)

## Quick Reference to Technical Spec

For detailed specifications, see TECHNICAL_SPEC.md:

- **Section 1**: System Overview - Purpose, tech stack, design principles
- **Section 2**: Architecture - Directory structure, dependency flow, domain boundaries
- **Section 3**: Configuration - Environment variables, config validation
- **Section 4**: Data Models - Complete Pydantic model specifications
- **Section 5**: Database Schema - Table definitions, indexes, constraints
- **Section 6**: Feature 001 - Data Extraction & Snapshots (Airtable + Firecrawl)
- **Section 7**: Feature 002 - Change Detection & Status Analysis
- **Section 8**: Feature 003 - Social Media Discovery (12 platforms)
- **Section 9**: Feature 004 - News Monitoring (Kagi Search API)
- **Section 10**: Significance Analysis - Keyword dictionaries, classification rules
- **Section 11**: CLI Interface - Complete command reference
- **Section 12**: External API Contracts - Airtable, Firecrawl, Kagi, Anthropic
- **Section 13**: Error Handling - Retry logic, error categories
- **Section 14**: Testing Strategy - Test structure, fixtures, categories
- **Section 15**: Migration Strategy - Database migrations
- **Section 16**: Constraints & Invariants - Critical rules, performance, limitations

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
