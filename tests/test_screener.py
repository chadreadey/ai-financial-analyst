"""Tests for the lean-quant screener composite (Phase 1)."""

from __future__ import annotations

from quant.screener import (
    SCREENER_WEIGHTS,
    Candidate,
    candidates_to_dict,
    compute_screener_composite,
    select_candidates,
)
from quant.signals import SignalResult, SignalVector


def _make_sv(qmj=0.0, sue=0.0, erm=0.0, earnings=0.0):
    sv = SignalVector(
        sma_trend=SignalResult(0.0),
        mean_reversion_z=SignalResult(0.0),
        bollinger_pctb=SignalResult(0.0),
        rsi=SignalResult(0.0),
        obv_trend=SignalResult(0.0),
        atr_regime=SignalResult(0.0),
    )
    sv.qmj_score = qmj
    sv.erm_earnings_score = erm  # type: ignore[attr-defined]
    sv.sue_earnings_score = sue  # type: ignore[attr-defined]
    sv.earnings_rank_score = earnings
    return sv


class TestScreenerWeights:
    def test_weights_sum_to_one(self):
        assert abs(sum(SCREENER_WEIGHTS.values()) - 1.0) < 1e-9

    def test_all_survivors_positive_weight(self):
        for signal, weight in SCREENER_WEIGHTS.items():
            assert weight > 0, f"{signal} should have positive t-stat-derived weight"

    def test_qmj_is_highest_weighted(self):
        assert SCREENER_WEIGHTS["qmj_score"] == max(SCREENER_WEIGHTS.values())


class TestComputeScreenerComposite:
    def test_weighted_average(self):
        sv = _make_sv(qmj=0.8, sue=0.4, erm=0.2)
        composite, contribs = compute_screener_composite(sv)
        expected = (
            0.8 * SCREENER_WEIGHTS["qmj_score"]
            + 0.4 * SCREENER_WEIGHTS["sue_earnings_score"]
            + 0.2 * SCREENER_WEIGHTS["erm_earnings_score"]
        )
        assert abs(composite - expected) < 1e-6
        assert set(contribs.keys()) == set(SCREENER_WEIGHTS.keys())

    def test_composite_clipped_to_unit(self):
        sv = _make_sv(qmj=5.0, sue=5.0, erm=5.0)
        composite, _ = compute_screener_composite(sv)
        assert -1.0 <= composite <= 1.0

    def test_legacy_earnings_fallback(self):
        sv = SignalVector(
            sma_trend=SignalResult(0.0),
            mean_reversion_z=SignalResult(0.0),
            bollinger_pctb=SignalResult(0.0),
            rsi=SignalResult(0.0),
            obv_trend=SignalResult(0.0),
            atr_regime=SignalResult(0.0),
        )
        sv.qmj_score = 0.5
        sv.earnings_rank_score = 0.4
        composite, _ = compute_screener_composite(sv)
        earnings_w = SCREENER_WEIGHTS["sue_earnings_score"] + SCREENER_WEIGHTS["erm_earnings_score"]
        expected = 0.5 * SCREENER_WEIGHTS["qmj_score"] + 0.4 * earnings_w
        assert abs(composite - expected) < 1e-6

    def test_all_zeros_yields_zero(self):
        sv = _make_sv()
        composite, _ = compute_screener_composite(sv)
        assert composite == 0.0


