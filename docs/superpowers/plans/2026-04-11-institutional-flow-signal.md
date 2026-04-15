# 13F Institutional Flow Signal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 13F institutional flow signal (FMP + Finnhub) to the quant backtest pipeline and validate it through Phase 0 diagnostics.

**Architecture:** New `quant/institutional_flow.py` module with two data fetchers (FMP historical institutional holders, Finnhub institutional ownership) and one scorer that computes QoQ holder count change, shares flow, and buyer/seller ratio. Blends into composite at 0.15 weight following the same pattern as `blend_earnings_signals`. Cached via `FMPFundamentalCache` (SQLite) and `SentimentDiskCache` (JSON files). Integrated into all three backtest paths (walk-forward, CPCV, simple) and Phase 0 redundancy/IC diagnostics.

**Tech Stack:** Python, pandas, numpy, FMP REST API, Finnhub REST API, SQLite cache, existing backtest framework

---

### File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| **Create** | `quant/institutional_flow.py` | FMP/Finnhub fetchers, scoring, blending |
| **Create** | `tests/test_institutional_flow.py` | Unit tests for scoring + blending logic |
| **Modify** | `fmp_client.py` | Add `get_institutional_ownership_history()` method |
| **Modify** | `finnhub_client.py` | Add `get_institutional_ownership()` method + cache support |
| **Modify** | `quant/backtest.py:39-100` | Add `enable_institutional_flow` config fields |
| **Modify** | `quant/backtest.py:1808-1816` | Wire blend into walk-forward rebalance loop |
| **Modify** | `quant/backtest.py:2217-2225` | Wire blend into CPCV rebalance loop |
| **Modify** | `quant/backtest.py:2530-2538` | Wire blend into simple backtest rebalance loop |
| **Modify** | `quant/backtest.py:1960-2019` | Auto-init FMP client for institutional flow |
| **Modify** | `quant/redundancy.py:26-28` | Add `institutional_flow` to SIGNAL_NAMES |
| **Modify** | `quant/redundancy.py:31-69` | Include institutional_flow in `compute_signal_scores_at_date` |
| **Modify** | `quant/signals.py:25-39` | Add `institutional_flow_score` field to SignalVector |
| **Modify** | `scripts/run_phase0.py:105-123` | Add `--enable-institutional-flow` flag and config wiring |
| **Modify** | `quant/fmp_cache.py` | Add `get_institutional_quarterly()` / `set_institutional_quarterly()` methods |

---

### Task 1: Add FMP institutional ownership endpoint

**Files:**
- Modify: `fmp_client.py:166-168`
- Modify: `fmp_client.py:171-188` (FMPCache class)
- Test: `tests/test_institutional_flow.py`

- [ ] **Step 1: Write the failing test for the FMP endpoint**

```python
# tests/test_institutional_flow.py
"""Tests for institutional flow signal."""

import pytest
from unittest.mock import MagicMock, patch


class TestFMPInstitutionalOwnership:
    """Test FMP institutional ownership endpoint."""

    def test_get_institutional_ownership_history_returns_list(self):
        """FMP client should return list of quarterly snapshots."""
        from fmp_client import FMPClient

        mock_response = [
            {
                "date": "2025-12-31",
                "investorName": "Vanguard Group",
                "sharesNumber": 1_200_000_000,
                "sharesNumberChange": 50_000_000,
                "ownershipPercent": 8.5,
                "typeOfOwner": "Investment Advisor",
            },
            {
                "date": "2025-12-31",
                "investorName": "BlackRock",
                "sharesNumber": 1_000_000_000,
                "sharesNumberChange": -20_000_000,
                "ownershipPercent": 7.1,
                "typeOfOwner": "Investment Advisor",
            },
        ]

        client = FMPClient("test-key")
        with patch.object(client, "_get", return_value=mock_response):
            result = client.get_institutional_ownership_history("AAPL")

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["investorName"] == "Vanguard Group"
        assert result[0]["sharesNumberChange"] == 50_000_000

    def test_get_institutional_ownership_history_handles_error(self):
        """Should return empty list on API error."""
        from fmp_client import FMPClient

        client = FMPClient("test-key")
        with patch.object(client, "_get", side_effect=Exception("API error")):
            result = client.get_institutional_ownership_history("AAPL")

        assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -m pytest tests/test_institutional_flow.py::TestFMPInstitutionalOwnership -v`
Expected: FAIL with `AttributeError: 'FMPClient' object has no attribute 'get_institutional_ownership_history'`

- [ ] **Step 3: Implement FMP endpoint**

In `fmp_client.py`, replace the stub `get_institutional_holders` at line 166-168:

