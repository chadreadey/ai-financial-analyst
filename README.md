# AI Financial Analyst

A production-grade multi-agent equity research platform. Enter a ticker and get a full investment brief produced by six specialist AI analysts running in parallel — each modeled after a top-tier firm's methodology — synthesized into a single verdict with health scores, price target, and conviction rating.

**Live deployment:**
- Frontend: Vercel
- Backend API: Railway

---

## What It Does

1. You input a stock ticker
2. The system fetches SEC EDGAR filings (10-K, 10-Q, XBRL financials), enriches with Tiingo price data, FMP estimates, FRED macro indicators, Tavily web research, and Pinecone RAG context
3. Six analyst agents run in parallel, each examining the data through a different lens
4. A synthesis agent cross-references all six reports, resolves contradictions, and produces a final investment brief with a structured JSON verdict

```
Input: AAPL
       │
       ▼
 Prepare Data (parallel)
 ├── SEC EDGAR ──── XBRL financials + 10-K/10-Q text sections
 ├── Tiingo ──────── price history, live quote, 52W range
 ├── FMP ─────────── analyst estimates, earnings surprises, key metrics
 ├── FRED ────────── 10Y/2Y treasury, fed funds, CPI, credit spreads
 ├── Tavily ──────── company/industry/risk web research
 ├── Peers ───────── dynamic peer discovery + comparison tables
 └── Pinecone RAG ── historical 10-K vectors for comparable context
       │
       ▼ asyncio.gather()
 ┌──────────────────────────────────────────────────────┐
 │  DCF Analyst        │  Risk Analyst    │  Earnings   │
 │  (Morgan Stanley)   │  (Bridgewater)   │  (JPMorgan) │
 ├──────────────────────────────────────────────────────┤
 │  Competitive Analyst  │  Pattern Analyst  │  Macro   │
 │  (Bain & Co.)         │  (Renaissance)    │  (GS)    │
 └──────────────────────────────────────────────────────┘
       │
       ▼
 Synthesis Agent (CIO) ── resolves contradictions, issues verdict
       │
       ▼
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
| LLM | Anthropic Claude (`claude-sonnet-4-20250514` default), OpenAI-compatible fallback |
| Market data | Tiingo (price history + quotes), FMP (estimates + metrics), FRED (macro) |
| SEC data | SEC EDGAR API + edgartools + XBRL parser |
| RAG | Pinecone (llama-text-embed-v2, index: `financial-analyst`) |
| Time-series forecasting | Google TimesFM 2.5 (optional, pre-computed nightly) |
| Cache | SQLite (SEC + warehouse), Redis (TimesFM forecast cache) |
| Hosting | Railway (backend), Vercel (frontend) |
| Error monitoring | Sentry (FastAPI integration) |

### Repository Layout

```
ai-financial-analyst/
├── backend/                   # FastAPI app
│   ├── main.py                # App factory, CORS, Sentry, router mounting
│   ├── jobs.py                # In-process async job queue + SSE streaming
│   ├── schemas.py             # Pydantic request/response models
│   ├── backtest_engine.py     # Walk-forward backtesting engine
│   ├── history_outcomes.py    # Retroactive outcome scoring
│   └── routers/
│       ├── analysis.py        # POST /run, GET /stream/:id, GET /result/:id
│       ├── market_data.py     # Price history + sparklines (Tiingo)
│       ├── recommendations.py # Per-ticker recommendation history
│       ├── watchlist.py       # Watchlist CRUD + summary
│       ├── portfolio.py       # Holdings with cost basis tracking
│       ├── news.py            # FMP news feed
│       ├── industry.py        # Sector performance aggregation
│       ├── backtest.py        # Backtest job management
│       ├── paper_trading.py   # Virtual portfolio + equity curve
│       ├── reports.py         # Report file listing + download
│       └── config.py          # Feature flag defaults for frontend
├── frontend/                  # Vite + React SPA
│   ├── src/
│   │   ├── App.tsx            # Routes: /analysis /portfolio /stock/:ticker /news /industry /backtest /paper-trading
│   │   ├── api/
│   │   │   ├── client.ts      # Typed wrappers for all 25 API endpoints
│   │   │   └── types.ts       # Shared TypeScript types
│   │   ├── components/
│   │   │   ├── analysis/      # TickerInput, ProgressStream, ResultView, AgentTabs, DiagnosticsPanel
│   │   │   ├── charts/        # PriceChart (LWC v5), SparklineChart (Recharts), EquityCurveChart
│   │   │   ├── deepdive/      # PriceHistoryTab, HistoricalPerformanceCards, PerformanceMetricsPanel
│   │   │   ├── watchlist/     # WatchlistCard, StatusDots
│   │   │   ├── backtest/      # BacktestConfigPanel, BacktestMetricsPanel, TradeLogTable
│   │   │   ├── paper-trading/ # OpenPositionsTable, ClosedTradesTable, PaperMetricsPanel
│   │   │   ├── layout/        # TopNav, Sidebar
│   │   │   └── common/        # Badge, Card, MarkdownRenderer
│   │   ├── hooks/             # useAnalysis, usePriceHistory, useRecommendationHistory, useWatchlist, useBacktest, usePaperTrading
│   │   └── pages/             # AnalysisPage, WatchlistPage, StockDeepDivePage, NewsPage, IndustryPage, BacktestPage, PaperTradingPage
│   └── vercel.json            # SPA rewrites for React Router
├── agents/                    # Six analyst agents
│   ├── base.py                # BaseAgent: build_context(), append_enrichment_sections()
│   ├── dcf.py                 # DCF Analyst (Morgan Stanley style)
│   ├── risk.py                # Risk Analyst (Bridgewater style)
│   ├── earnings.py            # Earnings Analyst (JPMorgan style)
│   ├── competitive.py         # Competitive Analyst (Bain style)
│   ├── pattern.py             # Pattern Analyst (Renaissance style) + quantstats metrics
│   ├── macro.py               # Macro Strategist (Goldman Sachs style)
│   └── sector.py              # Sector specialist briefings
├── sec/                       # SEC data layer
│   ├── client.py              # EDGAR API client + rate limiting
│   ├── xbrl_parser.py         # XBRL → structured financials + CAGRs + metrics
│   ├── filing_parser.py       # 10-K/10-Q HTML → MD&A, Risk Factors, Business Desc
│   ├── cache.py               # SQLite caching (WAL mode, thread-safe, two-lock pattern)
│   └── supabase_history.py    # Optional: sync analysis history to Supabase
├── warehouse/                 # Persistent filing warehouse
│   ├── db.py                  # SQLite schema + all read/write operations
│   ├── bootstrap.py           # Cold-start ingestion for any ticker
│   ├── change_detector.py     # Incremental update on new SEC filings
│   ├── scheduler.py           # Batch refresh loop
│   ├── reader.py              # Translate warehouse rows → AnalysisData
│   ├── embedder.py            # Pinecone upsert (llama-text-embed-v2)
│   ├── financial_vectors.py   # Financial time-series RAG vectors
│   ├── macro_vectors.py       # Macro indicator RAG vectors
│   ├── xbrl_vectors.py        # XBRL structured data vectors
│   ├── seed.py                # Pinecone index seeding CLI
│   └── cli.py                 # `python -m warehouse.cli bootstrap|refresh|status`
├── quant/                     # Quantitative modules
│   ├── discount_rate.py       # FRED-based risk-free rate + WACC helpers (QuantLib)
│   └── timesfm/               # Google TimesFM 2.5 nightly batch + Redis cache
│       ├── model.py           # Lazy singleton, threading.Lock, optional import
│       ├── cache.py           # Redis read/write, graceful degradation (never raises)
│       ├── signals.py         # Extract P10/P50/P90 bands + trend direction
│       ├── enrichment.py      # Format signals as agent-readable text sections
│       └── batch.py           # Nightly batch: Tiingo history → TimesFM → Redis
├── llm/
│   └── providers.py           # LLM provider abstraction (Anthropic / OpenAI-compatible)
├── prompts/                   # Agent system prompts (Markdown, editable without code changes)
│   ├── dcf.md / risk.md / earnings.md / competitive.md / pattern.md / macro.md
│   └── synthesis.md           # Synthesis agent + TimesFM validation instructions
├── scripts/
│   ├── run_timesfm_batch.py   # APScheduler cron (11 PM nightly) + --run-now flag
│   ├── bulk_bootstrap.py      # One-time Pinecone bootstrap for large ticker lists
│   └── seed_timeseries.py     # Seed RAG time-series namespaces
├── tests/                     # pytest suite
├── infra/                     # Archived infrastructure (Supabase schema, queue workers)
├── orchestrator.py            # Core pipeline: prepare_data() + asyncio.gather() + synthesis
├── market_enrichment.py       # Parallel enrichment: Tiingo, FMP, FRED, Tavily, peers, RAG
├── peer_enrichment.py         # Dynamic peer discovery + comparison tables
├── config.py                  # Pydantic BaseSettings — all env vars and feature flags
├── models.py                  # AnalysisData, AnalysisResult, AgentReport (Pydantic)
├── context_budget.py          # Deterministic context trimming (trim_text, per-agent caps)
├── main.py                    # CLI entry point
├── report.py                  # Text + PDF report generation
├── tiingo_client.py           # Tiingo REST client (thread-safe cache)
├── fmp_client.py              # FMP REST client (two-lock cache pattern)
├── Dockerfile                 # Railway deployment (reads $PORT)
├── railway.json               # Railway build config (Dockerfile builder, health check)
└── vercel.json                # Vercel build config (frontend build + SPA rewrites)
```

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

# Install Python dependencies
pip install -r requirements.txt
pip install -e .

# Configure environment
cp .env.example .env
# Edit .env and fill in your API keys (see Environment Variables below)

# Start the API server
uvicorn backend.main:app --reload --port 8000
```

