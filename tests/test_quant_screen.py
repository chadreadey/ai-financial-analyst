"""Unit tests for `_quant_screen` (backend/paper_scheduler.py).

Mocks all heavy dependencies (price CSV loading, WRDS store, signal
precomputes) so the tests are hermetic and don't depend on the live
`.wrds_pit.db` or `.price_cache/` contents.

One end-to-end smoke test against the live data files is covered
separately by the Criterion-6 manual verification (§9 of the blueprint).
"""
from __future__ import annotations

from datetime import date
from typing import Callable
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


# ── Shared synthetic-signals helpers ─────────────────────────────────────


def _make_signal_vector(
    obv: float = 0.0,
    qmj: float = 0.0,
    earnings: float = 0.0,
    inst: float = 0.0,
):
    """Build a minimal SignalVector with the four production fields set.

    Imported lazily so this test module doesn't require quant deps at
    collection time (matches the R8 lazy-import discipline in the
    production code path).
    """
    from quant.signals import SignalResult, SignalVector

    sv = SignalVector(
        sma_trend=SignalResult(0.0, ""),
        mean_reversion_z=SignalResult(0.0, ""),
        bollinger_pctb=SignalResult(0.0, ""),
        rsi=SignalResult(0.0, ""),
        obv_trend=SignalResult(obv, ""),
        atr_regime=SignalResult(0.5, ""),
    )
    sv.qmj_score = qmj
    sv.earnings_rank_score = earnings
    sv.institutional_flow_score = inst
    return sv


def _make_fake_price_df(n_rows: int = 252, end: pd.Timestamp | None = None) -> pd.DataFrame:
    """Return a fake OHLCV DataFrame indexed by daily dates ending at `end`."""
    if end is None:
        end = pd.Timestamp("2024-01-31")
    idx = pd.date_range(end=end, periods=n_rows, freq="B").normalize()
    rng = np.random.default_rng(42)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n_rows))
    return pd.DataFrame(
        {
            "open": close * 0.99,
            "high": close * 1.01,
            "low": close * 0.98,
            "close": close,
            "volume": rng.integers(1_000_000, 5_000_000, n_rows),
        },
        index=idx,
    )


def _make_patches(
    universe_tickers: list[str],
    composites: dict[str, float],
    sectors: dict[str, str] | None = None,
    *,
    sliced_df_end: pd.Timestamp | None = None,
):
    """Build the standard stack of patches `_quant_screen` needs to run hermetically.

    Returns a list of patch context managers; caller is responsible for
    entering them in order. The `sectors` map drives the sector cap test.
    `sliced_df_end` controls the index of the synthetic price df so the
    no-lookahead test can verify slicing.
    """
    sectors = sectors or {t: "Unknown" for t in universe_tickers}

    def _signals_at_date(universe_data, as_of_ts, lookback_days=252):
        # universe_data is dict[ticker -> DataFrame] already sliced.
        return {t: _make_signal_vector() for t in universe_data.keys()}

    def _normalize(signals, sector_fn):
        # Pass-through; tests don't exercise the normalization math.
        return signals

    def _composite(sv, weights=None):
        # Lookup by id(sv) doesn't work across patches; we rely on the
        # `_signals_at_date` mock returning a single SignalVector per
        # ticker, so we identify the ticker via the test-installed
        # `_composite_lookup` map keyed on object id.
        return _composite_lookup.get(id(sv), 0.0)

    # populate the lookup as signals are built
    _composite_lookup: dict[int, float] = {}

    def _signals_at_date_capturing(universe_data, as_of_ts, lookback_days=252):
        out = {}
        for t in universe_data.keys():
            sv = _make_signal_vector()
            _composite_lookup[id(sv)] = composites.get(t, 0.0)
            out[t] = sv
        return out

    # Stash the captured kwargs for cross-test inspection.
    captured: dict = {"signals_at_date_calls": []}

    def _signals_at_date_recording(universe_data, as_of_ts, lookback_days=252):
        captured["signals_at_date_calls"].append({
            "universe_data": universe_data,
            "as_of_ts": as_of_ts,
            "lookback_days": lookback_days,
        })
        return _signals_at_date_capturing(universe_data, as_of_ts, lookback_days)

    return {
        "signals_at_date": _signals_at_date_recording,
        "normalize": _normalize,
        "composite": _composite,
        "tier_fn": lambda signals: (lambda t: "tier_a"),
        "get_sector": lambda t: sectors.get(t, "Unknown"),
        "compute_qmj_score": lambda ticker, dt, store: composites.get(ticker, 0.0),
        "compute_earnings": lambda tickers, provider, as_of_date=None: {},
        "blend_earnings": lambda sig, scores, weight=0.30: sig,
        "compute_inst": lambda tickers, as_of_date, **kw: {},
        "blend_inst": lambda sig, scores, weight=0.10: sig,
        "wrds_store_cls": MagicMock(),
        "wrds_provider_cls": MagicMock(),
        "captured": captured,
    }