```python
    def get_institutional_holders(self, symbol: str) -> list[dict]:
        """Not available on free/starter FMP plans — returns [] gracefully."""
        return []

    def get_institutional_ownership_history(self, symbol: str) -> list[dict]:
        """
        Fetch institutional ownership snapshots from FMP.

        FMP endpoint: /stable/institutional-ownership/symbol-ownership
        Returns list of dicts with keys:
            date, investorName, sharesNumber, sharesNumberChange,
            ownershipPercent, typeOfOwner
        """
        try:
            data = self._get(
                "/stable/institutional-ownership/symbol-ownership",
                {"symbol": symbol},
            )
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.debug("fmp institutional-ownership/%s failed: %s", symbol, exc, exc_info=True)
            return []
```

Also add to `FMPCache` class (after `_holders_cache` at line 188):

```python
        self._inst_ownership_cache: Dict[str, list] = {}
```

And add the cached method (after `get_institutional_holders` method in FMPCache):

```python
    def get_institutional_ownership_history(self, symbol: str) -> list[dict]:
        sym = symbol.upper()
        with self._lock:
            if sym in self._inst_ownership_cache:
                return self._inst_ownership_cache[sym]
        result = self._client.get_institutional_ownership_history(sym)
        with self._lock:
            self._inst_ownership_cache[sym] = result
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -m pytest tests/test_institutional_flow.py::TestFMPInstitutionalOwnership -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst
git add fmp_client.py tests/test_institutional_flow.py
git commit -m "feat: add FMP institutional ownership history endpoint"
```

---

### Task 2: Add Finnhub institutional ownership endpoint

**Files:**
- Modify: `finnhub_client.py:38-63` (FinnhubClient class)
- Modify: `finnhub_client.py:228-248` (SentimentDiskCache class)
- Test: `tests/test_institutional_flow.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_institutional_flow.py`:

```python
class TestFinnhubInstitutionalOwnership:
    """Test Finnhub institutional ownership endpoint."""

    def test_get_institutional_ownership_returns_list(self):
        from finnhub_client import FinnhubClient

        mock_response = {
            "data": [
                {
                    "name": "Vanguard Group",
                    "share": 1_200_000_000,
                    "change": 50_000_000,
                    "filingDate": "2025-11-14",
                    "ownership": 8.5,
                },
                {
                    "name": "BlackRock",
                    "share": 1_000_000_000,
                    "change": -20_000_000,
                    "filingDate": "2025-11-14",
                    "ownership": 7.1,
                },
            ],
            "symbol": "AAPL",
        }

        client = FinnhubClient("test-key")
        with patch.object(client, "_get", return_value=mock_response):
            result = client.get_institutional_ownership("AAPL")

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["name"] == "Vanguard Group"

    def test_get_institutional_ownership_handles_error(self):
        from finnhub_client import FinnhubClient

        client = FinnhubClient("test-key")
        with patch.object(client, "_get", side_effect=Exception("API error")):
            result = client.get_institutional_ownership("AAPL")

        assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -m pytest tests/test_institutional_flow.py::TestFinnhubInstitutionalOwnership -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement Finnhub endpoint**

Add to `FinnhubClient` class in `finnhub_client.py` (after `get_earnings_surprises` at ~line 170):

```python
    def get_institutional_ownership(self, symbol: str) -> list[dict]:
        """
        Fetch institutional ownership data from Finnhub.

        Endpoint: /institutional-ownership
        Returns list of dicts with keys:
            name, share, change, filingDate, ownership
        """
        try:
            data = self._get(
                "institutional-ownership",
                {"symbol": symbol.upper()},
            )
            return data.get("data", []) if isinstance(data, dict) else []
        except Exception as exc:
            logger.debug("finnhub institutional-ownership/%s failed: %s", symbol, exc)
            return []
```

Also add to the `SentimentDiskCache` class — a method to cache institutional data:

```python
    def get_institutional(self, ticker: str, quarter: str) -> list[dict] | None:
        """Load cached institutional ownership for a ticker+quarter."""
        path = os.path.join(self._dir, f"inst_{ticker}_{quarter}.json")
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
        return None

    def set_institutional(self, ticker: str, quarter: str, data: list[dict]) -> None:
        """Cache institutional ownership for a ticker+quarter."""
        path = os.path.join(self._dir, f"inst_{ticker}_{quarter}.json")
        with open(path, "w") as f:
            json.dump(data, f)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -m pytest tests/test_institutional_flow.py::TestFinnhubInstitutionalOwnership -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst
git add finnhub_client.py tests/test_institutional_flow.py
git commit -m "feat: add Finnhub institutional ownership endpoint + cache"
```

---

### Task 3: Add FMP fundamental cache methods for institutional data

**Files:**
- Modify: `quant/fmp_cache.py`
- Test: `tests/test_institutional_flow.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_institutional_flow.py`:

```python
import tempfile
import os


