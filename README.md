# Portfolio Company Monitoring System

A CLI tool for monitoring a venture capital portfolio of hundreds of companies. Extracts company data from Airtable, captures website snapshots, detects content changes, discovers social media presence, monitors news coverage, and tracks leadership changes -- all from a single `airtable-extractor` command.

## Features

### 1. Data Extraction and Snapshots
- Extract company metadata from an Airtable base (the source of truth)
- Capture periodic website snapshots via Firecrawl (markdown + HTML)
- Batch API support for ~8x faster processing (761 companies in ~16 minutes vs ~2 hours)
- Logo extraction from Firecrawl branding data with perceptual hashing

### 2. Website Change Detection and Status Analysis
- Detect content changes between consecutive snapshots
- Automatic significance classification: SIGNIFICANT / INSIGNIFICANT / UNCERTAIN
- Sentiment analysis: POSITIVE / NEGATIVE / MIXED / NEUTRAL
- 150+ keyword dictionary across 16 categories (funding, layoffs, product launches, closures, etc.)
- Negation detection ("no funding", "not acquired") and false positive handling
- Optional LLM validation via Claude for borderline cases
- Company operational status analysis (operational / likely_closed / uncertain)

### 3. Social Media Discovery
- Homepage-based discovery across 12 platforms: LinkedIn, Twitter/X, YouTube, GitHub, Bluesky, Facebook, Instagram, TikTok, Medium, Substack, Discord, Slack
- Blog URL detection
- Full-site crawl mode for deeper discovery
- Batch processing with parallel execution
- Logo-based company verification using perceptual hashing
- Platform-specific URL normalization and deduplication

### 4. News Monitoring
- News search via Kagi Search API
- Multi-signal company verification: logo matching (30%), domain matching (30%), name context (15%), LLM verification (25%)
- Reuses the significance analysis system for article classification
- Integrated into change history view for correlated analysis

### 5. LinkedIn Leadership Extraction
- Extract CEO, founder, CTO, and other executive profiles from LinkedIn
- Headed Playwright browser with persistent session cookies (log in once, reuse)
- Kagi search fallback when LinkedIn blocks access
- Leadership change detection: CEO/Founder/CTO/COO departures flagged as CRITICAL
- 25+ executive title patterns with seniority ranking

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | Python >= 3.12 |
| Package Manager | uv |
| CLI Framework | Click |
| Data Validation | Pydantic |
| Database | SQLite |
| Logging | structlog |
| Web Scraping | Firecrawl (v2 API) |
| Airtable Client | pyairtable |
| LLM Integration | Anthropic (Claude) |
| Image Processing | Pillow + imagehash |
| Browser Automation | Playwright |
| News Search | Kagi Search API |
| Linting | ruff |
| Type Checking | mypy (strict) |
| Testing | pytest |

## Architecture

**Functional Core / Imperative Shell (FC/IS)** -- pure functions for all business logic, I/O isolated in services.

```
CLI (Click commands)
  |
  v
Services (Imperative Shell - I/O)
  |
  v
Core (Functional Core - Pure functions)
  |
  v
Models (Pydantic - Data structures)
```

Domain-driven structure with bounded contexts:

```
src/
  cli/           # Click command definitions
  core/          # Shared pure functions (no I/O)
  domains/
    discovery/   # Social media discovery
    monitoring/  # Website change detection and status
    news/        # News monitoring (Kagi)
    leadership/  # LinkedIn leadership extraction
  models/        # Pydantic models (shared)
  repositories/  # Shared data access
  services/      # I/O operations (Airtable, Firecrawl, database, LLM)
  utils/         # Logging, image processing, retry, progress
```

## Setup

### Prerequisites

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) package manager

### Installation

```bash
uv sync
```

For leadership extraction (Feature 5), also install the Playwright browser:

```bash
uv run playwright install chromium
```

### Configuration

Create a `.env` file in the project root:

```bash
# Required
AIRTABLE_API_KEY=pat.xxxxx
AIRTABLE_BASE_ID=appXXXXXXXXXXXXXX
FIRECRAWL_API_KEY=fc-xxxxx

# Optional
DATABASE_PATH=data/companies.db          # Default: data/companies.db
LOG_LEVEL=INFO                           # DEBUG, INFO, WARNING, ERROR
MAX_RETRY_ATTEMPTS=2                     # 0-5 (default: 2)

# LLM significance validation (optional)
ANTHROPIC_API_KEY=sk-xxxxx
LLM_MODEL=claude-haiku-4-5-20251001
LLM_VALIDATION_ENABLED=false

# News monitoring (Feature 4)
KAGI_API_KEY=xxxxx

# Leadership extraction (Feature 5)
LINKEDIN_HEADLESS=false                  # Run browser headless (default: false)
LINKEDIN_PROFILE_DIR=data/linkedin_profile
```

