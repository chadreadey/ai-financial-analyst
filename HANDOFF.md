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
| RAG | Pinecone, index `financial-analyst`, llama-text-embed-v2 (currently disabled) |
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
quant/backtest.py            ← quant-only backtest engine (no LLM)
quant/signals.py             ← 6 deterministic technical signals
quant/universe.py            ← S&P 500 subset ticker lists (liquid_10/20/50)
quant/timesfm/               ← TimesFM/Chronos model wrapper + signal extraction
```

---

## Quant Backtest Engine (as of 2026-04-05)

### What's Built

`quant/backtest.py` — full quant-only backtest engine with:
- **6 technical signals**: SMA trend, mean reversion Z-score, Bollinger %B, RSI, OBV trend, ATR regime
- **Multi-level regime detection**: VIX thresholds (caution=20, risk-off=28) + SPY 200d SMA + death/golden cross (50d vs 200d SMA)
- **Position sizing by regime**: risk_off=25%, bearish=50%, cautious=70%, bullish/strong_bull=100%
- **VIX-driven risk-off blocks ALL positions** (both longs and shorts) to prevent snap-back losses
- **Golden cross lowers long threshold** by 0.10 (more aggressive entries in strong trends)
- **IC weight calibration** (adaptive signal weights from trailing Spearman rank IC) — works but equal weights outperform OOS
- **TimesFM/Chronos overlay** as optional 7th signal (blended into composite score)
- **Walk-forward validation** with rolling train/test windows
- **Local CSV price cache** in `.price_cache/` to avoid Tiingo rate limits
- **VIX data** fetched from yfinance with local cache

### Best Configuration Found

| Parameter | Value | Why |
|-----------|-------|-----|
| Regime filter | ON | VIX + death/golden cross |
| VIX caution threshold | 20 | Reduce sizing when elevated |
| VIX risk-off threshold | 28 | Go to cash (no longs or shorts) |
| Death/golden cross | ON | SPY 50d vs 200d SMA |
| Short threshold | -0.40 | Tightened from -0.20 |
| Long threshold | 0.20 | Standard |
| IC calibration | OFF | Equal weights more robust OOS |
| Rebalance | Monthly (in-sample), Weekly (walk-forward) | Weekly survives crises better |

### Performance Results

**Single-period (liquid_10, 2022-2026, monthly):**
- **Sharpe 1.10**, +51.76% return, +6.21% alpha over SPY, 9.63% max drawdown

**Walk-forward (liquid_20, 2018-2026, weekly):**
- **Sharpe 0.42**, +4.08% return, 10.62% max drawdown, positive across all windows

**Previous (before VIX regime):** Sharpe 0.58 single-period, -0.50 walk-forward

### CLI

```bash
# Single backtest
python scripts/run_backtest.py --universe liquid_10 --start 2022-01-01 --no-ic-calibration

# Walk-forward
python scripts/run_backtest.py --universe liquid_20 --start 2018-01-01 --walk-forward --rebalance weekly --no-ic-calibration

# TimesFM/Chronos overlay A/B
python scripts/run_timesfm_backtest.py --universe liquid_10 --start 2022-01-01 --sweep-weights

