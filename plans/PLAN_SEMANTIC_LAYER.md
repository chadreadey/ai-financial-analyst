# Semantic Data Layer Cleanup

**Created:** 2026-04-07
**Status:** Ready for implementation
**Prerequisite for:** PLAN_ALPHA_EXPANSION Phase 0 (validation infrastructure must be trustworthy first)
**Origin:** Data layer audit revealing 5 divergent Sharpe formulas, 8 duplicated threshold blocks, no API schema validation, and stale cache reads

---

## Strategic Context

The quant pipeline has accumulated technical debt from rapid iteration:
- **Metric divergence:** 5 separate Sharpe implementations, 2 of which produce mathematically wrong results
- **Magic number scatter:** BUY/SELL/HOLD thresholds (0.30 / -0.30 / 0.40) copy-pasted across 8 locations
- **Silent data corruption:** API field renames produce zeros with no warning
- **Stale cache reads:** FMP fundamental cache never checks age on read
- **Parallel universe:** `backend/backtest_engine.py` computes metrics independently with incompatible formulas

**Principle:** Define every metric once. Validate data at boundaries. Make inconsistency structurally impossible.

---

## Dependency Graph

```
Phase 1A (metrics.py)  ──┐
                          ├── Phase 2 (backend convergence)
Phase 1B (scoring.py)  ──┤
                          ├── Phase 3 (schema validation)
Phase 1C (cache TTL)   ──┘
```

Phases 1A, 1B, 1C are independent — can be done in any order or in parallel.
Phase 2 requires 1A.
Phase 3 is independent of everything.

---

## Phase 1A: Canonical Metrics Module

**Goal:** Single source of truth for Sharpe, Sortino, max drawdown, Calmar, annual return, alpha.

### Create: `quant/metrics.py`

Pure functions, no I/O, no imports from other `quant/` modules.

```python
# Interface sketch — not implementation code
def compute_sharpe(daily_returns: pd.Series, annual_factor: float = 252.0) -> Optional[float]
def compute_sortino(daily_returns: pd.Series, annual_factor: float = 252.0) -> Optional[float]
def compute_max_drawdown(equity_curve: pd.Series) -> float  # returns percentage 0-100
def compute_calmar(annual_return_pct: float, max_drawdown_pct: float) -> Optional[float]
def compute_annual_return(equity_curve: pd.Series, initial_capital: float) -> float  # returns percentage
def compute_alpha(total_return_pct: float, benchmark_return_pct: float) -> float
```

- Move `compute_sharpe_from_returns` from `quant/cpcv.py:304` here as the canonical Sharpe. Keep a thin re-export in `cpcv.py` for backwards compat during transition.
- Sortino: use `daily_returns[daily_returns < 0].std()` (matches `quant/backtest.py` convention, not the `statistics.stdev` + single-element fallback in `backend/backtest_engine.py`).
- Max drawdown: `(cumulative - cumulative.cummax()) / cumulative.cummax()` → `abs(min) * 100`. This matches the 3 correct implementations.

### Modify: `quant/backtest.py`

**Lines 1881–1902** (main backtest metrics block): Replace inline Sharpe/Sortino/drawdown/Calmar with calls to `metrics.compute_sharpe()`, `metrics.compute_sortino()`, `metrics.compute_max_drawdown()`, `metrics.compute_calmar()`.

**Lines 2297–2314** (walk-forward aggregate metrics): Same replacement. This block is a direct copy of lines 1881–1902.

### Modify: `scripts/run_ml_backtest.py`

**Lines 326–353** (ML backtest metrics — inlined copy from commit `5e1c630`): Replace with imports from `quant/metrics.py`.

### Modify: `agents/pattern.py`

**Lines 26–30** (`_format_risk_lines`): Replace inline Sharpe/Sortino/drawdown/Calmar with `metrics.*` calls. The algebraically-equivalent-but-differently-written formula `(mean_ret * ann_factor) / (std_ret * sqrt(ann_factor))` becomes a simple `metrics.compute_sharpe(returns)`.

### Modify: `quant/cpcv.py`

**Line 304** (`compute_sharpe_from_returns`): Replace body with `return metrics.compute_sharpe(daily_returns, annual_factor)` or re-export. Keep the function signature for any direct callers.

### Modify: `backend/routers/paper_trading.py`

**Lines 232–241**: Replace `mean_r / std_r * sqrt(len(returns))` (dimensionally wrong — grows with trade count) with `metrics.compute_sharpe()`. This requires converting trade-level returns to a daily return series, or documenting that paper trading Sharpe is per-trade (not annualized). Decision: convert to daily returns for comparability with backtest Sharpe.

### Verification

