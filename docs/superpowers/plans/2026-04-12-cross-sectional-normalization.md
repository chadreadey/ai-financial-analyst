# Cross-Sectional Signal Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace raw signal scores with sector-adjusted winsorized z-scores so signal ranking generalizes across any universe size.

**Architecture:** New `quant/cross_sectional.py` module with normalization + composite functions. Blend functions refactored to set individual score fields instead of modifying composite. Normalization runs once per rebalance date across all tickers, then composite is built from normalized values. All three backtest paths (walk-forward, CPCV, simple) updated.

**Tech Stack:** Python, numpy, pandas, scipy.stats (for winsorize)

---

### File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| **Create** | `quant/cross_sectional.py` | `normalize_signals_cross_sectionally()` + `compute_normalized_composite()` |
| **Create** | `tests/test_cross_sectional.py` | Unit tests for normalization and composite |
| **Modify** | `quant/signals.py:38-39` | Add `sentiment_score` field to SignalVector |
| **Modify** | `quant/earnings_signals.py:316-348` | Refactor `blend_earnings_signals` to set field only |
| **Modify** | `quant/institutional_flow.py:505-535` | Refactor `blend_institutional_flow` to set field only |
| **Modify** | `quant/backtest.py:1066-1147` | Refactor `blend_sentiment_into_signals` to set field only |
| **Modify** | `quant/backtest.py:1802-1848` | Restructure walk-forward blend chain |
| **Modify** | `quant/backtest.py:2260-2310` | Restructure CPCV blend chain |
| **Modify** | `quant/backtest.py:2590-2640` | Restructure simple backtest blend chain |

---

### Task 1: Create cross_sectional.py with normalization function

