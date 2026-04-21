# Price Regression & ARIMA Forecast Signals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two statistically-grounded short-term signals: an R²-filtered price regression trend signal and an ARIMA(1,1,1) forecast signal gated to stable vol regimes.

**Architecture:** Two new signal modules (`regression_signal.py`, `arima_signal.py`) follow the existing `additional_signals.py` pattern — each exposes a plural wrapper function returning `{ticker: float}` that the backtest loop injects into `SignalVector`. Unlike the Kalshi regime modifiers (which are blended post-normalization), these are per-stock technical signals that enter the **cross-sectional normalization pipeline** exactly like `price_momentum_score`: (1) raw values set on `SignalVector` pre-normalization, (2) added to `SIGNAL_FIELDS` in `cross_sectional.py` for sector-adjusted z-scoring, (3) added to `DEFAULT_COMPOSITE_WEIGHTS` so `compute_normalized_composite` picks them up automatically. No manual additive blending needed.

**Tech Stack:** `scipy.stats.linregress`, `statsmodels.tsa.arima.model.ARIMA`, `numpy`, `pandas`, `pytest`

---

## Background: 12M Momentum Already Exists

`quant/additional_signals.py` already implements classic 12-1M Jegadeesh-Titman momentum in `compute_price_momentum_scores()`, wired into `SignalVector.price_momentum_score`. Do not re-implement. This plan adds the two missing signals only.

---

## File Map

| File | Action | What changes |
|------|--------|--------------|
| `quant/regression_signal.py` | Create | `compute_price_regression_score()` + `compute_price_regression_scores()` wrapper |
| `quant/arima_signal.py` | Create | `compute_arima_forecast_score()` + `compute_arima_forecast_scores()` wrapper |
| `quant/signals.py` | Modify | Add `price_regression_score: float = 0.0` and `arima_forecast_score: float = 0.0` after `kalshi_event_score` |
| `quant/cross_sectional.py` | Modify | Add both fields to `SIGNAL_FIELDS` (for cross-sectional normalization) and to `DEFAULT_COMPOSITE_WEIGHTS` (for composite inclusion) |
| `quant/backtest.py` | Modify | Add 5 config flags; inject raw signal values at both the single-pass site (~line 1895) AND the walk-forward site (~line 2526) — walk-forward is the default path |
| `scripts/run_backtest.py` | Modify | Add 5 CLI args; wire into `BacktestConfig` |
| `tests/test_regression_signal.py` | Create | 6 unit tests |
| `tests/test_arima_signal.py` | Create | 5 unit tests |

**Critical architecture note:** The default backtest is walk-forward (`run_walk_forward`, ~line 2105). The single-pass `run_backtest` (~line 1864) is a quick sanity-check path. CPCV is opt-in via `--cpcv`. Always verify the walk-forward injection site first.

**Why cross-sectional normalization (not post-normalization blending like Kalshi):** `price_regression_score` and `arima_forecast_score` are per-stock signals — their meaning is relative (which stocks have the strongest reliable trend vs. the universe). Cross-sectional z-scoring removes universe-wide bias and puts them on the same scale as `price_momentum_score`. Kalshi macro modifier is the same value for all stocks (regime modifier), so it must be applied post-normalization. Regression and ARIMA are not uniform across stocks — they belong in the normalized composite.

---

## Task 1: `quant/regression_signal.py` + tests

**Files:**
- Create: `quant/regression_signal.py`
- Create: `tests/test_regression_signal.py`

- [ ] **Step 1: Write the tests first**

Create `tests/test_regression_signal.py`:

```python
"""
Unit tests for quant/regression_signal.py.

Run with:
    cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst
    python -m pytest tests/test_regression_signal.py -v --noconftest
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quant.regression_signal import (
    compute_price_regression_score,
    compute_price_regression_scores,
)


def test_regression_low_r2_returns_zero():
    """Random walk prices have R² near zero — signal must be suppressed."""
    np.random.seed(42)
    prices = pd.Series(100 + np.random.randn(100).cumsum())
    score = compute_price_regression_score(prices, window=60, r2_threshold=0.6)
    assert score == 0.0, f"Expected 0.0 for random walk, got {score}"


def test_regression_strong_uptrend_returns_positive():
    """Perfect linear uptrend → R²=1.0 → score should be well above 0.3."""
    prices = pd.Series(np.linspace(90.0, 110.0, 60))
    score = compute_price_regression_score(prices, window=60, r2_threshold=0.6)
    assert score > 0.3, f"Expected score > 0.3 for linear uptrend, got {score}"


def test_regression_strong_downtrend_returns_negative():
    """Perfect linear downtrend → R²=1.0 → score should be well below -0.3."""
    prices = pd.Series(np.linspace(110.0, 90.0, 60))
    score = compute_price_regression_score(prices, window=60, r2_threshold=0.6)
    assert score < -0.3, f"Expected score < -0.3 for linear downtrend, got {score}"


def test_regression_clips_to_unit_interval():
    """Score must always stay within [-1.0, +1.0] regardless of slope magnitude."""
    prices = pd.Series(np.linspace(1.0, 1_000_000.0, 60))
    score = compute_price_regression_score(prices, window=60, r2_threshold=0.0)
    assert -1.0 <= score <= 1.0, f"Score {score} out of [-1, 1]"

    prices_down = pd.Series(np.linspace(1_000_000.0, 1.0, 60))
    score_down = compute_price_regression_score(prices_down, window=60, r2_threshold=0.0)
    assert -1.0 <= score_down <= 1.0, f"Score {score_down} out of [-1, 1]"


def test_regression_insufficient_data_returns_zero():
    """Fewer prices than window → must return 0.0 without raising."""
    prices = pd.Series(np.linspace(90.0, 100.0, 30))  # only 30 points, window=60
    score = compute_price_regression_score(prices, window=60, r2_threshold=0.6)
    assert score == 0.0, f"Expected 0.0 for insufficient data, got {score}"


def test_regression_scores_wrapper_returns_dict():
    """Wrapper must return a dict keyed by ticker with float values in [-1, 1]."""
    import datetime

    prices_up = pd.Series(
        np.linspace(90.0, 110.0, 120),
        index=pd.date_range("2024-01-01", periods=120, freq="B"),
    )
    df_up = pd.DataFrame({"close": prices_up})

    prices_flat = pd.Series(
        np.ones(120) * 100.0,
        index=pd.date_range("2024-01-01", periods=120, freq="B"),
    )
    df_flat = pd.DataFrame({"close": prices_flat})

    universe_data = {
        "AAPL": {"price_history": df_up},
        "MSFT": {"price_history": df_flat},
    }

    reb_date = datetime.date(2024, 6, 30)
    result = compute_price_regression_scores(
        universe_data, reb_date, window=60, r2_threshold=0.6
    )

    assert isinstance(result, dict), "Result must be a dict"
    assert set(result.keys()) == {"AAPL", "MSFT"}
    for ticker, score in result.items():
        assert isinstance(score, float), f"Score for {ticker} must be float"
        assert -1.0 <= score <= 1.0, f"Score for {ticker} out of [-1, 1]: {score}"
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -m pytest tests/test_regression_signal.py -v --noconftest 2>&1 | head -15
```

Expected: `ModuleNotFoundError: No module named 'quant.regression_signal'`

- [ ] **Step 3: Implement `quant/regression_signal.py`**