class TestFMPFundamentalCacheInstitutional:
    """Test FMP cache methods for institutional data."""

    def test_round_trip_institutional_data(self):
        from quant.fmp_cache import FMPFundamentalCache

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_cache.db")
            cache = FMPFundamentalCache(db_path=db_path)

            test_data = [
                {"date": "2025-12-31", "investorName": "Vanguard", "sharesNumber": 1_000_000},
                {"date": "2025-12-31", "investorName": "BlackRock", "sharesNumber": 800_000},
            ]

            cache.set_institutional_quarterly("AAPL", test_data)
            result = cache.get_institutional_quarterly("AAPL")

            assert result is not None
            assert len(result) == 2
            assert result[0]["investorName"] == "Vanguard"

    def test_get_institutional_returns_none_when_missing(self):
        from quant.fmp_cache import FMPFundamentalCache

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_cache.db")
            cache = FMPFundamentalCache(db_path=db_path)

            result = cache.get_institutional_quarterly("MISSING")
            assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -m pytest tests/test_institutional_flow.py::TestFMPFundamentalCacheInstitutional -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Implement cache methods**

Add to `FMPFundamentalCache` class in `quant/fmp_cache.py` (after existing getter/setter methods):

```python
    def get_institutional_quarterly(self, ticker: str, max_age_seconds: float = -1) -> Optional[list[dict]]:
        """Get cached institutional ownership data."""
        return self._get(ticker, "institutional_q", max_age_seconds)

    def set_institutional_quarterly(self, ticker: str, data: list[dict]) -> None:
        """Cache institutional ownership data."""
        self._set(ticker, "institutional_q", data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -m pytest tests/test_institutional_flow.py::TestFMPFundamentalCacheInstitutional -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst
git add quant/fmp_cache.py tests/test_institutional_flow.py
git commit -m "feat: add institutional data methods to FMP cache"
```

---

### Task 4: Implement institutional flow scoring module

**Files:**
- Create: `quant/institutional_flow.py`
- Test: `tests/test_institutional_flow.py`

- [ ] **Step 1: Write the failing tests for scoring logic**

Append to `tests/test_institutional_flow.py`:

```python
import numpy as np
import pandas as pd


class TestComputeInstitutionalFlowScore:
    """Test the core scoring function."""

    def test_strong_buying_returns_positive_score(self):
        from quant.institutional_flow import compute_institutional_flow_score

        # 10 institutions, 8 buying, 1 selling, 1 unchanged
        current_snapshot = [
            {"investorName": f"Fund{i}", "sharesNumber": 1_000_000 + i * 100_000,
             "sharesNumberChange": 100_000}
            for i in range(8)
        ] + [
            {"investorName": "Seller1", "sharesNumber": 500_000, "sharesNumberChange": -50_000},
            {"investorName": "Flat1", "sharesNumber": 300_000, "sharesNumberChange": 0},
        ]
        prior_snapshot = [
            {"investorName": f"Fund{i}", "sharesNumber": 1_000_000 + i * 100_000 - 100_000,
             "sharesNumberChange": 0}
            for i in range(8)
        ] + [
            {"investorName": "Seller1", "sharesNumber": 550_000, "sharesNumberChange": 0},
            {"investorName": "Flat1", "sharesNumber": 300_000, "sharesNumberChange": 0},
        ]

        score, meta = compute_institutional_flow_score(
            current_snapshot=current_snapshot,
            prior_snapshot=prior_snapshot,
        )

        assert -1.0 <= score <= 1.0
        assert score > 0.3, f"Expected positive score for net buying, got {score}"
        assert meta["n_buying"] == 8
        assert meta["n_selling"] == 1

    def test_strong_selling_returns_negative_score(self):
        from quant.institutional_flow import compute_institutional_flow_score

        current_snapshot = [
            {"investorName": f"Fund{i}", "sharesNumber": 500_000,
             "sharesNumberChange": -200_000}
            for i in range(8)
        ] + [
            {"investorName": "Buyer1", "sharesNumber": 600_000, "sharesNumberChange": 50_000},
            {"investorName": "Flat1", "sharesNumber": 300_000, "sharesNumberChange": 0},
        ]
        prior_snapshot = [
            {"investorName": f"Fund{i}", "sharesNumber": 700_000, "sharesNumberChange": 0}
            for i in range(8)
        ] + [
            {"investorName": "Buyer1", "sharesNumber": 550_000, "sharesNumberChange": 0},
            {"investorName": "Flat1", "sharesNumber": 300_000, "sharesNumberChange": 0},
        ]

        score, meta = compute_institutional_flow_score(
            current_snapshot=current_snapshot,
            prior_snapshot=prior_snapshot,
        )

        assert -1.0 <= score <= 1.0
        assert score < -0.3, f"Expected negative score for net selling, got {score}"
        assert meta["n_selling"] == 8

    def test_insufficient_data_returns_zero(self):
        from quant.institutional_flow import compute_institutional_flow_score

        score, meta = compute_institutional_flow_score(
            current_snapshot=[{"investorName": "Solo", "sharesNumber": 100, "sharesNumberChange": 10}],
            prior_snapshot=[],
        )

        assert score == 0.0
        assert "insufficient" in meta.get("error", "").lower() or meta.get("n_institutions", 0) < 3

    def test_empty_snapshots_returns_zero(self):
        from quant.institutional_flow import compute_institutional_flow_score

        score, meta = compute_institutional_flow_score(
            current_snapshot=[],
            prior_snapshot=[],
        )
        assert score == 0.0


class TestBlendInstitutionalFlow:
    """Test blending institutional flow into composite scores."""

    def test_blend_adjusts_composite_score(self):
        from quant.institutional_flow import blend_institutional_flow
        from quant.signals import SignalResult, SignalVector

        sv = SignalVector(
            sma_trend=SignalResult(0.0),
            mean_reversion_z=SignalResult(0.0),
            bollinger_pctb=SignalResult(0.0),
            rsi=SignalResult(0.0),
            obv_trend=SignalResult(0.5),
            atr_regime=SignalResult(0.0),
        )
        sv.composite_score = 0.5

        signals = {"AAPL": sv}
        flow_scores = {"AAPL": (0.8, {"n_institutions": 50})}

        result = blend_institutional_flow(signals, flow_scores, weight=0.15)

        # composite = 0.5 * 0.85 + 0.8 * 0.15 = 0.425 + 0.12 = 0.545
        assert abs(result["AAPL"].composite_score - 0.545) < 0.01

    def test_blend_skips_missing_tickers(self):
        from quant.institutional_flow import blend_institutional_flow
        from quant.signals import SignalResult, SignalVector

        sv = SignalVector(
            sma_trend=SignalResult(0.0),
            mean_reversion_z=SignalResult(0.0),
            bollinger_pctb=SignalResult(0.0),
            rsi=SignalResult(0.0),
            obv_trend=SignalResult(0.5),
            atr_regime=SignalResult(0.0),
        )
        sv.composite_score = 0.5

        signals = {"AAPL": sv}
        flow_scores = {"MSFT": (0.8, {"n_institutions": 50})}

        result = blend_institutional_flow(signals, flow_scores, weight=0.15)

        assert result["AAPL"].composite_score == 0.5  # unchanged
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -m pytest tests/test_institutional_flow.py::TestComputeInstitutionalFlowScore tests/test_institutional_flow.py::TestBlendInstitutionalFlow -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quant.institutional_flow'`