**Files:**
- Create: `quant/cross_sectional.py`
- Create: `tests/test_cross_sectional.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cross_sectional.py
"""Tests for cross-sectional signal normalization."""

import numpy as np
import pytest
from quant.signals import SignalResult, SignalVector


def _make_sv(obv=0.0, earnings=0.0, inst_flow=0.0, sentiment=0.0):
    """Helper to create a SignalVector with specified scores."""
    sv = SignalVector(
        sma_trend=SignalResult(0.0),
        mean_reversion_z=SignalResult(0.0),
        bollinger_pctb=SignalResult(0.0),
        rsi=SignalResult(0.0),
        obv_trend=SignalResult(obv),
        atr_regime=SignalResult(0.0),
    )
    sv.earnings_rank_score = earnings
    sv.institutional_flow_score = inst_flow
    sv.sentiment_score = sentiment
    return sv


class TestNormalizeSignals:
    """Test cross-sectional normalization."""

    def test_normalization_centers_scores(self):
        """After normalization, mean of each signal should be near zero."""
        from quant.cross_sectional import normalize_signals_cross_sectionally

        signals = {
            "AAPL": _make_sv(obv=0.8, earnings=0.5),
            "MSFT": _make_sv(obv=0.6, earnings=0.3),
            "GOOGL": _make_sv(obv=0.7, earnings=0.4),
            "JPM": _make_sv(obv=0.2, earnings=0.1),
            "BAC": _make_sv(obv=0.1, earnings=0.0),
            "GS": _make_sv(obv=0.3, earnings=0.2),
            "XOM": _make_sv(obv=-0.1, earnings=-0.2),
            "CVX": _make_sv(obv=-0.2, earnings=-0.1),
            "KO": _make_sv(obv=0.0, earnings=0.1),
            "PG": _make_sv(obv=0.1, earnings=0.0),
        }

        sector_fn = lambda t: {
            "AAPL": "Tech", "MSFT": "Tech", "GOOGL": "Tech",
            "JPM": "Financials", "BAC": "Financials", "GS": "Financials",
            "XOM": "Energy", "CVX": "Energy",
            "KO": "Staples", "PG": "Staples",
        }[t]

        result = normalize_signals_cross_sectionally(signals, sector_fn)

        # Mean of OBV scores should be near zero after normalization
        obv_scores = [sv.obv_trend.score for sv in result.values()]
        assert abs(np.mean(obv_scores)) < 0.15  # approximately centered

    def test_sector_adjustment_reranks(self):
        """A standout in a low-scoring sector should rank above average in a high-scoring sector."""
        from quant.cross_sectional import normalize_signals_cross_sectionally

        signals = {
            "AAPL": _make_sv(obv=0.35),  # average for tech
            "MSFT": _make_sv(obv=0.40),  # average for tech
            "GOOGL": _make_sv(obv=0.30),  # average for tech
            "DUK": _make_sv(obv=0.25),   # standout for utilities
            "SO": _make_sv(obv=0.05),    # average for utilities
            "AEP": _make_sv(obv=0.00),   # average for utilities
            "JPM": _make_sv(obv=0.10),   # filler
            "BAC": _make_sv(obv=0.15),   # filler
            "KO": _make_sv(obv=0.05),    # filler
            "PG": _make_sv(obv=0.00),    # filler
        }

        sector_fn = lambda t: {
            "AAPL": "Tech", "MSFT": "Tech", "GOOGL": "Tech",
            "DUK": "Utilities", "SO": "Utilities", "AEP": "Utilities",
            "JPM": "Financials", "BAC": "Financials",
            "KO": "Staples", "PG": "Staples",
        }[t]

        result = normalize_signals_cross_sectionally(signals, sector_fn)

        # DUK (standout utility) should score higher than AAPL (average tech)
        duk_obv = result["DUK"].obv_trend.score
        aapl_obv = result["AAPL"].obv_trend.score
        assert duk_obv > aapl_obv, f"DUK ({duk_obv:.3f}) should outrank AAPL ({aapl_obv:.3f})"

    def test_scores_bounded(self):
        """Normalized scores should be in [-1, +1]."""
        from quant.cross_sectional import normalize_signals_cross_sectionally

        signals = {
            f"T{i}": _make_sv(obv=float(i) / 10 - 0.5)
            for i in range(15)
        }

        result = normalize_signals_cross_sectionally(signals, lambda t: "Same")

        for sv in result.values():
            assert -1.0 <= sv.obv_trend.score <= 1.0

    def test_skip_if_too_few_tickers(self):
        """With < 10 tickers, normalization should be skipped (raw scores preserved)."""
        from quant.cross_sectional import normalize_signals_cross_sectionally

        signals = {
            "AAPL": _make_sv(obv=0.8),
            "MSFT": _make_sv(obv=0.2),
        }

        result = normalize_signals_cross_sectionally(signals, lambda t: "Tech")

        # Scores should be unchanged
        assert result["AAPL"].obv_trend.score == 0.8
        assert result["MSFT"].obv_trend.score == 0.2


class TestComputeNormalizedComposite:
    """Test composite construction from normalized signals."""

    def test_weighted_average(self):
        from quant.cross_sectional import compute_normalized_composite

        sv = _make_sv(obv=0.8, earnings=0.4, inst_flow=0.2, sentiment=0.1)

        weights = {
            "obv_trend": 0.40,
            "earnings_rank_score": 0.30,
            "institutional_flow_score": 0.15,
            "sentiment_score": 0.10,
        }

        score = compute_normalized_composite(sv, weights)

        # (0.8*0.40 + 0.4*0.30 + 0.2*0.15 + 0.1*0.10) / (0.40+0.30+0.15+0.10)
        # = (0.32 + 0.12 + 0.03 + 0.01) / 0.95 = 0.48 / 0.95 = 0.505
        assert abs(score - 0.505) < 0.01

    def test_composite_clipped(self):
        from quant.cross_sectional import compute_normalized_composite

        sv = _make_sv(obv=1.0, earnings=1.0, inst_flow=1.0, sentiment=1.0)

        weights = {
            "obv_trend": 0.40,
            "earnings_rank_score": 0.30,
            "institutional_flow_score": 0.15,
            "sentiment_score": 0.10,
        }

        score = compute_normalized_composite(sv, weights)
        assert score <= 1.0

    def test_missing_signals_handled(self):
        """Signals with 0.0 score (no data) should not distort composite."""
        from quant.cross_sectional import compute_normalized_composite

        sv = _make_sv(obv=0.6, earnings=0.0, inst_flow=0.0, sentiment=0.0)

        weights = {
            "obv_trend": 0.40,
            "earnings_rank_score": 0.30,
            "institutional_flow_score": 0.15,
            "sentiment_score": 0.10,
        }

        score = compute_normalized_composite(sv, weights)
        # Only OBV has signal, so composite should reflect that
        # (0.6*0.40 + 0*0.30 + 0*0.15 + 0*0.10) / 0.95 = 0.253
        assert abs(score - 0.253) < 0.01
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3.13 -m pytest tests/test_cross_sectional.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quant.cross_sectional'`

