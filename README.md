# AI Financial Analyst

A production-grade multi-agent equity research platform with a validated quantitative backtesting engine. Enter a ticker and get a full investment brief produced by six specialist AI analysts running in parallel — each modeled after a top-tier firm's methodology — synthesized into a single verdict with health scores, price target, and conviction rating.

The platform combines LLM-based qualitative analysis with a rigorous quant signal pipeline (CPCV-validated, Sharpe 1.04 baseline) and multi-provider market data layer.

**Live deployment:**
- Frontend: Vercel
- Backend API: Railway

---

## What It Does

1. You input a stock ticker (or run a backtest across a universe)
2. The system fetches SEC EDGAR filings (10-K, 10-Q, XBRL financials), enriches with multi-provider price data (Alpaca/Tiingo), FMP fundamentals, Finnhub sentiment, FRED macro indicators, Tavily web research, and Pinecone RAG context
3. A quant signal pipeline computes technical + fundamental signals per ticker, validated via CPCV combinatorial purged cross-validation
4. Six analyst agents run in parallel, each examining the data through a different lens
5. A synthesis agent cross-references all six reports, resolves contradictions, and produces a final investment brief with a structured JSON verdict

```
Input: AAPL
       |
       v
 Prepare Data (parallel)
 +-- SEC EDGAR ---------- XBRL financials + 10-K/10-Q text sections
 +-- Alpaca / Tiingo ---- price history, live quote, 52W range (switchable)
 +-- FMP ---------------- analyst estimates, earnings surprises, key metrics
 +-- Finnhub ------------ company news sentiment, insider MSPR, earnings calendar
 +-- FRED --------------- 10Y/2Y treasury, fed funds, CPI, credit spreads
 +-- Tavily ------------- company/industry/risk web research
 +-- Peers -------------- dynamic peer discovery + comparison tables
 +-- Pinecone RAG ------- historical 10-K vectors for comparable context
       |
       v
 Quant Signal Pipeline
 +-- OBV trend (validated alpha), RSI, SMA, Bollinger, mean reversion, ATR
 +-- Fundamental scoring: balance sheet quality + earnings revision momentum
 +-- Finnhub sentiment: FinBERT/VADER news scoring + insider MSPR
 +-- Optional: TimesFM / LSTM price forecasts, WRDS point-in-time fundamentals
       |
       v asyncio.gather()
 +------------------------------------------------------------+
 |  DCF Analyst        |  Risk Analyst    |  Earnings          |
 |  (Morgan Stanley)   |  (Bridgewater)   |  (JPMorgan)        |
 +------------------------------------------------------------+
 |  Competitive Analyst |  Pattern Analyst |  Macro Strategist  |
 |  (Bain & Co.)       |  (Renaissance)   |  (Goldman Sachs)   |
 +------------------------------------------------------------+
       |
       v
 Synthesis Agent (CIO) -- resolves contradictions, issues verdict
       |
       v
 {verdict, conviction, price_target, health_scores, risks, catalysts}
```

---

## Architecture

### Stack

| Layer | Technology |
|-------|------------|
| Frontend | Vite 6, React 19, TypeScript, Tailwind CSS v3 |
| Charting | TradingView Lightweight Charts v5, Recharts |
| Component lib | Radix UI primitives, Lucide icons |
| Backend API | FastAPI + Uvicorn (Python 3.11+) |
| Analysis engine | asyncio orchestrator, 6 parallel agents |
| Quant engine | Walk-forward backtesting, CPCV validation, signal stress testing |
| LLM | Anthropic Claude (`claude-sonnet-4-20250514` default), OpenAI-compatible fallback |
| Market data | Alpaca (primary, switchable) / Tiingo (price history + quotes), FMP (fundamentals + estimates), Finnhub (sentiment + earnings), FRED (macro) |
| SEC data | SEC EDGAR API + edgartools + XBRL parser |
| RAG | Pinecone (llama-text-embed-v2, index: `financial-analyst`) |
| Time-series forecasting | Google TimesFM 2.5 (optional), custom LSTM walk-forward (optional) |
| Cache | SQLite (SEC + warehouse + FMP fundamentals), Redis (TimesFM forecast cache) |
| Hosting | Railway (backend), Vercel (frontend) |
| Error monitoring | Sentry (FastAPI integration) |

### Repository Layout

