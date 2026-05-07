# Two-Stage Pipeline — Implementation Blueprint

**Branch**: `feat/two-stage-pipeline` (worktree: `.worktrees/two-stage-pipeline`)
**Base branch**: `main`
**Owner role (Cursor agent)**: Implementer
**Date authored**: 2026-04-27
**Do not implement the feature** — read this document, verify every cited file:line, then follow the Build Sequence.

---

## 1. Codebase Orientation

### Current Rebalance Flow

`backend/paper_scheduler.py` defines `run_rebalance` (line 31). The current flow:

1. `get_alpaca_client()` → current Alpaca paper positions (line 32-34)
2. If `target_tickers` is None, fall back to `_get_watchlist_tickers()` (line 36-37), which queries `SELECT ticker FROM watchlist` from `settings.warehouse_db_path` (line 23)
3. Build `target_set` of uppercase tickers (line 38)
4. Close any Alpaca positions not in target_set (line 44-50)
5. For each ticker in target_set not already held: create a job, call `run_analysis_job(job, request)` synchronously (line 58), check conviction_score and verdict, submit a market order (line 78). The conviction threshold is `settings.auto_paper_trade_min_conviction` (line 68, default `0.40` per `config.py` line 157).
6. Call `client.sync_positions_to_db()` (line 85)
7. Return `{"status": "ok"|"partial", "closed": [...], "opened": [...], "errors": [...]}`

The monthly cron is `settings.paper_rebalance_cron` (default `"0 9 1 * *"`, set at `config.py` line 173).

The FastAPI endpoint `POST /api/paper-trading/rebalance` is at `backend/routers/paper_trading.py` line 415-424. It imports `run_rebalance` at line 383 (with a try/except guard). It currently reads `body.get("tickers")` and passes it as `target_tickers` (line 419-420).

### Quant Composite Architecture

**`quant/cross_sectional.py`**

- `SIGNAL_FIELDS` (line 77): list of `(field_name, sub_attr)` tuples for all 12 signals that participate in normalization. `sub_attr` is `"score"` for `SignalResult` fields, `None` for plain floats.
- `DEFAULT_COMPOSITE_WEIGHTS` (line 133): production weights as of audit 2026-04-28. Active signals: `earnings_rank_score=0.40`, `qmj_score=0.30`, `obv_trend=0.20`, `institutional_flow_score=0.10`. All others 0.0.
- `normalize_signals_cross_sectionally(signals, sector_fn)` (line 173): takes `dict[str, SignalVector]`, modifies in-place, returns same dict. Requires >= 10 tickers (`MIN_CROSS_SECTION = 10`, line 73). `sector_fn` must be a `Callable[[str], str]`.
- `compute_normalized_composite(sv, weights=None)` (line 229): computes the weighted composite for a single `SignalVector` after normalization.
- `make_volatility_tier_fn(signals, n_tiers=3)` (line 28): builds a grouping function based on ATR volatility tier — this is what `run_walk_forward` passes as the sector_fn to `normalize_signals_cross_sectionally` (see `quant/backtest.py` line 2356).

**`quant/signals.py`**

- `SignalVector` (line 26): dataclass. Key fields for the production composite: `obv_trend: SignalResult` (line 33), `qmj_score: float = 0.0` (line 52), `earnings_rank_score: float = 0.0` (line 38), `institutional_flow_score: float = 0.0` (line 39). Also `atr_regime: SignalResult` (line 34) — needed for `make_volatility_tier_fn`.
- `compute_signal_vector(close, volume, high, low)` (line 423): main entry point for price-based signals.

**`quant/backtest.py`**

- `BacktestConfig` (line 39): `enable_qmj_signal: bool = True` (line 166, default flipped to True on 2026-04-28), `max_per_sector: int = 5` (line 184), `max_long_positions: int = 10` (line 57).
- `compute_signals_at_date(universe_data, as_of_date, lookback_days)` (line 376): PIT-safe — slices `df[df.index <= as_of_date]` before computing signals (line 385).
- `_PRICE_CACHE_DIR` (line 237): `os.path.join(os.path.dirname(__file__), "..", ".price_cache")` — the local price CSV cache.
- `_load_cached(ticker, start_date)` (line 240): loads from `.price_cache/{ticker}.csv`.
- The QMJ precompute block in `run_backtest` is at lines 2232-2265. It checks `config.enable_qmj_signal and _wrds_provider is not None and hasattr(_wrds_provider, "_store")`, then calls `compute_qmj_score(ticker, reb_date.date(), _qmj_store)` per ticker (line 2243). `_qmj_store = _wrds_provider._store` (line 2239).
- The earnings signals precompute: `blend_earnings_signals` sets `sv.earnings_rank_score` (line 2186 call, `quant/earnings_signals.py` line 398).
- The institutional flow precompute: `blend_institutional_flow` sets `sv.institutional_flow_score` (line 2201).
- Sector cap logic: uses `from quant.universe import get_sector` (line 1511), iterates candidates and tracks `sector_counts` (line 1513).
- Cross-sectional normalization: `normalize_signals_cross_sectionally(signals, make_volatility_tier_fn(signals))` (line 2356), then `compute_normalized_composite(sv)` per ticker (line 2418).