```python
"""
Price Regression Signal — R²-filtered OLS trend.

Fits log(price) ~ time-index via OLS over a rolling window.
Only emits a signal when R² >= r2_threshold (default 0.6), indicating
the trend is statistically reliable. Slope is converted to [-1, +1]
via tanh scaling so that a 1%/day trend over 60 days maps to ~0.99.

Returns 0.0 when trend is not reliable or data is insufficient.
Pattern: mirrors compute_price_momentum_scores() in additional_signals.py.
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd
from scipy.stats import linregress

logger = logging.getLogger(__name__)


def compute_price_regression_score(
    prices: pd.Series,
    window: int = 60,
    r2_threshold: float = 0.6,
) -> float:
    """
    Returns a signal in [-1, +1] if price trend is statistically significant
    (R² >= r2_threshold), else 0.0.

    Uses log(price) regression so slope is daily % return.
    Scaling: tanh(slope * window * 5) — a 1%/day trend over 60 days maps to ~tanh(3) = 0.99.
    """
    if len(prices) < window:
        return 0.0
    series = np.log(prices.iloc[-window:].values.astype(float))
    if np.any(np.isnan(series)) or np.any(series <= 0):
        return 0.0
    x = np.arange(len(series), dtype=float)
    slope, _, r_value, _, _ = linregress(x, series)
    r2 = r_value ** 2
    if r2 < r2_threshold:
        return 0.0
    raw = np.tanh(slope * window * 5.0)
    return float(np.clip(raw, -1.0, 1.0))


def compute_price_regression_scores(
    universe_data: dict,
    reb_date: date,
    window: int = 60,
    r2_threshold: float = 0.6,
) -> dict[str, float]:
    """
    Compute price regression scores for all tickers in universe_data.

    Args:
        universe_data: dict keyed by ticker. Each value is either:
                       - a dict with a 'price_history' key → pd.DataFrame with 'close' column
                       - a pd.DataFrame directly with a 'close' column
        reb_date:      rebalance date — only prices on or before this date are used.
        window:        rolling window in trading days (default: 60).
        r2_threshold:  minimum R² to emit a non-zero signal (default: 0.6).

    Returns:
        dict mapping ticker -> float score in [-1, +1].
    """
    scores: dict[str, float] = {}

    for ticker, data in universe_data.items():
        try:
            if isinstance(data, dict):
                df = data.get("price_history")
            else:
                df = data

            if df is None or not isinstance(df, pd.DataFrame):
                scores[ticker] = 0.0
                continue

            available = df[df.index <= pd.Timestamp(reb_date)]
            if "close" not in available.columns:
                scores[ticker] = 0.0
                continue

            prices = available["close"].dropna()
            scores[ticker] = compute_price_regression_score(
                prices, window=window, r2_threshold=r2_threshold
            )
        except Exception as exc:
            logger.warning("Regression score failed for %s: %s", ticker, exc)
            scores[ticker] = 0.0

    return scores
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -m pytest tests/test_regression_signal.py -v --noconftest
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && git add quant/regression_signal.py tests/test_regression_signal.py && git commit -m "feat: add R²-filtered price regression signal"
```

---

## Task 2: `quant/arima_signal.py` + tests

**Files:**
- Create: `quant/arima_signal.py`
- Create: `tests/test_arima_signal.py`

- [ ] **Step 1: Write the tests first**

Create `tests/test_arima_signal.py`:

```python
"""
Unit tests for quant/arima_signal.py.

Run with:
    cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst
    python -m pytest tests/test_arima_signal.py -v --noconftest
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quant.arima_signal import (
    compute_arima_forecast_score,
    compute_arima_forecast_scores,
)


def test_arima_high_vol_returns_zero():
    """When 20d realized vol exceeds threshold, signal must be 0.0."""
    np.random.seed(42)
    # High-vol prices: large daily moves ~80% annualized
    returns = np.random.randn(80) * 0.05
    prices = pd.Series(100.0 * np.exp(returns.cumsum()))
    score = compute_arima_forecast_score(prices, lookback=60, horizon=5, vol_threshold=0.25)
    assert score == 0.0, f"Expected 0.0 for high-vol regime, got {score}"


def test_arima_insufficient_data_returns_zero():
    """Fewer prices than lookback + horizon must return 0.0 without raising."""
    prices = pd.Series(np.linspace(90.0, 100.0, 50))  # 50 < 60 + 5
    score = compute_arima_forecast_score(prices, lookback=60, horizon=5, vol_threshold=0.25)
    assert score == 0.0, f"Expected 0.0 for insufficient data, got {score}"


def test_arima_stable_regime_returns_float_in_unit_interval():
    """
    Low-vol smooth uptrend — ARIMA should fit and return a float in [-1, 1].
    We don't assert direction (depends on fit convergence) but assert the contract.
    """
    np.random.seed(42)
    # Low-vol: daily return ~0.1% + tiny noise (~5% annualized)
    daily_returns = 0.001 + np.random.randn(75) * 0.003
    prices = pd.Series(100.0 * np.exp(daily_returns.cumsum()))
    score = compute_arima_forecast_score(prices, lookback=60, horizon=5, vol_threshold=0.25)
    assert isinstance(score, float), f"Score must be float, got {type(score)}"
    assert -1.0 <= score <= 1.0, f"Score {score} out of [-1, 1]"


def test_arima_clips_to_unit_interval():
    """Score must never exceed [-1, +1] regardless of forecast magnitude."""
    np.random.seed(0)
    daily_returns = np.random.randn(75) * 0.001
    prices = pd.Series(100.0 * np.exp(daily_returns.cumsum()))
    score = compute_arima_forecast_score(prices, lookback=60, horizon=5, vol_threshold=1.0)
    assert -1.0 <= score <= 1.0, f"Score {score} out of [-1, 1]"


def test_arima_scores_wrapper_returns_dict():
    """Wrapper must return dict keyed by ticker; high-vol ticker gated to 0.0."""
    import datetime

    np.random.seed(42)
    idx = pd.date_range("2024-01-01", periods=100, freq="B")

    # Low-vol smooth uptrend
    r1 = 0.001 + np.random.randn(100) * 0.003
    df_stable = pd.DataFrame({"close": 100.0 * np.exp(r1.cumsum())}, index=idx)

    # High-vol random walk
    r2 = np.random.randn(100) * 0.05
    df_volatile = pd.DataFrame({"close": 100.0 * np.exp(r2.cumsum())}, index=idx)

    universe_data = {
        "AAPL": {"price_history": df_stable},
        "TSLA": {"price_history": df_volatile},
    }

    reb_date = datetime.date(2024, 6, 30)
    result = compute_arima_forecast_scores(universe_data, reb_date, vol_threshold=0.25)

    assert isinstance(result, dict)
    assert set(result.keys()) == {"AAPL", "TSLA"}
    for ticker, score in result.items():
        assert isinstance(score, float)
        assert -1.0 <= score <= 1.0, f"Score for {ticker} out of [-1, 1]: {score}"
    assert result["TSLA"] == 0.0, f"Expected TSLA=0.0 (high vol gated), got {result['TSLA']}"
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -m pytest tests/test_arima_signal.py -v --noconftest 2>&1 | head -15
```