- [ ] **Step 3: Implement the scoring module**

Create `quant/institutional_flow.py`:

```python
"""
Institutional flow signal from FMP + Finnhub 13F ownership data.

Computes QoQ changes in institutional ownership as a cross-sectional
signal for the backtest pipeline. Three sub-signals:
  1. Holder count change (% change in number of institutional holders)
  2. Shares flow (% change in total institutional shares held)
  3. Buyer/seller ratio (net buyers - sellers / total)

Point-in-time safety: only uses snapshots with report_date + 45 days <= as_of_date.

Returns (score, metadata) tuples following the earnings_signals.py pattern.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np

from quant.scoring import reclassify

logger = logging.getLogger(__name__)

# Minimum institutions to produce a signal (suppress noise from thinly held stocks)
MIN_INSTITUTIONS = 3


def compute_institutional_flow_score(
    current_snapshot: list[dict],
    prior_snapshot: list[dict],
) -> tuple[float, dict]:
    """
    Compute institutional flow score from two quarterly ownership snapshots.

    Args:
        current_snapshot: Latest quarter's institutional holders.
            Each dict has: investorName, sharesNumber, sharesNumberChange
        prior_snapshot: Prior quarter's institutional holders (same format).

    Returns:
        (score in [-1, +1], metadata dict)
    """
    if not current_snapshot or len(current_snapshot) < MIN_INSTITUTIONS:
        return 0.0, {"error": "insufficient institutions", "n_institutions": len(current_snapshot)}

    # --- Sub-signal 1: Holder count change ---
    n_current = len(current_snapshot)
    n_prior = len(prior_snapshot) if prior_snapshot else n_current

    if n_prior > 0:
        holder_count_change_pct = (n_current - n_prior) / n_prior
    else:
        holder_count_change_pct = 0.0

    # Winsorize at +/- 50% change and map to [-1, +1]
    holder_score = float(np.clip(holder_count_change_pct / 0.50, -1.0, 1.0))

    # --- Sub-signal 2: Shares flow ---
    current_total = sum(h.get("sharesNumber", 0) for h in current_snapshot)
    prior_total = sum(h.get("sharesNumber", 0) for h in prior_snapshot) if prior_snapshot else current_total

    if prior_total > 0:
        shares_flow_pct = (current_total - prior_total) / prior_total
    else:
        shares_flow_pct = 0.0

    # Winsorize at +/- 30% change and map to [-1, +1]
    shares_score = float(np.clip(shares_flow_pct / 0.30, -1.0, 1.0))

    # --- Sub-signal 3: Buyer/seller ratio ---
    n_buying = 0
    n_selling = 0
    n_unchanged = 0

    for h in current_snapshot:
        change = h.get("sharesNumberChange", 0) or 0
        if change > 0:
            n_buying += 1
        elif change < 0:
            n_selling += 1
        else:
            n_unchanged += 1

    n_active = n_buying + n_selling
    if n_active > 0:
        buyer_seller_ratio = (n_buying - n_selling) / n_active
    else:
        buyer_seller_ratio = 0.0

    buyer_seller_score = float(np.clip(buyer_seller_ratio, -1.0, 1.0))

    # --- Composite: equal weight of three sub-signals ---
    score = (holder_score + shares_score + buyer_seller_score) / 3.0
    score = float(np.clip(score, -1.0, 1.0))

    metadata = {
        "n_institutions": n_current,
        "n_prior_institutions": n_prior,
        "n_buying": n_buying,
        "n_selling": n_selling,
        "n_unchanged": n_unchanged,
        "holder_count_change_pct": round(holder_count_change_pct * 100, 2),
        "shares_flow_pct": round(shares_flow_pct * 100, 2),
        "buyer_seller_ratio": round(buyer_seller_ratio, 3),
        "sub_scores": {
            "holder_count": round(holder_score, 4),
            "shares_flow": round(shares_score, 4),
            "buyer_seller": round(buyer_seller_score, 4),
        },
    }

    return round(score, 4), metadata


def _quarter_key(d: date) -> str:
    """Convert date to quarter string, e.g. '2025Q4'."""
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def _pit_safe_date(report_date: date, filing_lag_days: int = 45) -> date:
    """Earliest date this data would be publicly available (point-in-time safe)."""
    return report_date + timedelta(days=filing_lag_days)


def fetch_and_score_institutional_flow(
    ticker: str,
    as_of_date: date,
    fmp_client=None,
    fmp_cache=None,
    finnhub_client=None,
    finnhub_disk_cache=None,
    lookback_quarters: int = 4,
    filing_lag_days: int = 45,
) -> tuple[float, dict]:
    """
    Fetch institutional ownership data and compute flow score.

    Tries FMP first (richer data), uses Finnhub as enrichment.
    Caches results to avoid repeat API calls during backtesting.

    Point-in-time safety: only uses snapshots where
    report_date + filing_lag_days <= as_of_date.

    Args:
        ticker: Stock ticker
        as_of_date: Valuation date (only data available by this date is used)
        fmp_client: FMPClient or FMPCache instance
        fmp_cache: FMPFundamentalCache for persistent SQLite caching
        finnhub_client: FinnhubClient instance (optional enrichment)
        finnhub_disk_cache: SentimentDiskCache instance (optional)
        lookback_quarters: How many quarters back to look for prior snapshot
        filing_lag_days: Days after quarter-end before 13F data is public

    Returns:
        (score in [-1, +1], metadata dict)
    """
    current_snapshot = []
    prior_snapshot = []
    data_source = "none"

    # --- Try FMP data ---
    fmp_data = None
    if fmp_cache is not None:
        fmp_data = fmp_cache.get_institutional_quarterly(ticker, max_age_seconds=0)

    if fmp_data is None and fmp_client is not None:
        if hasattr(fmp_client, "get_institutional_ownership_history"):
            fmp_data = fmp_client.get_institutional_ownership_history(ticker)
        elif hasattr(fmp_client, "_client"):
            # FMPCache wrapper
            fmp_data = fmp_client._client.get_institutional_ownership_history(ticker)

        if fmp_data and fmp_cache is not None:
            fmp_cache.set_institutional_quarterly(ticker, fmp_data)

    if fmp_data:
        # Group by quarter, filter by point-in-time safety
        from collections import defaultdict
        quarters = defaultdict(list)
        for record in fmp_data:
            rec_date_str = record.get("date", "")
            if not rec_date_str:
                continue
            try:
                rec_date = date.fromisoformat(str(rec_date_str)[:10])
            except (ValueError, TypeError):
                continue

            # Point-in-time: only use if filing would be public by as_of_date
            if _pit_safe_date(rec_date, filing_lag_days) > as_of_date:
                continue

            qkey = _quarter_key(rec_date)
            quarters[qkey].append(record)

        # Sort quarters descending
        sorted_quarters = sorted(quarters.keys(), reverse=True)

        if len(sorted_quarters) >= 1:
            current_snapshot = quarters[sorted_quarters[0]]
            data_source = "fmp"

        if len(sorted_quarters) >= 2:
            prior_snapshot = quarters[sorted_quarters[1]]

    # --- Finnhub enrichment ---
    finnhub_meta = {}
    if finnhub_client is not None:
        fh_data = None
        quarter_str = _quarter_key(as_of_date)

        if finnhub_disk_cache is not None:
            fh_data = finnhub_disk_cache.get_institutional(ticker, quarter_str)

        if fh_data is None:
            fh_data = finnhub_client.get_institutional_ownership(ticker)
            if fh_data and finnhub_disk_cache is not None:
                finnhub_disk_cache.set_institutional(ticker, quarter_str, fh_data)

        if fh_data:
            finnhub_meta = {
                "finnhub_n_holders": len(fh_data),
                "finnhub_total_shares": sum(h.get("share", 0) for h in fh_data),
            }
            if data_source == "fmp":
                data_source = "both"
            else:
                # Use Finnhub as primary if FMP failed
                if not current_snapshot and len(fh_data) >= MIN_INSTITUTIONS:
                    current_snapshot = [
                        {
                            "investorName": h.get("name", ""),
                            "sharesNumber": h.get("share", 0),
                            "sharesNumberChange": h.get("change", 0),
                        }
                        for h in fh_data
                    ]
                    data_source = "finnhub"

    score, meta = compute_institutional_flow_score(current_snapshot, prior_snapshot)
    meta["data_source"] = data_source
    meta["as_of_date"] = str(as_of_date)
    meta["finnhub_enrichment"] = finnhub_meta

    return score, meta


def compute_institutional_flow_scores(
    tickers: list[str],
    as_of_date: date,
    fmp_client=None,
    fmp_cache=None,
    finnhub_client=None,
    finnhub_disk_cache=None,
    lookback_quarters: int = 4,
) -> dict[str, tuple[float, dict]]:
    """
    Compute institutional flow scores for all tickers in the universe.

    Returns {ticker: (score, metadata)}.
    """
    results = {}
    for ticker in tickers:
        try:
            score, meta = fetch_and_score_institutional_flow(
                ticker=ticker,
                as_of_date=as_of_date,
                fmp_client=fmp_client,
                fmp_cache=fmp_cache,
                finnhub_client=finnhub_client,
                finnhub_disk_cache=finnhub_disk_cache,
                lookback_quarters=lookback_quarters,
            )
            if score != 0.0 or "error" not in meta:
                results[ticker] = (score, meta)
        except Exception as exc:
            logger.debug("Institutional flow failed for %s: %s", ticker, exc)

    return results


def blend_institutional_flow(
    signals: dict,
    flow_scores: dict[str, tuple[float, dict]],
    weight: float = 0.15,
) -> dict:
    """
    Blend institutional flow scores into SignalVector composite scores.

    Same pattern as blend_earnings_signals in earnings_signals.py.
    """
    if not flow_scores:
        return signals

    for ticker, sv in signals.items():
        entry = flow_scores.get(ticker)
        if entry is None:
            continue

        score, meta = entry
        quant_scale = 1.0 - weight
        blended = sv.composite_score * quant_scale + score * weight
        sv.composite_score = float(np.clip(blended, -1.0, 1.0))

        reclassify(sv)

        n_inst = meta.get("n_institutions", 0)
        src = meta.get("data_source", "unknown")
        sv.flags.append(f"inst_flow_w={weight:.3f}(n={n_inst},src={src})")

    return signals
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -m pytest tests/test_institutional_flow.py -v`
Expected: ALL PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst
git add quant/institutional_flow.py tests/test_institutional_flow.py
git commit -m "feat: implement institutional flow scoring module with FMP/Finnhub"
```

---

### Task 5: Add institutional_flow_score field to SignalVector

**Files:**
- Modify: `quant/signals.py:25-39`
- Test: `tests/test_institutional_flow.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_institutional_flow.py`:

```python
class TestSignalVectorField:
    """Test that SignalVector has institutional_flow_score field."""

    def test_signal_vector_has_institutional_flow_score(self):
        from quant.signals import SignalResult, SignalVector

        sv = SignalVector(
            sma_trend=SignalResult(0.0),
            mean_reversion_z=SignalResult(0.0),
            bollinger_pctb=SignalResult(0.0),
            rsi=SignalResult(0.0),
            obv_trend=SignalResult(0.5),
            atr_regime=SignalResult(0.0),
        )

        assert hasattr(sv, "institutional_flow_score")
        assert sv.institutional_flow_score == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -m pytest tests/test_institutional_flow.py::TestSignalVectorField -v`
Expected: FAIL with `AssertionError`

- [ ] **Step 3: Add the field to SignalVector**

In `quant/signals.py`, after line 38 (`earnings_rank_score: float = 0.0`), add:

```python
    institutional_flow_score: float = 0.0  # Set by institutional flow signal
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -m pytest tests/test_institutional_flow.py::TestSignalVectorField -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst
git add quant/signals.py tests/test_institutional_flow.py
git commit -m "feat: add institutional_flow_score field to SignalVector"
```

---

### Task 6: Wire institutional flow into BacktestConfig and backtest pipeline

**Files:**
- Modify: `quant/backtest.py:98-100` (BacktestConfig)
- Modify: `quant/backtest.py:1808-1816` (walk-forward rebalance loop)
- Modify: `quant/backtest.py:2217-2225` (CPCV rebalance loop)
- Modify: `quant/backtest.py:2530-2538` (simple backtest rebalance loop)
- Modify: `quant/backtest.py:1960-2019` (auto-init section)

- [ ] **Step 1: Add config fields to BacktestConfig**

In `quant/backtest.py`, after line 100 (`earnings_rank_mode: bool = False`), add:

```python
    # Institutional flow signal (FMP + Finnhub 13F ownership data)
    enable_institutional_flow: bool = False
    institutional_flow_weight: float = 0.15  # weight in composite
