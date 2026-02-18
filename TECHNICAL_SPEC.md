# Technical Specification: Portfolio Company Monitoring System

**Version**: 1.0
**Last Updated**: 2026-02-17
**Status**: Complete reference specification for rebuild

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture](#2-architecture)
3. [Configuration and Environment](#3-configuration-and-environment)
4. [Data Models](#4-data-models)
5. [Database Schema](#5-database-schema)
6. [Feature 001: Data Extraction and Snapshots](#6-feature-001-data-extraction-and-snapshots)
7. [Feature 002: Website Change Detection and Status Analysis](#7-feature-002-website-change-detection-and-status-analysis)
8. [Feature 003: Social Media Discovery](#8-feature-003-social-media-discovery)
9. [Feature 004: News Monitoring](#9-feature-004-news-monitoring)
10. [Significance Analysis System](#10-significance-analysis-system)
11. [CLI Interface](#11-cli-interface)
12. [External API Contracts](#12-external-api-contracts)
13. [Error Handling and Retry Logic](#13-error-handling-and-retry-logic)
14. [Testing Strategy](#14-testing-strategy)
15. [Migration Strategy](#15-migration-strategy)
16. [Constraints and Invariants](#16-constraints-and-invariants)

---

## 1. System Overview

### 1.1 Purpose

This system monitors a venture capital portfolio of hundreds of companies by:

1. **Extracting** company data from an Airtable base (the source of truth for company metadata)
2. **Capturing** periodic website snapshots via Firecrawl (a web scraping API)
3. **Detecting** content changes between snapshots and classifying their business significance
4. **Discovering** social media presence across 12 platforms
5. **Monitoring** news coverage via Kagi search API with multi-signal company verification

The system is a CLI tool (`airtable-extractor`) that an operator runs on-demand. It is not a continuously running service.

### 1.2 Technology Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Language | Python | >= 3.12 |
| Package Manager | uv | Latest |
| Data Validation | Pydantic + pydantic-settings | >= 2.12.3 |
| CLI Framework | Click | >= 8.3.0 |
| Database | SQLite | Built-in |
| Logging | structlog | >= 25.5.0 |
| HTTP Client | requests | >= 2.32.5 |
| Airtable Client | pyairtable | >= 3.2.0 |
| Web Scraping | firecrawl-py | >= 4.5.0 |
| LLM Integration | anthropic | >= 0.40.0 |
| Image Processing | Pillow, imagehash | >= 12.0.0, >= 4.3.2 |
| HTML Parsing | beautifulsoup4 | >= 4.14.2 |
| Retry Logic | tenacity | >= 9.1.2 |
| Linting | ruff | >= 0.14.3 |
| Type Checking | mypy (strict) | >= 1.18.2 |
| Testing | pytest | >= 8.4.2 |
| Build System | hatchling | Latest |

### 1.3 Design Principles

- **Functional Core / Imperative Shell (FC/IS)**: Pure functions for all business logic; I/O operations isolated in services
- **SOLID principles**: Single responsibility, open/closed, etc.
- **src/ layout**: All source code under `src/` package
- **Full type hints**: mypy strict mode enforced
- **XDG Base Directory standards** for file locations where applicable
- **No emojis**: Text-based markers only ([NOTE], [WARNING], etc.)

---

## 2. Architecture

### 2.1 Directory Structure

```
src/
  __init__.py
  cli/
    __init__.py              # Click group definition, exports `cli`
    commands.py              # All CLI command implementations
  core/                      # Functional Core (pure functions, NO I/O)
    advanced_extraction.py   # Schema.org, meta tag, aria-label extraction
    data_access.py           # Data access pure functions
    duplicate_resolver.py    # Social media link deduplication
    link_aggregator.py       # Link aggregation from multiple pages
    llm_prompts.py           # LLM prompt templates
    result_aggregation.py    # Batch result aggregation
    social_account_extractor.py  # Extract handles from social URLs
    transformers.py          # Data transformation functions
    validators.py            # Data validation functions
    website_mapper.py        # Website URL mapping/grouping
  domains/
    discovery/               # Social Media Discovery domain
      core/
        account_patterns.py    # Platform-specific account patterns
        batch_aggregator.py    # Batch discovery result aggregation
        blog_detection.py      # Blog URL detection
        html_region_detector.py # Detect footer/header/nav regions
        link_extraction.py     # Extract links from HTML/markdown
        logo_comparison.py     # Perceptual hash comparison
        platform_detection.py  # Detect platform from URL
        url_normalization.py   # Normalize URLs to canonical form
        youtube_resolver.py    # Resolve video URLs to channels
      repositories/
        social_media_link_repository.py
      services/
        account_classifier.py       # Classify company vs personal
        batch_social_discovery.py   # Parallel batch processing
        full_site_social_discovery.py # Full-site crawl discovery
        logo_service.py             # Logo extraction and comparison
        mcp_social_discovery.py     # MCP-based discovery
        social_media_discovery.py   # Homepage-based discovery
    monitoring/              # Website Monitoring domain
      core/
        change_detection.py       # Content diff logic
        checksum.py               # MD5 checksum computation
        http_headers.py           # HTTP header parsing
        significance_analysis.py  # Keyword-based significance
        status_rules.py           # Company status determination
      repositories/
        change_record_repository.py
        company_status_repository.py
        snapshot_repository.py
      services/
        batch_processor.py        # Batch snapshot capture
        change_detector.py        # Orchestrates change detection
        significance_analyzer.py  # Orchestrates significance analysis
        status_analyzer.py        # Orchestrates status analysis
    news/                    # News Monitoring domain
      core/
        verification_logic.py     # Multi-signal verification
      repositories/
        news_article_repository.py
      services/
        company_verifier.py       # Verify article matches company
        kagi_client.py            # Kagi search API client
        news_analyzer.py          # Article significance analysis
        news_monitor_manager.py   # Orchestrates news workflow
  models/                    # Pydantic models (shared)
    __init__.py
    batch_result.py
    blog_link.py
    change_record.py
    company.py
    company_logo.py
    company_status.py
    config.py
    discovery_result.py
    keyword_match.py
    llm_validation.py
    news_article.py
    processing_error.py
    snapshot.py
    social_media_link.py
  repositories/
    company_repository.py
  services/                  # Imperative Shell (I/O operations)
    __init__.py
    airtable_client.py       # Airtable API client
    batch_processor.py       # Generic batch processor
    batch_snapshot_manager.py # Firecrawl batch API snapshots
    database.py              # SQLite database service
    extractor.py             # Company extraction orchestrator
    firecrawl_client.py      # Firecrawl API client
    firecrawl_mcp_client.py  # Firecrawl MCP client (stub)
    firecrawl_mcp_client_real.py # Real MCP client (stub)
    llm_client.py            # Anthropic LLM client
    mcp_bridge.py            # MCP batch request/response bridge
    protocols.py             # Service protocols/interfaces
    snapshot_manager.py      # Sequential snapshot capture
  utils/
    health_checks.py         # API health check utilities
    image_utils.py           # Image processing utilities
    logger.py                # structlog configuration
    progress.py              # Progress tracking utilities
    retry.py                 # Retry decorator
    validators.py            # URL and data validators
```

### 2.2 Dependency Flow

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

Key rule: `core/` modules MUST NOT import from `services/`. Services import core functions and orchestrate I/O around them.

### 2.3 Domain Boundaries

Three bounded contexts exist within `domains/`:

1. **Discovery** - Social media link discovery (depends on Firecrawl)
2. **Monitoring** - Website change detection (depends on Database, Firecrawl)
3. **News** - News article monitoring (depends on Kagi, Database)

Each domain has its own `core/`, `repositories/`, and `services/` subdirectories.

---

## 3. Configuration and Environment

### 3.1 Environment Variables

Loaded from `.env` file via `pydantic-settings`:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AIRTABLE_API_KEY` | Yes | - | Airtable personal access token |
| `AIRTABLE_BASE_ID` | Yes | - | Airtable base ID (format: `appXXXXXXXXXXXXXX`) |
| `FIRECRAWL_API_KEY` | Yes | - | Firecrawl API key (format: `fc-...`) |
| `DATABASE_PATH` | No | `data/companies.db` | SQLite database file path |
| `LOG_LEVEL` | No | `INFO` | Logging level: DEBUG, INFO, WARNING, ERROR |
| `MAX_RETRY_ATTEMPTS` | No | `2` | Max retry attempts (0-5) |
| `ANTHROPIC_API_KEY` | No | None | Anthropic API key for LLM features |
| `LLM_MODEL` | No | `claude-haiku-4-5-20251001` | Model ID for LLM calls |
| `LLM_VALIDATION_ENABLED` | No | `false` | Enable LLM significance validation |
| `KAGI_API_KEY` | No | None | Kagi API key for news search |

### 3.2 Config Model

```python
class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
```

Validation rules:
- `airtable_api_key`: min_length=1
- `airtable_base_id`: must match pattern `^app[a-zA-Z0-9]+$`
- `firecrawl_api_key`: min_length=1
- `database_path`: parent directory is auto-created if missing
- `max_retry_attempts`: 0-5 inclusive

---

## 4. Data Models

### 4.1 Company

```python
class Company(BaseModel):
    model_config = ConfigDict(strict=True, validate_assignment=True, extra="forbid")

    id: int | None = None
    name: str                           # min_length=1, max_length=500
    homepage_url: HttpUrl | None = None # Pydantic HttpUrl type
    source_sheet: str                   # min_length=1
    flagged_for_review: bool = False
    flag_reason: str | None             # max_length=1000
    created_at: datetime                # default: now(UTC)
    updated_at: datetime                # default: now(UTC)
```

Validation:
- `homepage_url`: Pydantic `HttpUrl` type (not a plain string validator)
- `name`: Stripped of whitespace, title-cased, collapsed spaces (via `field_validator`)
- `flag_reason`: Required when `flagged_for_review` is True (via `model_validator`)

### 4.2 Snapshot

```python
class Snapshot(BaseModel):
    model_config = ConfigDict(strict=True)

    id: int | None = None
    company_id: int                     # gt=0
    url: HttpUrl                        # Pydantic HttpUrl type
    content_markdown: str | None        # max_length=10MB, Firecrawl markdown output
    content_html: str | None            # max_length=10MB, Firecrawl HTML output
    status_code: int | None             # 100-599 if present
    captured_at: datetime               # default: now(UTC), must not be future
    has_paywall: bool = False           # Detected paywall
    has_auth_required: bool = False     # Detected auth wall
    error_message: str | None           # max_length=2000, error details on failure
    content_checksum: str | None        # MD5 hex string, 32 chars
    http_last_modified: datetime | None # Parsed from HTTP header
    capture_metadata: str | None        # JSON string for extensibility
```

Validation:
- `status_code`: 100-599 (Optional, None for failed captures)
- `content_checksum`: Must be valid 32-char hex string, lowercased (Optional)
- `captured_at`: Must not be in the future
- At least one of `content_markdown`, `content_html`, or `error_message` required (via `model_validator`)

### 4.3 ChangeRecord

```python
class ChangeMagnitude(str, Enum):
    MINOR = "minor"         # similarity >= 0.90 (< 10% content changed)
    MODERATE = "moderate"   # similarity 0.50-0.90 (10-50% changed)
    MAJOR = "major"         # similarity < 0.50 (> 50% changed)

class SignificanceClassification(str, Enum):
    SIGNIFICANT = "significant"
    INSIGNIFICANT = "insignificant"
    UNCERTAIN = "uncertain"

class SignificanceSentiment(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"

class ChangeRecord(BaseModel):
    id: int | None = None
    company_id: int
    snapshot_id_old: int
    snapshot_id_new: int
    checksum_old: str                   # MD5 hex
    checksum_new: str                   # MD5 hex
    has_changed: bool
    change_magnitude: ChangeMagnitude
    detected_at: datetime
    # Significance fields (populated after analysis)
    significance_classification: SignificanceClassification | None
    significance_sentiment: SignificanceSentiment | None
    significance_confidence: float | None   # 0.0-1.0
    matched_keywords: list[str]
    matched_categories: list[str]
    significance_notes: str | None
    evidence_snippets: list[str]
```

### 4.4 CompanyStatus

```python
class CompanyStatusType(str, Enum):
    OPERATIONAL = "operational"
    LIKELY_CLOSED = "likely_closed"
    UNCERTAIN = "uncertain"

class SignalType(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"

class StatusIndicator(BaseModel):
    type: str       # e.g., "copyright_year", "acquisition_text"
    value: str      # e.g., "2025", "acquired by TechCorp"
    signal: SignalType

class CompanyStatus(BaseModel):
    id: int | None = None
    company_id: int
    status: CompanyStatusType
    confidence: float               # 0.0-1.0
    indicators: list[StatusIndicator]  # JSON-serialized in DB
    last_checked: datetime
    http_last_modified: datetime | None
```

### 4.5 SocialMediaLink

```python
class Platform(str, Enum):
    LINKEDIN = "linkedin"
    TWITTER = "twitter"
    YOUTUBE = "youtube"
    BLUESKY = "bluesky"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    GITHUB = "github"
    TIKTOK = "tiktok"
    MEDIUM = "medium"
    MASTODON = "mastodon"
    THREADS = "threads"
    PINTEREST = "pinterest"
    BLOG = "blog"

class DiscoveryMethod(str, Enum):
    PAGE_FOOTER = "page_footer"
    PAGE_HEADER = "page_header"
    PAGE_CONTENT = "page_content"
    FULL_SITE_CRAWL = "full_site_crawl"

class VerificationStatus(str, Enum):
    LOGO_MATCHED = "logo_matched"
    UNVERIFIED = "unverified"
    MANUALLY_REVIEWED = "manually_reviewed"
    FLAGGED = "flagged"

class HTMLRegion(str, Enum):
    FOOTER = "footer"
    HEADER = "header"
    NAV = "nav"
    ASIDE = "aside"
    MAIN = "main"
    UNKNOWN = "unknown"

class AccountType(str, Enum):
    COMPANY = "company"
    PERSONAL = "personal"
    UNKNOWN = "unknown"

class SocialMediaLink(BaseModel):
    id: int | None = None
    company_id: int
    platform: Platform
    profile_url: str
    discovery_method: DiscoveryMethod
    verification_status: VerificationStatus = UNVERIFIED
    similarity_score: float | None      # 0.0-1.0, logo match score
    discovered_at: datetime
    last_verified_at: datetime | None
    html_location: HTMLRegion | None
    account_type: AccountType | None
    account_confidence: float | None    # 0.0-1.0
    rejection_reason: RejectionReason | None
```

### 4.6 BlogLink

```python
class BlogType(str, Enum):
    COMPANY_BLOG = "company_blog"   # blog.example.com or example.com/blog
    MEDIUM = "medium"
    SUBSTACK = "substack"
    GHOST = "ghost"
    WORDPRESS = "wordpress"
    OTHER = "other"

class BlogLink(BaseModel):
    id: int | None = None
    company_id: int
    blog_type: BlogType
    blog_url: str
    discovery_method: DiscoveryMethod   # page_footer, subdomain_detection, etc.
    is_active: bool = True
    discovered_at: datetime
    last_verified_at: datetime | None
```

### 4.7 CompanyLogo

```python
class ExtractionLocation(str, Enum):
    TOP_LEFT = "top_left"
    HEADER = "header"
    NAV = "nav"
    FAVICON = "favicon"
    OG_IMAGE = "og_image"

class CompanyLogo(BaseModel):
    id: int | None = None
    company_id: int
    image_data: str                 # Base64-encoded
    image_format: str               # PNG, JPEG, GIF
    perceptual_hash: str            # pHash for similarity matching
    source_url: str
    extraction_location: ExtractionLocation
    width: int | None
    height: int | None
    extracted_at: datetime
```

### 4.8 NewsArticle

```python
class NewsArticle(BaseModel):
    model_config = ConfigDict(strict=True)

    id: int | None = None
    company_id: int                     # gt=0
    title: str                          # min_length=1, max_length=500
    content_url: HttpUrl                # Pydantic validated URL
    source: str                         # min_length=1
    published_at: datetime
    discovered_at: datetime
    match_confidence: float             # 0.0-1.0
    match_evidence: list[str]
    logo_similarity: float | None       # 0.0-1.0
    company_match_snippet: str | None
    keyword_match_snippet: str | None
    significance_classification: SignificanceClassification | None
    significance_sentiment: SignificanceSentiment | None
    significance_confidence: float | None   # 0.0-1.0
    matched_keywords: list[str]
    matched_categories: list[str]
    significance_notes: str | None
```

### 4.9 Supporting Models

**KeywordMatch**: Represents a matched keyword with context for significance analysis.
```python
class KeywordMatch(BaseModel):
    keyword: str
    category: str
    position: int               # >= 0
    context_before: str         # max_length=50
    context_after: str          # max_length=50
    is_negated: bool = False
    is_false_positive: bool = False
```

**LLMValidationResult**: Result from LLM-based significance validation.
```python
class LLMValidationResult(BaseModel):
    classification: SignificanceClassification
    sentiment: SignificanceSentiment
    confidence: float           # 0.0-1.0
    reasoning: str
    validated_keywords: list[str]
    false_positives: list[str]
    error: str | None
```

**BatchResult**: Statistics for batch operations.
```python
class BatchResult(BaseModel):
    processed: int
    successful: int
    failed: int
    skipped: int
    duration_seconds: float
    errors: list[str]
```

**DiscoveryResult**: Transient result of a discovery operation (not persisted).
```python
class DiscoveryResult(BaseModel):
    company_id: int
    company_name: str
    homepage_url: str
    discovered_links: list[SocialMediaLink]
    discovered_blogs: list[BlogLink]
    extracted_logo: CompanyLogo | None
    logo_extraction_attempted: bool = False
    logo_extraction_failed: bool = False
    flagged_for_review: bool = False
    flag_reason: str | None
    error_message: str | None
    processing_time_seconds: float | None
    processed_at: datetime              # default: now(UTC)
```

**ProcessingError**: Tracks failures for retry/debugging.
```python
class ProcessingError(BaseModel):
    model_config = ConfigDict(strict=True)
    entity_type: Literal["company", "snapshot"]
    entity_id: int | None
    error_type: str             # PascalCase, 1-100 chars
    error_message: str          # 1-5000 chars
    retry_count: int = 0        # 0-2
    occurred_at: datetime
```

---

## 5. Database Schema

SQLite database at `data/companies.db`. Schema is created programmatically in `Database.init_db()` with migrations applied incrementally via Python scripts.

### 5.1 Tables

#### companies
```sql
CREATE TABLE companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    homepage_url TEXT,
    source_sheet TEXT NOT NULL,
    flagged_for_review INTEGER DEFAULT 0,
    flag_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(name, homepage_url)
);
CREATE INDEX idx_companies_name ON companies(name);
```

#### snapshots
```sql
CREATE TABLE snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    content_markdown TEXT,
    content_html TEXT,
    status_code INTEGER,
    captured_at TEXT NOT NULL,
    has_paywall INTEGER DEFAULT 0,
    has_auth_required INTEGER DEFAULT 0,
    error_message TEXT,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);
-- content_checksum, http_last_modified, capture_metadata added via ALTER TABLE migration
CREATE INDEX idx_snapshots_company_id ON snapshots(company_id);
CREATE INDEX idx_snapshots_captured_at ON snapshots(captured_at);
```

#### change_records
```sql
CREATE TABLE change_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
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
    matched_keywords TEXT,                  -- JSON array
    matched_categories TEXT,                -- JSON array
    significance_notes TEXT,
    evidence_snippets TEXT,                 -- JSON array
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id_old) REFERENCES snapshots(id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id_new) REFERENCES snapshots(id) ON DELETE CASCADE
);
CREATE INDEX idx_change_records_company_id ON change_records(company_id);
```

#### company_statuses
```sql
CREATE TABLE company_statuses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    confidence REAL NOT NULL,
    indicators TEXT NOT NULL,           -- JSON array of StatusIndicator
    last_checked TEXT NOT NULL,
    http_last_modified TEXT,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);
```

#### social_media_links
```sql
CREATE TABLE social_media_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    profile_url TEXT NOT NULL,
    discovery_method TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    similarity_score REAL,
    discovered_at TEXT NOT NULL,
    last_verified_at TEXT,
    html_location TEXT,
    account_type TEXT,
    account_confidence REAL,
    rejection_reason TEXT,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    UNIQUE(company_id, profile_url)
);
CREATE INDEX idx_social_media_links_company_id ON social_media_links(company_id);
CREATE INDEX idx_social_media_links_platform ON social_media_links(platform);
```

Note: No CHECK constraints are used. Validation is handled at the Pydantic model layer.

#### blog_links
```sql
CREATE TABLE blog_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    blog_type TEXT NOT NULL,
    blog_url TEXT NOT NULL,
    discovery_method TEXT NOT NULL,
    is_active INTEGER DEFAULT 1,
    discovered_at TEXT NOT NULL,
    last_checked_at TEXT,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    UNIQUE(company_id, blog_url)
);
```

#### news_articles
```sql
CREATE TABLE news_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    content_url TEXT NOT NULL,
    source TEXT NOT NULL,
    published_at TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    match_confidence REAL NOT NULL,
    match_evidence TEXT,                    -- JSON array
    logo_similarity REAL,
    company_match_snippet TEXT,
    keyword_match_snippet TEXT,
    significance_classification TEXT,
    significance_sentiment TEXT,
    significance_confidence REAL,
    matched_keywords TEXT,                  -- JSON array
    matched_categories TEXT,                -- JSON array
    significance_notes TEXT,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    UNIQUE(content_url)
);
CREATE INDEX idx_news_articles_company_id ON news_articles(company_id);
CREATE INDEX idx_news_articles_published_at ON news_articles(published_at);
CREATE INDEX idx_news_articles_significance ON news_articles(significance_classification);
```

#### processing_errors
```sql
CREATE TABLE processing_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    retry_count INTEGER DEFAULT 0,
    occurred_at TEXT NOT NULL
);
```

#### company_logos
```sql
CREATE TABLE company_logos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    image_data BLOB NOT NULL,
    image_format TEXT NOT NULL,
    perceptual_hash TEXT NOT NULL,
    source_url TEXT NOT NULL,
    extraction_location TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    extracted_at TEXT NOT NULL,
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
    UNIQUE(company_id, perceptual_hash)
);
CREATE INDEX idx_company_logos_company_id ON company_logos(company_id);
CREATE INDEX idx_company_logos_perceptual_hash ON company_logos(perceptual_hash);
```

### 5.2 JSON Serialization Convention

List fields stored as JSON text in SQLite:
- `matched_keywords` -> `'["funding", "series a"]'`
- `matched_categories` -> `'["funding_investment"]'`
- `match_evidence` -> `'["domain_match", "name_context"]'`
- `indicators` -> `'[{"type": "copyright_year", "value": "2025", "signal": "positive"}]'`

---

## 6. Feature 001: Data Extraction and Snapshots

### 6.1 Company Extraction from Airtable

#### Use Case: Extract companies and store locally

**Happy Path:**
1. CLI command `extract-companies` invoked
2. Config loaded from `.env`
3. AirtableClient connects to the configured base
4. Fetches all records from "Online Presence" table
5. For each record with `resources` containing "homepage":
   a. Extract `url` field as homepage URL
   b. Resolve `company_name` field (which is a linked record pointer to "Portfolio Companies" table) to get the actual company name
6. Each company is upserted into SQLite (matched by name + URL unique constraint)
7. Summary printed: processed, stored, skipped, errors

**Unhappy Paths:**
- Missing `company_name` pointer: Record skipped, counted in "skipped"
- Invalid URL: Company stored with NULL homepage_url
- Airtable API error: Retried per retry config, then error logged
- Duplicate company (same name + URL): Upserted (updated, not duplicated)

#### Airtable Data Structure (Inferred)

**"Online Presence" table fields:**
- `url` (string): Website URL
- `resources` (multi-select/array): Resource types, must include "homepage"
- `company_name` (linked record): Pointer to "Portfolio Companies" table

**"Portfolio Companies" table:**
- Contains the resolved company name

#### AirtableClient Interface

```python
class AirtableClient:
    def __init__(self, api_key: str, base_id: str): ...
    def fetch_online_presence_records(self) -> list[dict]: ...
    def resolve_company_name(self, record_id: str) -> str | None: ...
```

### 6.2 Website Snapshot Capture

#### Use Case: Capture homepage snapshots (Sequential)

**Happy Path:**
1. CLI command `capture-snapshots` invoked
2. All companies with homepage URLs fetched from database
3. For each company:
   a. Firecrawl API `scrape()` called with `only_main_content=False` (CRITICAL)
   b. Returns markdown content, HTML content, metadata
   c. MD5 checksum computed from markdown content
   d. Snapshot stored in database with HTTP headers if available
4. Summary printed

**CRITICAL INVARIANT**: `only_main_content` MUST be `False`. Setting it to `True` causes 127% fewer social media links to be detected because social links are in headers/footers.

#### Use Case: Capture snapshots (Batch API)

**Happy Path:**
1. CLI command `capture-snapshots --use-batch-api` invoked
2. All companies with homepage URLs fetched
3. URLs grouped into batches (default size: 20, max: 1000)
4. Firecrawl batch API called per batch
5. Batch API handles parallel processing server-side (~8x faster)
6. Results polled until complete
7. Each result stored as snapshot
8. Summary printed

**Unhappy Paths:**
- Individual URL fails: Error logged, other URLs continue
- Batch API timeout: Retry with exponential backoff
- Rate limiting: Handled by tenacity retry decorator

#### FirecrawlClient Interface

```python
class FirecrawlClient:
    def __init__(self, api_key: str): ...

    def capture_snapshot(self, url: str) -> dict[str, Any]:
        """Scrape single URL. Uses only_main_content=False.
        Returns dict with: success, markdown, html, statusCode, has_paywall,
        has_auth_required, error."""

    def batch_capture_snapshots(
        self,
        urls: list[str],
        poll_interval: int = 2,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Batch scrape using Firecrawl batch API.
        Returns dict with: success, documents, total, completed, failed, errors."""

    def crawl_website(
        self,
        url: str,
        max_depth: int = 3,
        max_pages: int = 50,
        include_subdomains: bool = True,
    ) -> dict[str, Any]:
        """Crawl entire website for full-site discovery.
        Returns dict with: success, pages, total_pages, error."""
```

Note: `FirecrawlClient` returns raw dictionaries, not Pydantic models. The transformation to `Snapshot` models happens in `transformers.prepare_snapshot_data()`.

### 6.3 Checksum Computation

Pure function in `src/domains/monitoring/core/checksum.py`:

```python
def compute_content_checksum(content: str) -> str:
    """Compute MD5 hex digest of content string."""
    return hashlib.md5(content.encode("utf-8")).hexdigest()
```

---

## 7. Feature 002: Website Change Detection and Status Analysis

### 7.1 Change Detection

#### Use Case: Detect changes between snapshots

**Happy Path:**
1. CLI command `detect-changes` invoked
2. For each company with 2+ snapshots:
   a. Get latest two snapshots ordered by `captured_at`
   b. Compare checksums
   c. If checksums differ:
      - Calculate change magnitude (minor/moderate/major) using content similarity
      - Create ChangeRecord
      - Run significance analysis (see Section 10)
   d. Store ChangeRecord in database
3. Summary printed with counts of changes found

**Magnitude Calculation (SequenceMatcher):**
```
similarity = SequenceMatcher(None, old_content, new_content).ratio()
minor:    similarity >= 0.90 (< 10% changed)
moderate: similarity 0.50-0.90 (10-50% changed)
major:    similarity < 0.50 (> 50% changed)
```
For content > 50,000 characters, only the first 50k chars are compared to avoid excessive computation. This correctly detects when content is completely replaced with different text of similar length (unlike a length-delta approach).

**Unhappy Paths:**
- Company has < 2 snapshots: Skipped
- Checksums identical: ChangeRecord stored with `has_changed=False`
- Missing snapshot content: Error logged, company skipped

### 7.2 Status Analysis

#### Use Case: Determine company operational status

**Happy Path:**
1. CLI command `analyze-status` invoked
2. For each company with snapshots:
   a. Get latest snapshot content
   b. Extract indicators:
      - Copyright year (via regex pattern matching)
      - Acquisition keywords detection
      - HTTP Last-Modified header freshness
   c. Each indicator produces a signal (positive/negative/neutral)
   d. Calculate confidence score from indicators
   e. Determine status using decision rules
   f. Store CompanyStatus in database

**Status Determination Rules:**
```
High confidence (>= 0.7):
  - Any negative signals -> "likely_closed"
  - Otherwise -> "operational"
Medium confidence (0.4-0.7):
  - More positive than negative -> "operational"
  - More negative than positive -> "likely_closed"
  - Equal counts or all neutral -> "uncertain"
Low confidence (< 0.4):
  -> "uncertain"
```

**Confidence Scoring:**
```
+0.4 per positive indicator
+0.4 per negative indicator
+0.2 per neutral indicator
Clamped to [0.0, 1.0]
```

**Copyright Year Extraction:**
Patterns: `(c) YYYY`, `(C) YYYY`, `Copyright YYYY`, `© YYYY`. Supports year ranges (e.g., `© 2020-2025`). Returns the highest year found across all matches. Requires a copyright marker before the year (bare years are not matched).

**Acquisition Detection:**
Keywords: "acquired by", "merged with", "sold to", "now part of", "is now a subsidiary/division/part/unit/brand of" (the bare phrase "is now" without a corporate structure word is intentionally not matched to avoid false positives like "Product X is now available")

### 7.3 Query Commands

- `show-changes <company>`: Display change history with significance data and related news articles
- `show-status <company>`: Display current status with indicators
- `list-active --days N`: Companies with changes in last N days
- `list-inactive --days N`: Companies without changes in last N days
- `list-significant-changes --days N [--sentiment S]`: Significant changes, optionally filtered by sentiment
- `list-uncertain-changes`: Changes classified as UNCERTAIN requiring manual review

---

## 8. Feature 003: Social Media Discovery

### 8.1 Supported Platforms (12 + Blog)

| Platform | URL Patterns | Regex |
|----------|-------------|-------|
| LinkedIn | `linkedin.com/company/X`, `linkedin.com/in/X` | `linkedin\.com/(company\|in)/` |
| Twitter/X | `twitter.com/X`, `x.com/X` | `(twitter\|x)\.com/` |
| YouTube | `youtube.com/@X`, `youtube.com/channel/X`, `youtube.com/c/X` | `youtube\.com/(c/\|channel/\|@\|user/)` |
| Facebook | `facebook.com/X`, `fb.com/X`, `m.facebook.com/X` | `(facebook\|fb)\.com/` |
| Instagram | `instagram.com/X` | `instagram\.com/` |
| GitHub | `github.com/X` | `github\.com/[^/]+` |
| TikTok | `tiktok.com/@X` | `tiktok\.com/@` |
| Medium | `medium.com/@X`, `X.medium.com` | `medium\.com/@\|\.medium\.com` |
| Mastodon | `mastodon.social/@X`, `any-instance/@X` | `mastodon\.\|/@[a-zA-Z0-9_]+` |
| Threads | `threads.net/@X` | `threads\.net/@` |
| Pinterest | `pinterest.com/X` | `pinterest\.com/` |
| Bluesky | `bsky.app/profile/X` | `bsky\.app/profile/` |

### 8.2 Homepage Discovery (Default, Cost-Optimized)

#### Use Case: Discover social media from homepages using batch API

**Happy Path:**
1. CLI command `discover-social-media` invoked
2. All companies with homepage URLs fetched
3. URLs grouped into batches (default: 50, max: 1000)
4. Firecrawl batch API scrapes all homepages
5. For each scraped page:
   a. Extract links from markdown content
   b. Extract links from HTML using multiple strategies:
      - Standard `<a href>` tag extraction
      - Schema.org JSON-LD `sameAs` property
      - Meta tags (twitter:site, og:url)
      - Aria-labels and title attributes
      - Regex pattern matching across raw HTML
   c. Detect HTML region (footer/header/nav/main) for each link
   d. Detect blog links (blog subdomain or /blog path)
   e. Detect platform for each social media URL
   f. Normalize URLs to account level
   g. Deduplicate links per company
   h. Classify account type (company vs personal)
   i. Extract company logo for verification
   j. Compare logo hashes for verification
6. Store links in database
7. Summary printed per company and overall

**URL Normalization Rules:**
- GitHub: `github.com/org/repo` -> `github.com/org` (keep org only)
- LinkedIn: `linkedin.com/company/X/about/` -> `linkedin.com/company/X`
- Twitter/X: Remove trailing slash
- All platforms: Remove query parameters, lowercase, remove `www.`

**Link Extraction Strategies (in order):**
1. Markdown link extraction (from Firecrawl markdown output)
2. HTML `<a href>` tag parsing
3. Schema.org JSON-LD structured data
4. Twitter card and Open Graph meta tags
5. Aria-label/title attribute scanning
6. Regex pattern matching across full HTML

**Unhappy Paths:**
- Company has no homepage URL: Skipped
- Firecrawl API error: Error logged, company skipped
- No social links found: DiscoveryResult stored with empty links
- Logo extraction fails: Links stored without verification

### 8.3 Full-Site Discovery

#### Use Case: Deep discovery across entire website

**Happy Path:**
1. CLI command `discover-social-full-site --company-id X` invoked
2. `FullSiteSocialMediaDiscovery` service calls `FirecrawlClient.crawl_website()`
3. Firecrawl crawl API discovers and scrapes all pages on the website (including subdomains)
4. For each page: extract links using same strategies as homepage discovery
5. Links aggregated and deduplicated across all pages
6. Social media links filtered and stored with source page tracking

**Implementation Status:** This command is fully functional using the Firecrawl crawl API (`self.client.crawl()`). It does NOT use MCP. The separate MCP-based stubs (`FirecrawlMCPClient`, `RealFirecrawlMCPClient`) are unrelated and raise `NotImplementedError` -- they were intended for a different batch discovery approach via Claude Code orchestration.

### 8.4 Account Classification

The account classifier determines if a discovered social media link belongs to the company or is an unrelated account (investor, tool vendor, spam).

**Classification Signals:**
- Company name appears in account handle
- Account found in footer/header (higher confidence)
- Account found in main content (lower confidence - might be a mention)
- Logo perceptual hash similarity score

**Logo Comparison:**
Uses `imagehash` library for perceptual hashing (pHash). Two images are compared by Hamming distance between their hashes. Similarity score is computed as:
```
similarity = 1.0 - (hamming_distance / max_distance)
```

### 8.5 YouTube Video Resolution

When YouTube embed URLs (`/embed/VIDEO_ID`) are found, the system resolves them to channel URLs using the YouTube oEmbed API:
```
GET https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={VIDEO_ID}&format=json
```
The `author_url` field in the response gives the channel URL.

### 8.6 Blog Detection

Blog links are detected by:
1. **Subdomain patterns**: `blog.example.com`, `news.example.com`
2. **Path patterns**: `example.com/blog`, `example.com/news`
3. **Platform detection**: Medium, Substack, Ghost, WordPress, dev.to

Blog URLs are normalized to hub level:
- `blog.example.com/2024/01/post-title` -> `blog.example.com`
- `example.com/blog/category/post` -> `example.com/blog`
- `company.substack.com/p/article` -> `company.substack.com`

---

## 9. Feature 004: News Monitoring

### 9.1 News Search

#### Use Case: Search news for a single company

**Happy Path:**
1. CLI command `search-news --company-name "X"` (or `--company-id N`) invoked
2. Company details fetched from database
3. Date range calculated:
   - With 2+ snapshots: oldest snapshot date to now
   - Without snapshots: 90 days ago to now
4. Kagi Search API called with company name + date range
5. For each article returned:
   a. Check for duplicate URL in database
   b. Verify company match (multi-signal verification)
   c. Create NewsArticle model
   d. Analyze significance (reuses significance analysis system)
   e. Store in database
6. Summary printed: found, verified, stored

#### Use Case: Batch search all companies

**Happy Path:**
1. CLI command `search-news-all [--limit N]` invoked
2. All companies (or first N) fetched from database
3. For each company: run single-company search flow
4. Aggregate summary printed

### 9.2 Multi-Signal Company Verification

Articles must pass verification with >= 40% combined confidence to be stored.

**Verification Signals:**

| Signal | Weight | Description |
|--------|--------|-------------|
| Logo Match | 30% | Perceptual hash comparison between article image and company logo |
| Domain Match | 30% | Company's domain found in article URL or content |
| Name Context | 15% | Company name found in business context (not generic mention) |
| LLM Verification | 25% | Claude confirms article is about the same company |

**Verification Logic (Pure Functions):**
```python
def calculate_weighted_confidence(
    signals: dict[str, float],      # signal_name -> value (0.0 or 1.0)
    weights: dict[str, float],      # signal_name -> weight (e.g., 0.30)
) -> float:
    """Returns total weighted confidence score (0.0-1.0)."""

def build_evidence_list(
    logo_match: tuple[bool, float] | None,
    domain_match: bool,
    domain_name: str,
    context_match: bool,
    company_name: str,
    llm_match: tuple[bool, str] | None,
) -> list[str]:
    """Returns list of human-readable evidence strings."""
```

Default weights defined in `DEFAULT_VERIFICATION_WEIGHTS`:
```python
{"logo": 0.30, "domain": 0.30, "context": 0.15, "llm": 0.25}
```

**Domain Matching:** Uses regex word boundary matching to prevent false positives (e.g., `ai.com` matching inside `email.ai.common`). Pattern: `(?<![a-zA-Z0-9.\-]){domain}(?![a-zA-Z0-9\-])`.

**Threshold:** Article is verified if `confidence >= 0.40`

**Unhappy Paths:**
- No articles found: Zero-result response returned
- All articles fail verification: Zero stored, count reported
- Kagi API error (401): InvalidAPIKey error raised
- Kagi API error (429): Retried with exponential backoff (2s, 4s, 8s)
- Missing published date: Current datetime used as fallback
- Generic company name matches wrong entity: Low verification score filters it out

### 9.3 Kagi API Integration

**Endpoint:** `GET https://kagi.com/api/v0/search`

**Authentication:** Bearer token in Authorization header

**Query Format:**
```
{company_name} [business_description] after:YYYY-MM-DD before:YYYY-MM-DD
```

**Response Mapping:**
| Kagi Field | NewsArticle Field |
|-----------|------------------|
| `title` | `title` |
| `url` | `content_url` |
| `snippet` or `description` | article content |
| `published` or `t` | `published_at` |
| Extracted from `url` | `source` (domain name) |

**Retry Configuration:**
- Max attempts: 3
- Retry on: TimeoutError, ConnectionError, HTTP 429
- Backoff: Exponential (2s, 4s, 8s)

---

## 10. Significance Analysis System

This system classifies changes (website content changes or news articles) as SIGNIFICANT, INSIGNIFICANT, or UNCERTAIN.

### 10.1 Keyword Dictionaries

**Positive Keywords (7 categories, 60+ terms):**

| Category | Example Keywords |
|----------|-----------------|
| funding_investment | funding, raised, series a/b/c/d/e, venture capital, seed round, valuation, unicorn |
| product_launch | launched, new product, beta release, general availability, rollout |
| growth_success | revenue growth, profitable, milestone, ARR, MRR, doubled, tripled |
| partnerships | partnership, strategic alliance, joint venture, signed deal |
| expansion | expansion, new office, international, hiring, scale up, new market |
| recognition | award, winner, top 10, best of, innovation award |
| ipo_exit | ipo, going public, filed s-1, direct listing, nasdaq, nyse |

**Negative Keywords (9 categories, 60+ terms):**

| Category | Example Keywords |
|----------|-----------------|
| closure | shut down, closed down, ceased operations, discontinued, winding down |
| layoffs_downsizing | layoffs, downsizing, workforce reduction, job cuts, restructuring, furlough |
| financial_distress | bankruptcy, insolvent, chapter 11, cash crunch, debt crisis |
| legal_issues | lawsuit, litigation, investigation, settlement, fine, penalty |
| security_breach | data breach, hacked, cyberattack, ransomware, vulnerability |
| acquisition | acquired by, merged with, sold to, bought by, takeover |
| leadership_changes | ceo resigned, founder left, stepping down, ousted |
| product_failures | recall, discontinued product, defect, safety issue |
| market_exit | exiting market, pulling out, retreat, abandoned |

**Insignificant Patterns (3 categories):**

| Category | Patterns |
|----------|----------|
| css_styling | font-family, background-color, margin:, padding:, .css |
| copyright_year | `(c) YYYY`, `Copyright YYYY`, `all rights reserved` |
| tracking_analytics | google-analytics, gtag, tracking, pixel |

### 10.2 Classification Rules

1. **Only insignificant patterns + minor magnitude** -> INSIGNIFICANT (85% confidence)
2. **2+ negative keywords** -> SIGNIFICANT (80-95% confidence)
3. **2+ positive keywords** -> SIGNIFICANT (80-90% confidence)
4. **1 keyword + major magnitude** -> SIGNIFICANT (70% confidence)
5. **1 keyword + minor magnitude** -> UNCERTAIN (50% confidence)
6. **No keywords** -> INSIGNIFICANT (75% confidence)

### 10.3 Sentiment Classification

- 2+ positive AND 2+ negative -> MIXED
- 2+ negative only -> NEGATIVE
- 2+ positive only -> POSITIVE
- < 2 total keywords -> NEUTRAL

### 10.4 False Positive Detection

Certain keyword matches are false positives:
- "talent acquisition" (HR term, not company acquisition)
- "customer acquisition" (marketing term)
- "data acquisition" (technical term)
- "funding opportunities" / "funding sources" (informational)
- "self-funded" (bootstrap, not fundraising)

### 10.5 Negation Detection

Keywords preceded by negation words are flagged:
- "no [keyword]", "not [keyword]", "never [keyword]"
- "[keyword] status: none", "[keyword] date: N/A"
- "without [keyword]", "lacks [keyword]"

**Impact:** Negation reduces confidence by 20%. False positive reduces by 30%.

### 10.6 LLM Validation (Optional)

When `LLM_VALIDATION_ENABLED=true` and `ANTHROPIC_API_KEY` is set:

1. Keyword-based analysis runs first
2. Results sent to Claude for validation
3. LLM can confirm, override, or add nuance to keyword classification
4. LLM result takes precedence over keyword-only result

**LLM Prompt Structure:**
- System prompt defines the classification task
- Content of the change/article provided
- Detected keywords listed
- LLM returns structured JSON with classification, sentiment, confidence, reasoning

**Fallback:** If LLM call fails, keyword-based classification is used.

### 10.7 Backfill Support

Existing change records without significance data can be backfilled:

```bash
uv run airtable-extractor backfill-significance [--dry-run]
```

This finds all ChangeRecords with NULL significance fields, loads their snapshot content, and runs the analysis pipeline.

---

## 11. CLI Interface

Entry point: `airtable-extractor` (configured in pyproject.toml as `src.cli:cli`)

### 11.1 Command Reference

#### Data Extraction
```
airtable-extractor extract-companies
```
No options. Extracts all companies from Airtable.

#### Snapshot Capture
```
airtable-extractor capture-snapshots [--use-batch-api] [--batch-size N] [--timeout N]
```
- `--use-batch-api`: Use Firecrawl batch API (8x faster)
- `--batch-size N`: URLs per batch (default: 20, max: 1000)
- `--timeout N`: Timeout per batch in seconds (default: 300)

#### Change Detection
```
airtable-extractor detect-changes [--batch-size N] [--output-format FORMAT]
```
- `--batch-size N`: Companies per batch (default: 50)
- `--output-format`: Output format (summary/detailed/json, default: summary)

#### Status Analysis
```
airtable-extractor analyze-status [--batch-size N] [--confidence-threshold F] [--output-format FORMAT]
```
- `--batch-size N`: Companies per batch (default: 50)
- `--confidence-threshold F`: Minimum confidence 0.0-1.0 (default: 0.7)
- `--output-format`: Output format (summary/detailed/json, default: summary)

#### Social Media Discovery
```
airtable-extractor discover-social-media [--batch-size N] [--limit N] [--company-id ID]
```
- `--batch-size N`: Homepages per batch (default: 50)
- `--limit N`: Process first N companies
- `--company-id ID`: Single company (bypasses batching)

```
airtable-extractor discover-social-full-site --company-id ID [--max-depth N] [--max-pages N] [--include-subdomains/--no-subdomains]
```
- `--max-depth N`: Maximum crawl depth (default: 3)
- `--max-pages N`: Maximum pages to crawl (default: 50)
- `--include-subdomains/--no-subdomains`: Include subdomain pages (default: include)

```
airtable-extractor discover-social-batch [--company-ids IDS] [--limit N] [--batch-size N] [--max-workers N] [--scraping-parallelism N]
```
- `--company-ids IDS`: Comma-separated company IDs (e.g., "1,2,3")
- `--batch-size N`: Companies per database commit batch (default: 10)
- `--max-workers N`: Parallel workers (default: 5)
- `--scraping-parallelism N`: Page scraping parallelism per company (default: 10)

#### Significance Commands
```
airtable-extractor backfill-significance [--batch-size N] [--dry-run]
airtable-extractor list-significant-changes [--days N] [--sentiment S] [--min-confidence F]
airtable-extractor list-uncertain-changes [--limit N]
```
- `backfill-significance --batch-size N`: Records per batch (default: 100)
- `list-significant-changes --min-confidence F`: Minimum confidence threshold (default: 0.5)
- `list-uncertain-changes --limit N`: Maximum records to display (default: 50)

#### News Monitoring
```
airtable-extractor search-news --company-name NAME
airtable-extractor search-news --company-id ID
airtable-extractor search-news-all [--limit N]
```

#### Query Commands
```
airtable-extractor show-changes COMPANY_NAME
airtable-extractor show-status COMPANY_NAME
airtable-extractor list-active [--days N]
airtable-extractor list-inactive [--days N]
```

### 11.2 Output Format

All commands print to stdout. Status messages use bracketed prefixes:
- `[INFO]` - Informational
- `[WARNING]` - Warning
- `[ERROR]` - Error
- `[SUCCESS]` - Completion

No emojis. No colors. Plain text output suitable for piping.

---

## 12. External API Contracts

### 12.1 Airtable API

**Library:** pyairtable >= 3.2.0
**Auth:** Personal access token via `AIRTABLE_API_KEY`
**Base:** Identified by `AIRTABLE_BASE_ID`

**Operations:**
- `Table.all()` - Fetch all records from a table
- `Table.get(record_id)` - Fetch single record

**Rate Limits:** 5 requests per second per base (handled by pyairtable)

### 12.2 Firecrawl API v2

**Library:** firecrawl-py >= 4.5.0
**Auth:** API key via `FIRECRAWL_API_KEY`
**Class:** `from firecrawl import Firecrawl` (instantiated as `Firecrawl(api_key=api_key)`)

**Operations:**

Single scrape:
```python
client.scrape(
    url,
    formats=["markdown", "html"],
    only_main_content=False,   # CRITICAL: Must be False
    block_ads=False,
    wait_for=2000,             # Wait 2s for JavaScript rendering
    timeout=30000,             # 30s timeout per page
    proxy="stealth",           # Bypass anti-bot protections
    skip_tls_verification=True,
)
```
Returns: `Document` object with `.markdown`, `.html`, `.metadata`, `.warning`

Batch scrape:
```python
client.batch_scrape(
    urls=urls,
    formats=["markdown", "html"],
    only_main_content=False,   # CRITICAL: Must be False
    block_ads=False,
    wait_for=2000,
    timeout=30000,
    proxy="stealth",
    skip_tls_verification=True,
    poll_interval=poll_interval,
    wait_timeout=timeout,
)
```
Returns: `BatchScrapeJob` with `.data` (list of Documents), `.total`, `.completed`

Crawl (full-site):
```python
client.crawl(
    url=url,
    limit=max_pages,
    scrape_options={
        "formats": ["markdown", "html"],
        "only_main_content": False,
        "wait_for": 2000,
        "timeout": 30000,
    },
)
```
Returns: Crawl result with `.data` (list of pages)

### 12.3 Kagi Search API

**Library:** requests (direct HTTP)
**Auth:** Bearer token via `KAGI_API_KEY`
**Endpoint:** `GET https://kagi.com/api/v0/search`

**Request:**
```
Headers: Authorization: Bearer {api_key}
Params: q={query} after:{date} before:{date}, limit={N}
```

**Response:**
```json
{
    "meta": {"api_balance": 1.50, "ms": 245},
    "data": [
        {"title": "...", "url": "...", "snippet": "...", "published": "2024-01-15T10:30:00Z"}
    ]
}
```

### 12.4 Anthropic API

**Library:** anthropic >= 0.40.0
**Auth:** API key via `ANTHROPIC_API_KEY`
**Model:** Configurable. Config default: `claude-haiku-4-5-20251001`. LLMClient constructor default: `claude-haiku-4.5-20250924`. The Config value is passed to LLMClient at runtime, so the Config default takes precedence in normal usage.

**Operations:**
- `validate_significance()` - Validate keyword-based significance classification
- `validate_news_significance()` - Validate news article significance
- `verify_company_identity()` - Verify article is about the correct company

All three methods use `temperature=0.0` for deterministic results, and `max_tokens=500` for JSON responses. Retryable API exceptions (`APIConnectionError`, `APITimeoutError`, `APIStatusError`) are re-raised to propagate to the retry decorator; only non-retryable errors are caught and returned as UNCERTAIN results.

### 12.5 YouTube oEmbed API

**Endpoint:** `GET https://www.youtube.com/oembed`
**Params:** `url=https://www.youtube.com/watch?v={VIDEO_ID}&format=json`
**Response:** `{"author_url": "https://www.youtube.com/@channelname", ...}`
**Timeout:** 5 seconds
**No auth required.**

---

## 13. Error Handling and Retry Logic

### 13.1 Retry Decorator

```python
def retry_with_logging(max_attempts: int = 3):
    """Decorator using tenacity with structured logging.
    Uses @functools.wraps to preserve original function metadata."""
```

Default behavior:
- Exponential backoff: `wait_exponential(multiplier=1, min=2, max=10)` (starts at 2s, capped at 10s)
- Max 3 attempts (default; LLM methods and batch capture use `max_attempts=2`)
- Logs each retry with attempt number and error
- Retries on: `ConnectionError`, `TimeoutError`, `OSError`, and HTTP status codes 429/500/502/503/504

### 13.2 Error Categories

| Category | Handling | Examples |
|----------|---------|---------|
| Transient Network | Retry with backoff | ConnectionError, TimeoutError |
| Rate Limiting | Retry with longer backoff | HTTP 429 |
| Auth Failure | Fail immediately, log | HTTP 401 |
| Data Validation | Log and skip record | Invalid URL, missing fields |
| API Error | Log and skip operation | HTTP 5xx |
| Database Error | Rollback transaction, log | Constraint violation |

### 13.3 Batch Error Isolation

In batch operations, individual failures do not abort the batch:
- Each company/URL is processed independently
- Errors are accumulated in a list
- Summary reports total successes and failures
- Individual error details logged via structlog

### 13.4 ProcessingError Model

Failures can be stored for later analysis:
```python
ProcessingError(
    entity_type="company",  # or "snapshot"
    entity_id=42,
    error_type="FirecrawlTimeout",
    error_message="Request timed out after 30s",
    retry_count=2,
    occurred_at=datetime.now(UTC),
)
```

---

## 14. Testing Strategy

### 14.1 Test Structure

```
tests/
  conftest.py                 # Shared fixtures (temp DB, mock clients)
  unit/                       # Pure function tests (no I/O)
    core/
      test_result_aggregation.py
    test_account_classifier.py
    test_account_patterns.py
    test_checksum_utils.py
    test_company_model.py
    test_company_verifier.py
    test_config_kagi.py
    test_core_validators.py
    test_data_access.py
    test_duplicate_resolver.py
    test_firecrawl_crawl.py
    test_html_region_detector.py
    test_http_headers.py
    test_link_extraction.py
    test_llm_prompts.py
    test_llm_validation_models.py
    test_logo_comparison.py
    test_news_analyzer.py
    test_news_article_model.py
    test_platform_detection.py
    test_progress.py
    test_significance_analysis.py
    test_snapshot_model.py
    test_status_rules.py
    test_transformers.py
    test_validators.py
    test_verification_logic.py
  contract/                   # Service boundary tests (mocked I/O)
    test_airtable_batch.py
    test_airtable_contract.py
    test_batch_processor_contract.py
    test_change_record_repository_contract.py
    test_company_repository_contract.py
    test_company_status_repository_contract.py
    test_firecrawl_contract.py
    test_health_checks.py
    test_kagi_client.py
    test_llm_client_contract.py
    test_llm_client_news.py
    test_logo_service_contract.py
    test_news_article_repository_contract.py
    test_snapshot_repository_contract.py
    test_social_media_link_repository_contract.py
  integration/                # End-to-end workflow tests
    test_batch_snapshot_workflow.py
    test_duplicate_handling.py
    test_extraction_workflow.py
    test_llm_significance_integration.py
    test_paywall_detection.py
    test_significance_workflow.py
```

### 14.2 Test Categories

**Unit Tests (core/ functions):**
- Test pure functions with known inputs/outputs
- No mocking needed (no I/O)
- Fast execution
- Example: `test_significance_analysis.py` tests keyword detection, negation, classification

**Contract Tests (service boundaries):**
- Test repository and service interfaces
- Use temp SQLite databases (real DB, temp files)
- Mock external APIs (Airtable, Firecrawl, Kagi)
- Verify API call patterns and data flow

**Integration Tests (end-to-end flows):**
- Test complete workflows
- Use temp databases
- Mock only external HTTP calls
- Verify data flows from CLI through to database

### 14.3 Test Configuration

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-v --strict-markers"
```

### 14.4 Key Test Fixtures

```python
@pytest.fixture
def temp_db() -> Database:
    """Create temporary database with schema applied."""

@pytest.fixture
def mock_firecrawl() -> Mock:
    """Mock FirecrawlClient with configurable responses."""

@pytest.fixture
def mock_airtable() -> Mock:
    """Mock AirtableClient with sample records."""
```

### 14.5 Test Counts

As of last run: **717 passing, 0 failing, 0 errors (100% pass rate)**

---

## 15. Migration Strategy

Migrations are standalone Python scripts in `scripts/`:

| Script | Purpose |
|--------|---------|
| `migrate_add_checksums.py` | Add checksum columns to snapshots |
| `migrate_add_social_media.py` | Create social_media_links table |
| `migrate_add_blog_platform.py` | Add 'blog' to platform CHECK constraint |
| `migrate_add_link_filtering_fields.py` | Add html_location, account_type, etc. |
| `migrate_normalize_social_urls.py` | Normalize existing URLs to Airtable format |
| `migrate_add_news_articles.py` | Create news_articles table |

SQL migration in `migrations/`:
| File | Purpose |
|------|---------|
| `003_add_blog_links_table.sql` | Create blog_links table |

### Migration Pattern

1. Check if migration already applied (e.g., column exists)
2. Apply changes in a transaction
3. Rollback on any error
4. Support `--dry-run` flag where applicable
5. Print summary of changes

### SQLite CHECK Constraint Workaround

SQLite does not support `ALTER TABLE ... MODIFY CONSTRAINT`. To change CHECK constraints:
1. Create new table with updated constraint
2. Copy all data from old table
3. Drop old table
4. Rename new table
5. Recreate all indexes

---

## 16. Constraints and Invariants

### 16.1 Critical Invariants

1. **`only_main_content=False`** in ALL Firecrawl scrape calls. This is non-negotiable. Social media links are in headers/footers (90%+ of cases).

2. **Unique constraints** enforce data integrity:
   - `companies(name, homepage_url)` - No duplicate companies
   - `social_media_links(company_id, profile_url)` - No duplicate links per company (platform not included)
   - `news_articles(content_url)` - No duplicate article URLs (globally unique, not per-company)
   - `blog_links(company_id, blog_url)` - No duplicate blogs per company
   - `company_logos(company_id, perceptual_hash)` - No duplicate logo hashes per company

3. **Foreign keys** with `ON DELETE CASCADE` ensure referential integrity when companies are removed.

4. **Checksums** are always lowercase hex MD5 strings.

5. **Datetime handling**: All datetimes stored as ISO 8601 strings in SQLite. Python uses `datetime` with `UTC` timezone.

### 16.2 Performance Characteristics

| Operation | Sequential | Batch API |
|-----------|-----------|-----------|
| 761 company snapshots | ~2 hours | ~16 minutes |
| Social media discovery (761) | ~3 hours | ~45 minutes |
| Change detection | ~5 minutes | N/A |
| News search (all) | ~30 minutes | N/A |

### 16.3 Cost Considerations

- **Firecrawl**: Batch API significantly cheaper than individual scraping
- **Kagi**: Usage-based pricing, use `--limit` for testing
- **Anthropic**: Only used when `LLM_VALIDATION_ENABLED=true`

### 16.4 Data Retention

- Snapshots: All snapshots retained indefinitely (for historical comparison)
- Change records: All records retained
- Social media links: Accumulated over time, deduplication on insert
- News articles: Deduplicated by URL per company

### 16.5 Known Limitations

1. **MCP Integration Incomplete**: `FirecrawlMCPClient` and `RealFirecrawlMCPClient` raise `NotImplementedError`. Full-site discovery via MCP requires Claude Code environment orchestration.

2. **No Scheduled Execution**: The system is CLI-only, no cron/scheduler integration.

3. **No URL Shortener Resolution**: Short URLs (`t.co`, `bit.ly`) are not resolved.

4. **Single-threaded CLI**: The CLI itself is synchronous. Batch parallelism is handled by APIs (Firecrawl batch) or ThreadPoolExecutor (within services).

5. **No Business Description Field**: The Company model lacks a `business_description` field, which would improve news verification accuracy.

6. **SQLite Single-Writer**: SQLite supports only one writer at a time. Concurrent writes from multiple processes will fail.
