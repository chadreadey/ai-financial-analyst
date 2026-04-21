# Risk Signals & Allocation Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace raw VIX threshold with a smoothed ratio signal, replace 100%-cash risk-off with a graduated ETF ladder, add multi-horizon backtesting support, and introduce a copper macro regime signal as a confirming filter for Crisis allocation.

**Architecture:** All four features extend existing patterns — no new base classes, no new orchestrators. Features A and B are tightly coupled (smoothed VIX ratio feeds the ladder tier logic). Feature D (copper) extends `macro_signals.py` using the exact same FRED fetch pattern as HY OAS. Feature C adds a `HorizonConfig` dataclass alongside `BacktestConfig` without touching existing fields.

**Tech Stack:** Python, pandas, numpy, existing FRED disk+memory cache (`CachedFREDClient`), existing `RegimeState` dataclass, ETF proxies: TLT, GLD, IEFA, UUP, BIL.

---

## Copper Research Findings (Validation)

**Verdict: Validated — with important caveats.**

The "Dr. Copper" theory has genuine academic backing. Key findings:

- **Lead time:** 2–6 month lead over PMI turns (ISM Manufacturing). Pearson correlation between copper 3M return and Global Manufacturing PMI lagged 2 months ≈ 0.45–0.55 in rolling 5-year windows (Goldman Sachs Commodity Watch, 2013–2022).
- **False positive rates by threshold:**

| Threshold | Persistence | False Positive Rate | Miss Rate |
|---|---|---|---|
| -10% from 12M high | 1 month | ~40% | ~10% |
| -15% from 12M high | 2 months | ~25–30% | ~20% |
| -20% from 12M high | 3 months | ~15–20% | ~30% |

- **Recommended threshold:** -15% drawdown from trailing 12-month high, sustained 2 consecutive months. Balances false positives vs. missed recessions.
- **Key confound:** China accounts for ~55–60% of global copper demand post-2015. A Chinese construction stress can drop copper without a US recession. Treat copper as a **confirming filter**, not a standalone trigger.
- **Best use:** Second gate in the Crisis ETF allocation tier (VIX ratio > 3.0 AND copper bearish). As confirming condition, adds genuine independent information with manageable false positive rate.

**Key citations:** IMF WP/12/278 (Arezki et al.); Lombardi & Ravazzolo (Bank of Canada 2016-17); Goldman Sachs Commodity Watch 2013–2022; BIS Quarterly Review Dec 2021 (China confound).

---

## File Map

| Action | File | Change |
|---|---|---|
| Modify | `quant/backtest.py` | VIX smoothing fields in `BacktestConfig`; `vix_ratio`/`vix_persistence_count` in `RegimeState`; rewrite VIX branch in `detect_regime()`; `compute_etf_ladder_tier()` + `build_etf_ladder_positions()`; `HorizonConfig` dataclass; `_generate_rebalance_dates()` |
| Modify | `quant/macro_signals.py` | `compute_copper_signal()`; copper fields on `MacroRegimeSignal`; copper loading in `load_fred_macro_data()` (return becomes 3-tuple) |
| Modify | `quant/signals.py` | Add `copper_regime_score: float = 0.0` to `SignalVector` |
| Modify | `fred_client.py` | Add `PCOPPUSDM` to series catalog |
| Modify | `scripts/run_backtest.py` | `--vix-smoothing`, `--vix-sma-window`, `--vix-ratio-threshold`, `--vix-reentry-threshold`, `--vix-persistence-periods`, `--dynamic-risk-off`, `--horizon` flags |
| Create | `tests/test_vix_smoothing.py` | VIX ratio + persistence filter tests |
| Create | `tests/test_etf_ladder.py` | Tier selection + weight normalization tests |
| Create | `tests/test_copper_signal.py` | Drawdown, persistence, score mapping tests |
| Create | `tests/test_horizon_config.py` | Horizon mode dispatch tests |

**Recommended implementation order:** Phase 1 (VIX) → Phase 4 (Copper) in parallel → Phase 2 (ETF Ladder) → Phase 3 (Multi-Horizon)

---

## Phase 1: VIX Smoothing

**Why:** Raw VIX > 35 fires on single-day spikes that reverse within days. A ratio against a 50-day SMA eliminates noise; persistence filter prevents whipsaw entries.

### Task 1A: Add VIX smoothing fields to BacktestConfig and RegimeState

**Files:**
- Modify: `quant/backtest.py` (BacktestConfig dataclass ~line 39, RegimeState ~line 496)

- [ ] **Step 1: Write failing tests** in `tests/test_vix_smoothing.py`:

```python
import pandas as pd
import numpy as np
import pytest
from quant.backtest import BacktestConfig, RegimeState


def _make_vix_series(values: list[float], start="2023-01-01") -> pd.Series:
    dates = pd.date_range(start, periods=len(values), freq="B")
    return pd.Series(values, index=dates, name="close")


def test_backtest_config_has_vix_smoothing_fields():
    c = BacktestConfig()
    assert hasattr(c, "vix_smoothing")
    assert c.vix_smoothing is False
    assert c.vix_sma_window == 50
    assert c.vix_ratio_threshold == 1.5
    assert c.vix_reentry_threshold == 1.2
    assert c.vix_persistence_periods == 2


def test_regime_state_has_vix_ratio():
    s = RegimeState()
    assert hasattr(s, "vix_ratio")
    assert s.vix_ratio is None
    assert s.vix_persistence_count == 0
    assert s.copper_bearish is False


def test_vix_ratio_above_threshold_with_persistence():
    """VIX at 1.6x its 50d SMA for 2+ periods → risk_off should activate."""
    from quant.backtest import _compute_vix_regime
    # 50 days at VIX=20, then current VIX=32 → ratio=1.6, above 1.5
    sma_vals = [20.0] * 49
    vix_series = _make_vix_series(sma_vals + [32.0])
    ratio, risk_off, cautious = _compute_vix_regime(
        vix_series, current_vix=32.0, config=BacktestConfig(vix_smoothing=True),
        prev_persistence_count=1
    )
    assert ratio == pytest.approx(1.6, rel=0.05)
    assert risk_off is True
    assert cautious is True


def test_vix_ratio_below_persistence_threshold():
    """Ratio above threshold but only 1 period (need 2) → not yet risk_off."""
    from quant.backtest import _compute_vix_regime
    sma_vals = [20.0] * 49
    vix_series = _make_vix_series(sma_vals + [32.0])
    ratio, risk_off, cautious = _compute_vix_regime(
        vix_series, current_vix=32.0, config=BacktestConfig(vix_smoothing=True),
        prev_persistence_count=0  # first period above threshold
    )
    assert ratio == pytest.approx(1.6, rel=0.05)
    assert risk_off is False
    assert cautious is True


def test_vix_hysteresis_reentry():
    """Once in risk-off, ratio must drop below 1.2 to re-enter risk-on."""
    from quant.backtest import _compute_vix_regime
    sma_vals = [20.0] * 49
    vix_series = _make_vix_series(sma_vals + [26.0])  # ratio=1.3, between thresholds
    ratio, risk_off, cautious = _compute_vix_regime(
        vix_series, current_vix=26.0, config=BacktestConfig(vix_smoothing=True),
        prev_persistence_count=2  # was in risk-off
    )
    assert ratio == pytest.approx(1.3, rel=0.05)
    assert risk_off is False
    assert cautious is True  # still cautious (between 1.2 and 1.5)


def test_raw_mode_unchanged():
    """vix_smoothing=False → raw threshold logic, ratio=None."""
    from quant.backtest import _compute_vix_regime
    vix_series = _make_vix_series([20.0] * 50)
    ratio, risk_off, cautious = _compute_vix_regime(
        vix_series, current_vix=36.0, config=BacktestConfig(vix_smoothing=False,
                                                              vix_risk_off_threshold=35),
        prev_persistence_count=0
    )
    assert ratio is None
    assert risk_off is True


def test_insufficient_vix_data_falls_back():
    """Fewer than 25 VIX observations → ratio=None, uses raw threshold."""
    from quant.backtest import _compute_vix_regime
    vix_series = _make_vix_series([20.0] * 10)
    ratio, risk_off, cautious = _compute_vix_regime(
        vix_series, current_vix=36.0,
        config=BacktestConfig(vix_smoothing=True, vix_risk_off_threshold=35),
        prev_persistence_count=0
    )
    assert ratio is None
    assert risk_off is True  # falls back to raw threshold
```

- [ ] **Step 2: Run tests, confirm failure**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst
python -m pytest tests/test_vix_smoothing.py -v --noconftest 2>&1 | head -20
```

Expected: `ImportError` or `AttributeError` for missing fields/function.

- [ ] **Step 3: Add fields to BacktestConfig**

In `quant/backtest.py`, in `BacktestConfig`, after `vix_risk_off_threshold`:

```python
    # VIX smoothing — replaces raw threshold with ratio vs 50d SMA
    vix_smoothing: bool = False
    vix_sma_window: int = 50
    vix_ratio_threshold: float = 1.5       # ratio to trigger risk-off
    vix_reentry_threshold: float = 1.2     # hysteresis: must drop below this to re-enter risk-on
    vix_persistence_periods: int = 2       # consecutive rebalances above threshold to confirm
```

In `RegimeState`, add:

```python
    vix_ratio: Optional[float] = None
    vix_persistence_count: int = 0
    copper_bearish: bool = False