API runs at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### Frontend Setup

```bash
cd frontend
cp .env.example .env.local
# .env.local already has VITE_API_URL=http://localhost:8000

npm install
npm run dev
```

App runs at `http://localhost:5173`.

### CLI (direct analysis without the web UI)

```bash
# Run analysis for a ticker
python main.py AAPL

# Inspect context sizes without calling any LLM
python main.py AAPL --inspect-context

# Save report to file
python main.py AAPL --save

# Disable all enrichment (SEC/XBRL only)
ENABLE_YAHOO=false ENABLE_TAVILY=false python main.py AAPL
```

---

## Deployment

### Backend → Railway

1. Create a new Railway project and connect the GitHub repo
2. Railway auto-detects `railway.json` and builds via `Dockerfile`
3. Add all environment variables (see table below) in the Railway dashboard
4. Add a **Volume** mounted at `/data` — SQLite files persist here across deploys
5. Copy your Railway service URL (e.g. `https://your-app.up.railway.app`)

### Frontend → Vercel

1. Create a new Vercel project and import the GitHub repo
2. Vercel auto-detects `vercel.json` at the repo root — no extra config needed
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
| `TIINGO_API_KEY` | — | Tiingo market data (price history, quotes) |
| `FMP_API_KEY` | — | Financial Modeling Prep (estimates, earnings, metrics) |
| `FRED_API_KEY` | — | FRED macro data (optional — raises rate limits) |
| `TAVILY_API_KEY` | — | Tavily web search enrichment |
| `PINECONE_API_KEY` | — | Pinecone RAG (required if `ENABLE_RAG=true`) |

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
| `ENABLE_RAG` | `false` | Pinecone RAG enrichment (requires seeded index) |
| `ENABLE_WAREHOUSE` | `false` | Persistent filing warehouse (SQLite) |
| `ENABLE_TIMESFM` | `false` | TimesFM nightly forecast batch + Redis cache |
| `ENABLE_QUANTSTATS` | `true` | quantstats risk metrics in Pattern agent |
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
| `CORS_ORIGINS` | — | Comma-separated extra origins (e.g. your Vercel URL) |
| `SENTRY_DSN` | — | Sentry error tracking DSN |
| `SENTRY_ENVIRONMENT` | `production` | Sentry environment tag |
| `REDIS_URL` | — | Redis URL for TimesFM cache (required if `ENABLE_TIMESFM=true`) |
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