## Usage

All commands are run via `uv run airtable-extractor <command>`.

### Data Extraction and Snapshots

```bash
# Extract companies from Airtable
airtable-extractor extract-companies

# Import social media / blog URLs from Airtable
airtable-extractor import-urls

# Capture website snapshots
airtable-extractor capture-snapshots                          # Sequential
airtable-extractor capture-snapshots --use-batch-api          # Batch (~8x faster)
airtable-extractor capture-snapshots --use-batch-api --batch-size 50
airtable-extractor capture-snapshots --company-id 42          # Single company

# Refresh company logos
airtable-extractor refresh-logos
airtable-extractor refresh-logos --force --batch-size 100
```

### Change Detection and Status Analysis

```bash
# Detect content changes with significance analysis
airtable-extractor detect-changes
airtable-extractor detect-changes --output-format json

# Backfill significance for existing records
airtable-extractor backfill-significance
airtable-extractor backfill-significance --dry-run

# Baseline signal analysis on snapshots
airtable-extractor analyze-baseline
airtable-extractor analyze-baseline --dry-run

# List significant / uncertain changes
airtable-extractor list-significant-changes --days 180
airtable-extractor list-significant-changes --sentiment positive
airtable-extractor list-uncertain-changes

# Company status analysis
airtable-extractor analyze-status

# View per-company details
airtable-extractor show-changes "Company Name"    # Change history + related news
airtable-extractor show-status "Company Name"

# Activity filtering
airtable-extractor list-active --days 180
airtable-extractor list-inactive --days 180
```

### Social Media Discovery

```bash
# Homepage-based batch discovery (default, cost-optimized)
airtable-extractor discover-social-media
airtable-extractor discover-social-media --batch-size 100 --limit 10
airtable-extractor discover-social-media --company-id 42

# Full-site crawl for a single company (deeper, slower)
airtable-extractor discover-social-full-site --company-id 42

# Advanced batch discovery with parallel full-site crawls
airtable-extractor discover-social-batch --limit 50 --max-workers 10

# View results
airtable-extractor show-social-links --company-name "Company Name"
airtable-extractor show-social-links --company-id 42
```

### News Monitoring

Requires `KAGI_API_KEY` in `.env`.

```bash
# Single company
airtable-extractor search-news --company-name "Company Name"
airtable-extractor search-news --company-id 42

# All companies (parallel)
airtable-extractor search-news-all
airtable-extractor search-news-all --limit 10 --max-workers 5

# News is also shown in change history
airtable-extractor show-changes "Company Name"
```

### Leadership Extraction

Requires Playwright (`uv run playwright install chromium`). On first run, a browser window opens for manual LinkedIn login. Session cookies persist for subsequent runs.

```bash
# Single company
airtable-extractor extract-leadership --company-id 42
airtable-extractor extract-leadership --company-id 42 --headless

# All companies
airtable-extractor extract-leadership-all
airtable-extractor extract-leadership-all --limit 10

# Check for leadership changes (re-extract and report)
airtable-extractor check-leadership-changes
```

## Development

```bash
# Run all tests (1277 tests)
uv run pytest

# With coverage
uv run pytest --cov=src --cov-report=term-missing

# Linting and formatting
uv run ruff check .
uv run ruff format .

# Type checking
uv run mypy src/ --strict
```

### Test Structure

- `tests/unit/` -- Pure function tests (no I/O, fast)
- `tests/contract/` -- Service boundary tests (mocked APIs, temp DB)
- `tests/integration/` -- End-to-end workflow tests

## Database

SQLite at `data/companies.db` with the following core tables:

| Table | Purpose |
|-------|---------|
| `companies` | Portfolio companies with homepage URLs |
| `snapshots` | Website content snapshots (markdown + HTML) |
| `change_records` | Detected changes with significance analysis |
| `company_statuses` | Operational status tracking |
| `social_media_links` | Discovered social media profiles (12 platforms) |
| `blog_links` | Discovered blog URLs |
| `company_logos` | Extracted logos with perceptual hashes |
| `news_articles` | News mentions with verification and significance |
| `company_leadership` | Leadership profiles from LinkedIn |
| `processing_errors` | Failed operations for debugging |

## License

Private.