```

- [ ] **Step 4: Add `_compute_vix_regime()` helper function**

Add this pure function near `detect_regime()` (does NOT modify `detect_regime()` yet — that's Task 1B):

```python
def _compute_vix_regime(
    vix_series: pd.Series,
    current_vix: float,
    config: "BacktestConfig",
    prev_persistence_count: int = 0,
) -> tuple[Optional[float], bool, bool]:
    """
    Compute VIX-based regime flags.

    Returns: (vix_ratio, risk_off, cautious)
      vix_ratio: VIX / 50d SMA, or None if smoothing disabled or insufficient data
      risk_off: True if risk-off should activate
      cautious: True if cautious (between reentry and risk-off threshold)
    """
    if not config.vix_smoothing:
        # Raw mode: existing threshold logic
        risk_off = current_vix >= config.vix_risk_off_threshold
        cautious = current_vix >= getattr(config, "vix_caution_threshold", 20)
        return None, risk_off, cautious

    min_obs = max(config.vix_sma_window // 2, 25)
    if vix_series is None or len(vix_series) < min_obs:
        # Insufficient data: fall back to raw threshold
        risk_off = current_vix >= config.vix_risk_off_threshold
        cautious = risk_off
        return None, risk_off, cautious

    sma = float(vix_series.tail(config.vix_sma_window).mean())
    if sma <= 0:
        return None, False, False

    ratio = current_vix / sma

    # Risk-off: ratio above threshold AND persistence requirement met
    persistence_met = prev_persistence_count >= (config.vix_persistence_periods - 1)
    risk_off = ratio >= config.vix_ratio_threshold and persistence_met

    # Cautious: ratio above reentry threshold (between thresholds, or above both)
    cautious = ratio >= config.vix_reentry_threshold

    return ratio, risk_off, cautious
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_vix_smoothing.py -v --noconftest
```

Expected: 6/6 PASS.

- [ ] **Step 6: Commit**

```bash
git add quant/backtest.py tests/test_vix_smoothing.py
git commit -m "feat: VIX smoothing fields + _compute_vix_regime() helper"
```

### Task 1B: Wire `_compute_vix_regime()` into the walk-forward loop

**Files:**
- Modify: `quant/backtest.py` (three call sites for `detect_regime()`)

- [ ] **Step 1: Find all three rebalance loop sites**

```bash
grep -n "detect_regime\|vix_risk_off\|regime.level" quant/backtest.py | head -40
```

Note the three line numbers where VIX risk-off decisions are made in the rebalance loops.

- [ ] **Step 2: At each site, add persistence tracking and `_compute_vix_regime()` call**

Before the loop, initialize:
```python
_vix_persistence_count = 0
```

Inside the loop, after loading `vix_now` but before the existing risk-off check, add:

```python
# VIX regime (smoothed or raw)
vix_ratio, vix_risk_off_flag, vix_cautious_flag = _compute_vix_regime(
    vix_df.loc[:reb_date] if vix_df is not None else pd.Series(dtype=float),
    current_vix=vix_now or 0.0,
    config=config,
    prev_persistence_count=_vix_persistence_count,
)
# Update persistence counter
if vix_ratio is not None and vix_ratio >= config.vix_ratio_threshold:
    _vix_persistence_count += 1
else:
    _vix_persistence_count = 0

# Override existing risk_off logic when smoothing enabled
if config.vix_smoothing:
    regime_risk_off = vix_risk_off_flag
else:
    regime_risk_off = (vix_now or 0) >= config.vix_risk_off_threshold
```

- [ ] **Step 3: Smoke test — short backtest with VIX smoothing off (existing behavior)**

```bash
python scripts/run_backtest.py --tickers AAPL MSFT GOOGL --start 2023-01-01 --end 2024-01-01 --no-cpcv 2>&1 | tail -5
```

Expected: completes without error.

- [ ] **Step 4: Smoke test — with VIX smoothing on**

```bash
python scripts/run_backtest.py --tickers AAPL MSFT GOOGL --start 2020-01-01 --end 2021-01-01 --no-cpcv --vix-smoothing 2>&1 | grep -i "vix\|regime" | head -10
```

Expected: log lines showing VIX ratio at March 2020 rebalance (should be >> 1.5, triggering risk-off).

- [ ] **Step 5: Commit**

```bash
git add quant/backtest.py scripts/run_backtest.py
git commit -m "feat: wire VIX smoothing into walk-forward rebalance loop"
```

---

## Phase 2: Dynamic Risk-Off ETF Ladder

**Why:** 100% cash during bearish-but-not-crisis regimes forfeits bond and gold returns that historically cushion drawdowns. The graduated ladder keeps capital working proportionally to regime severity.

**Depends on:** Phase 1 (`vix_ratio` from `RegimeState`).

### ETF Ladder Tiers

| Tier | Condition | Equity | TLT | GLD | IEFA | UUP | BIL |
|---|---|---|---|---|---|---|---|
| Mild | ratio 1.2–1.5 | 75% | 20% | 5% | — | — | — |
| Moderate | ratio 1.5–2.0 | 50% | 40% | 10% | — | — | — |
| Severe | ratio 2.0–3.0 | 40% | 30% | 15% | 10% | 5% | — |
| Crisis | ratio > 3.0 AND copper bearish | 0% | 50% | 20% | 15% | — | 15% |

### Task 2A: Tier selection function

**Files:**
- Create: `tests/test_etf_ladder.py`
- Modify: `quant/backtest.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_etf_ladder.py
import pytest
from quant.backtest import BacktestConfig, compute_etf_ladder_tier, ETF_LADDER_TIERS


def _cfg(**kwargs):
    return BacktestConfig(vix_smoothing=True, enable_dynamic_risk_off=True, **kwargs)


def test_tier_none_below_mild():
    """ratio < 1.2 → no tier, full equity."""
    tier = compute_etf_ladder_tier(vix_ratio=1.1, copper_bearish=False, config=_cfg())
    assert tier is None


def test_tier_mild():
    tier = compute_etf_ladder_tier(vix_ratio=1.3, copper_bearish=False, config=_cfg())
    assert tier == "mild"


def test_tier_moderate():
    tier = compute_etf_ladder_tier(vix_ratio=1.7, copper_bearish=False, config=_cfg())
    assert tier == "moderate"


def test_tier_severe():
    tier = compute_etf_ladder_tier(vix_ratio=2.5, copper_bearish=False, config=_cfg())
    assert tier == "severe"


def test_tier_crisis_requires_copper():
    """ratio > 3.0 alone → severe, not crisis (copper gates crisis tier)."""
    tier = compute_etf_ladder_tier(vix_ratio=3.5, copper_bearish=False, config=_cfg())
    assert tier == "severe"


def test_tier_crisis_with_copper():
    tier = compute_etf_ladder_tier(vix_ratio=3.5, copper_bearish=True, config=_cfg())
    assert tier == "crisis"


def test_all_tier_weights_sum_to_one():
    """ETF allocations + equity_frac must sum to 1.0 for each tier."""
    for tier_name, alloc in ETF_LADDER_TIERS.items():
        etf_weight = sum(v for k, v in alloc.items() if k != "equity_frac")
        total = etf_weight + alloc["equity_frac"]
        assert total == pytest.approx(1.0), f"Tier {tier_name} weights sum to {total}"


def test_dynamic_risk_off_disabled_returns_none():
    """enable_dynamic_risk_off=False → always returns None (use raw cash logic)."""
    cfg = BacktestConfig(vix_smoothing=True, enable_dynamic_risk_off=False)
    tier = compute_etf_ladder_tier(vix_ratio=2.0, copper_bearish=False, config=cfg)
    assert tier is None
```

- [ ] **Step 2: Run tests, confirm failure**

```bash
python -m pytest tests/test_etf_ladder.py -v --noconftest 2>&1 | head -15
```

Expected: `ImportError` for `compute_etf_ladder_tier`, `ETF_LADDER_TIERS`.

- [ ] **Step 3: Implement in `quant/backtest.py`**

Add `enable_dynamic_risk_off: bool = False` to `BacktestConfig`.

Add constants and function (place near `compute_fomc_proximity_boost`):

```python
ETF_LADDER_TIERS: dict[str, dict] = {
    "mild":     {"TLT": 0.20, "GLD": 0.05, "equity_frac": 0.75},
    "moderate": {"TLT": 0.40, "GLD": 0.10, "equity_frac": 0.50},
    "severe":   {"TLT": 0.30, "GLD": 0.15, "IEFA": 0.10, "UUP": 0.05, "equity_frac": 0.40},
    "crisis":   {"TLT": 0.50, "GLD": 0.20, "IEFA": 0.15, "BIL": 0.15, "equity_frac": 0.00},
}

HEDGE_ETFS = ["TLT", "GLD", "IEFA", "UUP", "BIL"]


def compute_etf_ladder_tier(
    vix_ratio: Optional[float],
    copper_bearish: bool,
    config: "BacktestConfig",
) -> Optional[str]:
    """
    Return ETF ladder tier name, or None if full equity is appropriate.

    Requires config.enable_dynamic_risk_off=True and a non-None vix_ratio.
    """
    if not config.enable_dynamic_risk_off or vix_ratio is None:
        return None

    reentry = config.vix_reentry_threshold  # 1.2
    if vix_ratio < reentry:
        return None
    elif vix_ratio < config.vix_ratio_threshold:  # 1.2–1.5
        return "mild"
    elif vix_ratio < 2.0:
        return "moderate"
    elif vix_ratio < 3.0:
        return "severe"
    else:
        # Crisis requires copper confirmation
        return "crisis" if copper_bearish else "severe"
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_etf_ladder.py -v --noconftest
```

Expected: 8/8 PASS.

- [ ] **Step 5: Commit**

```bash
git add quant/backtest.py tests/test_etf_ladder.py
git commit -m "feat: ETF ladder tier selection with copper Crisis gate"
```

### Task 2B: Wire ETF ladder into portfolio construction

**Files:**
- Modify: `quant/backtest.py` (portfolio construction, ~3 sites)

- [ ] **Step 1: Add ETF price loading**

Find `_load_sector_etf_data()` or equivalent function that loads ETF price history. After it, add:

```python
def _load_hedge_etf_data(start_date: str, end_date: str) -> dict[str, pd.Series]:
    """Load price series for hedge ETFs (TLT, GLD, IEFA, UUP, BIL)."""
    import yfinance as yf
    result = {}
    for ticker in HEDGE_ETFS:
        try:
            df = yf.download(ticker, start=start_date, end=end_date,
                             auto_adjust=True, progress=False)
            if not df.empty:
                result[ticker] = df["Close"]
        except Exception as exc:
            logger.warning("Failed to load hedge ETF %s: %s", ticker, exc)
    return result
```

Call this at backtest startup when `config.enable_dynamic_risk_off=True`:
```python
hedge_prices = {}
if config.enable_dynamic_risk_off:
    hedge_prices = _load_hedge_etf_data(config.start_date, config.end_date)
    missing = [t for t in HEDGE_ETFS if t not in hedge_prices]
    if missing:
        logger.warning("Missing hedge ETF price data for: %s", missing)
```

- [ ] **Step 2: At portfolio construction, apply ladder**

At each rebalance, after computing `vix_ratio` (Phase 1), add:

```python
# ETF ladder allocation
etf_positions = []
equity_capital_frac = 1.0
if config.enable_dynamic_risk_off:
    tier = compute_etf_ladder_tier(
        vix_ratio=vix_ratio,
        copper_bearish=regime.copper_bearish,
        config=config,
    )
    if tier is not None:
        alloc = ETF_LADDER_TIERS[tier]
        equity_capital_frac = alloc["equity_frac"]
        for etf_ticker, weight in alloc.items():
            if etf_ticker == "equity_frac":
                continue
            if etf_ticker not in hedge_prices:
                logger.warning("No price data for hedge ETF %s, skipping", etf_ticker)
                continue
            etf_price_series = hedge_prices[etf_ticker]
            price = etf_price_series.asof(reb_date)
            if pd.isna(price):
                continue
            etf_positions.append({
                "ticker": etf_ticker,
                "weight": weight,
                "price": price,
                "direction": "LONG",
                "is_hedge_etf": True,
            })

# Scale equity capital
available_capital = portfolio_value * equity_capital_frac
```

- [ ] **Step 3: Smoke test**

```bash
python scripts/run_backtest.py --tickers AAPL MSFT GOOGL --start 2020-01-01 --end 2021-01-01 --no-cpcv --vix-smoothing --dynamic-risk-off 2>&1 | grep -i "TLT\|GLD\|ladder\|tier" | head -10
```

Expected: log lines showing ETF ladder activation at March 2020 rebalance.

- [ ] **Step 4: Commit**

```bash
git add quant/backtest.py
git commit -m "feat: wire ETF ladder into portfolio construction"
```

---

## Phase 3: Multi-Horizon Backtesting

**Why:** Monthly is not the only valid cadence. Event-driven entries (pre-earnings) serve different strategies. A `HorizonConfig` lets CPCV run per-horizon.

> ⚠️ **Warning:** Weekly rebalance historically produces Sharpe ≈ 0.02 vs monthly 1.04 on this universe (documented in project memory). Weekly mode is implemented for research purposes, not production use.

### Task 3: HorizonConfig and rebalance date generation

**Files:**
- Create: `tests/test_horizon_config.py`
- Modify: `quant/backtest.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_horizon_config.py
import pandas as pd
import pytest
from quant.backtest import HorizonConfig, _generate_rebalance_dates


def test_monthly_produces_month_start_dates():
    h = HorizonConfig(mode="monthly")
    dates = _generate_rebalance_dates(
        pd.Timestamp("2020-01-01"), pd.Timestamp("2020-06-30"), h
    )
    assert len(dates) == 6
    assert all(d.day == 1 for d in dates)


def test_weekly_produces_more_dates_than_monthly():
    h = HorizonConfig(mode="weekly", weekly_rebalance_days=5)
    dates = _generate_rebalance_dates(
        pd.Timestamp("2020-01-01"), pd.Timestamp("2020-06-30"), h
    )
    assert len(dates) > 20  # ~26 for 6 months


def test_hybrid_is_superset_of_monthly():
    monthly = _generate_rebalance_dates(
        pd.Timestamp("2020-01-01"), pd.Timestamp("2020-06-30"),
        HorizonConfig(mode="monthly")
    )
    hybrid = _generate_rebalance_dates(
        pd.Timestamp("2020-01-01"), pd.Timestamp("2020-06-30"),
        HorizonConfig(mode="hybrid")
    )
    for d in monthly:
        assert d in hybrid


def test_unknown_mode_raises():
    with pytest.raises(ValueError, match="Unknown horizon mode"):
        _generate_rebalance_dates(
            pd.Timestamp("2020-01-01"), pd.Timestamp("2020-06-30"),
            HorizonConfig(mode="daily")
        )


def test_horizon_config_defaults():
    h = HorizonConfig()
    assert h.mode == "monthly"
    assert h.weekly_rebalance_days == 5
    assert h.event_entry_days_before == 5
    assert h.event_exit_days_after == 3
```

- [ ] **Step 2: Run tests, confirm failure**

```bash
python -m pytest tests/test_horizon_config.py -v --noconftest 2>&1 | head -15
```

- [ ] **Step 3: Implement `HorizonConfig` and `_generate_rebalance_dates()`**

Add to `quant/backtest.py` (after `BacktestConfig`):

```python
@dataclass
class HorizonConfig:
    """
    Controls rebalance frequency and event-driven overlay cadence.

    Modes:
      monthly      — month-start rebalances (default; best Sharpe on this universe)
      weekly       — every N business days (WARNING: historically Sharpe ≈ 0.02)
      event_driven — enter N days before earnings, exit N days after
      hybrid       — monthly base + event-driven overlays
    """
    mode: str = "monthly"
    weekly_rebalance_days: int = 5
    event_entry_days_before: int = 5
    event_exit_days_after: int = 3
    hybrid_base: str = "monthly"
    hybrid_overlay: bool = True


def _generate_rebalance_dates(
    start: pd.Timestamp,
    end: pd.Timestamp,
    horizon: HorizonConfig,
) -> pd.DatetimeIndex:
    """Return sorted rebalance dates for the given horizon mode."""
    if horizon.mode == "monthly":
        return pd.date_range(start, end, freq="MS")
    elif horizon.mode == "weekly":
        return pd.date_range(start, end, freq=f"{horizon.weekly_rebalance_days}B")
    elif horizon.mode == "event_driven":
        # Stub: returns monthly until earnings calendar integration is complete.
        # Full implementation wires into quant/event_timing.py earnings dates.
        logger.warning("event_driven horizon uses monthly stub until earnings calendar is wired")
        return pd.date_range(start, end, freq="MS")
    elif horizon.mode == "hybrid":
        base = _generate_rebalance_dates(start, end, HorizonConfig(mode=horizon.hybrid_base))
        event = _generate_rebalance_dates(start, end, HorizonConfig(mode="event_driven"))
        return base.union(event).sort_values()
    else:
        raise ValueError(f"Unknown horizon mode: {horizon.mode!r}. "
                         f"Valid: monthly, weekly, event_driven, hybrid")
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_horizon_config.py -v --noconftest
```

Expected: 5/5 PASS.

- [ ] **Step 5: Add `--horizon` CLI flag to `scripts/run_backtest.py`**

```python
parser.add_argument(
    "--horizon",
    choices=["monthly", "weekly", "event_driven", "hybrid"],
    default="monthly",
    help="Rebalance frequency. WARNING: weekly historically produces Sharpe ~0.02.",
)
parser.add_argument("--event-entry-days", type=int, default=5)
parser.add_argument("--event-exit-days", type=int, default=3)
```

Wire into function call:
```python
horizon_config = HorizonConfig(
    mode=args.horizon,
    event_entry_days_before=args.event_entry_days,
    event_exit_days_after=args.event_exit_days,
)
```

- [ ] **Step 6: Commit**

```bash
git add quant/backtest.py scripts/run_backtest.py tests/test_horizon_config.py
git commit -m "feat: HorizonConfig + _generate_rebalance_dates() + --horizon CLI flag"
```

---

## Phase 4: Copper Regime Signal

**Why:** Validated confirming indicator for Crisis ETF tier. Extends `macro_signals.py` using the exact same FRED fetch + rolling computation pattern as HY OAS and yield curve.

**Depends on:** Phase 2 (`copper_bearish` consumed by ETF Crisis tier gate).

### Task 4A: Copper signal computation

**Files:**
- Create: `tests/test_copper_signal.py`
- Modify: `quant/macro_signals.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_copper_signal.py
import pandas as pd
import numpy as np
import pytest
from quant.macro_signals import compute_copper_signal


def _copper_series(values: list[float], start="2018-01-01") -> pd.Series:
    """Monthly copper price series (PCOPPUSDM format)."""
    dates = pd.date_range(start, periods=len(values), freq="MS")
    return pd.Series(values, index=dates)


def test_near_high_bullish():
    """Copper within 5% of 12M high → bullish."""
    # 12 months at 8000, current at 7900 (1.25% below high)
    vals = [8000.0] * 12 + [7900.0]
    s = _copper_series(vals)
    as_of = s.index[-1]
    price, dd, regime, score = compute_copper_signal(s, as_of)
    assert regime == "bullish"
    assert score > 0


def test_new_12m_high():
    """Copper at new 12M high → score = +1.0."""
    vals = [7000.0] * 12 + [8500.0]
    s = _copper_series(vals)
    _, _, regime, score = compute_copper_signal(s, s.index[-1])
    assert regime == "bullish"
    assert score == pytest.approx(1.0)


def test_neutral_zone():
    """10% below 12M high → neutral."""
    vals = [8000.0] * 12 + [7200.0]  # 10% below
    s = _copper_series(vals)
    _, _, regime, score = compute_copper_signal(s, s.index[-1])
    assert regime == "neutral"
    assert score == pytest.approx(0.0)


def test_bearish_not_persistent():
    """17% below 12M high but prior month only 8% below → not yet bearish."""
    prior_vals = [8000.0] * 11 + [7360.0]   # prior: 8% below 8000
    current = 6640.0                          # current: 17% below 8000
    s = _copper_series(prior_vals + [current])
    _, _, regime, score = compute_copper_signal(s, s.index[-1])
    assert regime == "neutral"  # persistence not met
    assert score > -0.5


def test_bearish_persistent():
    """17% below 12M high, prior month also 17% below → bearish."""
    vals = [8000.0] * 11 + [6640.0, 6640.0]  # both months 17% below
    s = _copper_series(vals)
    _, _, regime, score = compute_copper_signal(s, s.index[-1])
    assert regime == "bearish"
    assert score == pytest.approx(-0.5)


def test_crisis():
    """28% below 12M high, prior month also below → crisis."""
    vals = [8000.0] * 11 + [5800.0, 5760.0]  # both ~27-28% below
    s = _copper_series(vals)
    _, _, regime, score = compute_copper_signal(s, s.index[-1])
    assert regime == "crisis"
    assert score == pytest.approx(-1.0)


def test_insufficient_data():
    """Fewer than 13 observations → unknown, score 0."""
    s = _copper_series([8000.0] * 10)
    price, dd, regime, score = compute_copper_signal(s, s.index[-1])
    assert regime == "unknown"
    assert score == 0.0
    assert price is None
```

- [ ] **Step 2: Run tests, confirm failure**

```bash
python -m pytest tests/test_copper_signal.py -v --noconftest 2>&1 | head -15
```

- [ ] **Step 3: Implement `compute_copper_signal()` in `quant/macro_signals.py`**

```python
def compute_copper_signal(
    copper_series: pd.Series,
    as_of_date: pd.Timestamp,
) -> tuple[Optional[float], Optional[float], str, float]:
    """
    Compute copper regime signal from PCOPPUSDM (monthly, USD/MT).

    Thresholds based on empirical literature (IMF WP/12/278, BoC 2016-17):
      >= -5% of 12M high  : bullish
      -5% to -15%         : neutral
      -15% to -25%, persistent (2+ months) : bearish
      < -25%, persistent  : crisis

    Returns: (current_price, drawdown_from_12m_high, regime_label, score)
    Score: -1.0 (crisis) to +1.0 (new high)
    """
    available = copper_series[copper_series.index <= as_of_date].dropna()
    if len(available) < 13:
        return None, None, "unknown", 0.0

    current = float(available.iloc[-1])
    prior = available.iloc[:-1]

    # Point-in-time 12M trailing high (excludes current month)
    high_12m = float(prior.iloc[-12:].max())
    drawdown = (current - high_12m) / high_12m  # <= 0 if below high

    # New 12M high
    if current >= high_12m:
        return current, round(drawdown, 4), "bullish", 1.0

    # Persistence: check if prior month was also below -15% threshold
    persistent = False
    if len(prior) >= 2 and len(available) >= 14:
        prior_current = float(prior.iloc[-1])
        prior_high = float(prior.iloc[-13:-1].max()) if len(prior) >= 13 else high_12m
        prior_drawdown = (prior_current - prior_high) / prior_high
        persistent = prior_drawdown <= -0.15

    if drawdown >= -0.05:
        regime, score = "bullish", 0.5
    elif drawdown >= -0.15:
        regime, score = "neutral", 0.0
    elif drawdown >= -0.25:
        if persistent:
            regime, score = "bearish", -0.5
        else:
            regime, score = "neutral", -0.2
    else:
        if persistent:
            regime, score = "crisis", -1.0
        else:
            regime, score = "neutral", -0.3

    return current, round(drawdown, 4), regime, round(score, 3)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_copper_signal.py -v --noconftest
```

Expected: 7/7 PASS.

- [ ] **Step 5: Add copper fields to `MacroRegimeSignal`**

In `quant/macro_signals.py`, in the `MacroRegimeSignal` dataclass:

```python
    copper_price: Optional[float] = None
    copper_drawdown_12m: Optional[float] = None
    copper_regime: str = "unknown"
    copper_score: float = 0.0
```

Update `to_dict()` and `to_context_text()` to include copper fields.

- [ ] **Step 6: Commit**

```bash
git add quant/macro_signals.py tests/test_copper_signal.py
git commit -m "feat: copper regime signal — compute_copper_signal() + MacroRegimeSignal fields"
```

### Task 4B: Wire copper into FRED loading, backtest, and SignalVector

**Files:**
- Modify: `fred_client.py`
- Modify: `quant/macro_signals.py` (`load_fred_macro_data()`, `compute_macro_regime()`)
- Modify: `quant/signals.py`
- Modify: `quant/backtest.py` (`RegimeState.copper_bearish` population)

> ⚠️ **Risk:** `load_fred_macro_data()` return signature changes from 2-tuple to 3-tuple. Run `grep -n "load_fred_macro_data" quant/backtest.py quant/macro_signals.py` before starting and update ALL call sites.

- [ ] **Step 1: Add PCOPPUSDM to FRED catalog**

In `fred_client.py`, find the `MACRO_SERIES` dict or series list and add:
```python
"PCOPPUSDM": ("Global Copper Price (USD/MT)", "USD/MT"),
```

- [ ] **Step 2: Add copper loading to `load_fred_macro_data()`**

```python
# In load_fred_macro_data(), add copper fetch alongside HY OAS and yield curve:
copper = pd.Series(dtype=float)
try:
    raw = client.get_series("PCOPPUSDM", observation_start=start_date)
    if raw is not None and not raw.empty:
        copper = raw.resample("MS").last().ffill()
except Exception as exc:
    logger.warning("Failed to load PCOPPUSDM: %s", exc)

# Change return from 2-tuple to 3-tuple:
return hy_oas_series, t10y3m_series, copper
```

Update ALL callers — find them with:
```bash
grep -n "load_fred_macro_data" quant/backtest.py quant/macro_signals.py
```
Change unpacking from `hy, t10y = load_fred_macro_data(...)` to `hy, t10y, copper = load_fred_macro_data(...)`.

- [ ] **Step 3: Wire copper into `compute_macro_regime()`**

```python
def compute_macro_regime(
    hy_oas_series, t10y3m_series, as_of_date, vix=None,
    copper_series=None,  # NEW optional parameter
) -> MacroRegimeSignal:
    ...
    if copper_series is not None and not copper_series.empty:
        price, dd, regime, score = compute_copper_signal(copper_series, as_of_date)
        signal.copper_price = price
        signal.copper_drawdown_12m = dd
        signal.copper_regime = regime
        signal.copper_score = score
```

- [ ] **Step 4: Add `copper_regime_score` to `SignalVector`**

In `quant/signals.py`, in `SignalVector`:
```python
    copper_regime_score: float = 0.0   # Set by copper macro signal (-1 to +1)
```

- [ ] **Step 5: Populate `RegimeState.copper_bearish` in backtest**

At each rebalance, after computing macro signal:
```python
if regime.macro_signal and regime.macro_signal.copper_regime in ("bearish", "crisis"):
    regime.copper_bearish = True
else:
    regime.copper_bearish = False
```

- [ ] **Step 6: Run full test suite**

```bash
python -m pytest tests/test_copper_signal.py tests/test_etf_ladder.py tests/test_vix_smoothing.py tests/test_horizon_config.py -v --noconftest
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add fred_client.py quant/macro_signals.py quant/signals.py quant/backtest.py
git commit -m "feat: wire copper signal into FRED loading, MacroRegimeSignal, RegimeState, SignalVector"
```

---

## Risk Flags

1. **`load_fred_macro_data()` return signature change** is the highest-risk change. Run `grep -rn "load_fred_macro_data"` across the full repo before starting Phase 4B — update every call site.

2. **ETF price availability (Phase 2).** TLT/GLD/IEFA/UUP/BIL are not in the default equity universe. Load them separately at backtest startup when `enable_dynamic_risk_off=True`. Never silently skip ETF positions if price data is unavailable — log a warning.

3. **`_compute_vix_regime()` persistence parameter (Phase 1B).** The persistence counter is stateful across rebalances and must be maintained as a local variable in each of the three walk-forward loop sites. Search for all three and update each.

4. **CPCV × Horizon interaction (Phase 3).** Weekly mode produces ~4× more rebalance dates. `n_groups=16` will create much smaller CPCV groups. Add a `--cpcv-min-periods-per-group` guard that warns when group size < 8.

5. **Copper signal is monthly; weekly horizon produces sub-monthly rebalances.** The copper value repeats within each month for weekly rebalances (correct point-in-time behavior). Document this in comments.

---

## CPCV Validation Gates

After completing all four phases, run CPCV validation on the liquid_50 universe:

```bash
# Baseline (no new signals)
python scripts/run_backtest.py --universe liquid_50 --start 2020-01-01 --cpcv 2>&1 | grep -E "Sharpe|PBO|Alpha"

# With VIX smoothing + dynamic risk-off + copper
python scripts/run_backtest.py --universe liquid_50 --start 2020-01-01 --cpcv --vix-smoothing --dynamic-risk-off 2>&1 | grep -E "Sharpe|PBO|Alpha"
```

**Acceptance criteria:** PBO stays below 15%. If PBO rises, tighten the Crisis tier conditions before merging.
