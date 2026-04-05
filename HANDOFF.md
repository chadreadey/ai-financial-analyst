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
- **Peer validation:** Peer candidates from Tavily are validated against the SEC ticker map (~13k tickers). Prevents brand names (NIKE, ASICS) from being treated as tickers.

---

## Signal Architecture (as of 2026-04-05)

The system has been redesigned from equity-research narration to systematic trading signals.

### Synthesis Agent → Signal Aggregator

`prompts/synthesis.md` replaces the CIO persona with a **Systematic Investment Decision Engine**:
- Each of the 6 agent reports is scored on a normalized -1.0 to +1.0 scale
- Scores are combined using IC-weighted averages (Earnings 0.22, Pattern 0.18, Risk 0.17, DCF 0.17, Competitive 0.14, Macro 0.12)
- Macro operates as a **regime multiplier** (adverse macro scales all conviction by 0.7), not an additive signal
- Output is JSON-first with `conviction_score` (0-1), `weighted_score` (-1 to +1), `signal_breakdown`, `prior_bull_probability`, `sizing_guidance`
- Verdict maps directly to sizing: STRONG BUY = 1.5× weight, BUY = 1.0×, HOLD = 0×, SELL = 1.0× short, STRONG SELL = 1.5× short
- Price targets are triangulated across DCF intrinsic value, peer multiples, analyst consensus, and technical levels

### Pattern Agent → Math-Based Signals + LLM Interpretation

Technical signals are now **computed with exact math** in `quant/signals.py` (not LLM-approximated):
- **SMA Trend** (weight 0.25) — 50/200-day crossover, gate signal for longs
- **Mean Reversion Z-score** (weight 0.20) — suppressed on trending stocks (>30% drift)
- **Bollinger %B** (weight 0.20) — with squeeze detection
- **RSI** (weight 0.15) — with divergence detection bonus
- **OBV Trend** (weight 0.20) — volume confirmation
- **ATR Regime** (no weight) — position sizing and stop-loss calculation only
- Composite score: weighted sum, |score| ≥ 0.40 is actionable for paper trading

Computed signals flow via the `computed_signals` enrichment section. The pattern agent LLM **interprets** pre-computed scores (does not compute them). Proven deterministic: std=0.000000 across runs.

Reproducibility tester: `python scripts/test_reproducibility.py AAPL --runs 5`

### Auto-Paper-Trade Pipeline

`orchestrator.py → _auto_paper_trade()` fires after every analysis:
- If `conviction_score ≥ settings.auto_paper_trade_min_conviction` (default 0.40):
  - BUY/STRONG BUY → LONG position auto-created
  - SELL/STRONG SELL → SHORT position auto-created
  - HOLD → no action
- Stop-loss and horizon are written as `exit_conditions` on the position
- Paper positions now have `direction` (LONG/SHORT) and `conviction_score` columns
- PnL math is direction-aware: LONG = (exit - entry) / entry, SHORT = (entry - exit) / entry
- Controlled by `AUTO_PAPER_TRADE=true` and `AUTO_PAPER_TRADE_MIN_CONVICTION=0.40` env vars

---

## Frontend Pages

| Route | Page | Status |
|-------|------|--------|
| `/analysis` | Stock analysis with SSE progress stream | ✅ Working |
| `/portfolio` | Watchlist grid with sparklines | ✅ Working |
| `/stock/:ticker` | Deep dive with price chart, hit rate, rec cards, re-run button | ✅ Working |
| `/news` | FMP news feed | ✅ Working |
| `/industry` | Sector overview | ✅ Working |
| `/backtest` | Walk-forward backtest with NL config | ✅ Working |
| `/paper-trading` | Virtual portfolio + equity curve | ✅ Working |

---

## What's Left (see TODO.md for full detail)

**Completed (2026-04-05):**
- ~~Railway Volume~~ — `/data` volume attached, `WAREHOUSE_DB_PATH=/data/warehouse.db`
- ~~Sentry on frontend~~ — `@sentry/react` installed, `VITE_SENTRY_DSN` in Vercel
- ~~Schema migration~~ — `conviction_score`, `bull_probability`, `bear_probability`, `weighted_score`, `sizing_guidance` columns added
- ~~StockDeepDivePage~~ — entry/target prices, hit rate, re-run analysis button wired
- ~~Synthesis → Decision Engine~~ — signal aggregator with IC-weighted scoring, JSON-first output
- ~~Pattern Agent → Signal Vector~~ — SMA, Bollinger, RSI, OBV, mean reversion, ATR signals
- ~~Auto-paper-trade~~ — orchestrator auto-enters positions on conviction ≥ 0.40
- ~~Short position support~~ — direction column, correct PnL math
- ~~FMP stable API migration~~ — all FMP endpoints migrated from legacy v3/v4 to /stable/
- ~~FMP enrichment wiring~~ — analyst grades, DCF cross-check, news, institutional holders
- ~~Entry price override~~ — orchestrator forces market price, never trusts LLM
- ~~Auto-paper-trade fallback~~ — derives conviction from old-format JSON when conviction_score missing
- ~~Math-based technical signals~~ — `quant/signals.py` replaces LLM-approximated indicators
- ~~Signal reproducibility tester~~ — `scripts/test_reproducibility.py`

**Next priority — see `PLAN_NEXT.md` for full roadmap:**
1. **Quant-only backtest engine** — backtest `quant/signals.py` on 10yr price data, no LLM. Target Sharpe > 0.7.
2. **TimeSeriesFM backtest overlay** — add P50 forecast as 7th signal, test additive value.
3. **IC weight calibration** — replace hardcoded weights with data-derived IC from backtest results.
4. **API authentication** — add API key middleware before any investor demos.
5. **50+ paper trades** — daily scan script to accumulate tracked outcomes.

**Also remaining (lower priority):**
6. **Alpha vs SPY** — compute in watchlist summary endpoint
7. **Replace SQLite with Postgres** — for concurrent safety
8. **Insider Transactions Agent** — Form 4 via edgartools → `agents/insider.py`
9. **Earnings Call Transcript Agent** — 8-K exhibit text → `agents/transcript.py`
10. **RAG auto-reseed** — after `change_detector.incremental_update()` finds new filings, re-seed Pinecone
7. **Multi-ticker scanner page** — batch analysis of 3-10 tickers with ranked table

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
055441a feat: math-based technical signals + reproducibility tester + plan
2991e74 fix: override LLM entry_price with actual market price
400e543 fix: auto-paper-trade fallback for missing conviction_score
7225d27 fix: migrate FMP client from legacy v3/v4 to stable API endpoints
2a8cc71 feat: wire FMP enrichment sections into agent pipeline
773363d fix: capture prose both before and after JSON block in synthesis output
2a4498e feat: signal engine rewrite + auto-paper-trade pipeline
762885c feat: wire StockDeepDivePage with entry/target prices, hit rate, re-run button
83b3c5a feat: add Sentry error monitoring to React frontend
04ad9fd docs: replace planning docs with TODO.md and full README rewrite
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