**`scripts/run_audit_ic.py`**

- `get_wrds_universe()` (line 132): `SELECT DISTINCT ticker FROM compustat_quarterly ORDER BY ticker` from `WRDS_DB_PATH`.
- Universe intersection logic (line 453-456): `universe = sorted(wrds_tickers & price_tickers)` where `price_tickers = {f.replace(".csv", "") for f in os.listdir(PRICE_CACHE_DIR) if f.endswith(".csv")}`.
- `WRDSPointInTimeStore()` (line 481) + `WRDSFundamentalProvider(store)` (line 482): canonical provider init pattern.
- `compute_signal_panel` (line 165): builds per-ticker scores at a single date. Calls `compute_qmj_score(t, as_of_d, wrds_store)` (line 229), `compute_erm_score` (line 194), `compute_institutional_flow_scores` is NOT called here (the IC script uses different signals for IC measurement than the production composite).

**`quant/universe.py`**

- `get_sector(ticker)` (line 213): returns GICS sector string. Tries `quant.universe_provider` first, falls back to `TICKER_SECTOR` dict. Returns `"Unknown"` for unrecognized tickers.

**`config.py`**

- `settings.auto_paper_trade_min_conviction: float = 0.40` (line 157)
- `settings.warehouse_db_path: str = ".warehouse.db"` (line 131)
- `settings.paper_default_qty: int = 10` (line 172)

**`quant/wrds_store.py`**

- `_DB_PATH = os.path.join(os.path.dirname(__file__), "..", ".wrds_pit.db")` (line 29): the default path relative to `quant/`.
- `WRDSPointInTimeStore()` uses this default path. For the screen function, the caller is `backend/paper_scheduler.py` which is at repo root, so the store will correctly resolve to `.wrds_pit.db` symlinked in the worktree.

**`tests/test_paper_scheduler.py`**

- Exists at `tests/test_paper_scheduler.py` (lines 1-46). Uses `@patch("backend.paper_scheduler.get_alpaca_client")`, `@patch("backend.paper_scheduler.run_analysis_job")`, `@patch("backend.paper_scheduler.create_job")`. This is the mock pattern to follow for new tests.

---

## 2. Architecture Decision

The production composite is a four-signal weighted average that requires:
1. Technical signals from price data (OBV via `compute_signal_vector`)
2. Earnings rank score (ERM+SUE+Dispersion from WRDS IBES via `compute_earnings_signal_scores`)
3. QMJ score (Asness Quality-Minus-Junk from WRDS Compustat via `compute_qmj_score`)
4. Institutional flow score (WRDS 13F + FMP via `compute_institutional_flow_scores`)

The chosen approach: implement `_quant_screen` in `backend/paper_scheduler.py` as a self-contained function that mirrors the per-rebalance precompute block from `quant/backtest.py` (lines 2125-2426), but only runs the four active signals, skips all disabled overlays, and returns a ranked ticker list rather than building Positions.

This keeps the screen in the same module as `run_rebalance`, avoids adding new files to the `quant/` layer (which is backtest-oriented), and makes the failure path simple (one try/except around the whole screen, fall back to watchlist).

### Pipeline ASCII Diagram

```
POST /api/paper-trading/rebalance
              |
              v
       trigger_rebalance()
    [routers/paper_trading.py]
              |
              v
         run_rebalance()
     [backend/paper_scheduler.py]
              |
    +---------+---------+
    |                   |
    | target_tickers    | (None — default path)
    | passed explicitly |
    |    [Stage 0]      |
    |                   v
    |          _quant_screen(as_of_date)   [NEW — Stage 1]
    |           WRDS PIT .db + .price_cache/
    |           earnings + QMJ + OBV + inst_flow
    |           cross-sectional normalize
    |           sector cap (max_per_sector=5)
    |           → top_n_quant tickers (default 30)
    |                   |
    |          [fallback: watchlist table]
    |                   |
    +---------+---------+
              |
              v
         LLM analysis per candidate   [Stage 2 — unchanged]
         run_analysis_job(job, request)
         filter: conviction >= 0.40 + verdict=BUY
              |
              v
         Alpaca paper orders           [Stage 3 — unchanged]
         client.submit_market_order()
```

---

## 3. Files to Modify