```

- [ ] **Step 2: Add module-level globals for institutional flow providers**

Near the existing `_finnhub_client`, `_fmp_client` etc. globals (search for `_finnhub_client = None`), add:

```python
_inst_fmp_cache = None  # FMPFundamentalCache for institutional data
```

- [ ] **Step 3: Add auto-init block for institutional flow**

In the `run_walk_forward` function, after the earnings signals auto-init block (around line 2019), add:

```python
    # Auto-init institutional flow data sources
    if config.enable_institutional_flow:
        global _inst_fmp_cache
        if _inst_fmp_cache is None:
            from quant.fmp_cache import FMPFundamentalCache
            _inst_fmp_cache = FMPFundamentalCache()
        if _fmp_client is None:
            fmp_key = os.getenv("FMP_API_KEY", "").strip()
            if fmp_key:
                from fmp_client import FMPClient
                _fmp_client = FMPClient(fmp_key)
```

- [ ] **Step 4: Wire blend into walk-forward rebalance loop**

In `quant/backtest.py`, after the earnings signals blend block (around line 1816: `signals = blend_earnings_signals(signals, earn_scores, config.earnings_signal_weight)`), add:

```python
        # Institutional flow overlay (FMP + Finnhub 13F ownership)
        if config.enable_institutional_flow:
            from quant.institutional_flow import compute_institutional_flow_scores, blend_institutional_flow
            inst_scores = compute_institutional_flow_scores(
                list(signals.keys()),
                as_of_date=reb_date.date(),
                fmp_client=_fmp_client,
                fmp_cache=_inst_fmp_cache,
                finnhub_client=_finnhub_client,
                finnhub_disk_cache=_sentiment_cache,
            )
            if inst_scores:
                signals = blend_institutional_flow(signals, inst_scores, config.institutional_flow_weight)
