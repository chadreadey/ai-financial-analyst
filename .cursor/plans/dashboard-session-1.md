# Session Plan: Portfolio Dashboard v1

**Goal:** end this session with a dashboard that joins paper positions + latest agent verdicts + candidate pipeline in one screen. Visible, usable, not polished. Paralysis-breaking over architecture-perfect.

**Time budget:** one focused day, ~6-8 hours of coding. If you overshoot, stop at phase 3 and ship what you have.

**Branch strategy:** new branch `dashboard-v1` off `main` (after PR #5 is merged). One PR, multiple commits.

---

## What exists you're building on

Already there — don't rebuild:

- `frontend/src/pages/PaperTradingPage.tsx` (141 LOC) — working skeleton with rebalance button
- `frontend/src/components/paper-trading/`
  - `OpenPositionsTable.tsx` (123) — current positions grid
  - `PaperMetricsPanel.tsx` (51) — equity/Sharpe/DD stats
  - `AccountPanel.tsx` (44) — Alpaca account info
  - `ClosedTradesTable.tsx` (75), `OrderHistoryTable.tsx` (64)
- `frontend/src/hooks/usePaperTrading.ts` — bundled state (positions, metrics, equity curve, orders, etc.)
- `frontend/src/pages/StockDeepDivePage.tsx` — per-ticker agent review page already exists
- `frontend/src/components/deepdive/AnalysisAccordion.tsx` — renders agent reports (reuse this)
- `backend/routers/paper_trading.py` — 8 endpoints working
- `backend/routers/analysis.py` — `/history/{ticker}` + `/history/{analysis_id}` return agent reports

**The critical observation:** the data you need is already in the backend. You're joining it, not producing it.

---

## Explicitly NOT in scope (write this down, come back to it)

Kill these the moment they tempt you:

- ❌ New agent prompts or signal work
- ❌ Portfolio construction / optimization math
- ❌ Automatic agent re-runs on stale positions (manual trigger only)
- ❌ Live price streaming (use last-close for v1)
- ❌ Factor exposures / sector pie charts
- ❌ Bloomberg-terminal styling — keep the existing muted palette
- ❌ Backtesting anything
- ❌ LLM news summaries
- ❌ Mobile responsive tweaks

Every one of these is a valid future session. None today.

---

## Pre-work (30 min)

1. Verify PR #5 merged to main, Railway and Vercel deployed clean. If not, fix that first.
2. `git checkout -b dashboard-v1`
3. `cd frontend && npm run dev` + `uvicorn backend.main:app --reload` locally.
4. Open `/paper-trading` in browser. Confirm positions table renders with whatever data you have. Add one or two paper positions if empty (you need data to look at).
5. Run one agent analysis on a ticker you hold (`/analysis` → enter ticker → Run). You need at least one position WITH a recent analysis to build against.

**Gate:** you can see real positions and real agent reports separately before starting.

---

## Phase 1 — Backend join endpoint (1.5 hrs)

**Goal:** single backend call that returns "positions + latest agent verdict for each."

**New endpoint:** `GET /api/paper-trading/positions-with-verdicts`

Returns:

```json
{
  "positions": [
    {
      "ticker": "NVDA",
      "entry_price": 450.0,
      "entry_verdict": "BUY",
      "qty": 10,
      "current_price": 512.30,
      "unrealized_pnl_pct": 0.138,
      "latest_verdict": {
        "analysis_id": "abc123",
        "verdict": "STRONG BUY",
        "conviction": "HIGH",
        "weighted_score": 0.72,
        "price_target": 580.0,
        "as_of": "2026-04-19T14:22:00Z",
        "days_stale": 2
      }
    }
  ],
  "total_equity": 50000.0,
  "day_pnl_usd": 234.50,
  "day_pnl_pct": 0.0047
}
```

**Implementation:**

In `backend/routers/paper_trading.py`, add a new handler that:

1. Calls existing `get_open_positions()` (already there)
2. For each ticker, calls `analysis.get_latest_history(ticker)` — grabs most recent analysis record
3. Extracts the synthesis verdict from the structured JSON block (already parsed by orchestrator)
4. Computes `days_stale = (today - analysis.created_at).days`
5. Gets current price from `price_provider.get_current_price(ticker)` (already exists, batched)
6. Joins into the response shape above

**Don't build:** a new database table, a new model, or async streaming. This is an in-process join over existing data.

**Acceptance:** `curl /api/paper-trading/positions-with-verdicts` returns clean JSON with 5+ positions and verdicts within 2 seconds.

---

## Phase 2 — Portfolio Overview page (2 hrs)

**Goal:** one table, joined view, visually informative.

**Decision:** extend `PaperTradingPage.tsx` — don't make a new page. Paralysis-break comes from using what you have, not proliferating files.

**Changes:**

1. New hook: `frontend/src/hooks/usePortfolioOverview.ts` (~60 lines)
   - Calls the new endpoint on mount, polls every 60s
   - Returns `{ positions, totals, isLoading, refresh }`
2. Replace `OpenPositionsTable.tsx` content (or add a v2 side-by-side):
   - Add columns: Current Px, Day Δ%, Verdict (colored badge), Conviction, Days Since Analysis, Target Px, Implied Upside %
   - Keep existing columns: Ticker, Entry, Entry Verdict, Close button
   - Stale badge: if `days_stale > 7`, show yellow "Stale (Nd)" chip; red if > 14
   - Row background tint: light green if current verdict is BUY/STRONG BUY, light red if SELL/STRONG SELL, neutral for HOLD
   - Click row → navigate to `/deepdive/{ticker}` (already exists)
3. Header strip above the table:
   - Total equity, day P/L ($ and %), # positions, # stale analyses
   - Simple. No charts. Just numbers with labels.

**Styling:** reuse existing Card, Badge, Table components from `@/components/ui/*`. No new design work.

**Acceptance:** you look at the page, your positions are there, you can see which ones the agents say to BUY vs SELL right now, and which ones haven't been analyzed in too long.

---

## Phase 3 — Candidate Pipeline (2 hrs)

**Goal:** a sidebar or bottom section that shows "names the quant likes but you don't own yet."

**Backend:** you already have `backend/routers/backtest.py` with `/quant/run` and `/quant/universes`. The quant screener output is accessible.

**Minimum path:**

1. New endpoint: `GET /api/portfolio/candidates?limit=20`
   - Loads the latest quant/backtest ranking output from whatever it persists to (if it doesn't persist rankings yet, add a simple cache: run the ranker nightly via a scheduler, save to `quant_rankings` table in SQLite, read from there)
   - Filters out tickers already in open positions
   - Returns top 20 by composite score

   **Shortcut if rankings aren't persisted yet:** run a small live ranking over a fixed universe (e.g., S&P 500 tickers you already have in `quant/universe.py`) using the current signal stack. Cache for 1 hour. Don't overthink persistence — this is a daily-cadence feature.

2. Frontend component: `frontend/src/components/paper-trading/CandidatePipeline.tsx` (~80 lines)
   - List of 10-20 rows: ticker, composite score, top 3 contributing signals (e.g., "ERM +0.85, BOLLINGER -0.2, OBV +0.3")
   - Each row has an "Analyze" button that kicks off an agent run (POST `/api/analysis/run`) and navigates to `/deepdive/{ticker}` with the job_id
3. Placement: right sidebar on PaperTradingPage OR a new tab. Sidebar is better — keeps everything on one screen.

**Acceptance:** you see a ranked list of names you don't own, you click one, agents run, you end up on the deep-dive page watching them stream. That's the core loop of "discovery → research."

---

## Phase 4 — Position → Agent Detail link (1.5 hrs)

**Goal:** one click from a held position to all 6 agent reports for it.

**Decision:** do NOT build a new modal/drawer. Link directly to the existing `StockDeepDivePage` (or `AnalysisPage` showing the history entry).

**Changes:**

1. In the open-positions table row, the ticker cell becomes a `<Link to={`/deepdive/${ticker}`}>`.
2. `StockDeepDivePage.tsx` — check if it already loads latest agent history. If not, add a tab or section at the top that renders `AnalysisAccordion` with the most recent analysis for this ticker.
3. Pass `?source=portfolio` in the URL so the deep-dive page can show a "← Back to portfolio" breadcrumb.

**If `StockDeepDivePage` is already good for this purpose:** skip most of the work; just add the link and breadcrumb. Verify before over-engineering.

**Acceptance:** click NVDA from the portfolio, see the 6 agent reports + synthesis for NVDA, click back, return to portfolio.

---

## Phase 5 — Ship it (30 min)

1. Local smoke: add a position, run its analysis, refresh portfolio page, verify verdict appears with correct staleness.
2. `npm run lint` and `tsc --noEmit` — at least not worse than current.
3. `python -m pytest tests/ -x --tb=short` on backend.
4. Commit in logical chunks:
   - `feat(backend): add positions-with-verdicts join endpoint`
   - `feat(dashboard): portfolio overview with verdicts and staleness`
   - `feat(dashboard): candidate pipeline sidebar`
   - `feat(dashboard): link positions to deep-dive`
5. PR against main. Merge. Deploy. Open the deployed URL. Actually use it.

**Acceptance for the whole session:** you have a URL you can open that shows your paper positions, what the agents currently think about each, and 10 candidates to analyze next. End of day you add 2-3 candidates to paper positions based on agent reports.

---

## Session 2 backlog (don't start today)

In priority order when you come back next weekend:

1. **Portfolio-level metrics panel** — Sharpe, max DD, vs-SPY benchmark, sector allocation pie
2. **Agent hit-rate tracker** — for each agent (DCF, Risk, etc.), track hit rate of their SIGNAL_SCORE vs realized forward returns on historical calls. This is agent validation.
3. **Auto-refresh stale verdicts** — button "Re-analyze all positions with analyses > 7 days old"
4. **Portfolio construction v0** — a simple mean-variance optimizer over top-ranked + held names, recommends weight adjustments. 30 lines of PyPortfolioOpt.
5. **Challenger agent** — when synthesis says STRONG BUY, a counter-agent runs arguing the bear case. Catches groupthink.
6. **News feed filtered to held + candidate tickers** — you already have news endpoints.

Each of these is a future half-day. None today.

---

## The single discipline

If, during the session, you find yourself thinking "I should just quickly add X" where X isn't in the plan: open a `dashboard-session-2.md` file in `.cursor/plans/`, write the idea there, move on. The paralysis comes from letting scope creep reset progress. The cure is a visible list of "not today."
