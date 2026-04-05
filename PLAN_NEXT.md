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

### P0: Quant-Only Backtest Engine (COMPLETED)
- `quant/backtest.py` — core engine: walk-forward + single-pass backtesting
- `quant/universe.py` — liquid_10/20/50 stock universes
- `scripts/run_backtest.py` — CLI with `--walk-forward`, `--universe`, `--rebalance` flags
- `backend/routers/backtest.py` — `/api/backtest/quant/run` + `/quant/result/{id}` + `/quant/universes`
- Local CSV price cache (`.price_cache/`) to avoid Tiingo rate limits
- Features: 10bps costs, 1-day execution delay, ATR-based sizing, stop-loss at 2x ATR
- Metrics: Sharpe, Sortino, Calmar, max drawdown, win rate by conviction band, SPY alpha
- Validated: signals compute correctly (composites -0.53 to +0.42), 22 rebalance dates per year

**Still needed for TimeSeriesFM overlay:**
- `scripts/run_timesfm_backtest.py` — backtest with P50 forecast as 7th signal

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
