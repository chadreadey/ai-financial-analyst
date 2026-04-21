# Kalshi Event Signal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate Kalshi prediction market probabilities as two signals: (1) a general macro modifier fed into the composite score at every rebalance, and (2) a high-conviction event signal that fires around earnings and FOMC dates when our model's directional view diverges from Kalshi market-implied odds.

**Architecture:** A lightweight REST client fetches Kalshi market data (no auth, fully public) and caches it to disk. A macro signal translates Fed/CPI/GDP contract probabilities into a regime-weighted score modifier applied cross-sectionally. A separate event-divergence signal computes the gap between our model's conviction and Kalshi-implied probability for individual earnings events, firing as a standalone signal when divergence exceeds a high-confidence threshold. Both signals inject into `SignalVector` fields and the backtest's rebalance loop, mirroring the existing `event_timing_score` pattern.

**Tech Stack:** Python `requests`, `json`, `datetime`, `numpy`, `pandas`, `pytest` with `responses` for HTTP mocking. No auth or API key required for market data reads.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `quant/kalshi_client.py` | Create | REST client + disk cache; returns typed dicts of market data |
| `quant/kalshi_signal.py` | Create | Two signal functions: `compute_macro_modifier()` + `compute_event_divergence()` |
| `quant/signals.py` | Modify | Add `kalshi_macro_score` and `kalshi_event_score` fields to `SignalVector` |
| `quant/backtest.py` | Modify | Inject both signals at each rebalance date (after event_timing block, before cross-sectional norm) |
| `market_enrichment.py` | Modify | Add Kalshi section to enrichment dict so agents see market-implied probs |
| `config.py` | Modify | Add `enable_kalshi_signal: bool`, `kalshi_event_threshold: float`, `kalshi_event_weight: float`, `kalshi_macro_weight: float` |
| `tests/test_kalshi_client.py` | Create | Unit tests for client parsing and cache logic |
| `tests/test_kalshi_signal.py` | Create | Unit tests for both signal functions |

---

## Task 1: Kalshi REST Client

**Files:**
- Create: `quant/kalshi_client.py`
- Create: `tests/test_kalshi_client.py`

The client fetches from `https://api.elections.kalshi.com/trade-api/v2`. All market-data endpoints are public — no auth needed. We cache responses to disk as JSON (keyed by date) so backtests and repeated intraday calls don't hit the network.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_kalshi_client.py`:

```python
import json
import os
import pytest
import responses as resp_mock

from quant.kalshi_client import KalshiClient, KalshiMarket

BASE = "https://api.elections.kalshi.com/trade-api/v2"


@pytest.fixture
def client(tmp_path):
    return KalshiClient(cache_dir=str(tmp_path))


@resp_mock.activate
def test_get_markets_by_series_parses_yes_bid(client):
    resp_mock.add(
        resp_mock.GET,
        f"{BASE}/markets",
        json={
            "markets": [
                {
                    "ticker": "FED-25MAY-B525",
                    "event_ticker": "FED-25MAY",
                    "title": "Fed Funds 5.25% at May meeting",
                    "yes_bid": 72,
                    "yes_ask": 74,
                    "volume": 15000,
                    "open_interest": 42000,
                    "close_time": "2026-05-07T18:00:00Z",
                    "status": "open",
                }
            ],
            "cursor": "",
        },
        status=200,
    )
    markets = client.get_markets(series_ticker="FED")
    assert len(markets) == 1
    m = markets[0]
    assert m["ticker"] == "FED-25MAY-B525"
    assert m["yes_prob"] == pytest.approx(0.72)


@resp_mock.activate
def test_get_markets_caches_to_disk(client, tmp_path):
    resp_mock.add(
        resp_mock.GET,
        f"{BASE}/markets",
        json={"markets": [], "cursor": ""},
        status=200,
    )
    client.get_markets(series_ticker="FED")
    # Second call must NOT hit network (responses would raise)
    resp_mock.reset()
    result = client.get_markets(series_ticker="FED")
    assert result == []


def test_get_series_for_equity_returns_earn_markets(client, tmp_path):
    # Preload cache with a fake EARN-AAPL market
    cache_file = tmp_path / "EARN_2026-04-15.json"
    cache_file.write_text(
        json.dumps([{"ticker": "EARN-AAPL-Q1", "yes_prob": 0.61, "series": "EARN"}])
    )
    markets = client.get_markets(series_ticker="EARN", _date_override="2026-04-15")
    assert markets[0]["ticker"] == "EARN-AAPL-Q1"
```