- [ ] **Step 3: Implement cross_sectional.py**

```python
# quant/cross_sectional.py
"""
Cross-sectional signal normalization.

Converts raw signal scores to sector-adjusted winsorized z-scores
so that signals generalize across any universe size. A utility stock's
exceptional OBV reading outranks a tech stock's average OBV reading.

Algorithm per signal per rebalance date:
1. Collect raw scores across all tickers
2. Subtract sector mean (sector-relative adjustment)
3. Winsorize at 2.5th / 97.5th percentile
4. Z-score (mean=0, std=1)
5. Scale to [-1, +1] via clip(z / 3.0)
"""

from __future__ import annotations

import logging
from typing import Callable

import numpy as np

from quant.signals import SignalResult, SignalVector

logger = logging.getLogger(__name__)

# Minimum cross-section size for meaningful normalization
MIN_CROSS_SECTION = 10

# Winsorization percentiles
WINSORIZE_LOW = 2.5
WINSORIZE_HIGH = 97.5

# Signal fields to normalize and how to read/write them
SIGNAL_FIELDS = [
    ("obv_trend", "score"),          # SignalResult — access .score
    ("earnings_rank_score", None),    # float field directly
    ("institutional_flow_score", None),
    ("sentiment_score", None),
]

# Default composite weights (normalized, not cumulative)
DEFAULT_COMPOSITE_WEIGHTS = {
    "obv_trend": 0.40,
    "earnings_rank_score": 0.30,
    "institutional_flow_score": 0.15,
    "sentiment_score": 0.10,
}


def _get_signal_score(sv: SignalVector, field_name: str, sub_attr: str | None) -> float:
    """Read a signal score from a SignalVector."""
    val = getattr(sv, field_name, 0.0)
    if sub_attr is not None and isinstance(val, SignalResult):
        return val.score
    if isinstance(val, (int, float)):
        return float(val)
    return 0.0


def _set_signal_score(sv: SignalVector, field_name: str, sub_attr: str | None, value: float) -> None:
    """Write a normalized signal score back to a SignalVector."""
    if sub_attr is not None:
        sr = getattr(sv, field_name)
        if isinstance(sr, SignalResult):
            sr.score = value
    else:
        setattr(sv, field_name, value)


def _winsorize(arr: np.ndarray, low_pct: float = 2.5, high_pct: float = 97.5) -> np.ndarray:
    """Winsorize array at given percentiles."""
    low = np.percentile(arr, low_pct)
    high = np.percentile(arr, high_pct)
    return np.clip(arr, low, high)


def normalize_signals_cross_sectionally(
    signals: dict[str, SignalVector],
    sector_fn: Callable[[str], str],
) -> dict[str, SignalVector]:
    """
    Normalize all active signals cross-sectionally with sector adjustment.

    For each signal:
    1. Subtract sector mean from each ticker's raw score
    2. Winsorize the adjusted scores at 2.5th/97.5th percentile
    3. Z-score the result
    4. Scale to [-1, +1] by dividing by 3 and clipping

    Modifies SignalVectors in-place and returns the same dict.
    Skips normalization if fewer than MIN_CROSS_SECTION tickers.
    """
    tickers = list(signals.keys())
    n = len(tickers)

    if n < MIN_CROSS_SECTION:
        logger.debug("Cross-section too small (%d < %d) — skipping normalization", n, MIN_CROSS_SECTION)
        return signals

    # Get sector for each ticker
    sectors = {t: sector_fn(t) for t in tickers}

    for field_name, sub_attr in SIGNAL_FIELDS:
        # 1. Collect raw scores
        raw_scores = np.array([_get_signal_score(signals[t], field_name, sub_attr) for t in tickers])

        # Skip if all scores are zero (signal not active)
        if np.all(raw_scores == 0.0):
            continue

        # 2. Subtract sector mean
        sector_means = {}
        for i, t in enumerate(tickers):
            sec = sectors[t]
            if sec not in sector_means:
                sec_mask = np.array([sectors[tt] == sec for tt in tickers])
                sector_means[sec] = np.mean(raw_scores[sec_mask])

        adjusted = np.array([raw_scores[i] - sector_means[sectors[t]] for i, t in enumerate(tickers)])

        # 3. Winsorize
        adjusted = _winsorize(adjusted, WINSORIZE_LOW, WINSORIZE_HIGH)

        # 4. Z-score
        std = np.std(adjusted)
        if std < 1e-8:
            # All scores identical after adjustment — set to zero
            normalized = np.zeros(n)
        else:
            mean = np.mean(adjusted)
            normalized = (adjusted - mean) / std

        # 5. Scale to [-1, +1]
        normalized = np.clip(normalized / 3.0, -1.0, 1.0)

        # 6. Write back
        for i, t in enumerate(tickers):
            _set_signal_score(signals[t], field_name, sub_attr, float(normalized[i]))

    return signals


def compute_normalized_composite(
    sv: SignalVector,
    weights: dict[str, float] | None = None,
) -> float:
    """
    Build composite score from (normalized) signal fields.

    Uses weighted average of available signals. Signals with 0.0 score
    still contribute (they may be genuinely neutral after normalization).
    """
    if weights is None:
        weights = DEFAULT_COMPOSITE_WEIGHTS

    total = 0.0
    total_w = 0.0

    for signal_name, weight in weights.items():
        val = getattr(sv, signal_name, 0.0)
        if isinstance(val, SignalResult):
            score = val.score
        elif isinstance(val, (int, float)):
            score = float(val)
        else:
            score = 0.0

        total += score * weight
        total_w += weight

    if total_w > 0:
        return float(np.clip(total / total_w, -1.0, 1.0))
    return 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3.13 -m pytest tests/test_cross_sectional.py -v`