class TestSelectCandidates:
    def _mk_universe(self, n=20):
        signals = {}
        for i in range(n):
            signals[f"T{i}"] = _make_sv(qmj=(i / n - 0.5), sue=(i / n - 0.5))
        return signals

    def test_top_n_respected(self):
        signals = self._mk_universe(20)
        candidates = select_candidates(signals, sector_fn=lambda t: "S", top_n=5)
        assert len(candidates) == 5

    def test_ordered_by_composite_desc(self):
        signals = self._mk_universe(10)
        candidates = select_candidates(signals, sector_fn=lambda t: "S", top_n=10)
        for a, b in zip(candidates, candidates[1:]):
            assert a.composite >= b.composite

    def test_sector_cap_enforced(self):
        signals = {}
        for i in range(10):
            signals[f"TECH{i}"] = _make_sv(qmj=0.9 - i * 0.01)
        for i in range(5):
            signals[f"UTIL{i}"] = _make_sv(qmj=0.4 - i * 0.01)
        sectors = {t: ("Tech" if t.startswith("TECH") else "Utilities") for t in signals}
        candidates = select_candidates(
            signals,
            sector_fn=lambda t: sectors[t],
            top_n=8,
            max_per_sector=3,
        )
        by_sector: dict[str, int] = {}
        for c in candidates:
            by_sector[c.sector] = by_sector.get(c.sector, 0) + 1
        assert by_sector.get("Tech", 0) <= 3
        assert by_sector.get("Utilities", 0) <= 5

    def test_min_composite_floor(self):
        signals = self._mk_universe(20)
        candidates = select_candidates(
            signals,
            sector_fn=lambda t: "S",
            top_n=50,
            min_composite=0.0,
        )
        assert all(c.composite >= 0.0 for c in candidates)

    def test_no_sector_cap_returns_pure_topn(self):
        signals = self._mk_universe(30)
        cands = select_candidates(signals, sector_fn=lambda t: "S", top_n=10)
        assert len(cands) == 10


class TestSelectCandidatesFromPanel:
    def test_panel_ranking_matches_signal_vector_ranking(self):
        import pandas as pd

        from quant.screener import select_candidates_from_panel

        # Panel with 5 tickers ranked by qmj (already normalized)
        panel = pd.DataFrame(
            {
                "qmj": [0.9, 0.6, 0.1, -0.2, -0.8],
                "sue": [0.5, 0.3, 0.0, -0.1, -0.5],
                "erm": [0.4, 0.2, 0.0, -0.1, -0.4],
            },
            index=["A", "B", "C", "D", "E"],
        )
        cands = select_candidates_from_panel(
            panel,
            sector_fn=lambda t: "S",
            top_n=3,
            already_normalized=True,
        )
        assert [c.ticker for c in cands] == ["A", "B", "C"]

    def test_panel_handles_nan_columns(self):
        import numpy as np
        import pandas as pd

        from quant.screener import select_candidates_from_panel

        panel = pd.DataFrame(
            {
                "qmj": [0.9, 0.6, np.nan, -0.2, -0.8],
                "sue": [0.5, np.nan, 0.0, -0.1, -0.5],
                "erm": [0.4, 0.2, 0.0, np.nan, -0.4],
            },
            index=["A", "B", "C", "D", "E"],
        )
        cands = select_candidates_from_panel(
            panel,
            sector_fn=lambda t: "S",
            top_n=5,
            already_normalized=True,
        )
        # All 5 should be scorable (NaN => 0 contribution)
        assert len(cands) == 5

    def test_panel_normalizes_by_default(self):
        import pandas as pd

        from quant.screener import select_candidates_from_panel

        # Very large raw values that would blow up an un-normalized composite
        panel = pd.DataFrame(
            {
                "qmj": [100.0, 80.0, 60.0, 40.0, 20.0, 10.0, 5.0, 3.0, 1.0, 0.0],
                "sue": [50.0, 40.0, 30.0, 20.0, 10.0, 5.0, 3.0, 1.0, 0.0, -5.0],
                "erm": [30.0, 25.0, 20.0, 15.0, 10.0, 5.0, 0.0, -5.0, -10.0, -15.0],
            },
            index=[f"T{i}" for i in range(10)],
        )
        cands = select_candidates_from_panel(
            panel,
            sector_fn=lambda t: "S",
            top_n=10,
        )
        # Composites remain bounded to [-1, +1] after normalization
        for c in cands:
            assert -1.0 <= c.composite <= 1.0


class TestSerialization:
    def test_candidates_to_dict(self):
        cands = [
            Candidate(
                ticker="AAPL",
                composite=0.35,
                sector="Tech",
                contributions={"qmj_score": 0.2, "sue_earnings_score": 0.1},
            )
        ]
        out = candidates_to_dict(cands)
        assert out == [
            {
                "ticker": "AAPL",
                "composite": 0.35,
                "sector": "Tech",
                "contributions": {"qmj_score": 0.2, "sue_earnings_score": 0.1},
            }
        ]