```

- [ ] **Step 5: Wire blend into CPCV rebalance loop**

Same block after earnings blend in the CPCV section (around line 2225):

```python
            # Institutional flow overlay
            if config.enable_institutional_flow:
                from quant.institutional_flow import compute_institutional_flow_scores, blend_institutional_flow
                inst_scores = compute_institutional_flow_scores(
                    list(signals.keys()),
                    as_of_date=reb_date.date(),
                    fmp_client=_fmp_client,
                    fmp_cache=_inst_fmp_cache,
                    finnhub_client=_finnhub_client,
                    finnhub_disk_cache=_sentiment_cache,
                )
                if inst_scores:
                    signals = blend_institutional_flow(signals, inst_scores, config.institutional_flow_weight)
```

- [ ] **Step 6: Wire blend into simple backtest rebalance loop**

Same block after earnings blend in the simple backtest section (around line 2538):

```python
            # Institutional flow overlay
            if config.enable_institutional_flow:
                from quant.institutional_flow import compute_institutional_flow_scores, blend_institutional_flow
                inst_scores = compute_institutional_flow_scores(
                    list(signals.keys()),
                    as_of_date=reb_date.date(),
                    fmp_client=_fmp_client,
                    fmp_cache=_inst_fmp_cache,
                    finnhub_client=_finnhub_client,
                    finnhub_disk_cache=_sentiment_cache,
                )
                if inst_scores:
                    signals = blend_institutional_flow(signals, inst_scores, config.institutional_flow_weight)
