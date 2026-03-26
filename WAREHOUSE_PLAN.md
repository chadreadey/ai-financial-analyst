# WAREHOUSE_PLAN.md — Persistent Filing Warehouse Implementation Plan

## Overview

This plan adds a persistent filing warehouse to the AI Financial Analyst platform. The warehouse stores SEC filings, XBRL facts, market prices, and macro data in SQLite, enabling any ticker to be bootstrapped on demand, change-detected incrementally, and read by agents as a first-tier data source before falling back to live fetching.

The plan is organized into four phases. Each phase is independently deliverable and non-breaking.

---

## Architectural Principles

Before any phase begins, lock in these invariants:

**Thread safety.** The existing `SECCache` stores `self._conn` as an instance attribute created in `__init__`. The new `WarehouseDB` must never store a connection as an instance attribute. Every public method must call `sqlite3.connect()` at entry and close it at exit (or use a context manager). This matches the constraint already documented in `sec/cache.py`.

**Feature flag.** Every warehouse code path is gated on `ENABLE_WAREHOUSE=true`. When false, the system behaves identically to today.

**Graceful fallback.** If the warehouse is unavailable, corrupted, or missing a ticker, the pipeline falls back to the current live-fetch path. Agents must never raise on a warehouse miss.

**No new infrastructure.** SQLite only. No Postgres, no Redis. Streamlit Cloud compatible.

**ENABLE_* pattern.** New env vars follow the existing pattern in `config.py` (Pydantic `BaseSettings` field, snake_case, `bool` type with `False` default, readable via `settings.enable_warehouse`). However, use `os.getenv()` at call sites in `orchestrator.py` — not `settings.enable_warehouse` — because `settings` is instantiated at import time before Streamlit's `_set_runtime_env()` has run.

---

## Phase 1 — Warehouse Schema + Bootstrap Ingestion

**Goal:** Create the persistent database file, define its schema, and provide a function that fully bootstraps any ticker from cold state.

### 1.1 New File: `warehouse/db.py`

Core module. Owns schema creation, all write operations, and all read operations. Never stores a connection as state.

**Interface sketch:**
```
class WarehouseDB:
    def __init__(self, db_path: str = ".warehouse.db")
    def _connect(self) -> sqlite3.Connection   # creates fresh connection each call
    def _init_schema(self) -> None             # idempotent CREATE TABLE IF NOT EXISTS

    # writes
    def upsert_company(self, ticker, cik, name, last_accession) -> None
    def upsert_filing(self, ticker, accession, form, filing_date, primary_doc) -> None
    def upsert_xbrl_fact(self, ticker, concept, unit, period_end, value, form, fiscal_year, fiscal_period) -> None
    def upsert_market_snapshot(self, ticker, as_of_date, price, market_cap, pe_ttm, forward_pe, beta, ...) -> None
    def upsert_macro_series(self, series_id, label, as_of_date, value) -> None
    def upsert_filing_section(self, ticker, accession, section_key, text) -> None

    # reads
    def get_company(self, ticker) -> Optional[dict]
    def get_filings(self, ticker, form_types=None, limit=10) -> list[dict]
    def get_xbrl_facts(self, ticker, concepts=None) -> list[dict]
    def get_market_snapshot(self, ticker) -> Optional[dict]
    def get_macro_series(self, series_ids=None) -> list[dict]
    def get_filing_section(self, ticker, accession, section_key) -> Optional[str]
    def get_latest_accession(self, ticker) -> Optional[str]
    def list_tracked_tickers(self) -> list[str]
```

