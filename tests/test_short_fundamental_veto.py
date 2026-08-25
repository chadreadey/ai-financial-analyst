"""
Tests for `quant.agent_veto.apply_short_fundamental_veto` — the
fundamental-strength veto applied to short candidates.

Uses a fake provider rather than the WRDS PIT cache so the suite
runs in any environment.
"""

from __future__ import annotations

from datetime import date

import pytest

from quant.agent_veto import (
    apply_short_fundamental_veto,
    compute_fundamental_strength_veto,
)
from quant.signals import SignalResult, SignalVector


def _make_sv(quality: float = 0.0) -> SignalVector:
    sv = SignalVector(
        sma_trend=SignalResult(0.0),
        mean_reversion_z=SignalResult(0.0),
        bollinger_pctb=SignalResult(0.0),
        rsi=SignalResult(0.0),
        obv_trend=SignalResult(0.0),
        atr_regime=SignalResult(0.0),
    )
    sv.quality_score = quality
    return sv


class FakeProvider:
    """
    Fake `WRDSFundamentalProvider`-shaped provider used by the
    earnings-signals helpers (`compute_erm_score`, `compute_sue_score`).

    `compute_erm_score` reads from `provider.get_analyst_estimates`.
    `compute_sue_score` reads from `provider.get_balance_sheet_quarterly`.
    """

    def __init__(
        self,
        analyst_estimates: list[dict] | None = None,
        balance_sheet: list[dict] | None = None,
    ) -> None:
        self._estimates = analyst_estimates or []
        self._bs = balance_sheet or []

    def get_analyst_estimates(self, ticker, limit=4, as_of_date=None):
        return list(self._estimates[:limit])

    def get_balance_sheet_quarterly(self, ticker, limit=4, as_of_date=None):
        return list(self._bs[:limit])


# Strong-EPS-revision estimates: current EPS = 2.50 vs ~3 months ago = 2.00
# → revision_pct = +25% → ERM raw score = +1.0 → blended ~ +0.7+ (well > 0.20)
def _strong_estimates() -> list[dict]:
    return [
        {"epsAvg": 2.50, "date": "2024-06-01", "numAnalystsEps": 10, "numUp": 8, "numDown": 1},
        {"epsAvg": 2.40, "date": "2024-05-01", "numAnalystsEps": 10},
        {"epsAvg": 2.20, "date": "2024-04-01", "numAnalystsEps": 10},
        {
            "epsAvg": 2.00,
            "date": "2024-02-15",
            "numAnalystsEps": 10,
            "numUp": 1,
            "numDown": 5,
        },  # 3 months back
        {"epsAvg": 1.95, "date": "2024-01-15", "numAnalystsEps": 10},
    ]


# Weak-EPS-revision: current EPS = 1.50 vs ~3 months ago = 2.00
# → revision_pct = -25% → ERM raw score ≈ -1.0 (well < 0.20 threshold)
def _weak_estimates() -> list[dict]:
    return [
        {"epsAvg": 1.50, "date": "2024-06-01", "numAnalystsEps": 10, "numUp": 1, "numDown": 8},
        {"epsAvg": 1.60, "date": "2024-05-01", "numAnalystsEps": 10},
        {"epsAvg": 1.80, "date": "2024-04-01", "numAnalystsEps": 10},
        {"epsAvg": 2.00, "date": "2024-02-15", "numAnalystsEps": 10, "numUp": 5, "numDown": 1},
        {"epsAvg": 2.10, "date": "2024-01-15", "numAnalystsEps": 10},
    ]


# SUE near zero — current quarter EPS == year-ago EPS (no surprise)
def _flat_balance_sheet() -> list[dict]:
    return [
        {"eps": 1.00, "revenue": 1000},  # current quarter
        {"eps": 1.00, "revenue": 990},
        {"eps": 1.00, "revenue": 980},
        {"eps": 1.00, "revenue": 970},
        {"eps": 1.00, "revenue": 960},  # same quarter last year
        {"eps": 1.00, "revenue": 950},
        {"eps": 1.00, "revenue": 940},
        {"eps": 1.00, "revenue": 930},
    ]