| File | Nature of Change |
|---|---|
| `backend/paper_scheduler.py` | Add `_quant_screen()` function; modify `run_rebalance()` signature and priority chain |
| `backend/routers/paper_trading.py` | Extend `trigger_rebalance` body to accept `use_quant_screen` and `top_n_quant` |
| `tests/test_paper_scheduler.py` | Add 5 new test cases (T7-T11) |

## 4. Files to Create

| File | Nature |
|---|---|
| `tests/test_quant_screen.py` | Unit tests for `_quant_screen` in isolation (T1-T6) |
| `tests/test_paper_trading_router_extended.py` | Router-level integration tests for new body shape (T12-T13) |
| `docs/plans/two-stage-pipeline.md` | This blueprint (single commit on the planning branch) |

---

## 5. Function-Level Specifications

### 5.1. `_quant_screen`

**File**: `backend/paper_scheduler.py`

**Location**: Insert before `run_rebalance` (after `_get_watchlist_tickers`).

**Imports to add at top of `backend/paper_scheduler.py`**:
```python
import os
import sqlite3
from datetime import date, datetime
from typing import Any, Optional
```
(Note: `sqlite3` and `logging` already imported; add `os`, `date`, `datetime` from `datetime`)

**Signature**:
```python
def _quant_screen(
    as_of_date: Optional[date] = None,
    top_n: int = 30,
    max_per_sector: int = 5,
    universe: Optional[list[str]] = None,
) -> list[str]:
```

**Docstring**:
```
Rank the WRDS PIT ∩ price-cache universe by the v4-qmj-only composite
and return the top-N tickers subject to a sector cap.

This function replicates the per-rebalance precompute block from
quant/backtest.py (lines 2125–2426) for the four active production
signals only:
  - OBV (price/volume, weight 0.20)
  - earnings_rank_score via ERM+SUE+Dispersion (weight 0.40)
  - QMJ via compute_qmj_score (weight 0.30)
  - institutional_flow_score (weight 0.10)

Point-in-time discipline: all data sources are filtered to as_of_date.
Missing data propagates as NaN for cross-sectional ranking purposes;
tickers where the composite is NaN are excluded from ranking.
Tickers with no WRDS fundamental data (qmj=0.0, earnings=0.0) are
still ranked if they have OBV signal — they receive a neutral composite
for the zeroed components.

Args:
    as_of_date: Ranking date. Defaults to today. Must be <= today.
    top_n: Number of tickers to return.
    max_per_sector: Maximum tickers from any single GICS sector.
    universe: Override the default WRDS ∩ price-cache universe.
              Primarily for testing. If None, derives the intersection
              from the live WRDS DB and .price_cache/ directory.

Returns:
    list[str]: Tickers ordered by composite score descending, length
    <= top_n. May be shorter if universe or sector constraints bind.

Raises:
    Never raises — all exceptions are caught and re-raised as
    RuntimeError by the caller (run_rebalance handles the fallback).
```

**Internal Logic (step-by-step)**:

1. Resolve `as_of_date`: if None, use `date.today()`.

2. **Universe loading**:
   ```python
   if universe is None:
       REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
       WRDS_DB_PATH = os.path.join(REPO_ROOT, ".wrds_pit.db")
       PRICE_CACHE_DIR = os.path.join(REPO_ROOT, ".price_cache")

       conn = sqlite3.connect(WRDS_DB_PATH)
       wrds_rows = conn.execute(
           "SELECT DISTINCT ticker FROM compustat_quarterly ORDER BY ticker"
       ).fetchall()
       conn.close()
       wrds_tickers = {r[0] for r in wrds_rows}

       price_tickers = {
           f.replace(".csv", "")
           for f in os.listdir(PRICE_CACHE_DIR)
           if f.endswith(".csv")
       }
       universe = sorted(wrds_tickers & price_tickers)
   ```
   If `universe` is empty after intersection, log a warning and return `[]`.

3. **Price data loading** (PIT-safe):
   For each ticker in universe, load CSV from `.price_cache/{ticker}.csv`. Use pandas `read_csv` with `parse_dates=["date"], index_col="date"`. Filter to `df[df.index <= pd.Timestamp(as_of_date)]`. Skip tickers with < 60 rows after filtering.
   ```python
   import pandas as pd
   universe_data: dict[str, pd.DataFrame] = {}
   for ticker in universe:
       path = os.path.join(PRICE_CACHE_DIR, f"{ticker}.csv")
       if not os.path.exists(path):
           continue
       df = pd.read_csv(path, parse_dates=["date"], index_col="date")
       df.index = df.index.normalize()
       available = df[df.index <= pd.Timestamp(as_of_date)]
       if len(available) < 60:
           continue
       universe_data[ticker] = available
   ```