```
ai-financial-analyst/
+-- backend/                   # FastAPI app
|   +-- main.py                # App factory, CORS, Sentry, router mounting
|   +-- jobs.py                # In-process async job queue + SSE streaming
|   +-- schemas.py             # Pydantic request/response models
|   +-- backtest_engine.py     # Lightweight portfolio backtest engine (API-facing)
|   +-- history_outcomes.py    # Retroactive outcome scoring
|   +-- routers/
|       +-- analysis.py        # POST /run, GET /stream/:id, GET /result/:id
|       +-- market_data.py     # Price history + sparklines
|       +-- recommendations.py # Per-ticker recommendation history
|       +-- watchlist.py       # Watchlist CRUD + summary
|       +-- portfolio.py       # Holdings with cost basis tracking
|       +-- news.py            # News feed (Tavily)
|       +-- industry.py        # Sector performance aggregation
|       +-- backtest.py        # Backtest job management
|       +-- paper_trading.py   # Virtual portfolio + equity curve
|       +-- reports.py         # Report file listing + download
|       +-- config.py          # Feature flag defaults for frontend
+-- frontend/                  # Vite + React SPA
|   +-- src/
|       +-- App.tsx            # Routes: /analysis /portfolio /stock/:ticker /news /industry /backtest /paper-trading
|       +-- api/
|       |   +-- client.ts      # Typed wrappers for all API endpoints
|       |   +-- types.ts       # Shared TypeScript types
|       +-- components/
|       |   +-- analysis/      # TickerInput, ProgressStream, ResultView, AgentTabs, DiagnosticsPanel
|       |   +-- charts/        # PriceChart (LWC v5), SparklineChart, EquityCurveChart
|       |   +-- deepdive/      # PriceHistoryTab, HistoricalPerformanceCards, PerformanceMetricsPanel
|       |   +-- watchlist/     # WatchlistCard, StatusDots
|       |   +-- backtest/      # BacktestConfigPanel, BacktestMetricsPanel, TradeLogTable
|       |   +-- paper-trading/ # OpenPositionsTable, ClosedTradesTable, PaperMetricsPanel
|       |   +-- layout/        # TopNav, Sidebar
|       |   +-- common/        # Badge, Card, MarkdownRenderer
|       +-- hooks/             # useAnalysis, usePriceHistory, useRecommendationHistory, useWatchlist, useBacktest, usePaperTrading
|       +-- pages/             # AnalysisPage, WatchlistPage, StockDeepDivePage, NewsPage, IndustryPage, BacktestPage, PaperTradingPage
+-- agents/                    # Six analyst agents
|   +-- base.py                # BaseAgent: build_context(), append_enrichment_sections()
|   +-- dcf.py                 # DCF Analyst (Morgan Stanley style)
|   +-- risk.py                # Risk Analyst (Bridgewater style)
|   +-- earnings.py            # Earnings Analyst (JPMorgan style)
|   +-- competitive.py         # Competitive Analyst (Bain style)
|   +-- pattern.py             # Pattern Analyst (Renaissance style) — OBV + fundamentals primary
|   +-- macro.py               # Macro Strategist (Goldman Sachs style)
|   +-- sector.py              # Sector specialist briefings
+-- quant/                     # Quantitative pipeline
|   +-- signals.py             # SignalVector: 6 technical signals + composite scoring
|   +-- scoring.py             # Canonical thresholds (BUY/SELL/HOLD) + reclassify()
|   +-- metrics.py             # Canonical metric computations (Sharpe, Sortino, drawdown, Calmar, alpha)
|   +-- backtest.py            # Walk-forward backtesting engine (VIX regime, monthly rebalance)
|   +-- cpcv.py                # Combinatorial Purged Cross-Validation (252 train/test paths)
|   +-- fundamentals.py        # Balance sheet quality + earnings revision momentum signals
|   +-- earnings_signals.py    # SUE, ERM (IBES), earnings dispersion signals
|   +-- sentiment.py           # FinBERT/VADER news sentiment + Finnhub insider MSPR
|   +-- fmp_cache.py           # SQLite cache for FMP fundamentals + Tiingo-to-FMP translation
|   +-- agent_veto.py          # Balance sheet veto rules (D/E spike, equity erosion, cash burn)
|   +-- redundancy.py          # Signal redundancy detection
|   +-- discount_rate.py       # FRED-based risk-free rate + WACC helpers (QuantLib)
|   +-- universe.py            # Dynamic ticker universe construction
|   +-- universe_provider.py   # Universe data provider abstraction
|   +-- fundamental_provider.py # Fundamental data provider abstraction
|   +-- wrds_store.py          # WRDS academic data integration (point-in-time fundamentals)
|   +-- lstm/                  # Custom LSTM walk-forward model (experimental)
|   +-- timesfm/               # Google TimesFM 2.5 nightly batch + Redis cache
+-- sec/                       # SEC data layer
|   +-- client.py              # EDGAR API client + rate limiting
|   +-- xbrl_parser.py         # XBRL -> structured financials + CAGRs + metrics
|   +-- filing_parser.py       # 10-K/10-Q HTML -> MD&A, Risk Factors, Business Desc
|   +-- cache.py               # SQLite caching (WAL mode, thread-safe, two-lock pattern)
|   +-- supabase_history.py    # Optional: sync analysis history to Supabase
+-- warehouse/                 # Persistent filing warehouse
|   +-- db.py                  # SQLite schema + all read/write operations
|   +-- bootstrap.py           # Cold-start ingestion for any ticker
|   +-- change_detector.py     # Incremental update on new SEC filings
|   +-- scheduler.py           # Batch refresh loop
|   +-- reader.py              # Translate warehouse rows -> AnalysisData
|   +-- embedder.py            # Pinecone upsert (llama-text-embed-v2)
|   +-- financial_vectors.py   # Financial time-series RAG vectors
|   +-- macro_vectors.py       # Macro indicator RAG vectors
|   +-- xbrl_vectors.py        # XBRL structured data vectors
|   +-- seed.py                # Pinecone index seeding CLI
|   +-- cli.py                 # python -m warehouse.cli bootstrap|refresh|status
+-- llm/
|   +-- providers.py           # LLM provider abstraction (Anthropic / OpenAI-compatible)
+-- prompts/                   # Agent system prompts (Markdown, editable without code changes)
|   +-- dcf.md / risk.md / earnings.md / competitive.md / pattern.md / macro.md
|   +-- synthesis.md           # Synthesis agent + validation instructions
+-- scripts/
|   +-- run_backtest.py        # Main backtest runner (--cpcv flag for validation)
|   +-- run_ml_backtest.py     # ML-enhanced backtest (LSTM/TimesFM)
|   +-- signal_stress_test.py  # Signal IC, alpha sweep, factor attribution
|   +-- cpcv_alpha_sweep.py    # Exhaustive alpha sweep with CPCV validation gate
|   +-- prefetch_fmp.py        # Bulk FMP fundamental cache prefetch
|   +-- prefetch_sentiment.py  # Bulk Finnhub sentiment cache prefetch
|   +-- run_timesfm_batch.py   # TimesFM nightly batch (APScheduler cron)
|   +-- seed_wrds.py           # WRDS data seeding
|   +-- bulk_bootstrap.py      # One-time Pinecone bootstrap for large ticker lists
|   +-- seed_timeseries.py     # Seed RAG time-series namespaces
+-- tests/                     # pytest suite (72+ tests)
+-- plans/                     # Implementation plans and research docs
+-- orchestrator.py            # Core pipeline: prepare_data() + asyncio.gather() + synthesis
+-- market_enrichment.py       # Parallel enrichment: Tiingo/Alpaca, FMP, Finnhub, FRED, Tavily, peers, RAG
+-- peer_enrichment.py         # Dynamic peer discovery + comparison tables
+-- price_provider.py          # Price provider abstraction (Alpaca / Tiingo, switchable via PRICE_PROVIDER)
+-- tiingo_client.py           # Tiingo REST client (thread-safe cache, EOD schema validation)
+-- fmp_client.py              # FMP REST client (two-lock cache, income/balance/estimate schema validation)
+-- finnhub_client.py          # Finnhub REST client (news/insider/earnings, schema validation)
+-- config.py                  # Pydantic BaseSettings -- all env vars and feature flags
+-- models.py                  # AnalysisData, AnalysisResult, AgentReport (Pydantic)
+-- context_budget.py          # Deterministic context trimming (trim_text, per-agent caps)
+-- rag_enrichment.py          # Pinecone RAG query + formatting
+-- main.py                    # CLI entry point
+-- report.py                  # Text + PDF report generation
+-- Dockerfile                 # Railway deployment (reads $PORT)
+-- railway.json               # Railway build config (Dockerfile builder, health check)
```