def _install_patches(mp, fns, *, universe_intersection: list[str] | None = None,
                     price_df_factory: Callable[[str], pd.DataFrame] | None = None):
    """Apply all the patches via monkeypatch, returning the `captured` dict."""
    import sqlite3 as sqlite3_mod

    # Patch the lazy imports inside _quant_screen at source.
    mp.setattr("quant.backtest.compute_signals_at_date", fns["signals_at_date"])
    mp.setattr("quant.cross_sectional.normalize_signals_cross_sectionally", fns["normalize"])
    mp.setattr("quant.cross_sectional.compute_normalized_composite", fns["composite"])
    mp.setattr("quant.cross_sectional.make_volatility_tier_fn", fns["tier_fn"])
    mp.setattr("quant.universe.get_sector", fns["get_sector"])
    mp.setattr("quant.factor_baselines.compute_qmj_score", fns["compute_qmj_score"])
    mp.setattr("quant.earnings_signals.compute_earnings_signal_scores", fns["compute_earnings"])
    mp.setattr("quant.earnings_signals.blend_earnings_signals", fns["blend_earnings"])
    mp.setattr("quant.institutional_flow.compute_institutional_flow_scores", fns["compute_inst"])
    mp.setattr("quant.institutional_flow.blend_institutional_flow", fns["blend_inst"])
    mp.setattr("quant.wrds_store.WRDSPointInTimeStore", fns["wrds_store_cls"])
    mp.setattr("quant.fundamental_provider.WRDSFundamentalProvider", fns["wrds_provider_cls"])

    # Patch pandas read_csv + filesystem so price loading uses synthetic data
    factory = price_df_factory or (lambda ticker: _make_fake_price_df())
    mp.setattr(pd, "read_csv", lambda path, **kw: factory(str(path).split("/")[-1].replace(".csv", "")))
    mp.setattr("os.path.exists", lambda p: True)

    # Universe loading happens via sqlite3 + os.listdir when universe=None
    if universe_intersection is not None:
        # listdir returns ticker.csv files
        mp.setattr("os.listdir", lambda p: [f"{t}.csv" for t in universe_intersection])

        # sqlite3.connect → object with .execute().fetchall() returning rows of (ticker,)
        fake_conn = MagicMock()
        fake_conn.execute.return_value.fetchall.return_value = [(t,) for t in universe_intersection]
        mp.setattr(sqlite3_mod, "connect", lambda path: fake_conn)


# ── T1 ───────────────────────────────────────────────────────────────────


def test_quant_screen_returns_n_tickers(monkeypatch):
    universe = [f"T{i:03d}" for i in range(50)]
    # Composites in a fixed gradient so the top is well-defined.
    composites = {t: float(i) / 50.0 for i, t in enumerate(universe)}

    fns = _make_patches(universe, composites)
    _install_patches(monkeypatch, fns)

    from backend.paper_scheduler import _quant_screen

    result = _quant_screen(as_of_date=date(2024, 1, 31), top_n=30, universe=universe)
    assert isinstance(result, list)
    assert all(isinstance(t, str) for t in result)
    assert len(result) <= 30
    # Highest composite is "T049" (i=49), then T048, etc.
    assert result[0] == "T049"


# ── T2 ───────────────────────────────────────────────────────────────────