4. **Compute technical signals** (OBV + ATR for volatility tier):
   Call `quant.backtest.compute_signals_at_date(universe_data, pd.Timestamp(as_of_date), lookback_days=252)`.
   This returns `dict[str, SignalVector]` using only data up to `as_of_date` (line 385 of backtest.py slices to `df[df.index <= as_of_date]`).

5. **Initialize WRDS store and provider**:
   ```python
   from quant.wrds_store import WRDSPointInTimeStore
   from quant.fundamental_provider import WRDSFundamentalProvider
   store = WRDSPointInTimeStore()
   provider = WRDSFundamentalProvider(store)
   ```

6. **Earnings signals** (`earnings_rank_score`, weight 0.40):
   ```python
   from quant.earnings_signals import compute_earnings_signal_scores, blend_earnings_signals
   earn_scores = compute_earnings_signal_scores(
       list(signals.keys()), provider, as_of_date=as_of_date,
   )
   if earn_scores:
       signals = blend_earnings_signals(signals, earn_scores, weight=0.30)
   ```
   Note: `blend_earnings_signals` sets `sv.earnings_rank_score` on each SignalVector (not the composite directly). The `weight` parameter in `blend_earnings_signals` is unused for score storage — it only sets `sv.earnings_rank_score = score`. Pass any non-zero value.

7. **QMJ signal** (`qmj_score`, weight 0.30):
   ```python
   from quant.factor_baselines import compute_qmj_score
   _qmj_store = store  # WRDSPointInTimeStore directly, not the provider
   for ticker, sv in signals.items():
       try:
           raw = compute_qmj_score(ticker, as_of_date, _qmj_store)
           sv.qmj_score = float(raw) if raw is not None else 0.0
       except Exception:
           sv.qmj_score = 0.0
   ```
   Important: `compute_qmj_score` takes a `WRDSPointInTimeStore` directly (not `WRDSFundamentalProvider`). The provider wraps the store at `provider._store`. You can also use `store` directly since you already have it.

8. **Institutional flow signal** (`institutional_flow_score`, weight 0.10):
   ```python
   from quant.institutional_flow import compute_institutional_flow_scores, blend_institutional_flow
   inst_scores = compute_institutional_flow_scores(
       list(signals.keys()),
       as_of_date=as_of_date,
       wrds_store=store,
       fmp_client=None,   # disk cache only — no API calls in the live screen
       fmp_cache=None,
       finnhub_client=None,
       finnhub_disk_cache=None,
   )
   if inst_scores:
       signals = blend_institutional_flow(signals, inst_scores, weight=0.10)
   ```
   This sets `sv.institutional_flow_score`. Passing None clients is safe — the function falls back to WRDS 13F data from the store.

9. **Cross-sectional normalization**:
   ```python
   from quant.cross_sectional import (
       normalize_signals_cross_sectionally,
       compute_normalized_composite,
       make_volatility_tier_fn,
   )
   signals = normalize_signals_cross_sectionally(
       signals, make_volatility_tier_fn(signals)
   )
   ```
   This requires >= 10 tickers to fire (skips if cross-section is too small).

10. **Compute composite per ticker**:
    ```python
    composites: dict[str, float] = {}
    for ticker, sv in signals.items():
        composites[ticker] = compute_normalized_composite(sv)
    ```

11. **Sort by composite descending**, then apply sector cap:
    ```python
    from quant.universe import get_sector
    ranked = sorted(composites.items(), key=lambda x: x[1], reverse=True)
    selected: list[str] = []
    sector_counts: dict[str, int] = {}
    for ticker, score in ranked:
        sector = get_sector(ticker)
        if sector_counts.get(sector, 0) >= max_per_sector:
            continue
        selected.append(ticker)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        if len(selected) >= top_n:
            break
    return selected
    ```

12. Return `selected` (empty list is a valid result, not an error).

### 5.2. Modified `run_rebalance`

**File**: `backend/paper_scheduler.py`

**New signature**:
```python
def run_rebalance(
    target_tickers: Optional[list[str]] = None,
    use_quant_screen: bool = True,
    top_n_quant: int = 30,
    as_of_date: Optional[date] = None,
) -> dict[str, Any]:
```