Expected: ALL PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add quant/cross_sectional.py tests/test_cross_sectional.py
git commit -m "feat: add cross-sectional normalization module"
```

---

### Task 2: Add sentiment_score field to SignalVector

**Files:**
- Modify: `quant/signals.py:38-39`

- [ ] **Step 1: Add the field**

In `quant/signals.py`, after line 39 (`institutional_flow_score: float = 0.0`), add:

```python
    sentiment_score: float = 0.0  # Set by sentiment blend for cross-sectional normalization
```

- [ ] **Step 2: Verify**

Run: `python3.13 -c "from quant.signals import SignalVector, SignalResult; sv = SignalVector(sma_trend=SignalResult(0.0), mean_reversion_z=SignalResult(0.0), bollinger_pctb=SignalResult(0.0), rsi=SignalResult(0.0), obv_trend=SignalResult(0.0), atr_regime=SignalResult(0.0)); print(f'sentiment_score={sv.sentiment_score}')"`
Expected: `sentiment_score=0.0`

- [ ] **Step 3: Commit**

```bash
git add quant/signals.py
git commit -m "feat: add sentiment_score field to SignalVector"
```

---

### Task 3: Refactor blend functions to set fields instead of modifying composite

**Files:**
- Modify: `quant/earnings_signals.py:316-348`
- Modify: `quant/institutional_flow.py:505-535`
- Modify: `quant/backtest.py:1066-1147` (blend_sentiment_into_signals)

This task changes three blend functions to **set their individual score fields** instead of directly modifying `composite_score`. The composite will be built later by `compute_normalized_composite`.

- [ ] **Step 1: Refactor blend_earnings_signals**

In `quant/earnings_signals.py`, replace the `blend_earnings_signals` function (lines 316-348) with:

```python
def blend_earnings_signals(
    signals: dict,
    earnings_scores: dict[str, tuple[float, int, dict]],
    weight: float = 0.30,
) -> dict:
    """
    Set earnings signal scores on SignalVectors for cross-sectional normalization.

    No longer modifies composite_score directly — just stores the blended
    earnings score on sv.earnings_rank_score. Composite is built later
    by compute_normalized_composite after cross-sectional normalization.
    """
    if not earnings_scores:
        return signals

    for ticker, sv in signals.items():
        entry = earnings_scores.get(ticker)
        if entry is None:
            continue

        score, n_signals, meta = entry
        sv.earnings_rank_score = score
        sv.flags.append(f"earnings(n={n_signals},src=wrds_ibes)")

    return signals