# All flags
--universe liquid_10|liquid_20|liquid_50
--tickers AAPL,MSFT,GOOGL
--start/--end YYYY-MM-DD
--rebalance weekly|monthly
--long-threshold 0.20 / --short-threshold -0.40
--vix-caution 20 / --vix-risk-off 28
--no-regime-filter / --no-cross-detection
--no-ic-calibration / --ic-shrinkage 0.90
--walk-forward / --train-months 24 / --test-months 6
--max-positions 10 / --short-min-signals 3
```

### TimesFM / Chronos Status

- **Model wrapper** (`quant/timesfm/model.py`): Tries Google TimesFM first, falls back to Amazon Chronos-T5-Small
- **TimesFM** requires Linux + `pip install timesfm torch`. API compat for v2.0: uses `max_horizon` in `ForecastConfig`, `inspect.signature` to detect `freq` param support
- **Chronos** works on macOS x86_64 CPU: `pip install chronos-forecasting torch` (py312 env)
- **Chronos A/B result**: Neutral impact — Sharpe 0.81 vs 0.82 baseline at 15% weight
- **TimesFM A/B on Colab T4**: IN PROGRESS — user running on Google Colab with T4 GPU. Results pending.
- Local py312 env for Chronos: `/Users/chadreadey/opt/anaconda3/envs/py312/bin/python`

---

## Signal Architecture

### Synthesis Agent → Signal Aggregator

`prompts/synthesis.md` replaces the CIO persona with a **Systematic Investment Decision Engine**:
- Each of the 6 agent reports is scored on a normalized -1.0 to +1.0 scale
- Scores are combined using IC-weighted averages (Earnings 0.22, Pattern 0.18, Risk 0.17, DCF 0.17, Competitive 0.14, Macro 0.12)
- Macro operates as a **regime multiplier** (adverse macro scales all conviction by 0.7), not an additive signal
- Output is JSON-first with `conviction_score` (0-1), `weighted_score` (-1 to +1), `signal_breakdown`, `prior_bull_probability`, `sizing_guidance`

### Pattern Agent → Math-Based Signals + LLM Interpretation

Technical signals computed with exact math in `quant/signals.py` (not LLM-approximated):
- **SMA Trend** (weight 0.25) — 50/200-day crossover
- **Mean Reversion Z-score** (weight 0.20) — suppressed on trending stocks
- **Bollinger %B** (weight 0.20) — with squeeze detection
- **RSI** (weight 0.15) — with divergence detection
- **OBV Trend** (weight 0.20) — volume confirmation
- **ATR Regime** (no weight) — position sizing / stop-loss only

### Auto-Paper-Trade Pipeline

`orchestrator.py → _auto_paper_trade()` fires after every analysis:
- conviction_score ≥ 0.40 → auto-enter position (LONG for BUY, SHORT for SELL)
- Stop-loss override: deterministic from 2×ATR, sanity checks on LLM output
- Entry price override: always uses market price, never trusts LLM

---

## LLM Variance Problem

Documented in memory. Key stats from 5-run AAPL reproducibility test:
- DCF std=0.30, conviction std=0.22 — high variance across identical inputs
- **Mitigations implemented**: deterministic signal computation, entry/stop-loss overrides
- **Mitigations planned**: GraphRAG (see `PLAN_GRAPHRAG.md`), constrained DCF inputs, ensemble averaging

---

## Recent Git History

```
85b5f41 fix: use max_horizon (not horizon) in TimesFM ForecastConfig
3ae9cb2 fix: set horizon=128 at TimesFM compile time, not forecast time
c8223e6 fix: TimesFM 2.0 API compat — remove freq param, fix singleton caching
28cf3ae feat: VIX regime detection, death/golden cross, IC calibration, Chronos fallback
7b6e4b5 fix: override LLM stop_loss with computed value when nonsensical
0a7addf chore: planning + reproducibility testing
2c75ec7 docs: update handoff and plan for session handover
055441a feat: math-based technical signals + reproducibility tester + plan
2991e74 fix: override LLM entry_price with actual market price
400e543 fix: auto-paper-trade fallback for missing conviction_score
```

---

## What's Next

### Immediate (in priority order)
1. **TimesFM backtest results** — user running sweep on Colab T4. Analyze results when available.
2. **Two-tier rebalancing** — quant signals run weekly (free), trigger LLM analysis only on material signal changes (new entry/exit, regime shift, stop-loss hit). Saves API costs while keeping weekly responsiveness.
3. **GraphRAG Phase 1** — SQLite property graph for deterministic agent context (plan in `PLAN_GRAPHRAG.md`, approved by user)

### Backlog
4. API authentication before investor demos
5. 50+ paper trades (daily scan script)
6. Replace SQLite with Postgres for concurrent safety
7. Insider Transactions Agent (Form 4)
8. RAG auto-reseed after filing updates
9. Multi-ticker scanner page

---

## Env Vars (already set in Railway + local .env)

All keys populated: `ANTHROPIC_API_KEY`, `TIINGO_API_KEY`, `FMP_API_KEY`, `FRED_API_KEY`, `TAVILY_API_KEY`, `PINECONE_API_KEY`, `SENTRY_DSN`.

---

## Quick Smoke Tests

```bash
# Backend health
curl https://ai-financial-analyst-production-b148.up.railway.app/api/health

# Local backend dev
uvicorn backend.main:app --reload --port 8000

# Local frontend dev
cd frontend && npm run dev

# Run analysis CLI
python main.py AAPL

# Run quant backtest (best config)
set -a && source .env && set +a
python scripts/run_backtest.py --universe liquid_10 --start 2022-01-01 --no-ic-calibration

# Run walk-forward (out-of-sample validation)
python scripts/run_backtest.py --universe liquid_20 --start 2018-01-01 --walk-forward --rebalance weekly --no-ic-calibration
```