Expected: `ModuleNotFoundError: No module named 'quant.arima_signal'`

- [ ] **Step 3: Implement `quant/arima_signal.py`**

```python
"""
ARIMA Forecast Signal — short-term price forecast gated to stable vol regimes.

Fits ARIMA(1,1,1) on log-prices over a lookback window, forecasts `horizon`
days ahead, and converts the predicted return to a score in [-1, +1].

Signal fires ONLY when 20-day realized volatility (annualized) is below
vol_threshold (default 0.25 = 25%). Above that threshold, ARIMA assumptions
break down and forecasts degrade to noise.

Returns 0.0 on any failure. Never raises.
Pattern: mirrors compute_price_momentum_scores() in additional_signals.py.
"""

from __future__ import annotations

import logging
import warnings
from datetime import date

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_arima_forecast_score(
    prices: pd.Series,
    lookback: int = 60,
    horizon: int = 5,
    vol_threshold: float = 0.25,
    order: tuple = (1, 1, 1),
) -> float:
    """
    Returns a signal in [-1, +1] based on ARIMA(1,1,1) price forecast,
    or 0.0 if vol is too high or fit fails.

    Signal = tanh(forecast_return * 20):
      - 5% predicted move → tanh(1) ≈ 0.76
      - 10% predicted move → tanh(2) ≈ 0.96
    """
    from statsmodels.tsa.arima.model import ARIMA

    if len(prices) < lookback + horizon:
        return 0.0

    recent = prices.iloc[-(lookback + horizon):-horizon]
    log_prices = np.log(recent.values.astype(float))

    if np.any(np.isnan(log_prices)) or np.any(log_prices <= 0):
        return 0.0

    # Stability gate: 20d realized vol (annualized)
    vol_window = log_prices[-20:]
    if len(vol_window) < 2:
        return 0.0
    returns = np.diff(vol_window)
    realized_vol = returns.std() * np.sqrt(252)
    if realized_vol >= vol_threshold:
        return 0.0

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = ARIMA(log_prices, order=order)
            fit = model.fit()
            forecast = fit.forecast(steps=horizon)
        predicted_log_price = forecast[-1]
        current_log_price = log_prices[-1]
        predicted_return = predicted_log_price - current_log_price
        raw = np.tanh(predicted_return * 20.0)
        return float(np.clip(raw, -1.0, 1.0))
    except Exception as exc:
        logger.debug("ARIMA fit failed: %s", exc)
        return 0.0


def compute_arima_forecast_scores(
    universe_data: dict,
    reb_date: date,
    lookback: int = 60,
    horizon: int = 5,
    vol_threshold: float = 0.25,
    order: tuple = (1, 1, 1),
) -> dict[str, float]:
    """
    Compute ARIMA forecast scores for all tickers in universe_data.

    Args:
        universe_data: dict keyed by ticker. Each value is either:
                       - a dict with a 'price_history' key → pd.DataFrame with 'close' column
                       - a pd.DataFrame directly with a 'close' column
        reb_date:      rebalance date — only prices on or before this date are used.
        lookback:      ARIMA training window in trading days (default: 60).
        horizon:       forecast horizon in days (default: 5).
        vol_threshold: max annualized realized vol to allow signal (default: 0.25).
        order:         ARIMA order tuple (default: (1, 1, 1)).

    Returns:
        dict mapping ticker -> float score in [-1, +1].
    """
    scores: dict[str, float] = {}

    for ticker, data in universe_data.items():
        try:
            if isinstance(data, dict):
                df = data.get("price_history")
            else:
                df = data

            if df is None or not isinstance(df, pd.DataFrame):
                scores[ticker] = 0.0
                continue

            available = df[df.index <= pd.Timestamp(reb_date)]
            if "close" not in available.columns:
                scores[ticker] = 0.0
                continue

            prices = available["close"].dropna()
            scores[ticker] = compute_arima_forecast_score(
                prices,
                lookback=lookback,
                horizon=horizon,
                vol_threshold=vol_threshold,
                order=order,
            )
        except Exception as exc:
            logger.warning("ARIMA score failed for %s: %s", ticker, exc)
            scores[ticker] = 0.0

    return scores
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -m pytest tests/test_arima_signal.py -v --noconftest
```