```

- [ ] **Step 2: Refactor blend_institutional_flow**

In `quant/institutional_flow.py`, replace the `blend_institutional_flow` function (around line 505) with:

```python
def blend_institutional_flow(
    signals: dict,
    flow_scores: dict[str, tuple[float, dict]],
    weight: float = 0.15,
) -> dict:
    """
    Set institutional flow scores on SignalVectors for cross-sectional normalization.

    No longer modifies composite_score directly — just stores the flow
    score on sv.institutional_flow_score. Composite is built later
    by compute_normalized_composite after cross-sectional normalization.
    """
    if not flow_scores:
        return signals

    for ticker, sv in signals.items():
        entry = flow_scores.get(ticker)
        if entry is None:
            continue

        score, meta = entry
        sv.institutional_flow_score = score

        n_inst = meta.get("n_institutions", 0)
        src = meta.get("data_source", "unknown")
        sv.flags.append(f"inst_flow(n={n_inst},src={src})")

    return signals
```

- [ ] **Step 3: Refactor blend_sentiment_into_signals**

In `quant/backtest.py`, replace the `blend_sentiment_into_signals` function (lines 1066-1147) with:

```python
def blend_sentiment_into_signals(
    signals: dict[str, SignalVector],
    sentiment_scores: dict[str, tuple[float, int]],
    sentiment_weight: float = 0.10,
) -> dict[str, SignalVector]:
    """
    Set sentiment scores on SignalVectors for cross-sectional normalization.

    Applies coverage and regime scaling to the raw sentiment score, then
    stores on sv.sentiment_score. No longer modifies composite_score.
    """
    if not sentiment_scores:
        return signals

    for ticker, sv in signals.items():
        entry = sentiment_scores.get(ticker)
        if entry is None:
            continue

        score, n_articles = entry

        # Coverage scaling: sparse news → reduced confidence
        coverage_scale = min(1.0, n_articles / _SENTIMENT_COVERAGE_FULL)

        # Regime scaling: noisy in high-vol environments
        vol_regime = sv.atr_regime.metadata.get("volatility_regime", "normal")
        regime_scale = _SENTIMENT_HIGH_VOL_SCALE if vol_regime == "high_vol" else 1.0

        effective_scale = coverage_scale * regime_scale

        if effective_scale < 1e-6:
            sv.flags.append(
                f"sentiment_suppressed(articles={n_articles},regime={vol_regime})"
            )
            continue

        # Scale the raw sentiment score by coverage/regime confidence
        sv.sentiment_score = score * effective_scale

        sv.flags.append(
            f"sentiment(cov={coverage_scale:.2f},regime={vol_regime})"
        )

    return signals
```

- [ ] **Step 4: Run all tests**

Run: `python3.13 -m pytest tests/test_institutional_flow.py tests/test_cross_sectional.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add quant/earnings_signals.py quant/institutional_flow.py quant/backtest.py
git commit -m "refactor: blend functions set score fields instead of modifying composite"
```

---

### Task 4: Wire normalization + composite into the walk-forward blend chain

**Files:**
- Modify: `quant/backtest.py:1802-1862`

The walk-forward rebalance loop currently runs blends sequentially, each modifying `composite_score`. Replace the section after all blends with the normalization barrier and composite recomputation.

- [ ] **Step 1: Replace the blend chain section**

In `quant/backtest.py`, find the section starting at the sentiment blend (around line 1802) through the FOMC boost (around line 1861). Replace the entire block from `# Sentiment overlay` through the institutional flow blend (ending around line 1848) with:

After the existing IC calibration and LSTM blends (which stay as-is), add:

```python
        # ── Signal scoring (set fields, no composite modification) ──
        # Sentiment overlay
        if config.enable_news_sentiment and (_finnhub_client is not None or _sentiment_cache is not None):
            sent_scores = compute_sentiment_scores(
                universe_data, reb_date, config,
                client=_finnhub_client, disk_cache=_sentiment_cache,
            )
            if sent_scores:
                signals = blend_sentiment_into_signals(
                    signals, sent_scores, config.news_sentiment_weight,
                )

        # Earnings signals (sets earnings_rank_score)
        if config.enable_earnings_signals and _wrds_provider is not None:
            from quant.earnings_signals import compute_earnings_signal_scores, blend_earnings_signals
            earn_scores = compute_earnings_signal_scores(
                list(signals.keys()), _wrds_provider,
                as_of_date=reb_date.date(),
            )
            if earn_scores:
                signals = blend_earnings_signals(signals, earn_scores, config.earnings_signal_weight)

        # Institutional flow (sets institutional_flow_score)
        if config.enable_institutional_flow:
            from quant.institutional_flow import compute_institutional_flow_scores, blend_institutional_flow
            inst_scores = compute_institutional_flow_scores(
                list(signals.keys()),
                as_of_date=reb_date.date(),
                wrds_store=_inst_wrds_store,
                fmp_client=_fmp_client,
                fmp_cache=_inst_fmp_cache,
                finnhub_client=_finnhub_client,
                finnhub_disk_cache=_sentiment_cache,
            )
            if inst_scores:
                signals = blend_institutional_flow(signals, inst_scores, config.institutional_flow_weight)

        # ── Cross-sectional normalization barrier ──
        from quant.cross_sectional import normalize_signals_cross_sectionally, compute_normalized_composite
        from quant.universe import get_sector
        signals = normalize_signals_cross_sectionally(signals, get_sector)

        # Recompute composite from normalized signals
        from quant.scoring import reclassify
        for sv in signals.values():
            sv.composite_score = compute_normalized_composite(sv)
            reclassify(sv)
```

Keep the FOMC boost and regime filter code that follows unchanged.

IMPORTANT: Also remove the `# Fundamental overlay` block if present between sentiment and earnings — it's disabled in the current config and would conflict with the new pipeline.

- [ ] **Step 2: Verify walk-forward imports work**

Run: `python3.13 -c "from quant.backtest import run_walk_forward; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add quant/backtest.py
git commit -m "feat: wire normalization into walk-forward blend chain"
```

---

### Task 5: Wire normalization into CPCV and simple backtest blend chains

**Files:**
- Modify: `quant/backtest.py:2260-2310` (CPCV)
- Modify: `quant/backtest.py:2590-2640` (simple backtest)

Apply the same pattern as Task 4 to the other two backtest paths. After each blend chain, add:

```python
            # ── Cross-sectional normalization barrier ──
            from quant.cross_sectional import normalize_signals_cross_sectionally, compute_normalized_composite
            from quant.universe import get_sector
            signals = normalize_signals_cross_sectionally(signals, get_sector)

            from quant.scoring import reclassify
            for sv in signals.values():
                sv.composite_score = compute_normalized_composite(sv)
                reclassify(sv)
```

- [ ] **Step 1: Update CPCV blend chain**

Find the CPCV section (around line 2260-2310). After the institutional flow blend, add the normalization barrier block above. Match the indentation (12 spaces in CPCV).

- [ ] **Step 2: Update simple backtest blend chain**

Find the simple backtest section (around line 2590-2640). Same change. Match the indentation (12 spaces).

- [ ] **Step 3: Verify all paths parse**

Run: `python3.13 -c "from quant.backtest import run_walk_forward, run_cpcv; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add quant/backtest.py
git commit -m "feat: wire normalization into CPCV and simple backtest paths"
```

---

### Task 6: Run tests and validate end-to-end

**Files:**
- All modified files

- [ ] **Step 1: Run full test suite**

Run: `python3.13 -m pytest tests/test_cross_sectional.py tests/test_institutional_flow.py -v`
Expected: ALL PASS

- [ ] **Step 2: Verify imports**

Run: `python3.13 -c "
from quant.cross_sectional import normalize_signals_cross_sectionally, compute_normalized_composite
from quant.backtest import BacktestConfig
print('All imports OK')
"`
Expected: `All imports OK`

- [ ] **Step 3: Run walk-forward on liquid_50**

Run: `python3.13 scripts/run_phase0.py --universe liquid_50 --start 2014-01-01 --enable-institutional-flow --institutional-flow-weight 0.15 --skip-cpcv --skip-redundancy`

Capture: Sharpe, FF5 alpha, t-stat, total return, raw alpha vs SPY

- [ ] **Step 4: Run walk-forward on liquid_100**

Run: `python3.13 scripts/run_phase0.py --universe liquid_100 --start 2014-01-01 --enable-institutional-flow --institutional-flow-weight 0.15 --skip-cpcv --skip-redundancy`

Capture same metrics. Compare gap between liquid_50 and liquid_100.

- [ ] **Step 5: Commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address issues found in end-to-end validation"
```