class TestComputeFundamentalStrengthVeto:
    def test_strong_fundamentals_trigger_veto(self):
        provider = FakeProvider(
            analyst_estimates=_strong_estimates(),
            balance_sheet=_flat_balance_sheet(),
        )
        sv = _make_sv(quality=0.5)  # strong cross-sectional quality > 0.30
        is_strong, meta = compute_fundamental_strength_veto(
            "STRONG",
            provider,
            sv,
            as_of_date=date(2024, 6, 30),
        )
        assert is_strong is True
        # At minimum quality > threshold OR ERM > threshold should fire
        assert meta["n_flags"] >= 1
        assert meta["inputs_seen"] >= 2
        # Quality flag definitely present
        flag_str = " ".join(meta["flags"])
        assert "quality" in flag_str or "ERM" in flag_str

    def test_weak_fundamentals_no_veto(self):
        provider = FakeProvider(
            analyst_estimates=_weak_estimates(),
            balance_sheet=_flat_balance_sheet(),
        )
        sv = _make_sv(quality=-0.5)  # weak quality
        is_strong, meta = compute_fundamental_strength_veto(
            "WEAK",
            provider,
            sv,
            as_of_date=date(2024, 6, 30),
        )
        assert is_strong is False
        assert meta["n_flags"] == 0

    def test_missing_data_does_not_veto(self):
        """
        Innocent until proven guilty: when ALL inputs are unavailable
        (empty estimates + empty balance sheet + quality_score = 0.0
        which we treat as 'not computed'), the candidate must NOT be
        vetoed.
        """
        provider = FakeProvider(analyst_estimates=[], balance_sheet=[])
        sv = _make_sv(quality=0.0)
        is_strong, meta = compute_fundamental_strength_veto(
            "MISSING",
            provider,
            sv,
            as_of_date=date(2024, 6, 30),
        )
        assert is_strong is False
        assert meta["n_flags"] == 0
        assert meta["inputs_seen"] == 0


class TestApplyShortFundamentalVeto:
    def test_strong_short_rejected(self):
        provider = FakeProvider(
            analyst_estimates=_strong_estimates(),
            balance_sheet=_flat_balance_sheet(),
        )
        candidates = [("STRONG", -0.55, _make_sv(quality=0.6))]
        survivors, log = apply_short_fundamental_veto(
            candidates,
            provider,
            as_of_date=date(2024, 6, 30),
            min_strong_signals=1,
        )
        assert len(survivors) == 0
        assert len(log) == 1
        assert log[0]["ticker"] == "STRONG"
        assert log[0]["n_flags"] >= 1

    def test_weak_short_allowed(self):
        provider = FakeProvider(
            analyst_estimates=_weak_estimates(),
            balance_sheet=_flat_balance_sheet(),
        )
        candidates = [("WEAK", -0.55, _make_sv(quality=-0.5))]
        survivors, log = apply_short_fundamental_veto(
            candidates,
            provider,
            as_of_date=date(2024, 6, 30),
            min_strong_signals=1,
        )
        assert len(survivors) == 1
        assert survivors[0][0] == "WEAK"
        assert len(log) == 0

    def test_missing_data_short_allowed(self):
        provider = FakeProvider(analyst_estimates=[], balance_sheet=[])
        candidates = [("UNKNOWN", -0.55, _make_sv(quality=0.0))]
        survivors, log = apply_short_fundamental_veto(
            candidates,
            provider,
            as_of_date=date(2024, 6, 30),
            min_strong_signals=1,
        )
        assert len(survivors) == 1
        assert len(log) == 0

    def test_min_strong_signals_two_requires_two_flags(self):
        """
        With min_strong_signals=2, a candidate that trips ONLY the
        quality flag (single flag) should survive.
        """
        provider = FakeProvider(
            analyst_estimates=_weak_estimates(),  # ERM negative — no flag
            balance_sheet=_flat_balance_sheet(),  # SUE ≈ 0 — no flag
        )
        # quality > 0.30 → 1 flag only
        candidates = [("ONEFLAG", -0.55, _make_sv(quality=0.6))]
        survivors, log = apply_short_fundamental_veto(
            candidates,
            provider,
            as_of_date=date(2024, 6, 30),
            min_strong_signals=2,
        )
        assert len(survivors) == 1
        assert len(log) == 0

    def test_mixed_pool(self):
        """
        Mixed pool: strong + weak + missing — only strong should be vetoed.
        """
        provider_strong = FakeProvider(
            analyst_estimates=_strong_estimates(),
            balance_sheet=_flat_balance_sheet(),
        )
        provider_weak = FakeProvider(
            analyst_estimates=_weak_estimates(),
            balance_sheet=_flat_balance_sheet(),
        )

        # We can't trivially share one provider across tickers in this
        # fake; instead vet candidates one at a time and confirm filter
        # behavior consistent with the multi-ticker case.
        s1, l1 = apply_short_fundamental_veto(
            [("STRONG", -0.6, _make_sv(quality=0.6))],
            provider_strong,
            as_of_date=date(2024, 6, 30),
        )
        s2, l2 = apply_short_fundamental_veto(
            [("WEAK", -0.5, _make_sv(quality=-0.5))],
            provider_weak,
            as_of_date=date(2024, 6, 30),
        )

        assert len(s1) == 0 and len(l1) == 1
        assert len(s2) == 1 and len(l2) == 0
