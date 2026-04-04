# RAG Freshness Plan

Closes the two gaps between the filing warehouse and a production-ready,
always-fresh Pinecone index.

- **Step 1** — Extract 10-Q narrative sections so RAG has current-quarter earnings context
- **Step 2** — Re-seed Pinecone automatically whenever the refresh cycle detects new filings

Both steps are self-contained and can be implemented independently.

---

## Background

The warehouse currently extracts narrative sections from annual 10-K filings only
(`mda`, `risk_factors`, `business_description`, `market_risk`, `legal_proceedings`,
`properties`). The incremental update pipeline (`change_detector.incremental_update`)
detects new 8-K and 10-Q filings and re-ingests XBRL facts, but:

1. It does not extract narrative text from 10-Q filings.
2. It does not re-seed Pinecone after finding changes.

The result: after an earnings release, XBRL numbers update but RAG still returns
stale annual-report prose. These two steps fix that.

---

## Step 1 — 10-Q Section Extraction

### Why

The MD&A in a 10-Q ("Results of Operations") is management's discussion of *this
quarter's* earnings — revenue vs. expectations, margin commentary, updated guidance.
This is the highest-signal narrative text for trading and portfolio decisions and is
published within 45 days of quarter-end. The 10-K equivalent is 12 months stale by
comparison.

### Section mapping

10-Q uses different item numbers than 10-K:

| Section key       | 10-Q item | Content                                              |
|-------------------|-----------|------------------------------------------------------|
| `tenq_mda`        | Item 2    | Results of operations, revenue, margins, guidance    |
| `tenq_risk_update`| Item 1A   | Changes to risk factors since the last 10-K          |
| `tenq_market_risk`| Item 3    | Quantitative market risk (interest rate, FX, etc.)   |

Distinct `tenq_*` keys prevent 10-Q sections from overwriting 10-K sections in
`filing_sections`. Both coexist: 10-K provides depth, 10-Q provides recency.

### Files to change

#### `config.py`

Add four settings:

```python
# 10-Q section char budgets
max_tenq_mda_chars: int = 3000
max_tenq_risk_update_chars: int = 1500
max_tenq_market_risk_chars: int = 1500

# How many recent 10-Qs to extract sections from (4 = 1 year of quarters)
warehouse_tenq_limit: int = 4
```

#### `sec/filing_parser.py`

Add a `TENQ_ITEM_PATTERNS` dict and a new `parse_tenq_sections(html, ticker)` function.

```python
TENQ_ITEM_PATTERNS = {
    "tenq_mda": [
        re.compile(
            r"item\s*2[.\s]*[-–—]?\s*management.{0,10}s?\s+discussion",
            re.IGNORECASE,
        ),
    ],
    "tenq_risk_update": [
        re.compile(
            r"item\s*1a[.\s]*[-–—]?\s*risk\s+factors",
            re.IGNORECASE,
        ),
    ],
    "tenq_market_risk": [
        re.compile(
            r"item\s*3[.\s]*[-–—]?\s*quantitative",
            re.IGNORECASE,
        ),
    ],
}
```

`parse_tenq_sections(html, ticker)` follows the same dual-path pattern as
`parse_filing_sections`:

1. **edgartools path** (latest 10-Q only): try `company.latest_tenq`, then extract
   via `_extract_edgartools_section()`. Attribute names to try:
   - `tenq_mda`: `item2`, `mda`, `management_discussion`
   - `tenq_risk_update`: `item1a`, `risk_factors`
   - `tenq_market_risk`: `item3`, `market_risk`

2. **HTML regex fallback** (all filings, or when edgartools fails): reuse
   `_find_section_boundaries()` with `TENQ_ITEM_PATTERNS` and `_parse_filing_sections_legacy()`
   logic, applying `max_tenq_*` char budgets from settings.

Returns `{"tenq_mda": "", "tenq_risk_update": "", "tenq_market_risk": ""}`.

#### `warehouse/bootstrap.py`

Add `_ingest_10q_sections(ticker, sec_client, db)` alongside the existing
`_ingest_10k_sections`:

```python
def _ingest_10q_sections(ticker, sec_client, db) -> int:
    limit = settings.warehouse_tenq_limit
    tenqs = sec_client.get_recent_filings(ticker, form_types=["10-Q"], limit=limit)
    # Same loop pattern as _ingest_10k_sections:
    # - fetch HTML for each filing
    # - edgartools only for i==0 (latest); ticker="" for older filings
    # - call parse_tenq_sections(html, ticker_for_edgar)
    # - write non-empty sections to db.upsert_filing_section()
```

Also call `_ingest_10q_sections` at the end of `bootstrap_ticker()` so cold-start
bootstraps populate quarterly sections too (alongside the existing 10-K call).

#### `warehouse/change_detector.py`

In `incremental_update()`, add the 10-Q trigger alongside the existing 10-K trigger:

```python
if settings.enable_filing_text:
    new_10k = [f for f in new_filings if f["form"] == "10-K"]
    if new_10k:
        _ingest_10k_sections(ticker, sec_client, db)

    new_10q = [f for f in new_filings if f["form"] == "10-Q"]
    if new_10q:
        _ingest_10q_sections(ticker, sec_client, db)
```

Import `_ingest_10q_sections` from `warehouse.bootstrap` alongside the existing import.

### Validation checklist

- [ ] Bootstrap a fresh ticker (e.g. `python -m warehouse.cli bootstrap ORCL`)
- [ ] Confirm `filing_sections` contains rows with `section_key IN ('tenq_mda', 'tenq_risk_update', 'tenq_market_risk')`
- [ ] Confirm accession numbers in those rows match actual 10-Q accessions (not 10-K)
- [ ] Run `python -m warehouse.seed --tickers ORCL` and verify Pinecone record count increases by the expected number of `tenq_*` rows
- [ ] Query Pinecone for a 10-Q-specific topic (e.g. "quarterly revenue results") and confirm hits come from `tenq_mda` sections