---

## Quant Pipeline

The quantitative backtesting engine validates all signals before they're used in production.

### Signal Hierarchy

| Signal | IC | Status | Role |
|--------|-----|--------|------|
| **OBV trend** | Validated | Primary | Volume-confirmed price trend — only technical signal with alpha |
| **Earnings Revision Momentum** | 0.04-0.10 | Primary | Analyst consensus trend (IBES/FMP) |
| **Balance sheet quality** | 0.04-0.10 | Primary | Equity ratio + current ratio scoring |
| **Finnhub sentiment** | Validated | Overlay | FinBERT/VADER news scoring + insider MSPR |
| SMA, RSI, Bollinger, Mean Rev, ATR | ~0 | Regime context | Describe environment, not direction |

### Backtest Validation

- **Gold standard baseline:** VIX 30/40 regime filter, monthly rebalance (Sharpe 1.04, PBO 0%)
- **CPCV validation:** 252 combinatorial purged cross-validation paths — prevents overfitting
- **Alpha sweep:** Automated sweep tool with CPCV gate for any new signal
- **Signal stress test:** IC analysis, factor attribution (FF5+Mom), redundancy detection

```bash
# Run the gold-standard backtest
python scripts/run_backtest.py --start 2020-01-01 --end 2026-01-01 --cpcv

# Signal stress test
python scripts/signal_stress_test.py

# Alpha sweep for a new signal
python scripts/cpcv_alpha_sweep.py
```

