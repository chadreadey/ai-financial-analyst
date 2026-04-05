# Session Handoff — AI Financial Analyst Platform

Use this document to get a new Claude Code session fully up to speed instantly.

---

## What This Project Is

Production 6-agent equity research platform. User inputs a stock ticker → 6 specialist AI agents run in parallel (DCF, Risk, Earnings, Competitive, Pattern, Macro) → Synthesis agent issues a verdict with health scores, price target, and conviction rating.

**Repo:** https://github.com/chadreadey/ai-financial-analyst  
**Local path:** `/Users/chadreadey/portfolio-analyst/ai-financial-analyst`

---

## Live Deployment (as of 2026-04-05)

| Service | URL | Host |
|---------|-----|------|
| Frontend (React) | https://frontend-sage-nu-51.vercel.app | Vercel |
| Backend API (FastAPI) | https://ai-financial-analyst-production-b148.up.railway.app | Railway |
| Health check | https://ai-financial-analyst-production-b148.up.railway.app/api/health | — |

**Railway project:** `eloquent-alignment`, service `ai-financial-analyst`  
**Vercel project:** `frontend` under team `chadreadey-7282s-projects`

### CLI Access (already configured locally)
```bash
railway link --project 06865ced-9179-4296-82f1-9a846ad61588 --environment production
railway service ai-financial-analyst
vercel link --scope chadreadey-7282s-projects --yes  # run from frontend/
```

### One pending Railway task
Add a **Volume** at `/data` in the Railway dashboard so SQLite DBs persist across deploys.  
Dashboard → `ai-financial-analyst` service → Volumes → Add → mount path `/data`

---

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vite 6, React 19, TypeScript, Tailwind CSS v3, React Router v7 |
| Charting | TradingView Lightweight Charts v5, Recharts |
| Backend | FastAPI + Uvicorn, Python 3.13 |
| LLM | Anthropic `claude-sonnet-4-20250514` (default) |
| Market data | Tiingo (price/quotes), FMP (estimates/earnings), FRED (macro) |
| SEC data | EDGAR API + edgartools + custom XBRL parser |
| RAG | Pinecone, index `financial-analyst`, llama-text-embed-v2 |
| Cache | SQLite (SEC + warehouse), Redis (TimesFM — optional) |
| Hosting | Railway (API) + Vercel (frontend) |
| Monitoring | Sentry (FastAPI only — frontend Sentry not yet wired) |

---

## Architecture

```
frontend/ (Vite + React SPA)
  └── api/client.ts → 25 typed API calls to Railway backend

backend/ (FastAPI)
  ├── routers/analysis.py    ← POST /run, SSE stream, GET /result
  ├── routers/market_data.py ← Tiingo price history + sparklines
  ├── routers/recommendations.py
  ├── routers/watchlist.py
  ├── routers/portfolio.py
  ├── routers/news.py
  ├── routers/industry.py
  ├── routers/backtest.py
  ├── routers/paper_trading.py
  └── jobs.py                ← in-process async job queue + SSE

orchestrator.py              ← prepare_data() + asyncio.gather() + synthesis
agents/{dcf,risk,earnings,competitive,pattern,macro}.py
market_enrichment.py         ← parallel enrichment: Tiingo, FMP, FRED, Tavily, peers, RAG
warehouse/                   ← SQLite persistent filing warehouse
quant/timesfm/               ← TimesFM nightly batch + Redis cache (ENABLE_TIMESFM=false)
```

---

## Key Architecture Rules