**Schema (all tables in `.warehouse.db`):**
```sql
-- Master company registry
CREATE TABLE IF NOT EXISTS companies (
    ticker          TEXT PRIMARY KEY,
    cik             TEXT NOT NULL,
    name            TEXT NOT NULL,
    last_accession  TEXT,
    bootstrapped_at REAL,
    last_checked_at REAL
);

-- Filing index
CREATE TABLE IF NOT EXISTS filings (
    ticker          TEXT NOT NULL,
    accession       TEXT NOT NULL,
    form            TEXT NOT NULL,
    filing_date     TEXT NOT NULL,
    primary_doc     TEXT NOT NULL DEFAULT '',
    ingested_at     REAL NOT NULL,
    PRIMARY KEY (ticker, accession)
);

-- XBRL facts (normalized, one row per concept-period)
CREATE TABLE IF NOT EXISTS xbrl_facts (
    ticker          TEXT NOT NULL,
    concept         TEXT NOT NULL,
    unit            TEXT NOT NULL,
    period_end      TEXT NOT NULL,
    value           REAL NOT NULL,
    form            TEXT,
    fiscal_year     INTEGER,
    fiscal_period   TEXT,
    filed_date      TEXT,
    ingested_at     REAL NOT NULL,
    PRIMARY KEY (ticker, concept, unit, period_end, form)
);

-- Market data snapshots
CREATE TABLE IF NOT EXISTS market_snapshots (
    ticker          TEXT NOT NULL,
    as_of_date      TEXT NOT NULL,
    price           REAL,
    market_cap      REAL,
    pe_ttm          REAL,
    forward_pe      REAL,
    ps_ttm          REAL,
    ev_ebitda       REAL,
    beta            REAL,
    week52_high     REAL,
    week52_low      REAL,
    target_mean     REAL,
    recommendation  TEXT,
    ingested_at     REAL NOT NULL,
    PRIMARY KEY (ticker, as_of_date)
);

-- Macro time series (FRED)
CREATE TABLE IF NOT EXISTS macro_series (
    series_id       TEXT NOT NULL,
    label           TEXT NOT NULL,
    as_of_date      TEXT NOT NULL,
    value           REAL NOT NULL,
    ingested_at     REAL NOT NULL,
    PRIMARY KEY (series_id, as_of_date)
);

-- Filing narrative sections (MDA, risk factors, business description)
CREATE TABLE IF NOT EXISTS filing_sections (
    ticker          TEXT NOT NULL,
    accession       TEXT NOT NULL,
    section_key     TEXT NOT NULL,   -- 'mda', 'risk_factors', 'business_description'
    text            TEXT NOT NULL,
    ingested_at     REAL NOT NULL,
    PRIMARY KEY (ticker, accession, section_key)
);
```

**Key implementation notes:**
- Use `PRAGMA journal_mode=WAL` on every connection (matches existing `sec/cache.py` pattern)
- Use `INSERT OR REPLACE` / `ON CONFLICT DO UPDATE` throughout for idempotent upserts
- `xbrl_facts` denormalizes what `XBRLParser._extract_concept()` currently returns as DataFrames — avoids re-parsing JSON blobs at query time
- `filing_sections` stores already-trimmed text (respecting existing `context_budget` limits) so retrieval is plug-in-ready for agents

### 1.2 New File: `warehouse/bootstrap.py`

Single entry point for full cold-start ingestion of a ticker.

**Interface sketch:**
```
def bootstrap_ticker(
    ticker: str,
    db: WarehouseDB,
    sec_client: SECClient,
    form_types: list[str] = ["10-K", "10-Q", "8-K"],
    filing_limit: int = 20,
) -> BootstrapResult:
    """
    1. Resolve CIK via sec_client
    2. Fetch submissions (filing index)
    3. Fetch XBRL company facts (all history, one call)
    4. Parse XBRL facts with XBRLParser; write each concept row to xbrl_facts
    5. Write filing index rows to filings
    6. If ENABLE_FILING_TEXT: fetch and parse 10-K sections; write to filing_sections
    7. Write company row with last_accession = most recent accession found
    Returns BootstrapResult(ticker, filing_count, fact_count, sections_extracted, elapsed_s)
    """
```

**XBRL ingestion detail:** Iterate over `XBRLParser.INCOME_STATEMENT_CONCEPTS + BALANCE_SHEET_CONCEPTS + CASH_FLOW_CONCEPTS`, call `_extract_concept()` for each, write each row. Mirrors existing parser logic exactly.

### 1.3 New File: `warehouse/__init__.py`

Exports `WarehouseDB` and `bootstrap_ticker` for clean imports.

### 1.4 Files to Modify

**`config.py`** — add to `Settings`:
```
enable_warehouse: bool = False
warehouse_db_path: str = ".warehouse.db"
warehouse_filing_limit: int = 20
warehouse_market_ttl_hours: int = 4
warehouse_macro_ttl_hours: int = 24
```

**`pyproject.toml`** — add `warehouse` to `packages` list under `[tool.setuptools]`.

**`requirements.txt`** — no new dependencies (all existing deps cover Phase 1).

### 1.5 New Env Vars
```
ENABLE_WAREHOUSE=true
WAREHOUSE_DB_PATH=.warehouse.db          # optional
WAREHOUSE_FILING_LIMIT=20                # optional
WAREHOUSE_MARKET_TTL_HOURS=4             # optional
WAREHOUSE_MACRO_TTL_HOURS=24             # optional
```