```bash
# Run the gold-standard backtest and confirm Sharpe matches baseline (1.04)
python scripts/run_backtest.py --start 2020-01-01 --end 2026-01-01 --cpcv

# Run ML backtest and confirm metrics match
python scripts/run_ml_backtest.py --start 2020-01-01 --end 2024-01-01

# Unit tests for metrics.py
python -m pytest tests/test_metrics.py -v
```

**Gate:** Sharpe from main backtest must match pre-refactor value (±0.01 tolerance from float ordering differences).

### Integration Risks

- `backend/backtest_engine.py` uses trade-level returns (not daily), so `compute_sharpe()` needs trade-level returns → daily conversion, OR the engine must be changed to track daily equity. Defer this to Phase 2.
- `agents/pattern.py` computes metrics from a returns Series that may not be daily-frequency. Ensure `ann_factor` parameter is passed correctly.

---

## Phase 1B: Scoring Constants & Direction Classification

**Goal:** Eliminate 8 duplicated threshold blocks. Make threshold changes a one-line edit.

### Create: `quant/scoring.py`

```python
# Interface sketch
BUY_THRESHOLD = 0.30
SELL_THRESHOLD = -0.30
ACTIONABLE_THRESHOLD = 0.40

def classify_direction(composite_score: float) -> tuple[str, bool]:
    """Returns (direction, actionable). Pure function."""

def reclassify(sv: "SignalVector") -> None:
    """Update sv.composite_direction and sv.actionable from sv.composite_score. Mutates in place."""
```

Design notes:
- Named constants (not config object) because these are domain invariants, not per-run parameters.
- `BacktestConfig.long_threshold` / `short_threshold` remain separate — those are portfolio construction cutoffs, not signal classification.
- String literals for direction ("BUY"/"SELL"/"HOLD") rather than enum — matches existing convention everywhere.

### Modify: `quant/signals.py`

**Lines 66–73** (`SignalVector.compute_composite`): Replace the `if/elif/else` block with `scoring.reclassify(self)`. This is the canonical definition site — it must call `reclassify` to stay consistent.

### Modify: `quant/backtest.py` (5 locations)

Each location has the identical 5-line pattern. Replace each with `scoring.reclassify(sv)`:

| Lines | Function | Context |
|-------|----------|---------|
| 403–409 | `compute_signals_at_date` | After custom weight composite |
| 759–765 | `apply_fomc_boost` | After FOMC boost adjustment |
| 876–882 | `blend_sentiment_into_signals` | After sentiment blend |
| 945–951 | `blend_timesfm_into_signals` | After TimesFM blend |
| 1117–1123 | `blend_lstm_into_signals` | After LSTM blend |

### Modify: `quant/fundamentals.py`

**Lines 284–290** (`blend_fundamentals_into_signals`): Replace with `scoring.reclassify(sv)`.

### Modify: `quant/earnings_signals.py`

**Lines 339–345** (`blend_earnings_signals`): Replace with `scoring.reclassify(sv)`.

### Verification

```bash
# Same gold-standard backtest — output must be byte-identical
python scripts/run_backtest.py --start 2020-01-01 --end 2026-01-01 --cpcv

# Grep confirms no remaining hardcoded thresholds
grep -rn "composite_score >= 0.30\|composite_score <= -0.30\|>= 0.40" quant/ agents/ backend/ scripts/
# Expected: zero matches
```

**Gate:** Zero remaining hardcoded threshold instances in `quant/`, `agents/`, `backend/`, `scripts/`.

### Integration Risks

- Low. Every callsite is a mechanical replacement of 5 identical lines with 1 function call.
- The `sma_gate_bearish` flag logic in `SignalVector.compute_composite()` (line 76) is AFTER the threshold block — ensure `reclassify()` is called before the gate check, preserving execution order.

---

## Phase 1C: FMP Cache TTL Enforcement

**Goal:** Prevent stale fundamental data from being served silently.

### Modify: `quant/fmp_cache.py`

**`_get()` method (line 58):** Add `max_age_seconds` parameter (default: `604800` = 7 days). Check `updated_at` column against current time. Return `None` if stale, triggering a re-fetch by the caller.

```python
# Pseudocode for the change
def _get(self, ticker: str, data_type: str, max_age_seconds: float = 604800) -> Optional[list]:
    row = ...  # existing query
    if row and max_age_seconds > 0:
        age = time.time() - row["updated_at"]
        if age > max_age_seconds:
            logger.info("FMP cache stale for %s/%s (age=%.0fs)", ticker, data_type, age)
            return None
    return json.loads(row["data_json"])
```