Expected: 5 tests pass. `test_arima_stable_regime_returns_float_in_unit_interval` does not assert a specific direction — only that ARIMA returns a valid float.

- [ ] **Step 5: Commit**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && git add quant/arima_signal.py tests/test_arima_signal.py && git commit -m "feat: add ARIMA(1,1,1) forecast signal with vol-regime gate"
```

---

## Task 3: Add fields to `SignalVector`

**Files:**
- Modify: `quant/signals.py`

- [ ] **Step 1: Insert two fields**

In `quant/signals.py`, locate line 47:
```python
    kalshi_event_score: float = 0.0   # Pre-earnings divergence vs Kalshi-implied prob
```

And line 48:
```python
    earnings_blocked: bool = False
```

Insert between them:

```python
    price_regression_score: float = 0.0  # R²-filtered OLS trend signal [-1, +1]
    arima_forecast_score: float = 0.0    # ARIMA(1,1,1) forecast signal, stable regimes only [-1, +1]
```

- [ ] **Step 2: Verify**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -c "from quant.signals import SignalVector; print('price_regression_score' in SignalVector.__dataclass_fields__, 'arima_forecast_score' in SignalVector.__dataclass_fields__)"
```

Expected: `True True`

- [ ] **Step 3: Commit**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && git add quant/signals.py && git commit -m "feat: add price_regression_score and arima_forecast_score to SignalVector"
```

---

## Task 4: Wire signals into cross-sectional pipeline + backtest injection

**Files:**
- Modify: `quant/cross_sectional.py` — add both signals to SIGNAL_FIELDS and DEFAULT_COMPOSITE_WEIGHTS
- Modify: `quant/backtest.py` — add config flags + inject raw values at single-pass and walk-forward sites

**Why this is different from Kalshi:** These are per-stock signals that vary across the universe. They enter the cross-sectional normalization pipeline (z-scored relative to the universe), then `compute_normalized_composite` picks them up automatically via their weights. No manual post-normalization additive blending needed.

### Step 4.1 — Add to cross_sectional.py

- [ ] In `quant/cross_sectional.py`, in `SIGNAL_FIELDS` (around line 77), add two new entries after `("event_timing_score", None)`:

```python
    ("price_regression_score", None),
    ("arima_forecast_score", None),
```

- [ ] In `DEFAULT_COMPOSITE_WEIGHTS` (around line 92), add after `"event_timing_score": 0.00`:

```python
    "price_regression_score": 0.10,  # R²-filtered OLS trend (sparse — many zeros in sideways markets)
    "arima_forecast_score": 0.05,    # ARIMA forecast (only fires in stable vol regimes)