---

## Agents

| Agent | Style | Focus |
|-------|-------|-------|
| **DCF Analyst** | Morgan Stanley | Intrinsic valuation, FCF projections, WACC, price target |
| **Risk Analyst** | Bridgewater | Balance sheet risk, macro sensitivity, tail scenarios, agent veto |
| **Earnings Analyst** | JPMorgan | EPS trajectory, margin analysis, earnings quality, SUE signals |
| **Competitive Analyst** | Bain & Co. | Moat analysis, Porter's Five Forces, sector dynamics |
| **Pattern Analyst** | Renaissance Tech | OBV + fundamentals (primary), regime classification via technicals |
| **Macro Strategist** | Goldman Sachs | Macro regime, monetary policy impact, sector rotation |

The synthesis agent acts as CIO — reads all six reports, resolves contradictions, and issues a final verdict (Strong Buy to Strong Sell) with a 1-10 health score across each analytical dimension.

Agent prompts live in `prompts/` as Markdown files. Edit them directly without touching Python code. Placeholder tokens: `[COMPANY NAME]`, `[STOCK NAME]`, `[TICKER]`.

---

## Semantic Data Layer

All metric computation, scoring thresholds, and API response validation are centralized:

| Module | Purpose |
|--------|---------|
| `quant/metrics.py` | Single source of truth for Sharpe, Sortino, max drawdown, Calmar, annual return, alpha |
| `quant/scoring.py` | Canonical BUY/SELL/HOLD thresholds + `reclassify()` — one-line edit to change thresholds |
| `quant/fmp_cache.py` | FMP fundamental cache with TTL enforcement (7-day default, disabled for backtests) |
| `*_client.py` validators | Schema validation at API boundaries — logs warnings for missing fields, no behavior change |

---

## Local Development

### Prerequisites

- Python 3.11+
- Node.js 18+
- (Optional) Redis — only needed if `ENABLE_TIMESFM=true`

### Backend Setup

```bash
git clone https://github.com/chadreadey/ai-financial-analyst.git
cd ai-financial-analyst

pip install -r requirements.txt
pip install -e .

cp .env.example .env
# Edit .env and fill in your API keys (see Environment Variables below)

uvicorn backend.main:app --reload --port 8000
```

API runs at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### Frontend Setup

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

App runs at `http://localhost:5173`.

### CLI (direct analysis without the web UI)

```bash
python main.py AAPL
python main.py AAPL --inspect-context
python main.py AAPL --save
ENABLE_YAHOO=false ENABLE_TAVILY=false python main.py AAPL
```

---

## Deployment

### Backend -> Railway

1. Create a new Railway project and connect the GitHub repo
2. Railway auto-detects `railway.json` and builds via `Dockerfile`
3. Add all environment variables (see table below) in the Railway dashboard
4. Add a **Volume** mounted at `/data` — SQLite files persist here across deploys
5. Copy your Railway service URL (e.g. `https://your-app.up.railway.app`)

### Frontend -> Vercel

1. Create a new Vercel project and import the GitHub repo
2. Vercel auto-detects config at the repo root
3. Add environment variable: `VITE_API_URL=https://your-app.up.railway.app`
4. Deploy

### Wire CORS

After both are deployed, go back to Railway and add:
```
CORS_ORIGINS=https://your-app.vercel.app
```