- The `updated_at` column already exists (written at line 77). This change only adds a read-side check.
- For backtesting (historical analysis), callers should pass `max_age_seconds=0` to disable TTL (historical data doesn't expire).
- For live analysis / agent pipelines, the 7-day default applies.

### Modify: `quant/fundamentals.py`

**`_CacheBackedFMP` class (line 210+):** Pass `max_age_seconds=0` when called from backtest context (where `as_of_date` is set), preserving current behavior. For live analysis (no `as_of_date`), use the default TTL.

### Verification

```bash
# Manually set a cache entry's updated_at to 8 days ago, confirm _get returns None
python -c "
from quant.fmp_cache import FMPFundamentalCache
c = FMPFundamentalCache()
# insert test data with old timestamp, then read it back
"
```

**Gate:** Stale entries return `None`; backtest path still reads all cached data (TTL disabled).

### Integration Risks

- Any code that calls `_get()` and doesn't handle `None` could break. Audit all callers of public methods (`get_income_quarterly`, `get_balance_quarterly`, `get_analyst_estimates`, `get_key_metrics`). Currently all callers already handle `None` returns — the prefetch path will re-fetch on the next run.

---

## Phase 2: Backend Engine Convergence

**Requires:** Phase 1A complete.

**Goal:** Eliminate the parallel metric universe in `backend/backtest_engine.py`.

### Modify: `backend/backtest_engine.py`

**Lines 258–271** (metric computation block): Replace with imports from `quant/metrics.py`.

The current code computes metrics from **trade-level returns** (not daily equity curve), using `statistics.mean/stdev`. Two options:

**Option A (recommended):** Convert trade-level returns to a daily equity curve inside `BacktestEngine.run()`, then call `metrics.compute_sharpe(daily_returns)`. This makes all Sharpe values comparable across engines.

**Option B:** Keep trade-level returns but call `metrics.compute_sharpe(trade_returns, annual_factor=252/TIME_DECAY_DAYS)`. This preserves the semantic intent but produces Sharpe values that are not directly comparable to the main backtest.

Recommend Option A. The `BacktestEngine` already builds an equity curve (line 248: `curve.append({"date": ..., "equity": ...})`). Convert that to a pd.Series and feed it to `metrics.*`.

### Also fix: Hardcoded Tiingo

**Line 88:** `BacktestEngine.__init__` creates a `TiingoClient` directly, ignoring `PRICE_PROVIDER`. Change to use `get_price_provider()` from `price_provider.py`.

### Verification

```bash
# Run backend tests
python -m pytest tests/test_backend.py -v

# Compare a recommendation-replay backtest result before and after
# (Sharpe WILL change because the formula was wrong — document the delta)
```

**Gate:** Backend Sharpe now matches main backtest Sharpe for equivalent strategies. Document the expected change in metric values.

### Integration Risks

- The backend API response schema for `BacktestResult` won't change (same field names). But numeric values will shift because the formula changes. If any frontend code has hardcoded expectations about Sharpe ranges, it could surface as a UX issue. Check frontend components that display Sharpe.
- `TIME_DECAY_DAYS = 90` is also used for annual return computation (line 269). Ensure this is handled correctly when switching to equity-curve-based metrics.

---

## Phase 3: API Response Schema Validation

**Goal:** Catch data source field renames before they silently produce zeros.

**Independent of Phases 1–2.**

### Design Decision: Warn-and-Default, Not Raise

API responses with missing fields should **log a warning and return a default** (not raise exceptions). This preserves the current fault-tolerant behavior while making data quality issues visible.

### Modify: `tiingo_client.py`

Add a `_validate_eod_bar(bar: dict) -> dict` helper that checks for required keys (`adjClose`, `adjHigh`, `adjLow`, `adjOpen`, `adjVolume`, `date`). Log warning if any are missing. Called in `get_eod_history()` before returning.

### Modify: `price_provider.py`

Add same validation in `AlpacaClient.get_eod_history()` for the Alpaca response schema (`open`, `high`, `low`, `close`, `volume`, `timestamp`).

### Modify: `fmp_client.py`

Add `_validate_income_statement(stmt: dict)` and `_validate_balance_sheet(stmt: dict)` that check for the ~10 keys that `quant/fundamentals.py` actually uses (`totalAssets`, `totalStockholdersEquity`, `netIncome`, `revenue`, etc.). Called in the FMP response path before caching.

### Modify: `quant/fmp_cache.py`

**`prefetch_from_tiingo()` (line 153):** Add validation after the Tiingo→FMP field mapping. The mapping at lines 185-210 translates `dataCode` values — if a Tiingo code changes, the mapped FMP field will be missing. Log a warning when a required FMP field is absent after translation.

### Modify: `finnhub_client.py`

Add `_validate_news_item(item: dict)` checking for `headline`, `datetime`, `source`. Called in the news fetching path.

### Create: `tests/test_schema_validation.py`

Unit tests that feed known-good and known-bad API response shapes into each validator. Confirm warnings are logged for missing keys and defaults are applied.

### Verification

```bash
python -m pytest tests/test_schema_validation.py -v

# Run full analysis for one ticker and check logs for validation warnings
python scripts/run_backtest.py --tickers AAPL --start 2024-01-01 --end 2024-06-01 2>&1 | grep "WARN.*schema\|WARN.*missing"
```

**Gate:** No false positives on current API responses. Warnings appear when a required key is removed from a mock response.

### Integration Risks

- If a provider API is currently returning data with missing keys that the code tolerates via `.get(key, 0)`, the new warnings will surface during normal runs. This is the desired behavior — it makes invisible data quality issues visible.
- Warn-and-default means no behavioral change for existing callers. Upgrading to raise-on-missing can be done later once all callers are audited.

---

## Implementation Priority (Effort vs. Impact)

| Priority | Phase | Effort | Impact | Rationale |
|----------|-------|--------|--------|-----------|
| 1 | 1B: scoring.py | 1 hour | High | Mechanical replacement, eliminates 8 duplication sites, zero regression risk |
| 2 | 1A: metrics.py | 2-3 hours | Critical | Fixes 2 mathematically wrong Sharpe implementations, single source of truth |
| 3 | 1C: cache TTL | 30 min | Medium | Simple change, prevents stale data in live analysis |
| 4 | 2: backend convergence | 2 hours | Medium | Depends on 1A, fixes wrong backend Sharpe, reduces code surface |
| 5 | 3: schema validation | 3-4 hours | Medium | Most effort, preventive rather than corrective, no urgency |

**Recommended session plan:** Do 1B → 1A → 1C in one session (3-4 hours), then 2 → 3 in a follow-up.

---

## Files Created

| File | Purpose |
|------|---------|
| `quant/metrics.py` | Canonical metric computations (Sharpe, Sortino, drawdown, Calmar, annual return, alpha) |
| `quant/scoring.py` | Threshold constants + `classify_direction()` + `reclassify()` |
| `tests/test_metrics.py` | Unit tests for metrics with known-value assertions |
| `tests/test_schema_validation.py` | Schema validation tests for API responses |

## Files Modified

| File | Change |
|------|--------|
| `quant/signals.py:66-73` | Replace threshold block with `scoring.reclassify(self)` |
| `quant/backtest.py:403,759,876,945,1117` | Replace 5 threshold blocks with `scoring.reclassify(sv)` |
| `quant/backtest.py:1881-1902,2297-2314` | Replace inline metrics with `metrics.*` calls |
| `quant/fundamentals.py:284-290` | Replace threshold block with `scoring.reclassify(sv)` |
| `quant/earnings_signals.py:339-345` | Replace threshold block with `scoring.reclassify(sv)` |
| `quant/cpcv.py:304-315` | Delegate to `metrics.compute_sharpe()` |
| `quant/fmp_cache.py:58-70` | Add TTL check in `_get()` |
| `quant/fundamentals.py:210+` | Pass `max_age_seconds=0` in backtest context |
| `scripts/run_ml_backtest.py:326-353` | Replace inline metrics with `metrics.*` calls |
| `agents/pattern.py:26-42` | Replace inline metrics with `metrics.*` calls |
| `backend/backtest_engine.py:258-271` | Replace wrong Sharpe formula with `metrics.*` calls |
| `backend/backtest_engine.py:88` | Use `get_price_provider()` instead of hardcoded `TiingoClient` |
| `backend/routers/paper_trading.py:232-241` | Replace `sqrt(n_trades)` Sharpe with `metrics.compute_sharpe()` |
| `tiingo_client.py` | Add EOD bar schema validation |
| `price_provider.py` | Add Alpaca response schema validation |
| `fmp_client.py` | Add income/balance schema validation |
| `quant/fmp_cache.py:153+` | Add post-translation schema validation in Tiingo→FMP path |
| `finnhub_client.py` | Add news item schema validation |

## New Dependencies

None. All implementations use `pandas`, `numpy`, `math` (already in the project).

## Out of Scope (Flagged for Future)

- Module-level globals in `quant/backtest.py` (`_VIX_CACHE`, `_timesfm_model`, etc.) — works for single-process, but would need DI container for concurrency
- `BacktestConfig` god object (40+ fields) — decompose into sub-configs when adding new signal categories
- Price cache CSV staleness — no TTL on `.price_cache/*.csv` files; needs end-date freshness check
- Cross-provider price consistency (Alpaca vs Tiingo adjusted prices diverge on corporate actions)