```

**Note on weights:** Both weights are modest because these signals are sparse — regression returns 0.0 when R² < 0.6, ARIMA returns 0.0 in high-vol regimes. The cross-sectional normalizer skips fields where all scores are 0.0 (`if np.all(raw_scores == 0.0): continue`), so sparse signals are handled cleanly.

### Step 4.2 — Verify cross_sectional.py changes compile

- [ ] Run:

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -c "from quant.cross_sectional import SIGNAL_FIELDS, DEFAULT_COMPOSITE_WEIGHTS; print([f for f,_ in SIGNAL_FIELDS]); print(sum(DEFAULT_COMPOSITE_WEIGHTS.values()))"
```

Expected: `price_regression_score` and `arima_forecast_score` appear in the list. Sum of weights should be ~1.0 (with the new 0.10 + 0.05 added, adjust other weights if needed to keep sum ≤ 1.0 — weights don't need to sum to exactly 1.0 since `compute_normalized_composite` uses `total_w` to normalise).

### Step 4.3 — Add BacktestConfig flags

- [ ] In `quant/backtest.py`, after line 115 (`kalshi_event_threshold: float = 0.20`), insert:

```python
    # Price regression signal (R²-filtered OLS trend)
    enable_regression_signal: bool = False
    regression_window: int = 60
    regression_r2_threshold: float = 0.6
    # ARIMA short-term forecast signal (stable vol regimes only)
    enable_arima_signal: bool = False
    arima_vol_threshold: float = 0.25
```

### Step 4.4 — Inject raw signal values at the two active backtest sites

There are 3 places in `backtest.py` where signals are injected (single-pass, walk-forward, CPCV). The default path is **walk-forward**. Inject at both the single-pass site AND the walk-forward site. CPCV is opt-in and lower priority.

Find the two active injection sites:
```bash
grep -n 'logger.warning("Kalshi signal injection failed' /Users/chadreadey/portfolio-analyst/ai-financial-analyst/quant/backtest.py
```

This returns 3 lines. The first (~line 1895) is single-pass, the second (~line 2526) is walk-forward. Insert the following block **after each of the first two occurrences** (and after the third/CPCV one too for completeness), matching indentation exactly:

```python
            # Price regression signal (R²-filtered OLS trend)
            if config.enable_regression_signal:
                try:
                    from quant.regression_signal import compute_price_regression_scores
                    _reg_scores = compute_price_regression_scores(
                        universe_data, reb_date,
                        window=config.regression_window,
                        r2_threshold=config.regression_r2_threshold,
                    )
                    for _ticker, _score in _reg_scores.items():
                        if _ticker in signals:
                            signals[_ticker].price_regression_score = _score
                except Exception as _exc:
                    logger.warning("Regression signal injection failed: %s", _exc)

            # ARIMA short-term forecast signal (stable regimes only)
            if config.enable_arima_signal:
                try:
                    from quant.arima_signal import compute_arima_forecast_scores
                    _arima_scores = compute_arima_forecast_scores(
                        universe_data, reb_date,
                        vol_threshold=config.arima_vol_threshold,
                    )
                    for _ticker, _score in _arima_scores.items():
                        if _ticker in signals:
                            signals[_ticker].arima_forecast_score = _score
                except Exception as _exc:
                    logger.warning("ARIMA signal injection failed: %s", _exc)
```

**These blocks must appear BEFORE the `# ── Cross-sectional normalization barrier ──` comment** (lines ~1897 and ~2528). The raw scores get set here, then `normalize_signals_cross_sectionally` z-scores them cross-sectionally, then `compute_normalized_composite` weights them into the composite. No manual blending after normalization is needed.

### Step 4.5 — Verify config loads

- [ ] Run:

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -c "from quant.backtest import BacktestConfig; c = BacktestConfig(tickers=['AAPL']); print(c.enable_regression_signal, c.regression_window, c.regression_r2_threshold, c.enable_arima_signal, c.arima_vol_threshold)"
```

Expected: `False 60 0.6 False 0.25`

### Step 4.6 — Smoke test on walk-forward path (the default)

- [ ] Run a 1-year walk-forward backtest with both signals enabled:

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python scripts/run_backtest.py --tickers AAPL,MSFT,GOOGL,JPM,XOM --start 2023-01-01 --end 2024-01-01 --enable-regression --enable-arima 2>&1 | tail -15
```

Expected: completes without traceback. No "Regression signal injection failed" or "ARIMA signal injection failed" warnings. Walk-forward results printed (Sharpe, return, etc.).

- [ ] Also verify default (both disabled) still works:

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python scripts/run_backtest.py --tickers AAPL,MSFT --start 2024-01-01 --end 2024-06-01 2>&1 | tail -5
```

Expected: completes cleanly, identical results to before this change.

### Step 4.7 — Commit

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && git add quant/cross_sectional.py quant/backtest.py && git commit -m "feat: add regression + ARIMA signals to cross-sectional pipeline and backtest injection"
```

---

## Task 5: CLI flags + smoke tests

**Files:**
- Modify: `scripts/run_backtest.py`

- [ ] **Step 1: Find insertion point**

```bash
grep -n "kalshi-event-threshold" /Users/chadreadey/portfolio-analyst/ai-financial-analyst/scripts/run_backtest.py
```

After that `add_argument` block, insert:

```python
    parser.add_argument("--enable-regression", action="store_true",
                        help="Enable R²-filtered price regression trend signal (weight: 0.15)")
    parser.add_argument("--regression-window", type=int, default=60,
                        help="Rolling window in trading days for regression signal (default: 60)")
    parser.add_argument("--regression-r2", type=float, default=0.6,
                        help="Minimum R² to emit regression signal (default: 0.6)")
    parser.add_argument("--enable-arima", action="store_true",
                        help="Enable ARIMA(1,1,1) forecast signal — stable vol regimes only (weight: 0.10)")
    parser.add_argument("--arima-vol-threshold", type=float, default=0.25,
                        help="Max annualized realized vol for ARIMA to fire (default: 0.25 = 25%%)")
```

- [ ] **Step 2: Wire into BacktestConfig**

Find the `BacktestConfig(...)` constructor call. Add before the closing `)`:

```python
        enable_regression_signal=args.enable_regression,
        regression_window=args.regression_window,
        regression_r2_threshold=args.regression_r2,
        enable_arima_signal=args.enable_arima,
        arima_vol_threshold=args.arima_vol_threshold,
```

- [ ] **Step 3: Verify help text**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python scripts/run_backtest.py --help 2>&1 | grep -A1 "regression\|arima"
```

Expected: shows `--enable-regression`, `--regression-window`, `--regression-r2`, `--enable-arima`, `--arima-vol-threshold`.

- [ ] **Step 4: Smoke test — both signals enabled**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python scripts/run_backtest.py --tickers AAPL,MSFT,GOOGL,JPM,XOM --start 2024-01-01 --enable-regression --enable-arima --no-cpcv 2>&1 | tail -15
```

Expected: completes without traceback. No "Regression signal injection failed" or "ARIMA signal injection failed" warnings.

- [ ] **Step 5: Commit**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && git add scripts/run_backtest.py && git commit -m "feat: add --enable-regression and --enable-arima CLI flags"
```

---

## Risks & Mitigations

- **ARIMA is slow for large universes** — The vol gate short-circuits most fits in high-vol periods (2020, 2022). If still slow on liquid_50, add `multiprocessing.Pool` inside `compute_arima_forecast_scores()` as a future pass.
- **statsmodels emits convergence warnings** — `warnings.simplefilter("ignore")` inside the fit block suppresses them. `logger.debug` (not warning) keeps logs clean.
- **R² gate at 0.6 may suppress sideways markets** — Lower to 0.5 only if CPCV IC analysis shows positive IC at lower R². Never tune from observed backtest PnL.
- **Composite weights dilute existing signals** — Weights are additive post-normalization, clipped to [-1, 1]. Run shadow-mode backtest vs gold-standard baseline (Sharpe 1.04) before enabling on live signal stack.

## Success Criteria

- [ ] 6 regression tests pass (`--noconftest`)
- [ ] 5 ARIMA tests pass (`--noconftest`)
- [ ] `SignalVector` has both new fields with `float = 0.0` defaults
- [ ] `BacktestConfig` has all 5 new flags with correct defaults
- [ ] Both signals inject cleanly at all 3 rebalance sites (no injection failures in smoke test)
- [ ] CLI smoke test completes without traceback
- [ ] No behavioral change when both flags are `False` (default)
- [ ] 5 git commits, one per task