### 1.6 Verification
```bash
python -c "
from warehouse.db import WarehouseDB
from warehouse.bootstrap import bootstrap_ticker
from sec.client import SECClient

db = WarehouseDB()
result = bootstrap_ticker('AAPL', db, SECClient())
print(result)
print(db.list_tracked_tickers())          # ['AAPL']
print(len(db.get_xbrl_facts('AAPL')))    # 100+
print(len(db.get_filings('AAPL')))       # 10+
"
```

### 1.7 Integration Risks
- **Concurrent Streamlit sessions writing simultaneously.** WAL mode handles this safely up to ~10 concurrent writers. The per-call connection pattern prevents connection-sharing issues. Risk: low.
- **Bootstrap duration.** Full AAPL bootstrap takes 3-8s. Must run in background (via `asyncio.to_thread`) — never block the analysis pipeline synchronously.
- **XBRL concept coverage.** Only concepts in the three concept lists are stored. Any concept accessed outside those lists still requires a live parse. Risk: low given current agent inputs.

---

## Phase 2 — Change Detection + Incremental Updates

*Depends on: Phase 1*

**Goal:** Poll SEC's `/submissions/{CIK}.json`, compare latest accession against stored `last_accession`, and re-ingest only when new filings have appeared.

### 2.1 New File: `warehouse/change_detector.py`

```
def get_latest_accession_from_sec(ticker: str, sec_client: SECClient) -> Optional[str]:
    """
    Fetch submissions for ticker, return the first (most recent) accessionNumber.
    Bypasses SECCache TTL — uses a direct HTTP call to get fresh state.
    """

def needs_update(ticker: str, db: WarehouseDB, sec_client: SECClient) -> bool:
    """
    Returns True if:
    - company is not bootstrapped (None in companies table), OR
    - latest SEC accession != stored last_accession, OR
    - last_checked_at is older than WAREHOUSE_CHECK_INTERVAL_HOURS
    """

def incremental_update(
    ticker: str,
    db: WarehouseDB,
    sec_client: SECClient,
    form_types: list[str] = ["10-K", "10-Q", "8-K"],
) -> UpdateResult:
    """
    1. Call needs_update(); return early if no change
    2. Fetch new filings since stored last_accession
    3. For each new accession:
       a. Upsert filing row
       b. If 10-K or 10-Q: re-fetch company_facts endpoint (full history, one call)
          and upsert all xbrl_fact rows
       c. If ENABLE_FILING_TEXT and 10-K: fetch + parse filing sections
    4. Update companies.last_accession + last_checked_at
    Returns UpdateResult(ticker, had_changes, new_filing_count, elapsed_s)
    """
```

**Change detection detail:** The submissions endpoint returns filings in reverse-chronological order. `accessionNumber[0]` is the most recent. Compare against `companies.last_accession` — string equality, no parsing required.

**XBRL re-ingestion strategy:** When a new 10-K or 10-Q appears, re-fetch the full `company_facts` endpoint (always returns complete history) and upsert all rows. `ON CONFLICT DO UPDATE` makes this idempotent. Simpler and safer than delta ingestion.

**Important:** `get_latest_accession_from_sec()` must bypass the 24-hour `SECCache` TTL. Use a direct `requests.get()` call (not `sec_client.get_submissions()`) so change detection always reflects the true current SEC state.

### 2.2 New File: `warehouse/scheduler.py`

Batch refresh loop for CLI/cron use (not used by Streamlit directly):

```
def run_refresh_cycle(
    tickers: list[str],
    db: WarehouseDB,
    sec_client: SECClient,
    dry_run: bool = False,
) -> dict[str, UpdateResult]:
    """Run incremental_update for each ticker in sequence. Returns summary dict."""
```

### 2.3 Files to Modify

**`warehouse/db.py`** — add `update_last_checked(ticker, accession)` method.

**`config.py`** — add `warehouse_check_interval_hours: int = 6`.

### 2.4 New Env Vars
```
WAREHOUSE_CHECK_INTERVAL_HOURS=6
```