---

## Step 2 — Pinecone Re-seed After Refresh Cycle

### Why

`run_refresh_cycle()` updates the SQLite warehouse but stops there. Pinecone stays
stale until someone manually runs `warehouse.seed`. After an earnings release, that
means RAG returns last quarter's narrative until a human intervenes.

This step wires the two together: when the refresh cycle detects changes, it
immediately re-seeds the affected tickers.

### Design constraints

- Pinecone logic stays out of `change_detector.py` — that module is DB-only.
  The right layer is `scheduler.py`, which already orchestrates the refresh loop.
- A Pinecone seed failure must never abort the refresh cycle for other tickers.
- `seed_pinecone` is opt-out, not opt-in — seeding should be the default.
- The Pinecone client is initialized once per cycle and reused across tickers.

### Files to change

#### `warehouse/scheduler.py`

Modify `run_refresh_cycle()` signature and body:

```python
def run_refresh_cycle(
    tickers: list[str] | None,
    db: WarehouseDB,
    sec_client: SECClient,
    dry_run: bool = False,
    seed_pinecone: bool = True,
) -> dict[str, UpdateResult]:
```

After each `incremental_update()` call, add:

```python
if result.had_changes and seed_pinecone and not dry_run:
    _seed_ticker(ticker, db)
```

Add a module-level helper `_seed_ticker(ticker, db)`:

```python
def _seed_ticker(ticker: str, db: WarehouseDB) -> None:
    """Re-seed Pinecone for a single ticker after a warehouse update."""
    try:
        from pinecone import Pinecone
        from warehouse.embedder import embed_and_upsert_all
        from config import settings

        api_key = settings.pinecone_api_key.strip()
        if not api_key:
            return

        pc = Pinecone(api_key=api_key)
        index = pc.Index(settings.pinecone_index_name)
        summary = embed_and_upsert_all(
            db_path=db._db_path,
            index=index,
            namespace=settings.pinecone_namespace or "__default__",
            tickers=[ticker],
        )
        seeded = sum(summary.values())
        logger.info("Pinecone re-seed %s: %d records", ticker, seeded)
    except Exception:
        logger.warning("Pinecone re-seed failed for %s", ticker, exc_info=True)
```

#### `warehouse/cli.py`

Update the `refresh` command to expose the new flag:

```python
p_refresh.add_argument(
    "--no-seed",
    action="store_true",
    help="Skip Pinecone re-seed after warehouse update (DB update only)",
)
```

Pass `seed_pinecone=not args.no_seed` to `run_refresh_cycle()`.

Updated usage:

```
python -m warehouse.cli refresh                    # refresh DB + re-seed Pinecone (default)
python -m warehouse.cli refresh --no-seed          # DB update only
python -m warehouse.cli refresh --dry-run          # check staleness, no writes
python -m warehouse.cli refresh AAPL MSFT          # specific tickers only
```

#### `orchestrator._flywheel_ingest()`

Extend to handle stale existing tickers, not just new ones. Current logic:

```
company is None  →  bootstrap + seed
company exists   →  skip (even if stale)
```

Updated logic:

```python
from warehouse.change_detector import needs_update

if company is None:
    # New ticker: full bootstrap
    sec = _SECClient()
    bootstrap_ticker(ticker, db, sec)
elif needs_update(ticker, db, _SECClient()):
    # Existing ticker with new filings: incremental update
    from warehouse.change_detector import incremental_update
    sec = _SECClient()
    incremental_update(ticker, db, sec)
else:
    # Already fresh: no-op
    logger.debug("Flywheel: %s is current, skipping", ticker)
    return
```

Then always seed Pinecone after either branch (the seed is idempotent).

This means every analysis run implicitly keeps the ticker fresh — the flywheel
handles both discovery (new tickers) and maintenance (stale existing ones).

### Validation checklist

- [ ] Run `python -m warehouse.cli refresh --dry-run` — confirm output shows `needs_update=True/False` per ticker
- [ ] Simulate a stale ticker: manually update `last_accession` in DB to an old value, then run refresh — confirm Pinecone record count updates
- [ ] Run `python -m warehouse.cli refresh --no-seed` — confirm DB updates but Pinecone vector count stays the same
- [ ] Run `python -m warehouse.cli refresh` — confirm log line `Pinecone re-seed {TICKER}: N records` appears for changed tickers
- [ ] Search a topic related to the most recent 10-Q in Pinecone — confirm `tenq_mda` sections are returned

---

## Implementation order

```
Step 1a  parse_tenq_sections() in filing_parser.py
Step 1b  _ingest_10q_sections() in bootstrap.py + wire into bootstrap_ticker()
Step 1c  Wire _ingest_10q_sections into incremental_update() in change_detector.py
Step 1d  Add config vars + validate with a bootstrap run

Step 2a  _seed_ticker() helper in scheduler.py
Step 2b  run_refresh_cycle() seed_pinecone param
Step 2c  --no-seed flag in cli.py
Step 2d  Update _flywheel_ingest() in orchestrator.py to handle stale tickers
Step 2e  Validate end-to-end with a forced-stale ticker
```

Step 1 should be completed first — Step 2 is more valuable once `tenq_*` sections
exist in the warehouse to be seeded.

---

## Related plans

- `WAREHOUSE_PLAN.md` — warehouse schema and reader layer
- `FMP_EXPANSION_PLAN.md` — additional FMP data sources
- `MARKET_DATA_PLAN.md` — Yahoo → Tiingo/FMP market data migration
- Cloud infrastructure (Supabase + Upstash + Fly.io workers) is tracked separately