**Priority chain implementation**:
```python
def run_rebalance(
    target_tickers: Optional[list[str]] = None,
    use_quant_screen: bool = True,
    top_n_quant: int = 30,
    as_of_date: Optional[date] = None,
) -> dict[str, Any]:
    client = get_alpaca_client()
    current_positions = client.get_positions()
    current_symbols = {p["symbol"] for p in current_positions}

    # ── Priority chain ─────────────────────────────────────────────────
    # 1. Explicit override
    # 2. Quant composite screen (new default)
    # 3. Watchlist (legacy fallback)
    # 4. No-op
    if target_tickers is not None:
        # Priority 1: explicit override — skip screen entirely
        resolved_tickers = target_tickers
        logger.info("Rebalance: using %d explicit tickers (override)", len(resolved_tickers))
    elif use_quant_screen:
        # Priority 2: quant screen
        try:
            resolved_tickers = _quant_screen(
                as_of_date=as_of_date,
                top_n=top_n_quant,
            )
            logger.info(
                "Rebalance: quant screen returned %d tickers as of %s",
                len(resolved_tickers),
                as_of_date or date.today(),
            )
        except Exception as exc:
            logger.warning(
                "Rebalance: quant screen failed (%s) — falling back to watchlist",
                exc,
                exc_info=True,
            )
            resolved_tickers = _get_watchlist_tickers()
            logger.info("Rebalance: watchlist fallback returned %d tickers", len(resolved_tickers))
    else:
        # Priority 3: watchlist (use_quant_screen=False requested explicitly)
        resolved_tickers = _get_watchlist_tickers()
        logger.info("Rebalance: watchlist returned %d tickers", len(resolved_tickers))

    if not resolved_tickers:
        logger.info("Rebalance: no targets resolved — no-op")
        return {"status": "no_targets", "closed": [], "opened": [], "errors": []}

    target_set = {t.upper() for t in resolved_tickers}
    # ... rest of existing logic unchanged (close, LLM analysis, order submission, sync) ...
```

The `if not target_tickers:` check at line 36 of the current code must be REPLACED by the priority chain above. The remainder of the function body (lines 38-93) is unchanged.

---

## 6. Router Change

**File**: `backend/routers/paper_trading.py`

**Current** (line 415-424):
```python
@router.post("/rebalance")
async def trigger_rebalance(body: dict = None):
    """Trigger a manual rebalance. Optionally pass {"tickers": ["AAPL", "MSFT"]}."""
    try:
        tickers = (body or {}).get("tickers")
        result = run_rebalance(target_tickers=tickers)
        return result
    except Exception as exc:
        logger.error("Rebalance failed: %s", exc, exc_info=True)
        return {"status": "error", "error": str(exc)}
```

**New version**:
```python
@router.post("/rebalance")
async def trigger_rebalance(body: dict = None):
    """
    Trigger a manual rebalance.

    Body (all fields optional):
      {
        "tickers": ["AAPL", "MSFT"],  // explicit override — bypasses quant screen
        "use_quant_screen": true,     // default true; set false to use watchlist
        "top_n_quant": 30             // default 30; number of quant candidates
      }

    Backward compat: passing only {"tickers": [...]} continues to work
    (explicit tickers override the quant screen, same as before).
    """
    try:
        body = body or {}
        tickers = body.get("tickers")                              # None → use default path
        use_quant_screen = bool(body.get("use_quant_screen", True))
        top_n_quant = int(body.get("top_n_quant", 30))
        result = run_rebalance(
            target_tickers=tickers,
            use_quant_screen=use_quant_screen,
            top_n_quant=top_n_quant,
        )
        return result
    except Exception as exc:
        logger.error("Rebalance failed: %s", exc, exc_info=True)
        return {"status": "error", "error": str(exc)}
```

---

## 7. Test Plan

### Tests for `_quant_screen` — create `tests/test_quant_screen.py`

All tests in this file mock the heavy dependencies (WRDS store, price loading, signal computation) to avoid hitting live DB files. One integration smoke test uses live files.

**T1. `test_quant_screen_returns_n_tickers`**
- Mock: `_quant_screen`'s internal calls. Provide a synthetic `universe` of 50 tickers with synthetic price DataFrames. Mock `compute_signals_at_date` to return 50 SignalVectors with varied composite scores. Mock `WRDSPointInTimeStore` and all signal precomputes to be no-ops (return empty dicts).
- Assert: `len(result) <= 30` (or the requested `top_n`).
- Assert: result is a `list[str]`.

**T2. `test_quant_screen_respects_sector_cap`**
- Provide a universe of 60 tickers, all in one sector (e.g. "Technology").
- Assert: `len(result) <= max_per_sector` (default 5).

**T3. `test_quant_screen_deterministic`**
- Call `_quant_screen(as_of_date=date(2024, 1, 31), universe=fixed_20_tickers)` twice with the same mocked dependencies.
- Assert: both calls return identical lists.

**T4. `test_quant_screen_empty_universe_returns_empty_list`**
- Pass `universe=[]`.
- Assert: returns `[]` with no exception raised.