### 2.5 Verification
```bash
# After Phase 1 bootstrap of AAPL:
python -c "
from warehouse.db import WarehouseDB
from warehouse.change_detector import needs_update, incremental_update
from sec.client import SECClient
import sqlite3

db = WarehouseDB()
client = SECClient()

print('needs_update (should be False):', needs_update('AAPL', db, client))

# Force stale accession
conn = sqlite3.connect('.warehouse.db')
conn.execute(\"UPDATE companies SET last_accession='0000000000-00-000000' WHERE ticker='AAPL'\")
conn.commit(); conn.close()

print('needs_update after forcing stale (should be True):', needs_update('AAPL', db, client))
result = incremental_update('AAPL', db, client)
print('result:', result)
"
```

### 2.6 Integration Risks
- **Submissions endpoint TTL conflict.** `sec_client.get_submissions()` caches with 24-hour TTL. Change detection must bypass this with a direct HTTP call. This is the one exception to using the existing client abstraction.
- **Concurrent update calls.** Two Streamlit sessions updating the same ticker simultaneously will both upsert the same rows — safe via `ON CONFLICT DO UPDATE`.
- **Empty accession arrays.** Guard with `if not accession_list: return None` for unusual companies.

---

## Phase 3 — Agent Integration (Warehouse-First with Live Fallback)

*Depends on: Phase 1. Enhanced by Phase 2.*

**Goal:** Agents read structured data from the warehouse instead of fetching live. Falls back transparently to the current live path on warehouse miss.

### 3.1 New File: `warehouse/reader.py`

Translates warehouse rows into existing `AnalysisData` structures. Keeps warehouse concerns out of `orchestrator.py` and agents.

```
def build_analysis_data_from_warehouse(
    ticker: str,
    db: WarehouseDB,
) -> Optional[AnalysisData]:
    """
    Attempts to build AnalysisData from warehouse rows.
    Returns None if ticker untracked or critical data missing.

    Populates from warehouse:
    - metrics: reconstructed from xbrl_facts rows
    - recent_filings: from filings table
    - historical_revenue, historical_net_income: from xbrl_facts
    - margin_trends, cash_flow_trends: derived from xbrl_facts
    - quarterly_metrics: xbrl_facts where form='10-Q'
    - financial_core_summary: XBRLParser.to_summary_text() on reconstructed metrics
    - enrichment_sections.filing_mda, filing_risk_factors, filing_business:
        from filing_sections table (latest 10-K accession)

    Does NOT populate (always fetched live, unchanged):
    - enrichment_sections.market_data (Yahoo — real-time by design)
    - enrichment_sections.external_*/industry/risks (Tavily)
    - enrichment_sections.rag_research (Qdrant)
    """

def get_market_snapshot_for_context(
    ticker: str,
    db: WarehouseDB,
    max_age_hours: int = 4,
) -> Optional[str]:
    """Returns formatted market section if fresh enough; None triggers live Yahoo fetch."""

def get_macro_for_context(
    db: WarehouseDB,
    max_age_hours: int = 24,
) -> Optional[str]:
    """Returns formatted macro section if fresh enough; None triggers live FRED fetch."""
```

**Metrics reconstruction:** `build_analysis_data_from_warehouse()` queries `xbrl_facts` grouped by concept and reconstructs the metrics dict. Mirrors `XBRLParser.compute_metrics()` but operates on normalized rows, not raw JSON. This is arithmetic, not JSON parsing — fast and correct.

### 3.2 Files to Modify

**`orchestrator.py` — `prepare_data()` method**

Wrap the existing live-fetch path with a warehouse-first branch at the top. Preserve the existing `ThreadPoolExecutor` overlap with `build_enrichment_context`:

```python
def prepare_data(self, ticker: str) -> AnalysisData:
    # NEW: warehouse-first path
    if os.getenv("ENABLE_WAREHOUSE", "").lower() == "true":
        try:
            db = WarehouseDB()
            company = db.get_company(ticker)
            if company is None:
                logger.info("Warehouse: bootstrapping %s...", ticker)
                bootstrap_ticker(ticker, db, self.sec_client)
            elif needs_update(ticker, db, self.sec_client):
                logger.info("Warehouse: updating %s...", ticker)
                incremental_update(ticker, db, self.sec_client)

            data = build_analysis_data_from_warehouse(ticker, db)
            if data is not None:
                # Still fetch real-time enrichment (Yahoo, Tavily, RAG) in parallel
                # [existing ThreadPoolExecutor enrichment call here]
                return data
        except Exception as exc:
            logger.warning("Warehouse read failed, falling back to live: %s", exc)

    # EXISTING live-fetch path — unchanged
    logger.info("Fetching SEC data for %s...", ticker.upper())
    ...
```