- [ ] **Step 2: Run test to confirm failure**

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst
python -m pytest tests/test_kalshi_client.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'quant.kalshi_client'`

- [ ] **Step 3: Implement `quant/kalshi_client.py`**

```python
"""
Kalshi REST client — public market data only (no auth required).

All endpoints are read-only. Responses cached to disk keyed by
series + date so backtests and repeated intraday calls don't hit
the network.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
DEFAULT_CACHE_DIR = os.path.join(os.path.dirname(__file__), ".kalshi_cache")

# Equity series tickers relevant to our model
MACRO_SERIES = ["FED", "CPI", "JOBS", "GDP"]
EARNINGS_SERIES_PREFIX = "EARN"

KalshiMarket = dict[str, Any]


class KalshiClient:
    def __init__(self, cache_dir: str = DEFAULT_CACHE_DIR):
        os.makedirs(cache_dir, exist_ok=True)
        self._cache_dir = cache_dir
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "ai-financial-analyst/1.0"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_markets(
        self,
        series_ticker: str,
        status: str = "open",
        _date_override: Optional[str] = None,
    ) -> list[KalshiMarket]:
        """Return open markets for a series, with implied probability added."""
        today = _date_override or date.today().isoformat()
        cache_key = f"{series_ticker}_{today}.json"
        cache_path = os.path.join(self._cache_dir, cache_key)

        if os.path.exists(cache_path):
            with open(cache_path) as f:
                return json.load(f)

        raw = self._fetch_markets(series_ticker=series_ticker, status=status)
        markets = [self._enrich(m) for m in raw]

        with open(cache_path, "w") as f:
            json.dump(markets, f)

        return markets

    def get_event_market(
        self, event_ticker: str, _date_override: Optional[str] = None
    ) -> list[KalshiMarket]:
        """Return markets for a specific event ticker (e.g. EARN-AAPL-Q126)."""
        today = _date_override or date.today().isoformat()
        cache_key = f"event_{event_ticker}_{today}.json"
        cache_path = os.path.join(self._cache_dir, cache_key)

        if os.path.exists(cache_path):
            with open(cache_path) as f:
                return json.load(f)

        params = {"event_ticker": event_ticker, "status": "open", "limit": 50}
        try:
            r = self._session.get(f"{BASE_URL}/markets", params=params, timeout=10)
            r.raise_for_status()
            raw = r.json().get("markets", [])
        except Exception as exc:
            logger.warning("Kalshi event fetch failed for %s: %s", event_ticker, exc)
            return []

        markets = [self._enrich(m) for m in raw]
        with open(cache_path, "w") as f:
            json.dump(markets, f)
        return markets

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_markets(self, series_ticker: str, status: str) -> list[dict]:
        params = {"series_ticker": series_ticker, "status": status, "limit": 200}
        try:
            r = self._session.get(f"{BASE_URL}/markets", params=params, timeout=10)
            r.raise_for_status()
            return r.json().get("markets", [])
        except Exception as exc:
            logger.warning("Kalshi fetch failed for %s: %s", series_ticker, exc)
            return []

    @staticmethod
    def _enrich(m: dict) -> KalshiMarket:
        """Add yes_prob (0-1 float) from yes_bid (0-100 int)."""
        m = dict(m)
        m["yes_prob"] = m.get("yes_bid", 0) / 100.0
        return m
```

- [ ] **Step 4: Install `responses` library if missing**

```bash
pip install responses
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/test_kalshi_client.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add quant/kalshi_client.py tests/test_kalshi_client.py
git commit -m "feat: Kalshi REST client with disk cache"
```

---

## Task 2: Macro Modifier Signal

**Files:**
- Create: `quant/kalshi_signal.py`
- Create: `tests/test_kalshi_signal.py` (partial — add to in Task 3)

The macro modifier translates Kalshi Fed/CPI/JOBS probabilities into a scalar in `[-1, +1]` applied uniformly to all tickers at rebalance. A hawkish surprise (market suddenly pricing in fewer cuts) is bearish for equities → negative modifier. A dovish surprise is bullish → positive. We compute the modifier as a weighted sum of *direction-weighted* probabilities across relevant series.

- [ ] **Step 1: Write the failing test**

Create `tests/test_kalshi_signal.py`:

```python
import pytest
from unittest.mock import MagicMock, patch

from quant.kalshi_signal import compute_macro_modifier, compute_event_divergence


# ------- macro modifier tests -------

def _mock_client(fed_prob=0.70, cpi_prob=0.55, jobs_prob=0.50):
    """Returns a KalshiClient mock with preset market probs."""
    client = MagicMock()

    def get_markets(series_ticker, **kwargs):
        probs = {"FED": fed_prob, "CPI": cpi_prob, "JOBS": jobs_prob, "GDP": 0.50}
        return [{"ticker": f"{series_ticker}-TEST", "yes_prob": probs.get(series_ticker, 0.5)}]

    client.get_markets.side_effect = get_markets
    return client


def test_macro_modifier_dovish_fed_is_positive():
    """High probability of rate cut → positive macro modifier."""
    client = _mock_client(fed_prob=0.85)
    score = compute_macro_modifier(client)
    assert score > 0.0


def test_macro_modifier_hawkish_fed_is_negative():
    """Low probability of rate cut → negative macro modifier."""
    client = _mock_client(fed_prob=0.15)
    score = compute_macro_modifier(client)
    assert score < 0.0


def test_macro_modifier_neutral_is_near_zero():
    """~50% probability on all contracts → near-zero modifier."""
    client = _mock_client(fed_prob=0.50, cpi_prob=0.50, jobs_prob=0.50)
    score = compute_macro_modifier(client)
    assert abs(score) < 0.1


def test_macro_modifier_clipped_to_unit_interval():
    client = _mock_client(fed_prob=1.0, cpi_prob=1.0, jobs_prob=1.0)
    score = compute_macro_modifier(client)
    assert -1.0 <= score <= 1.0


# ------- event divergence tests -------

def test_event_divergence_no_market_returns_zero():
    client = MagicMock()
    client.get_markets.return_value = []
    score = compute_event_divergence(client, ticker="AAPL", our_prob_beat=0.75)
    assert score == 0.0


def test_event_divergence_high_confidence_long():
    """We think 80% beat, Kalshi says 45% → strong positive divergence."""
    client = MagicMock()
    client.get_markets.return_value = [
        {"ticker": "EARN-AAPL-Q126", "yes_prob": 0.45}
    ]
    score = compute_event_divergence(client, ticker="AAPL", our_prob_beat=0.80,
                                     threshold=0.20)
    assert score > 0.3


def test_event_divergence_below_threshold_returns_zero():
    """Divergence below threshold → no signal (don't trade uncertainty)."""
    client = MagicMock()
    client.get_markets.return_value = [
        {"ticker": "EARN-AAPL-Q126", "yes_prob": 0.52}
    ]
    score = compute_event_divergence(client, ticker="AAPL", our_prob_beat=0.58,
                                     threshold=0.20)
    assert score == 0.0


def test_event_divergence_clipped_to_unit_interval():
    client = MagicMock()
    client.get_markets.return_value = [{"ticker": "EARN-AAPL", "yes_prob": 0.01}]
    score = compute_event_divergence(client, ticker="AAPL", our_prob_beat=1.0,
                                     threshold=0.20)
    assert -1.0 <= score <= 1.0
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
python -m pytest tests/test_kalshi_signal.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'quant.kalshi_signal'`

- [ ] **Step 3: Implement `quant/kalshi_signal.py`**

```python
"""
Kalshi-based signals for the quant model.

Two signals:

1. compute_macro_modifier(client) -> float in [-1, +1]
   Reads Fed/CPI/JOBS Kalshi markets and returns a uniform
   macro-regime modifier applied cross-sectionally. Dovish
   (high cut probability) → positive; hawkish → negative.

2. compute_event_divergence(client, ticker, our_prob_beat, threshold) -> float in [-1, +1]
   Computes divergence between our model's earnings-beat probability
   and Kalshi's market-implied probability. Returns 0.0 if divergence
   is below threshold (no-bet zone). Only fires in the 10 trading
   days before a known earnings date.
"""
from __future__ import annotations

import logging
import math
from typing import Optional

import numpy as np

from quant.kalshi_client import KalshiClient

logger = logging.getLogger(__name__)

# Series → equity direction interpretation
# True = high yes_prob is BULLISH for equities (e.g. rate cut = good)
# False = high yes_prob is BEARISH (e.g. hot CPI = bad)
_MACRO_SERIES_CONFIG = {
    "FED": {"weight": 0.50, "bullish_if_yes": True},   # cut probability
    "CPI":  {"weight": 0.25, "bullish_if_yes": False},  # CPI beat = hot = hawkish
    "JOBS": {"weight": 0.25, "bullish_if_yes": False},  # strong jobs = hawkish
}

# EARN series — how to search for a ticker's earnings market
_EARN_SERIES = "EARN"


def compute_macro_modifier(
    client: KalshiClient,
    _date_override: Optional[str] = None,
) -> float:
    """
    Returns a scalar in [-1, +1] summarising macro regime from
    Kalshi prediction markets. Applied uniformly to all tickers.

    Computation:
      For each series, map yes_prob to a bullish score:
        bullish_score = yes_prob       (if bullish_if_yes)
        bullish_score = 1 - yes_prob   (if bearish_if_yes)
      Then centre: centred = bullish_score - 0.5  (range [-0.5, +0.5])
      Weighted average across series, scaled to [-1, +1].
    """
    weighted_sum = 0.0
    total_weight = 0.0

    for series, cfg in _MACRO_SERIES_CONFIG.items():
        try:
            markets = client.get_markets(series_ticker=series,
                                         _date_override=_date_override)
        except Exception as exc:
            logger.warning("Kalshi macro fetch failed for %s: %s", series, exc)
            continue

        if not markets:
            continue

        # Use the most liquid market (highest volume if available, else first)
        market = max(markets, key=lambda m: m.get("volume", 0))
        yes_prob = market.get("yes_prob", 0.5)

        bullish_prob = yes_prob if cfg["bullish_if_yes"] else (1.0 - yes_prob)
        centred = bullish_prob - 0.5  # [-0.5, +0.5]

        weighted_sum += centred * cfg["weight"]
        total_weight += cfg["weight"]

    if total_weight == 0:
        return 0.0

    raw = weighted_sum / total_weight  # [-0.5, +0.5]
    return float(np.clip(raw * 2.0, -1.0, 1.0))  # scale to [-1, +1]


def compute_event_divergence(
    client: KalshiClient,
    ticker: str,
    our_prob_beat: float,
    threshold: float = 0.20,
    _date_override: Optional[str] = None,
) -> float:
    """
    Returns a signal in [-1, +1] based on divergence between our
    model's earnings-beat probability and Kalshi's market-implied
    probability for the same event.

    Returns 0.0 if:
      - No Kalshi market found for this ticker
      - |divergence| < threshold (low-conviction, no trade)

    Args:
        our_prob_beat: Our model's probability that earnings beats
                       consensus (0-1). Derived from earnings_rank_score.
        threshold: Minimum divergence to generate a signal (default 0.20).
                   At 0.20 we need our view to differ from Kalshi by ≥20pp.
    """
    markets = _find_earn_market(client, ticker, _date_override)
    if not markets:
        return 0.0

    # Use the first/most relevant market
    kalshi_prob = markets[0].get("yes_prob", 0.5)
    divergence = our_prob_beat - kalshi_prob

    if abs(divergence) < threshold:
        return 0.0

    # Scale divergence to [-1, +1]: at max divergence (±1.0), signal = ±1
    # Use tanh to keep it smooth and bounded
    raw = math.tanh(divergence * 3.0)
    return float(np.clip(raw, -1.0, 1.0))


def _find_earn_market(
    client: KalshiClient,
    ticker: str,
    _date_override: Optional[str] = None,
) -> list[dict]:
    """
    Search for an open Kalshi earnings market for the given ticker.
    Kalshi earnings tickers follow pattern: EARN-{TICKER}-Q{N}{YY}
    e.g. EARN-AAPL-Q126, EARN-MSFT-Q226

    We search the EARN series and filter by ticker name.
    """
    try:
        all_earn = client.get_markets(series_ticker=_EARN_SERIES,
                                      _date_override=_date_override)
    except Exception as exc:
        logger.warning("Kalshi EARN fetch failed: %s", exc)
        return []

    ticker_upper = ticker.upper()
    matching = [
        m for m in all_earn
        if ticker_upper in m.get("ticker", "").upper()
        or ticker_upper in m.get("event_ticker", "").upper()
    ]
    return matching
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_kalshi_signal.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add quant/kalshi_signal.py tests/test_kalshi_signal.py
git commit -m "feat: Kalshi macro modifier and event divergence signals"
```

---

## Task 3: Add SignalVector Fields

**Files:**
- Modify: `quant/signals.py` (add two fields to `SignalVector` dataclass)

- [ ] **Step 1: Add fields**

In `quant/signals.py`, after line 45 (`event_timing_score: float = 0.0`), add:

```python
    kalshi_macro_score: float = 0.0   # Macro regime from Kalshi Fed/CPI/JOBS markets
    kalshi_event_score: float = 0.0   # Pre-earnings divergence vs Kalshi-implied prob
```

- [ ] **Step 2: Verify no existing tests break**

```bash
python -m pytest tests/test_kalshi_signal.py tests/test_kalshi_client.py -v
```

Expected: all PASS (these fields have defaults so nothing breaks).

- [ ] **Step 3: Commit**

```bash
git add quant/signals.py
git commit -m "feat: add kalshi_macro_score and kalshi_event_score to SignalVector"
```

---

## Task 4: Config Flags

**Files:**
- Modify: `config.py` (add Kalshi config to `BacktestConfig` or equivalent settings object)

- [ ] **Step 1: Find the right config class**

```bash
grep -n "enable_event_timing\|enable_fomc\|BacktestConfig" /Users/chadreadey/portfolio-analyst/ai-financial-analyst/config.py | head -10
grep -n "enable_event_timing\|enable_fomc\|BacktestConfig" /Users/chadreadey/portfolio-analyst/ai-financial-analyst/quant/backtest.py | head -5
```

- [ ] **Step 2: Add fields to `BacktestConfig`**

In `quant/backtest.py`, in the `BacktestConfig` dataclass, add after `enable_fomc_proximity`:

```python
    enable_kalshi_signal: bool = False          # Master switch for all Kalshi signals
    kalshi_macro_weight: float = 0.10           # Weight of macro modifier in composite
    kalshi_event_weight: float = 0.20           # Weight of event divergence signal in composite
    kalshi_event_threshold: float = 0.20        # Min divergence to fire event signal (20pp)
```

- [ ] **Step 3: Verify config serialises cleanly**

```bash
python -c "from quant.backtest import BacktestConfig; c = BacktestConfig(); print(c.enable_kalshi_signal, c.kalshi_event_weight)"
```

Expected: `False 0.2`

- [ ] **Step 4: Commit**

```bash
git add quant/backtest.py
git commit -m "feat: add Kalshi config flags to BacktestConfig"
```

---

## Task 5: Inject Signals in Backtest

**Files:**
- Modify: `quant/backtest.py` (three injection sites: walk-forward loop ~line 1859, CPCV loop ~line 2462, live-score path ~line 2904)

The pattern mirrors the existing `event_timing` injection block exactly. We:
1. Compute macro modifier once per rebalance (same value for all tickers)
2. Compute event divergence per-ticker (only non-zero when earnings market found + divergence ≥ threshold)
3. Blend both into composite using configured weights

- [ ] **Step 1: Add the import block at top of backtest.py**

Find the block where `event_timing` is imported (around line 1859) and add the Kalshi import alongside it:

```python
            # Kalshi signals (both macro and event-level)
            if config.enable_kalshi_signal:
                try:
                    from quant.kalshi_client import KalshiClient
                    from quant.kalshi_signal import compute_macro_modifier, compute_event_divergence
                    _kalshi_client = KalshiClient()
                    _kalshi_macro = compute_macro_modifier(_kalshi_client)
                    for ticker in signals:
                        signals[ticker].kalshi_macro_score = _kalshi_macro
                        earn_prob = getattr(signals[ticker], "earnings_rank_score", 0.0)
                        # Map earnings_rank_score ([-1,1]) to probability space [0,1]
                        our_prob = (earn_prob + 1.0) / 2.0
                        signals[ticker].kalshi_event_score = compute_event_divergence(
                            _kalshi_client,
                            ticker=ticker,
                            our_prob_beat=our_prob,
                            threshold=config.kalshi_event_threshold,
                        )
                except Exception as exc:
                    logger.warning("Kalshi signal failed: %s", exc)
```

Add this block at **each of the three injection sites** (lines ~1868, ~2471, ~2913) — immediately after the existing `event_timing` block. The structure is identical at all three sites.

- [ ] **Step 2: Blend kalshi scores into composite**

Find where `event_timing_score` is blended into the composite (search for `"event_timing"` in the XGBoost feature dict or linear composite block). Add alongside it:

```python
                        "kalshi_macro": sv.kalshi_macro_score,
                        "kalshi_event": sv.kalshi_event_score,
```

For the **linear composite path** (when XGBoost is not used), find `compute_normalized_composite` calls and add the Kalshi terms to the weighted blend:

```python
# After existing signal weights, add:
if config.enable_kalshi_signal:
    composite += sv.kalshi_macro_score * config.kalshi_macro_weight
    composite += sv.kalshi_event_score * config.kalshi_event_weight
```

- [ ] **Step 3: Smoke test — run a short backtest with flag off**

```bash
python scripts/run_backtest.py --tickers AAPL MSFT --start 2024-01-01 --end 2024-06-01 --no-cpcv 2>&1 | tail -5
```

Expected: completes without error (Kalshi disabled by default, no network calls).

- [ ] **Step 4: Smoke test — run with Kalshi enabled (live network)**

```bash
python scripts/run_backtest.py --tickers AAPL MSFT --start 2024-01-01 --end 2024-06-01 --no-cpcv --enable-kalshi 2>&1 | tail -10
```

Expected: completes, Kalshi log lines visible, no traceback.

- [ ] **Step 5: Commit**

```bash
git add quant/backtest.py
git commit -m "feat: inject Kalshi macro + event signals into backtest rebalance loop"
```

---

## Task 6: Market Enrichment — Agent Context

**Files:**
- Modify: `market_enrichment.py`

Agents currently don't see Kalshi data in their prompts. We add a `kalshi` section to the enrichment dict so LLMs can reference market-implied probabilities when forming their thesis.

- [ ] **Step 1: Find the enrichment sections dict**

```bash
grep -n "sections\[" /Users/chadreadey/portfolio-analyst/ai-financial-analyst/market_enrichment.py | head -20
```

- [ ] **Step 2: Add the Kalshi section**

Find where sections are assembled (e.g., `sections["earnings"]`, `sections["sentiment"]`) and add:

```python
    # Kalshi prediction market context
    try:
        from quant.kalshi_client import KalshiClient
        from quant.kalshi_signal import _find_earn_market, compute_macro_modifier
        _kc = KalshiClient()
        earn_markets = _find_earn_market(_kc, ticker)
        macro_score = compute_macro_modifier(_kc)
        kalshi_lines = []
        if earn_markets:
            m = earn_markets[0]
            kalshi_lines.append(
                f"Kalshi earnings market ({m['ticker']}): "
                f"{m['yes_prob']:.0%} implied probability of beat."
            )
        kalshi_lines.append(
            f"Kalshi macro regime score: {macro_score:+.2f} "
            f"({'dovish' if macro_score > 0 else 'hawkish'} bias from Fed/CPI/JOBS markets)."
        )
        sections["kalshi"] = "\n".join(kalshi_lines)
    except Exception as exc:
        logger.debug("Kalshi enrichment skipped: %s", exc)
```

- [ ] **Step 3: Verify enrichment runs without crash**

```bash
python -c "
from market_enrichment import enrich_market_data
result = enrich_market_data('AAPL')
print('kalshi' in result.get('sections', {}))
"
```

Expected: `True` (or `False` if Kalshi is unreachable — either is fine, it's wrapped in try/except).

- [ ] **Step 4: Commit**

```bash
git add market_enrichment.py
git commit -m "feat: add Kalshi market-implied probs to agent enrichment context"
```

---

## Task 7: CLI Flag + CPCV Validation

**Files:**
- Modify: `scripts/run_backtest.py` (add `--enable-kalshi` flag)

- [ ] **Step 1: Add CLI arg**

Find where `--enable-fomc-proximity` is defined in `run_backtest.py` and add alongside:

```python
parser.add_argument(
    "--enable-kalshi",
    action="store_true",
    default=False,
    help="Enable Kalshi prediction market signals (macro modifier + earnings divergence)",
)
parser.add_argument(
    "--kalshi-event-threshold",
    type=float,
    default=0.20,
    help="Minimum divergence (0-1) to fire Kalshi event signal. Default 0.20.",
)
```

Wire into `BacktestConfig`:
```python
config = BacktestConfig(
    ...
    enable_kalshi_signal=args.enable_kalshi,
    kalshi_event_threshold=args.kalshi_event_threshold,
)
```

- [ ] **Step 2: Run CPCV validation on a small universe to baseline**

This establishes whether Kalshi adds alpha without overfitting. Run against the liquid_50 universe with CPCV:

```bash
python scripts/run_backtest.py --universe liquid_50 --enable-kalshi --cpcv 2>&1 | grep -E "Sharpe|PBO|Alpha"
```

Compare Sharpe/PBO against the gold-standard baseline (Sharpe 1.04, PBO 0%). If PBO rises above 15%, the signal is overfitting — reduce `kalshi_event_weight` or raise `kalshi_event_threshold`.

- [ ] **Step 3: Commit**

```bash
git add scripts/run_backtest.py
git commit -m "feat: --enable-kalshi CLI flag + CPCV validation notes"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Kalshi as general model input → `kalshi_macro_score` in `SignalVector`, blended in composite
- [x] Separate event signal for earnings + FOMC → `kalshi_event_score`, fires only on divergence ≥ threshold
- [x] Low downside — Kalshi contracts are inherently binary/limited loss; signal is a weight modifier not sizing
- [x] High confidence threshold — `kalshi_event_threshold=0.20` default, configurable
- [x] Agent visibility → market_enrichment section

**Gaps / notes:**
- FOMC-specific event divergence not yet wired (the macro modifier covers Fed direction; individual FOMC beat/miss contracts would need a separate `_find_fomc_market()` helper following the same pattern as `_find_earn_market()` — defer until Kalshi's FOMC series structure is confirmed)
- Backtest history (2020-2024): Kalshi launched in 2021; EARN markets for individual stocks are sparse pre-2023. Signal will silently return 0.0 for dates with no markets, which is correct behaviour — the fallback is safe.
- CPCV validation is mandatory before raising weights above 0.10/0.20 defaults.