## Agents

| Agent | Style | Focus |
|-------|-------|-------|
| **DCF Analyst** | Morgan Stanley | Intrinsic valuation, FCF projections, WACC, price target |
| **Risk Analyst** | Bridgewater | Balance sheet risk, macro sensitivity, tail scenarios |
| **Earnings Analyst** | JPMorgan | EPS trajectory, margin analysis, earnings quality, surprises |
| **Competitive Analyst** | Bain & Co. | Moat analysis, Porter's Five Forces, sector dynamics |
| **Pattern Analyst** | Renaissance Tech | Quantitative trends, Sharpe/Sortino/VaR, mean reversion |
| **Macro Strategist** | Goldman Sachs | Macro regime, monetary policy impact, sector rotation |

The synthesis agent acts as CIO — reads all six reports, resolves contradictions, and issues a final verdict (Strong Buy → Strong Sell) with a 1–10 health score across each analytical dimension.

Agent prompts live in `prompts/` as Markdown files. Edit them directly without touching Python code. Placeholder tokens: `[COMPANY NAME]`, `[STOCK NAME]`, `[TICKER]`.

---

## Warehouse + RAG

### Filing Warehouse

The warehouse (`ENABLE_WAREHOUSE=true`) persists SEC filings, XBRL facts, and filing narrative sections in SQLite. Agents read from warehouse first and fall back to live EDGAR fetches on cache miss.