- **SQLite thread safety:** Never pass SQLite connections across threads. Every `WarehouseDB` method opens a fresh connection.
- **ENABLE_* flags:** All features gated via Pydantic `BaseSettings` in `config.py`. Use `settings.enable_*` in new code.
- **Context budget:** `context_budget.py` `trim_text()` enforces per-agent char caps before LLM calls.
- **LWC v5:** `PriceChart.tsx` uses `createSeriesMarkers(series, markers)` — NOT `series.setMarkers()` (that's v4, will crash).
- **TimesFM:** Fully scaffolded in `quant/timesfm/` but `ENABLE_TIMESFM=false`. Not tested with real model yet.
- **CORS:** Backend reads `CORS_ORIGINS` env var for extra allowed origins (Railway has `https://frontend-sage-nu-51.vercel.app` set).

---

## Frontend Pages

| Route | Page | Status |
|-------|------|--------|
| `/analysis` | Stock analysis with SSE progress stream | ✅ Working |
| `/portfolio` | Watchlist grid with sparklines | ✅ Working |
| `/stock/:ticker` | Deep dive with price history + rec markers | ⚠️ Thin — needs work |
| `/news` | FMP news feed | ✅ Working |
| `/industry` | Sector overview | ✅ Working |
| `/backtest` | Walk-forward backtest with NL config | ✅ Working |
| `/paper-trading` | Virtual portfolio + equity curve | ✅ Working |

---

## What's Left (see TODO.md for full detail)

**High priority:**
1. **Railway Volume** — add `/data` volume so SQLite survives redeploys
2. **Sentry on frontend** — install `@sentry/react` in `frontend/`, init in `main.tsx` with `VITE_SENTRY_DSN`
3. **`analysis_history` schema migration** — `entry_price` + `target_price` columns need `ALTER TABLE` guard in `warehouse/db.py`; orchestrator should write them on each run
4. **`StockDeepDivePage`** — currently a thin wrapper; wire up `HistoricalPerformanceCards` and `PerformanceMetricsPanel` components (already exist)
5. **FMP section wiring** — `fmp_client.py` has `get_grades_summary()`, `get_stock_news()`, `get_dcf_valuation()`, `get_institutional_holders()` but none are wired into `market_enrichment.py` sections yet

**Medium priority:**
6. **Insider Transactions Agent** — Form 4 via edgartools → `agents/insider.py`
7. **Earnings Call Transcript Agent** — 8-K exhibit text → `agents/transcript.py`
8. **RAG auto-reseed** — after `change_detector.incremental_update()` finds new filings, re-seed Pinecone
9. **Multi-ticker scanner page** — batch analysis of 3-10 tickers with ranked table

---

## Env Vars (already set in Railway + local .env)

All keys are populated: `ANTHROPIC_API_KEY`, `TIINGO_API_KEY`, `FMP_API_KEY`, `FRED_API_KEY`, `TAVILY_API_KEY`, `PINECONE_API_KEY`, `SENTRY_DSN`.

To add a new env var to Railway:
```bash
railway service ai-financial-analyst
railway variables set KEY=VALUE
```

To add to Vercel frontend:
```bash
cd frontend && echo "VALUE" | vercel env add KEY production
vercel deploy --prod --yes --scope chadreadey-7282s-projects
```

---

## Recent Git History

```
aec55a6 fix: resolve TypeScript build errors blocking Vercel deploy
04ad9fd docs: replace planning docs with TODO.md and full README rewrite
1cc173d feat: expand warehouse, RAG pipeline, and SEC parsers
55b8149 feat: add TimesFM nightly batch + Redis cache module
dbf3a4f feat: expand core analysis engine with new enrichment signals
dcda0c7 feat: add React + Vite frontend replacing Streamlit UI
e0bfe3c feat: add FastAPI backend replacing Streamlit
857fdcd chore: migrate hosting from Fly.io to Railway + Vercel
```

---

## Quick Smoke Tests

```bash
# Backend health
curl https://ai-financial-analyst-production-b148.up.railway.app/api/health

# Railway logs
railway logs --tail 50

# Local backend dev
uvicorn backend.main:app --reload --port 8000

# Local frontend dev
cd frontend && npm run dev

# Run analysis CLI
python main.py AAPL

# TypeScript check
cd frontend && npx tsc --noEmit
```
