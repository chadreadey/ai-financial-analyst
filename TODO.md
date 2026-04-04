# TODO

Unimplemented items from the original expansion plans. Each item is self-contained and independently buildable.

---

## Analysis Engine

### Insider Transactions Agent
- New file: `agents/insider.py` + `prompts/insider.md`
- Data: SEC Form 4 via edgartools — `Company(ticker).get_filings(form="4").latest(20)`
- Output: net insider sentiment (BUY/NEUTRAL/SELL), rolling 90-day buy/sell volume, cluster buying detection
- Wire into `orchestrator.py` Phase 1 pool behind `ENABLE_INSIDER_AGENT=true`
- **Dependency:** edgartools already installed

### Earnings Call Transcript Agent
- New file: `agents/transcript.py` + `prompts/transcript.md`
- Data: 8-K exhibit via edgartools — `filing.exhibit("EX-99.1").text()`
- Output: management confidence vs. hedging language, guidance delta vs. prior call, key themes
- Wire into `orchestrator.py` behind `ENABLE_TRANSCRIPT_AGENT=true`
- **Dependency:** edgartools already installed

### ARIMA Forecasting (Pattern Agent)
- Add `forecast_series()` to `agents/pattern.py` using `pmdarima.auto_arima`
- Forecasts 3-year revenue + FCF with 95% confidence bands
- Add `pmdarima>=2.0` to `requirements.txt` and `pyproject.toml`
- Gate behind `ENABLE_ARIMA=true` in `config.py`

### FMP Enrichment Sections (client methods exist, not wired)
`fmp_client.py` has these methods but none are wired into `market_enrichment.py` sections yet:
- `get_grades_summary()` → add `fmp_analyst_grades` enrichment section (EarningsAgent + DCFAgent)
- `get_stock_news()` → add `fmp_news` enrichment section (all agents)
- `get_dcf_valuation()` → add `fmp_dcf` enrichment section (DCFAgent cross-check)
- `get_institutional_holders()` → add `fmp_institutional` enrichment section (RiskAgent)

Each follows the existing `_task_*` pattern in `market_enrichment.py`. Total new API calls per run: +4 (within 250/day free tier).

### AKShare for China/HK Coverage
- Add `fetch_akshare_data(ticker)` fallback in `market_enrichment.py`
- Activate when ticker has `.HK` suffix or is in known ADR list
- Add `akshare>=1.10` to deps
- Gate behind `ENABLE_AKSHARE=true`

---

## Data + Warehouse

### RAG Auto Re-seed After New Filings
- `warehouse/change_detector.py` detects new filings but does NOT re-seed Pinecone
- After `incremental_update()` finds `had_changes=True`, call `embed_and_upsert_all(ticker)` in a background thread
- Gate on `settings.enable_rag` — no-op if Pinecone key missing
- File to modify: `warehouse/change_detector.py` → add post-update hook

### `analysis_history` Schema Migration
The `entry_price` and `target_price` columns exist in the code but may not exist in deployed DB instances.
- Add migration guard in `warehouse/db.py` `_init_schema()`:
  ```python
  try:
      conn.execute("ALTER TABLE analysis_history ADD COLUMN entry_price REAL")
      conn.execute("ALTER TABLE analysis_history ADD COLUMN target_price REAL")
  except sqlite3.OperationalError:
      pass  # columns already exist
  ```
- Wire `orchestrator.py` to write `entry_price` (price at time of run) and `target_price` (from structured verdict) on each save

---

## Frontend

### Sentry in React Frontend
- Install `@sentry/react` in `frontend/`
- Initialize in `frontend/src/main.tsx` with DSN from `VITE_SENTRY_DSN` env var
- Wrap `App` in `Sentry.ErrorBoundary`
- Add `VITE_SENTRY_DSN=` to `frontend/.env.example`

### Multi-Ticker Portfolio Scanner Page
- Existing `/portfolio` (Watchlist) page shows one ticker at a time
- Add a batch scanner: user inputs 3-10 tickers, all run in parallel via `asyncio.Semaphore(3)`
- Results render as a ranked comparison table: ticker, verdict, composite score, top risk, top catalyst
- Backend: new `POST /api/analysis/scan` endpoint in `backend/routers/analysis.py`
- Frontend: new `ScannerPage.tsx` at `/scanner`

### `StockDeepDivePage` is incomplete
`frontend/src/pages/StockDeepDivePage.tsx` is a thin wrapper. Needs:
- Historical performance cards (component exists at `components/deepdive/HistoricalPerformanceCards.tsx`)
- Performance metrics panel (component exists at `components/deepdive/PerformanceMetricsPanel.tsx`)
- Wire up the actual analysis re-run button that pre-populates the ticker in AnalysisPage

---

## Infrastructure

### `docker-compose.yml` not committed
`docker-compose.yml` exists locally but was not included in the git push. Stage and commit it — it's useful for local dev (Redis + API together).

### TimesFM: Validate with Real Model
The TimesFM module (`quant/timesfm/`) is fully scaffolded but has only been tested with mocks.
- Install: `pip install timesfm` (or `timesfm[torch]`) — ~800MB
- Run: `python scripts/run_timesfm_batch.py --run-now` with a few tickers
- Verify Redis keys are written: `redis-cli keys "timesfm:*"`
- Set `ENABLE_TIMESFM=true` after validation

### Railway Persistent Volume
After deploying to Railway, attach a persistent volume at `/data` for SQLite files (`warehouse.db`, `sec_cache.db`). Without this, the DB resets on every deploy.

---

## Low Priority / Nice to Have

- **AKShare China/HK coverage** — only relevant for ADRs; low usage until explicitly needed
- **QuantLib bond math** — `quant/discount_rate.py` already has FRED-based risk-free rate; full QuantLib PV-of-debt math is marginal improvement
- **PDF generation via `report.py`** — `fpdf2` is installed but the PDF route in `backend/routers/reports.py` may not be wired
- **CLI `main.py`** — the existing CLI still works for direct analysis runs; document it in README