```

- [ ] **Step 7: Verify backtest.py still imports cleanly**

Run: `cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -c "from quant.backtest import BacktestConfig; c = BacktestConfig(tickers=['AAPL']); print(f'enable_institutional_flow={c.enable_institutional_flow}, weight={c.institutional_flow_weight}')" `
Expected: `enable_institutional_flow=False, weight=0.15`

- [ ] **Step 8: Commit**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst
git add quant/backtest.py
git commit -m "feat: wire institutional flow signal into backtest pipeline"
```

---

### Task 7: Add institutional flow to redundancy diagnostics

**Files:**
- Modify: `quant/redundancy.py:26-28` (SIGNAL_NAMES)
- Modify: `quant/redundancy.py:31-69` (compute_signal_scores_at_date)

- [ ] **Step 1: Add institutional_flow to SIGNAL_NAMES**

In `quant/redundancy.py`, change line 26-28 from:

```python
SIGNAL_NAMES = [
    "obv_trend",
]
```

to:

```python
SIGNAL_NAMES = [
    "obv_trend",
    "institutional_flow",
]
```

- [ ] **Step 2: Include institutional_flow in compute_signal_scores_at_date**

In `quant/redundancy.py`, modify `compute_signal_scores_at_date` to also compute institutional flow scores. After the existing signal vector computation (line 55: `rows[ticker] = {`), update:

```python
    # Also compute institutional flow if providers available
    inst_flow_scores = {}
    try:
        from quant.institutional_flow import compute_institutional_flow_scores
        from quant.fmp_cache import FMPFundamentalCache
        fmp_cache = FMPFundamentalCache()
        inst_flow_scores = compute_institutional_flow_scores(
            list(universe_data.keys()),
            as_of_date=as_of_date.date() if hasattr(as_of_date, 'date') else as_of_date,
            fmp_cache=fmp_cache,
        )
    except Exception:
        pass
```

And in the rows dict, add:

```python
            inst_entry = inst_flow_scores.get(ticker)
            rows[ticker] = {
                "sma_trend": sv.sma_trend.score,
                "mean_reversion_z": sv.mean_reversion_z.score,
                "bollinger_pctb": sv.bollinger_pctb.score,
                "rsi": sv.rsi.score,
                "obv_trend": sv.obv_trend.score,
                "high_52w": sv.high_52w.score,
                "institutional_flow": inst_entry[0] if inst_entry else 0.0,
            }
```

- [ ] **Step 3: Verify redundancy module imports**

Run: `cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -c "from quant.redundancy import SIGNAL_NAMES; print(SIGNAL_NAMES)"`
Expected: `['obv_trend', 'institutional_flow']`

- [ ] **Step 4: Commit**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst
git add quant/redundancy.py
git commit -m "feat: add institutional_flow to redundancy IC diagnostics"
```

---

### Task 8: Add --enable-institutional-flow to run_phase0.py

**Files:**
- Modify: `scripts/run_phase0.py:52-123`

- [ ] **Step 1: Add CLI argument**

In `scripts/run_phase0.py`, after `--test-months` argument (around line 73), add:

```python
    parser.add_argument("--enable-institutional-flow", action="store_true",
                        help="Enable institutional flow signal (FMP + Finnhub)")
    parser.add_argument("--institutional-flow-weight", type=float, default=0.15,
                        help="Institutional flow signal weight (default: 0.15)")
```

- [ ] **Step 2: Wire into BacktestConfig**

In the config construction (around line 105-123), add after `news_sentiment_weight=0.10`:

```python
        enable_institutional_flow=args.enable_institutional_flow,
        institutional_flow_weight=args.institutional_flow_weight,
```

- [ ] **Step 3: Add to the header printout**

After line 99 (`print(f"  CPCV groups: {args.n_groups}")`), add:

```python
    if args.enable_institutional_flow:
        print(f"  Institutional flow: ENABLED (weight={args.institutional_flow_weight})")
```

- [ ] **Step 4: Verify script parses the new flag**

Run: `cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python scripts/run_phase0.py --help | grep -A1 institutional`
Expected: Shows `--enable-institutional-flow` and `--institutional-flow-weight` in help text

- [ ] **Step 5: Commit**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst
git add scripts/run_phase0.py
git commit -m "feat: add --enable-institutional-flow flag to Phase 0 diagnostic"
```

---

### Task 9: Run tests and validate end-to-end

**Files:**
- All modified files

- [ ] **Step 1: Run full test suite**

Run: `cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -m pytest tests/test_institutional_flow.py -v`
Expected: ALL PASS (12+ tests)

- [ ] **Step 2: Verify imports work end-to-end**

Run: `cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -c "
from quant.institutional_flow import compute_institutional_flow_score, blend_institutional_flow, compute_institutional_flow_scores
from quant.backtest import BacktestConfig
from quant.redundancy import SIGNAL_NAMES
c = BacktestConfig(tickers=['AAPL'], enable_institutional_flow=True)
print(f'Config OK: enable={c.enable_institutional_flow}, weight={c.institutional_flow_weight}')
print(f'Redundancy signals: {SIGNAL_NAMES}')
print('All imports OK')
"`
Expected: All imports succeed, config shows enable=True, weight=0.15

- [ ] **Step 3: Run a quick smoke test with FMP data (if API key available)**

Run: `cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && python -c "
import os
from dotenv import load_dotenv
load_dotenv()
fmp_key = os.getenv('FMP_API_KEY', '')
if not fmp_key:
    print('SKIP: No FMP_API_KEY set')
else:
    from fmp_client import FMPClient
    client = FMPClient(fmp_key)
    data = client.get_institutional_ownership_history('AAPL')
    print(f'FMP returned {len(data)} institutional records for AAPL')
    if data:
        print(f'First record: {data[0]}')
"`
Expected: Either prints record count or SKIP message

- [ ] **Step 4: Run Phase 0 with institutional flow flag (dry run — just verify it starts)**

Run: `cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst && timeout 30 python scripts/run_phase0.py --universe liquid_20 --start 2018-01-01 --enable-institutional-flow --skip-cpcv --skip-ff5 --skip-redundancy 2>&1 | head -20`
Expected: Prints Phase 0 header with "Institutional flow: ENABLED", starts walk-forward

- [ ] **Step 5: Final commit if any fixes were needed**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst
git add -A
git commit -m "fix: address any issues found in end-to-end validation"
```