**T5. `test_quant_screen_no_lookahead`**
- Construct a universe_data dict where each ticker has price rows from 2010-2025, but one ticker has rows from 2010-2026. The as_of_date is `date(2024, 6, 30)`.
- Assert: the post-2024-06-30 rows are not used. (Verify by checking that the returned ranking does not change when you add future rows to a ticker's CSV — the composite should be identical.)
- Implementation hint: verify that the function correctly slices `df[df.index <= pd.Timestamp(as_of_date)]` and the result is stable.

**T6. `test_quant_screen_nan_propagation`**
- Provide a universe of 15 tickers. For 5 of them, mock `compute_signals_at_date` to return SignalVectors where `qmj_score = 0.0` and `earnings_rank_score = 0.0` (no WRDS data). The other 10 have full signal coverage.
- Assert: all 15 tickers are included in ranking (neutral scores for missing data do not disqualify a ticker from ranking).
- This validates the `project_silent_zeros` discipline: 0.0 as a neutral default (not NaN) for `SignalVector` float fields, consistent with the QMJ block comment at `quant/backtest.py` line 2252-2256.

### Tests for modified `run_rebalance` — add to `tests/test_paper_scheduler.py`

Follow existing patch pattern from `tests/test_paper_scheduler.py` lines 9-11.

**T7. `test_run_rebalance_uses_quant_screen_by_default`**
- Patch `backend.paper_scheduler._quant_screen` to return `["MSFT", "GOOGL"]`.
- Patch `get_alpaca_client`, `run_analysis_job`, `create_job` (same as existing test).
- Call `run_rebalance()` (no args).
- Assert: `_quant_screen` was called once with no explicit tickers.
- Assert: `run_analysis_job` was called for MSFT and GOOGL (or whichever passed conviction).

**T8. `test_run_rebalance_explicit_tickers_bypass_screen`**
- Patch `backend.paper_scheduler._quant_screen`.
- Call `run_rebalance(target_tickers=["AAPL"])`.
- Assert: `_quant_screen` was NOT called.
- Assert: the rebalance used `["AAPL"]`.

**T9. `test_run_rebalance_falls_back_to_watchlist_on_screen_error`**
- Patch `backend.paper_scheduler._quant_screen` to `raise RuntimeError("DB missing")`.
- Patch `backend.paper_scheduler._get_watchlist_tickers` to return `["JPM"]`.
- Call `run_rebalance()`.
- Assert: `_get_watchlist_tickers` was called.
- Assert: result contains no error about the quant screen (the fallback was transparent).

**T10. `test_run_rebalance_use_quant_screen_false_uses_watchlist`**
- Patch `backend.paper_scheduler._quant_screen`.
- Patch `backend.paper_scheduler._get_watchlist_tickers` to return `["XOM"]`.
- Call `run_rebalance(use_quant_screen=False)`.
- Assert: `_quant_screen` NOT called.
- Assert: `_get_watchlist_tickers` was called.

**T11. `test_run_rebalance_no_targets_returns_no_targets_status`**
- Patch `_quant_screen` to return `[]`.
- Patch `_get_watchlist_tickers` (should not be called — quant screen succeeded with empty result).
- Call `run_rebalance()`.
- Assert: result `== {"status": "no_targets", "closed": [], "opened": [], "errors": []}`.

If `_quant_screen` returns `[]`, the code falls to priority 4 (empty list = no-op). This is correct behavior since the screen "succeeded" but found nothing.

### Tests for router — create `tests/test_paper_trading_router_extended.py`

Use FastAPI `TestClient`. Follow any existing pattern in `tests/test_paper_trading_router.py` (if present, verify path) or create from scratch.

**T12. `test_paper_trading_endpoint_accepts_new_body_shape`**
- Mock `run_rebalance` at `backend.routers.paper_trading.run_rebalance`.
- POST `{"use_quant_screen": true, "top_n_quant": 20}`.
- Assert: `run_rebalance` called with `use_quant_screen=True, top_n_quant=20, target_tickers=None`.
- Assert: HTTP 200.

**T13. `test_paper_trading_endpoint_backward_compat`**
- Mock `run_rebalance`.
- POST `{"tickers": ["AAPL", "MSFT"]}`.
- Assert: `run_rebalance` called with `target_tickers=["AAPL", "MSFT"]`.
- Assert: HTTP 200.

---

## 8. Build Sequence

Follow this order. Each step is independently committable.

**Step 1: Write tests first (TDD)**
- Create `tests/test_quant_screen.py` with T1-T6 (all failing — `_quant_screen` not yet defined).
- Add T7-T11 to `tests/test_paper_scheduler.py` (all failing — `run_rebalance` signature unchanged).
- Create `tests/test_paper_trading_router_extended.py` with T12-T13 (failing).
- Run `python -m pytest tests/test_quant_screen.py tests/test_paper_scheduler.py tests/test_paper_trading_router_extended.py -v` — expect all new tests to fail (function not found or wrong behavior).

**Step 2: Implement `_quant_screen`**
- Add imports to `backend/paper_scheduler.py`: `import os`, `from datetime import date`, and any others needed.
- Implement `_quant_screen` following spec section 5.1 exactly.
- Run T1-T6. All should pass.

**Step 3: Modify `run_rebalance`**
- Replace the `if not target_tickers:` block (line 36-37) with the priority chain from spec section 5.2.
- Update the signature to add `use_quant_screen`, `top_n_quant`, `as_of_date`.
- Run T7-T11. All should pass.

**Step 4: Modify the router**
- Apply the router change from spec section 6.
- Run T12-T13. All should pass.

**Step 5: Full test suite**
- Run `python -m pytest` from the worktree root.
- Target: 336 existing tests pass + all 13 new tests pass = 349 total.

**Step 6: Smoke test** (see section 9 below)

---

## 9. Pre-registered Success Criteria

### Criterion 1: Determinism
Run the following Python snippet twice and assert identical output:
```python
from datetime import date
from backend.paper_scheduler import _quant_screen
result_a = _quant_screen(as_of_date=date(2024, 1, 31))
result_b = _quant_screen(as_of_date=date(2024, 1, 31))
assert result_a == result_b, f"Non-deterministic: {result_a} != {result_b}"
print("PASS: deterministic")
```
This verifies T3. Run from the worktree root: `cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst/.worktrees/two-stage-pipeline && python -c "from datetime import date; from backend.paper_scheduler import _quant_screen; a=_quant_screen(as_of_date=date(2024,1,31)); b=_quant_screen(as_of_date=date(2024,1,31)); assert a==b; print('PASS deterministic, top-5:', a[:5])"`

### Criterion 2: Cross-validation Against Audit Results
The audit walk-forward JSON is at `docs/audit/session-3/v4-qmj-pos10-sec5-results.json`. This file contains per-window results. Read the trades for the rebalance period closest to `2024-01-31` and extract the long positions entered. The `_quant_screen(as_of_date=date(2024, 1, 31))` top-10 should overlap with that window's longs by >= 3 names (not all 10, since the audit used a 200-ticker universe and may use a slightly different date).

Verification command:
```python
import json
from datetime import date
from backend.paper_scheduler import _quant_screen

with open("docs/audit/session-3/v4-qmj-pos10-sec5-results.json") as f:
    audit = json.load(f)

# Find trades near 2024-01-01
audit_longs = set()
for trade in audit.get("trade_log", []):
    if trade.get("direction") == "LONG" and "2024-01" in str(trade.get("entry_date", "")):
        audit_longs.add(trade["ticker"])

screen_top10 = set(_quant_screen(as_of_date=date(2024, 1, 31))[:10])
overlap = screen_top10 & audit_longs
print(f"Screen top-10: {sorted(screen_top10)}")
print(f"Audit Jan-2024 longs: {sorted(audit_longs)}")
print(f"Overlap: {sorted(overlap)} ({len(overlap)} names)")
assert len(overlap) >= 3, f"Cross-validation failed: only {len(overlap)} overlap"
print("PASS: cross-validation")
```

If the audit JSON does not contain a January 2024 window, the implementer must inspect the JSON's available date range and pick the closest available rebalance date. Document the chosen date in the test.

### Criterion 3: Sector Cap
```python
from datetime import date
from quant.universe import get_sector
from backend.paper_scheduler import _quant_screen
from collections import Counter
result = _quant_screen(as_of_date=date(2024, 1, 31), top_n=30, max_per_sector=5)
counts = Counter(get_sector(t) for t in result)
violations = {s: c for s, c in counts.items() if c > 5}
assert not violations, f"Sector cap violated: {violations}"
print(f"PASS: sector cap. Sectors: {dict(counts)}")
```

### Criterion 4: Backward Compat
```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst/.worktrees/two-stage-pipeline
python -m pytest tests/test_paper_scheduler.py::test_rebalance_job_runs_analysis_and_submits_orders -v
```
The original test (line 12-40 of `tests/test_paper_scheduler.py`) calls `run_rebalance(target_tickers=["MSFT"])` and must pass unchanged.

### Criterion 5: Full Test Suite
```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst/.worktrees/two-stage-pipeline
python -m pytest --tb=short -q 2>&1 | tail -20
```
Expect: no regressions, all new tests pass.

### Criterion 6: Smoke Test
```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst/.worktrees/two-stage-pipeline
python -c "
from datetime import date
import logging
logging.basicConfig(level=logging.INFO)
from backend.paper_scheduler import _quant_screen
result = _quant_screen(as_of_date=date.today(), top_n=30)
print(f'Top-30 as of today: {result}')
print(f'Count: {len(result)}')
"
```
Expected: Prints a list of 20-30 real ticker symbols. Should complete in < 5 minutes (dominated by earnings/QMJ computation over ~200 tickers). If it hangs > 5 min, check WRDS store connectivity.

---

## 10. Out of Scope

These items must NOT be implemented in this branch:

1. New universe sources (Sharadar SF1, NYSE+NASDAQ expansion)
2. New signals or signal recalibration
3. AI agent prompt or orchestrator changes
4. Order sizing, Alpaca client, or stop-loss logic changes
5. Scheduler cron cadence (already monthly, leave as-is)
6. The growth-system / FMP-screener pipeline
7. Modal walk-forward integration or CPCV anything
8. Frontend / dashboard changes
9. Score blending (alpha * quant + beta * LLM) — Stage 2 remains a simple conviction threshold, not a blended score
10. XGBoost meta-model integration
11. VIX regime filtering in the screen (no regime gating in `_quant_screen` — keep the screen pure composite ranking)

---

## 11. Risks and Open Questions

**R1: QMJ computation time at live scale**
`compute_qmj_score` is called per-ticker per-screen. At 200 tickers it may take 3-10 minutes. If this blocks the monthly rebalance cron intolerably, the implementer should move `_quant_screen` to a `ThreadPoolExecutor` for the per-ticker loops (steps 6, 7, 8 in section 5.1). The existing `load_universe_data` in backtest.py uses 10 parallel workers as a reference pattern (lines 338-354). Flag if latency > 5 min on smoke test.

**R2: `blend_institutional_flow` with None clients**
`compute_institutional_flow_scores` in `quant/institutional_flow.py` falls back to WRDS 13F data when `fmp_client=None`. Verify the WRDS store actually contains 13F data (`SELECT count(*) FROM inst_holdings` or equivalent). If the table is absent or empty, `inst_scores` will be empty and `institutional_flow_score` will stay 0.0 for all tickers — this degrades the composite to 3 signals but is not a fatal error. The implementer should log a warning if `len(inst_scores) == 0`.

**R3: `_wrds_provider._store` vs direct `store` for QMJ**
The QMJ block in `run_backtest` accesses `_wrds_provider._store` (line 2239). The `_quant_screen` function instantiates `store = WRDSPointInTimeStore()` directly and can pass it straight to `compute_qmj_score`. This is cleaner — no need to go through the provider's `_store` attribute. Verify `compute_qmj_score` signature matches `(ticker: str, as_of_date: date, store: WRDSPointInTimeStore) -> Optional[float]`.

**R4: `settings.warehouse_db_path` location**
The `_get_watchlist_tickers` function reads from `settings.warehouse_db_path` (default `".warehouse.db"`). This is a relative path — it resolves relative to the working directory at runtime, which is the repo root for both the FastAPI server and tests. The watchlist table may not exist if the warehouse is disabled. Verify `_get_watchlist_tickers` handles `OperationalError` gracefully (it does — line 28 of current code returns `[]` on any exception).

**R5: Cross-validation threshold**
Criterion 2 requires >= 3/10 overlap with audit longs. If the audit JSON at `docs/audit/session-3/v4-qmj-pos10-sec5-results.json` does not contain a January 2024 window (the walk-forward may use different start/end dates), adjust the target month to the first available window month in the audit results. The implementer must inspect the JSON and choose an available date before asserting.

**R6: `normalize_signals_cross_sectionally` grouping fn**
The production backtest uses `make_volatility_tier_fn(signals)` (line 2356), which groups by ATR volatility tier rather than GICS sector. This is important: using a GICS sector function here would change rankings relative to the audit. The spec correctly specifies `make_volatility_tier_fn` — do not substitute `get_sector` as the grouping function for normalization. The `get_sector` function is used ONLY for the sector cap step (step 11), not for normalization grouping.

**R7: `earnings_rank_score` — NaN discipline**
`blend_earnings_signals` sets `sv.earnings_rank_score = score` only for tickers that appear in `earn_scores` (tickers where at least one earnings sub-signal succeeded). Tickers with no WRDS IBES coverage retain `sv.earnings_rank_score = 0.0` (default from `SignalVector` line 38). In cross-sectional normalization, 0.0 is treated as a valid score (it is z-scored relative to the universe). This is the `project_silent_zeros` acceptable default for `SignalVector` plain float fields — 0.0 means "no earnings revision signal" which is a neutral, not missing.

**R8: Import order**
`backend/paper_scheduler.py` currently does not import `quant` modules. Adding `from quant.backtest import compute_signals_at_date` at module level will trigger all of `quant/backtest.py`'s module-level imports (pandas, numpy, etc.). These are all available in the venv (symlinked). However, if any import fails at startup, the FastAPI server will fail to start. Wrap the quant imports inside `_quant_screen` function body to lazy-load and isolate failures to screen time rather than startup time.

---

**End of Blueprint**