```bash
# Bootstrap a ticker
python -m warehouse.cli bootstrap AAPL MSFT NVDA

# Check warehouse status
python -m warehouse.cli status

# Run incremental update (detects new filings via SEC submissions endpoint)
python -m warehouse.cli refresh
```

### Pinecone RAG

RAG enrichment provides agents with vectorized historical 10-K context. Requires a seeded Pinecone index.

```bash
# Seed the index (10 default tickers + any extras)
python -m warehouse.seed

# Seed specific tickers
python3.10 -m warehouse.seed --tickers AAPL MSFT NVDA

# Dry run (check what would be seeded)
python3.10 -m warehouse.seed --dry-run
```

After seeding, set `ENABLE_RAG=true` in `.env`.

The data flywheel in `orchestrator.py` auto-seeds new tickers in a background thread after each analysis run — first query uses live data, every subsequent query gets RAG enrichment.

### TimesFM (Optional)

Google TimesFM 2.5 runs as a nightly batch that pre-computes price/EPS forecasts and caches them in Redis. Query-time cost is a single Redis lookup (<5ms). Agents receive P10/P50/P90 forecast bands as enrichment sections.

```bash
# Install TimesFM (large dependency, ~800MB)
pip install timesfm

# Run batch manually to test
python scripts/run_timesfm_batch.py --run-now

# Start nightly scheduler (11 PM cron)
python scripts/run_timesfm_batch.py

# Check Redis cache
redis-cli keys "timesfm:*"
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
| `GET` | `/api/news/` | FMP news feed (filter by ticker or sector) |
| `GET` | `/api/health` | Health check |

---

## Tests

```bash
# Run full test suite
pytest

# Run specific test files
pytest tests/test_timesfm_cache.py -v
pytest tests/test_timesfm_signals.py -v
```

Tests use `fakeredis` and `pytest-mock` — no live API dependencies required.

---

## Tech Stack Summary

- **Python 3.11+** — FastAPI, Pydantic v2, asyncio, SQLite
- **Node 18+** — Vite 6, React 19, TypeScript, Tailwind CSS v3
- **LLM** — Anthropic Claude (`claude-sonnet-4-20250514`)
- **Market data** — Tiingo, FMP, FRED, Yahoo Finance (fallback)
- **SEC** — EDGAR API, edgartools, custom XBRL parser
- **RAG** — Pinecone (llama-text-embed-v2)
- **Time-series** — Google TimesFM 2.5 (optional)
- **Hosting** — Railway (API) + Vercel (frontend)
- **Monitoring** — Sentry
