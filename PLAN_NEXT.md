# Next Phase Plan — From Prototype to Fundable Strategy

This plan captures all remaining work from the GAN-style evaluation, organized by priority.

---

## DONE THIS SESSION

### P0: Math-Based Technical Signals (COMPLETED)
- `quant/signals.py` — deterministic computation of SMA, RSI, Bollinger, OBV, mean reversion, ATR
- Wired into enrichment pipeline as `computed_signals` section
- Pattern agent prompt updated to interpret pre-computed signals (not compute them)
- Reproducibility proven: std=0.000000 across 3 runs (perfectly deterministic)

### P0: Signal Reproducibility Module (COMPLETED)
- `scripts/test_reproducibility.py` — runs ticker N times, measures variance
- Supports `--quant-only`, `--llm-only`, and combined modes
- Reports per-signal std, composite variance, verdict consistency
- Outputs JSON for tracking over time

---

## IN PROGRESS

### P0: Quant-Only Backtest Engine
**Goal:** Backtest the 6 technical signals on 10 years of price data without any LLM calls.
**Why:** Cheapest path to a track record. Proves signal quality independently.

**Design:**
1. Fetch 10-year daily OHLCV for a universe (S&P 500 or subset)
2. At each rebalance point (weekly or monthly), compute `SignalVector` for each stock
3. Rank stocks by composite score, go long top decile, short bottom decile
4. Track returns with realistic assumptions:
   - 10bps round-trip transaction costs
   - 1-day execution delay (no same-day fills)
   - Position sizing based on ATR regime
5. Compute: Sharpe, Sortino, max drawdown, Calmar, win rate by conviction band
6. Compare to SPY buy-and-hold benchmark
7. Walk-forward: train weights on rolling 2-year window, test on next 6 months

**TimeSeriesFM integration:**
- Run TimeSeriesFM price forecasts for each stock at each rebalance point
- Add P50 forecast return as a 7th signal
- Test whether TimeSeriesFM overlay improves Sharpe over quant-only

**Files to create:**
- `quant/backtest.py` — core backtesting engine
- `quant/universe.py` — stock universe management (S&P 500 constituents)
- `scripts/run_backtest.py` — CLI entry point
- `scripts/run_timesfm_backtest.py` — backtest with TimeSeriesFM overlay

**Data source:** Tiingo EOD (free tier supports historical data)

### P1: IC Weight Calibration
**Goal:** Replace hardcoded IC weights with data-derived weights.

**Academic reference values (from literature search):**

| Signal Category | Published IC | Recommended Weight |
|---|---|---|
| Earnings (SUE, revisions) | 0.04–0.10 | 25–30% |
| Momentum (12-1 month) | 0.04–0.06 | 15–20% |
| Valuation (E/P, EV/EBITDA) | 0.03–0.06 | 15–20% |
| Quality/Profitability | 0.03–0.06 | 15% |
| Risk (low vol, BAB) | 0.02–0.04 | 10% |
| Macro (yield curve, rates) | 0.01–0.03 | 5–10% |
| Technical (RSI, Bollinger) | 0.00–0.02 | Minimal standalone |

**Key papers:**
- Jegadeesh & Titman (1993): momentum IC 0.04-0.06
- Bernard & Thomas (1989): PEAD IC 0.06-0.09
- Gu, Kelly & Xiu (2020): ML factor IC 0.04-0.09
- McLean & Pontiff (2016): apply 0.4x haircut to pre-2000 anomalies
- Harvey, Liu & Zhu (2016): require t-stat > 3.0 for factor significance
- Lopez-Lira & Tang (2023): LLM sentiment IC 0.03-0.06

**Implementation:**
1. After 50+ backtest periods, compute rank IC for each signal vs forward returns
2. Use trailing 12-month IC for adaptive weighting
3. Apply Ledoit-Wolf shrinkage on signal covariance matrix
4. Store calibrated weights in config, update monthly

---

## NOT STARTED (by priority)

### P1: API Authentication
- Add API key middleware to FastAPI backend
- Simple: check `X-API-Key` header against env var
- Rate limiting: 10 analyses/hour per key
- Files: `backend/middleware/auth.py`, update `backend/main.py`

### P1: Accumulate 50+ Paper Trades
- Run daily scans across a universe of 50-100 stocks
- Auto-paper-trade on conviction >= 0.40
- Track outcomes at 30/60/90 day horizons
- Compute actual IC per signal from real outcomes
- Files: `scripts/daily_scan.py` (cron job)

### P2: Replace SQLite with Postgres
- Railway supports Postgres natively
- Eliminates concurrent write issues
- Use asyncpg for async access
- Migrate: analysis_history, paper_positions, paper_trades, warehouse
- Files: modify `sec/cache.py`, `backend/routers/paper_trading.py`, `warehouse/db.py`

### P2: Structured Error Reporting
- When enrichment fails silently, tag the analysis output
- Add `data_completeness` field to structured verdict
- Surface to user: "This analysis was produced without FMP data"
- Files: modify `orchestrator.py`, `market_enrichment.py`

### P2: Consult Securities Lawyer
- Before taking any investment money
- Key questions: RIA registration requirements, AI disclosure obligations
- Budget: $2-5K for initial consultation
- Timeline: before any funding conversation

### P3: Integration Tests
- Test critical path: analysis -> save -> paper trade -> PnL
- Test concurrent access patterns
- Test job lifecycle (create, stream, timeout, cleanup)
- Files: `tests/test_integration.py`

### P3: CORS Fix
- Replace wildcard Vercel subdomain match with specific project URL
- File: `backend/main.py`

### P3: Fix Wave 2 Serial Execution
- `orchestrator.py` line ~643: competitive agents run serially
- Change to `asyncio.gather()` like wave 1
- Easy win for latency

### P3: Clean Up Dead Code
- `FMPClient.get_institutional_holders()` always returns []
- Remove or gate behind paid plan check

---

## Success Criteria for Funding Conversations

1. **Quant-only backtest Sharpe > 0.7** across 5+ years
2. **50+ paper trades** with tracked 30-day outcomes
3. **Win rate > 55%** in conviction >= 0.60 band
4. **Signal IC validation** showing positive IC for at least 4/6 signal categories
5. **TimeSeriesFM overlay** improves Sharpe by >= 0.1 vs quant-only
6. **Live demo** showing real-time analysis with math-based signals
7. **Legal clarity** on RIA requirements