---

## Environment Variables

### Required

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key (required if `LLM_PROVIDER=anthropic`) |
| `OPENAI_API_KEY` | OpenAI-compatible API key (required if `LLM_PROVIDER=openai`) |

### Data Sources

| Variable | Default | Description |
|----------|---------|-------------|
| `TIINGO_API_KEY` | -- | Tiingo market data (price history, quotes, fundamentals) |
| `ALPACA_API_KEY` | -- | Alpaca market data (alternative price provider) |
| `ALPACA_SECRET_KEY` | -- | Alpaca secret key |
| `FMP_API_KEY` | -- | Financial Modeling Prep (estimates, earnings, metrics, financials) |
| `FINNHUB_API_KEY` | -- | Finnhub (company news sentiment, insider MSPR, earnings calendar) |
| `FRED_API_KEY` | -- | FRED macro data (optional — raises rate limits) |
| `TAVILY_API_KEY` | -- | Tavily web search enrichment |
| `PINECONE_API_KEY` | -- | Pinecone RAG (required if `ENABLE_RAG=true`) |

### Price Provider

| Variable | Default | Description |
|----------|---------|-------------|
| `PRICE_PROVIDER` | `tiingo` | `alpaca` or `tiingo` — switches the primary price data source |
| `ALPACA_DATA_FEED` | `iex` | `iex` (free) or `sip` (paid) |

### Feature Flags

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_TIINGO` | `true` | Tiingo price history and quotes |
| `ENABLE_FMP` | `true` | FMP estimates, earnings surprises, key metrics |
| `ENABLE_FRED` | `true` | FRED macro indicators |
| `ENABLE_TAVILY` | `true` | Tavily web research sections |
| `ENABLE_YAHOO` | `true` | Yahoo Finance fallback |
| `ENABLE_PEERS` | `true` | Dynamic peer discovery and comparison |
| `ENABLE_ESTIMATES` | `true` | Analyst estimate sections |
| `ENABLE_PRICE_HISTORY` | `true` | Price history enrichment section |
| `ENABLE_MACRO` | `true` | Macro data section |
| `ENABLE_MACRO_AGENT` | `true` | Macro Strategist agent |
| `ENABLE_QUANTSTATS` | `true` | Risk metrics in Pattern agent |
| `ENABLE_RAG` | `false` | Pinecone RAG enrichment (requires seeded index) |
| `ENABLE_WAREHOUSE` | `false` | Persistent filing warehouse (SQLite) |
| `ENABLE_TIMESFM` | `false` | TimesFM nightly forecast batch + Redis cache |
| `ENABLE_LSTM` | `false` | LSTM walk-forward price forecast (experimental) |
| `ENABLE_SUPABASE_HISTORY` | `false` | Sync analysis history to Supabase |

### LLM Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `anthropic` | `anthropic` or `openai` |
| `OPENAI_BASE_URL` | CBS endpoint | Override for any OpenAI-compatible API |
| `ENABLE_PROMPT_CACHING` | `true` | Anthropic prompt caching (reduces cost ~70%) |

### Infrastructure

| Variable | Default | Description |
|----------|---------|-------------|
| `CORS_ORIGINS` | -- | Comma-separated extra origins (e.g. your Vercel URL) |
| `SENTRY_DSN` | -- | Sentry error tracking DSN |
| `SENTRY_ENVIRONMENT` | `production` | Sentry environment tag |
| `REDIS_URL` | -- | Redis URL for TimesFM cache (required if `ENABLE_TIMESFM=true`) |
| `WAREHOUSE_DB_PATH` | `.warehouse.db` | SQLite warehouse path (set to `/data/warehouse.db` on Railway) |

### Context Budgets (tunable)

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_AGENT_CONTEXT_CHARS` | `12000` | Per-agent context cap before LLM call |
| `MAX_AGENT_OUTPUT_TOKENS` | `1200` | Per-agent max output tokens |
| `MAX_SYNTHESIS_OUTPUT_TOKENS` | `1500` | Synthesis agent max output tokens |
| `SYNTHESIS_INPUT_MAX_CHARS` | `22000` | Combined agent reports cap into synthesis |
| `SYNTHESIS_REPORT_MAX_CHARS` | `4500` | Per-agent report cap inside synthesis input |
| `ENRICHMENT_MAX_CHARS` | `10000` | Hard cap on total enrichment text |

