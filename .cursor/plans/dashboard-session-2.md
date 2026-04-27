# Session Plan: Portfolio Dashboard v2

Carry-overs from session 1 that we kept out of scope to ship v1.

## Parked from session 1

1. **Live agent streaming on deep-dive page**
   When CandidatePipeline kicks off `/api/analysis/run` and we navigate
   with `?job_id=...`, the deep-dive page only polls `/result/{job_id}`
   every 5s. The AnalysisPage already has a full SSE/EventSource
   progress stream (`useAnalysis` hook). Lift that progress UI into a
   shared component (`<JobProgressStrip jobId=...>`) and render it on
   the deep-dive header so the user sees agents firing in real time
   when they click "Analyze" from the candidate sidebar.

2. **Persist quant rankings on a real schedule**
   Current `/api/portfolio/candidates` has a 1-hour TTL and recomputes
   on demand over LIQUID_20. To extend to S&P-500 without making the
   first request after expiry slow:
   - Add a tiny APScheduler/cron job that recomputes every N hours
   - Bump universe to LIQUID_100 or full S&P 500
   - Surface a `last_ranked_at` timestamp in the sidebar header

3. **Auto-refresh stale verdicts**
   When `stale_count > 0`, expose a "Re-analyze stale positions" button
   that POSTs to a new `/api/paper-trading/reanalyze-stale` endpoint
   which fans out one job per ticker whose `days_stale > 7`.

4. **Replace OpenPositionsTable**
   Phase 2 left `OpenPositionsTable.tsx` in the tree (now unused by
   PaperTradingPage). It can be deleted once we're confident
   PositionsWithVerdictsTable is stable.

5. **Migrate /stock alias**
   Phase 4 added `/deepdive/:ticker` as an alias to `/stock/:ticker`.
   At some point pick one, remove the other, and update outbound
   links across the codebase (watchlist, recommendations, etc.).

6. **Avg P&L is naïve**
   `PortfolioOverviewStrip` shows `avg_unrealized_pnl_pct` weighted by
   entry price (used as a proxy for position equity). Once Alpaca
   account integration is fully wired we should join with the real
   per-position market value, not entry value.

7. **Better signal explanations on candidates**
   `top_signals` lists the raw signal name + score (e.g. `obv_trend
   +0.30`). Add a tooltip or inline gloss so a non-quant user can read
   "On-balance volume trend" instead.

## Already in the user's session-2 backlog (from session 1 plan)

These remain valid:

1. Portfolio-level metrics panel (Sharpe, max DD, vs-SPY)
2. Agent hit-rate tracker (per-agent, signal_score vs realized fwd return)
3. Auto-refresh stale verdicts (overlaps with #3 above)
4. Portfolio construction v0 (mean-variance, ~30 lines of PyPortfolioOpt)
5. Challenger agent on STRONG BUY synthesis verdicts
6. News feed filtered to held + candidate tickers