**Critical:** Use `os.getenv("ENABLE_WAREHOUSE")` not `settings.enable_warehouse` in `orchestrator.py` — `settings` is instantiated at import time.

**`market_enrichment.py` — `_task_macro()` and optionally `_task_yahoo()`**

Add warehouse check before live fetch in each task:
```python
# In _task_macro():
if os.getenv("ENABLE_WAREHOUSE", "").lower() == "true":
    cached = get_macro_for_context(db, max_age_hours=...)
    if cached:
        return {"section_entries": [("macro_data", cached)], "sources": ["Warehouse"]}
# existing live FRED fetch unchanged below
```

### 3.3 Verification
```bash
# After Phase 1 bootstrap of AAPL:
ENABLE_WAREHOUSE=true python main.py AAPL 2>&1 | grep -E "(Warehouse|Fetching SEC)"
# Expected: "Warehouse: reading" present; "Fetching SEC data for AAPL" absent

# Test fallback:
ENABLE_WAREHOUSE=false python main.py AAPL 2>&1 | grep "Fetching SEC"
# Expected: live fetch runs normally

# Test auto-bootstrap of unknown ticker:
ENABLE_WAREHOUSE=true python main.py TSLA 2>&1 | grep "bootstrapping"
# Expected: bootstrap message visible; analysis completes successfully
```

### 3.4 Integration Risks
- **Metrics reconstruction drift.** If `XBRLParser.compute_metrics()` changes in the future, `warehouse/reader.py` could diverge. Mitigation: add a `metrics_json` blob column to `companies` as a read cache, refreshed on each bootstrap/update. Implement in a follow-on iteration.
- **AnalysisData field completeness.** `build_analysis_data_from_warehouse()` must populate all required fields. `ticker` and `company_name` come from `companies` table. All `list` fields default to `[]` — validate this doesn't break agent prompts.
- **ThreadPoolExecutor overlap.** The warehouse read path is synchronous. Must ensure the `ThreadPoolExecutor` overlap with `build_enrichment_context()` is preserved even when taking the warehouse path.

---

## Phase 4 — On-Demand Company Onboarding Flow (UI + CLI)

*Depends on: Phase 3*

**Goal:** First-time bootstrap is visible and non-blocking in the UI. Any ticker works automatically.

### 4.1 Files to Modify

**`app.py` — `_run_analysis_sync()`**

Add bootstrap detection before pipeline runs:
```python
def _run_analysis_sync(ticker, user_agent, provider, model, progress) -> AnalysisResult:
    if os.getenv("ENABLE_WAREHOUSE", "").lower() == "true":
        db = WarehouseDB()
        if db.get_company(ticker.upper()) is None:
            progress.write(f"First time analyzing {ticker.upper()} — bootstrapping warehouse (~10s)...")
            bootstrap_ticker(ticker.upper(), db, SECClient(user_agent=user_agent))
            progress.write("Bootstrap complete. Running analysis...")

    # existing pipeline unchanged below
    cache = SECCache()
    ...
```

**`app.py` — sidebar**

Add a collapsible sidebar section (visible only when `ENABLE_WAREHOUSE=true`) showing:
- Number of tracked tickers
- Last bootstrap/update timestamp for current ticker
- "Force refresh" button that calls `incremental_update()` immediately

This is additive — does not modify the existing history panel or analysis display.

### 4.2 New File: `warehouse/cli.py`

CLI for manual warehouse operations (development, pre-warming before deploy, cron):

```
Commands:
  bootstrap TICKER [TICKER...]     Bootstrap one or more tickers
  refresh [TICKER...]              Run incremental update for tracked tickers (all if none given)
  status                           Print tracked tickers, last bootstrap, last check, filing counts
  drop TICKER                      Remove a ticker (forces re-bootstrap on next run)

Usage:
  python -m warehouse.cli bootstrap AAPL MSFT GOOGL NVDA META
  python -m warehouse.cli refresh
  python -m warehouse.cli status
```

This is the primary tool for pre-warming the warehouse before deploying to Streamlit Cloud.

### 4.3 Verification (End-to-End)