Per-agent context overrides: `MAX_CONTEXT_DCF_CHARS`, `MAX_CONTEXT_RISK_CHARS`, `MAX_CONTEXT_EARNINGS_CHARS`, `MAX_CONTEXT_COMPETITIVE_CHARS`, `MAX_CONTEXT_PATTERN_CHARS`, `MAX_CONTEXT_MACRO_CHARS` (all default to `MAX_AGENT_CONTEXT_CHARS`).

---

## Warehouse + RAG

### Filing Warehouse

The warehouse (`ENABLE_WAREHOUSE=true`) persists SEC filings, XBRL facts, and filing narrative sections in SQLite. Agents read from warehouse first and fall back to live EDGAR fetches on cache miss.

```bash
python -m warehouse.cli bootstrap AAPL MSFT NVDA
python -m warehouse.cli status
python -m warehouse.cli refresh
```

### Pinecone RAG

RAG enrichment provides agents with vectorized historical 10-K context. Requires a seeded Pinecone index.

```bash
python -m warehouse.seed
python -m warehouse.seed --tickers AAPL MSFT NVDA
python -m warehouse.seed --dry-run
```

After seeding, set `ENABLE_RAG=true` in `.env`.

The data flywheel in `orchestrator.py` auto-seeds new tickers in a background thread after each analysis run — first query uses live data, every subsequent query gets RAG enrichment.

### TimesFM (Optional)

Google TimesFM 2.5 runs as a nightly batch that pre-computes price/EPS forecasts and caches them in Redis. Query-time cost is a single Redis lookup (<5ms). Agents receive P10/P50/P90 forecast bands as enrichment sections.

```bash
pip install timesfm
python scripts/run_timesfm_batch.py --run-now
python scripts/run_timesfm_batch.py   # starts nightly scheduler (11 PM cron)
```

Enable with `ENABLE_TIMESFM=true` and `REDIS_URL=redis://localhost:6379`.

---

## API

The FastAPI backend auto-generates interactive API docs at `/docs` (Swagger) and `/redoc`.

### Key Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/analysis/run` | Start an analysis job |
| `GET` | `/api/analysis/stream/{job_id}` | SSE stream of agent progress |
| `GET` | `/api/analysis/result/{job_id}` | Completed analysis result |
| `GET` | `/api/analysis/history` | Past analyses (filterable by ticker) |
| `GET` | `/api/market/price-history/{ticker}` | OHLCV bars (periods: 1mo/3mo/1yr/3yr/5yr) |
| `GET` | `/api/market/sparkline/{ticker}` | 60-day close + dates for sparklines |
| `GET` | `/api/recommendations/history/{ticker}` | Past recommendations for a ticker |
| `GET` | `/api/watchlist/` | Watchlist entries |
| `POST` | `/api/watchlist/{ticker}` | Add to watchlist |
| `GET` | `/api/watchlist/{ticker}/summary` | Latest analysis summary for watchlist card |
| `POST` | `/api/backtest/run` | Run a walk-forward backtest |
| `POST` | `/api/backtest/nl` | Natural-language backtest config parsing |
| `GET` | `/api/paper-trading/positions` | Open paper trading positions |
| `GET` | `/api/paper-trading/metrics` | Paper trading performance metrics |
| `GET` | `/api/news/` | News feed (filter by ticker or sector) |
| `GET` | `/api/health` | Health check |

---

## Tests

```bash
pytest                                     # full suite (72+ tests)
pytest tests/test_metrics.py -v            # canonical metrics
pytest tests/test_scoring.py -v            # threshold classification
pytest tests/test_schema_validation.py -v  # API schema validation
pytest tests/test_orchestrator.py -v       # pipeline integration
```

Tests use `fakeredis`, `pytest-mock`, and `caplog` — no live API dependencies required.

---

## Tech Stack Summary

- **Python 3.11+** — FastAPI, Pydantic v2, asyncio, SQLite
- **Node 18+** — Vite 6, React 19, TypeScript, Tailwind CSS v3
- **LLM** — Anthropic Claude (`claude-sonnet-4-20250514`)
- **Market data** — Alpaca / Tiingo (switchable), FMP, Finnhub, FRED, Yahoo Finance (fallback)
- **SEC** — EDGAR API, edgartools, custom XBRL parser
- **RAG** — Pinecone (llama-text-embed-v2)
- **Quant** — CPCV validation, walk-forward backtest, signal stress testing
- **Time-series** — Google TimesFM 2.5 (optional), LSTM walk-forward (experimental)
- **Hosting** — Railway (API) + Vercel (frontend)
- **Monitoring** — Sentry