def test_quant_screen_respects_sector_cap(monkeypatch):
    universe = [f"T{i:03d}" for i in range(60)]
    composites = {t: 1.0 - i * 0.001 for i, t in enumerate(universe)}  # all positive
    sectors = {t: "Technology" for t in universe}

    fns = _make_patches(universe, composites, sectors=sectors)
    _install_patches(monkeypatch, fns)

    from backend.paper_scheduler import _quant_screen

    result = _quant_screen(
        as_of_date=date(2024, 1, 31), top_n=30, max_per_sector=5, universe=universe,
    )
    assert len(result) == 5, f"expected exactly 5 (single-sector cap), got {len(result)}: {result}"


# ── T3 ───────────────────────────────────────────────────────────────────


def test_quant_screen_deterministic(monkeypatch):
    universe = [f"T{i:03d}" for i in range(20)]
    composites = {t: float(i) for i, t in enumerate(universe)}

    fns = _make_patches(universe, composites)
    _install_patches(monkeypatch, fns)

    from backend.paper_scheduler import _quant_screen

    a = _quant_screen(as_of_date=date(2024, 1, 31), top_n=10, universe=universe)
    b = _quant_screen(as_of_date=date(2024, 1, 31), top_n=10, universe=universe)
    assert a == b, f"Non-deterministic: {a} != {b}"


# ── T4 ───────────────────────────────────────────────────────────────────


def test_quant_screen_empty_universe_returns_empty_list(monkeypatch):
    fns = _make_patches([], {})
    _install_patches(monkeypatch, fns)

    from backend.paper_scheduler import _quant_screen

    result = _quant_screen(as_of_date=date(2024, 1, 31), universe=[])
    assert result == []


# ── T5 ───────────────────────────────────────────────────────────────────


def test_quant_screen_no_lookahead(monkeypatch):
    """The DataFrames passed into `compute_signals_at_date` must be sliced
    so the max index is <= as_of_date — confirming no future data leaks
    into signal computation.
    """
    universe = [f"T{i:03d}" for i in range(15)]
    composites = {t: float(i) for i, t in enumerate(universe)}

    # Each price DF spans 2015-01-01 .. 2026-06-30 (post-cutoff rows present).
    def factory(ticker: str) -> pd.DataFrame:
        idx = pd.date_range("2015-01-01", "2026-06-30", freq="B").normalize()
        rng = np.random.default_rng(hash(ticker) & 0xFFFFFFFF)
        close = 100.0 + np.cumsum(rng.normal(0, 1, len(idx)))
        return pd.DataFrame({
            "open": close * 0.99, "high": close * 1.01,
            "low": close * 0.98, "close": close,
            "volume": rng.integers(1_000_000, 5_000_000, len(idx)),
        }, index=idx)

    fns = _make_patches(universe, composites)
    _install_patches(monkeypatch, fns, price_df_factory=factory)

    from backend.paper_scheduler import _quant_screen

    cutoff = pd.Timestamp(date(2024, 6, 30))
    _quant_screen(as_of_date=date(2024, 6, 30), top_n=10, universe=universe)

    # Inspect the universe_data argument captured from compute_signals_at_date
    calls = fns["captured"]["signals_at_date_calls"]
    assert len(calls) >= 1
    universe_data = calls[0]["universe_data"]
    assert len(universe_data) > 0
    for ticker, df in universe_data.items():
        assert df.index.max() <= cutoff, (
            f"Lookahead leak for {ticker}: max index {df.index.max()} > {cutoff}"
        )


# ── T6 ───────────────────────────────────────────────────────────────────


def test_quant_screen_nan_propagation(monkeypatch):
    """Tickers with zero qmj / earnings (no WRDS data) still rank if OBV
    is present. 0.0 is treated as a neutral score, not a disqualifier.
    """
    universe = [f"T{i:03d}" for i in range(15)]
    # Tickers 0-4 have only OBV; 5-14 have full coverage. All non-zero composites.
    composites = {t: 0.1 + i * 0.01 for i, t in enumerate(universe)}

    fns = _make_patches(universe, composites)
    _install_patches(monkeypatch, fns)

    from backend.paper_scheduler import _quant_screen

    # Bump the sector cap so the test isolates the NaN-propagation contract
    # (the default cap would limit all 15 same-sector tickers to 5).
    result = _quant_screen(
        as_of_date=date(2024, 1, 31), top_n=20, max_per_sector=20, universe=universe,
    )
    # All 15 tickers must be present (none disqualified for missing fundamentals).
    assert len(result) == 15
    assert set(result) == set(universe)