```bash
# Clean state
rm -f .warehouse.db

# Bootstrap via CLI
ENABLE_WAREHOUSE=true python -m warehouse.cli bootstrap AAPL

# Check status
ENABLE_WAREHOUSE=true python -m warehouse.cli status
# Expected: AAPL listed, bootstrapped_at recent, 100+ facts

# Full analysis from warehouse
ENABLE_WAREHOUSE=true python main.py AAPL 2>&1 | grep -E "(Warehouse|Fetching SEC)"
# Expected: warehouse path used; live SEC fetch skipped

# New ticker auto-bootstrap
ENABLE_WAREHOUSE=true python main.py TSLA 2>&1 | grep "bootstrapping"
# Expected: auto-bootstrap visible; analysis completes

# Change detection (no changes expected)
ENABLE_WAREHOUSE=true python -m warehouse.cli refresh AAPL
# Expected: had_changes=False

# Disable warehouse — clean fallback
ENABLE_WAREHOUSE=false python main.py AAPL 2>&1 | grep "Fetching SEC"
# Expected: live fetch path runs normally
```

### 4.4 Integration Risks
- **Streamlit Cloud file persistence.** `.warehouse.db` is wiped on each deploy. The warehouse is a session-level cache on Streamlit Community Cloud — not a true persistent store. Pre-warm via `warehouse/cli.py` as a deploy step, or document that first runs will bootstrap. For persistent storage, mount to a volume.
- **Bootstrap race in Streamlit.** Two concurrent reruns may both detect a ticker as untracked. Set `bootstrapping_at` timestamp at bootstrap start and check for it to prevent concurrent attempts. Both upserts produce identical rows so correctness is maintained regardless.
- **Large XBRL payloads.** Conglomerates (GE, JNJ) may return 5-10MB from `company_facts`. Ensure `requests.get()` has a 60s timeout in the bootstrap path — `SECClient._get()` may not have one set.

---

## Phase Dependency Map

```
Phase 1 (Schema + Bootstrap)
    │
    ├── Phase 2 (Change Detection)    ← buildable independently of Phase 3
    │       │
    │       └── Phase 3 (Agent Integration)   ← first phase touching orchestrator.py
    │               │
    │               └── Phase 4 (UI + CLI)    ← first phase touching app.py
```

Phases 1 and 2 can be built and tested with zero changes to the analysis pipeline. Phase 3 is the first modification to `orchestrator.py`. Phase 4 is the only modification to `app.py`.

---

## Full File Inventory

### New Files

| File | Purpose |
|------|---------|
| `warehouse/__init__.py` | Package init; exports `WarehouseDB`, `bootstrap_ticker` |
| `warehouse/db.py` | Core warehouse class; schema; all read/write operations |
| `warehouse/bootstrap.py` | Full cold-start ingestion for any ticker |
| `warehouse/change_detector.py` | SEC submissions comparison; incremental update |
| `warehouse/scheduler.py` | Batch refresh loop for CLI/cron |
| `warehouse/reader.py` | Translates warehouse rows into `AnalysisData` structures |
| `warehouse/cli.py` | `python -m warehouse.cli` entry point |

### Modified Files

| File | Change |
|------|--------|
| `config.py` | Add `enable_warehouse`, `warehouse_db_path`, TTL, and limit fields to `Settings` |
| `orchestrator.py` | Wrap `prepare_data()` with warehouse-first path + auto-bootstrap + incremental update |
| `market_enrichment.py` | Add warehouse-first check in `_task_macro()` and optionally `_task_yahoo()` |
| `app.py` | Add bootstrap spinner in `_run_analysis_sync()`; add sidebar warehouse status panel |
| `pyproject.toml` | Add `warehouse` to packages list |
| `requirements.txt` | No new dependencies required |

---

## New Environment Variables — Complete Reference

| Variable | Default | Phase | Purpose |
|----------|---------|-------|---------|
| `ENABLE_WAREHOUSE` | `false` | 1 | Master feature flag |
| `WAREHOUSE_DB_PATH` | `.warehouse.db` | 1 | SQLite file path |
| `WAREHOUSE_FILING_LIMIT` | `20` | 1 | Filings to ingest per bootstrap |
| `WAREHOUSE_MARKET_TTL_HOURS` | `4` | 1 | Max age for market snapshot before live re-fetch |
| `WAREHOUSE_MACRO_TTL_HOURS` | `24` | 1 | Max age for macro series before live re-fetch |
| `WAREHOUSE_CHECK_INTERVAL_HOURS` | `6` | 2 | Min interval between change-detection checks |

---

## Rollback Strategy

`ENABLE_WAREHOUSE=false` is the default. The live-fetch path in `orchestrator.py` is preserved unchanged inside an `else`/`except` branch. Disabling requires only setting `ENABLE_WAREHOUSE=false` or removing the env var. The `.warehouse.db` file can remain in place — it has no effect when the flag is off. No migrations required to disable.
