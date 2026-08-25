"""Tests for quant/scoring.py — threshold constants and direction classification."""

from __future__ import annotations

import pytest

from quant.scoring import (
    ACTIONABLE_THRESHOLD,
    BUY_THRESHOLD,
    SELL_THRESHOLD,
    classify_direction,
    reclassify,
)
from quant.signals import SignalResult, SignalVector


# ── Constants ────────────────────────────────────────────────────────────


class TestConstants:
    def test_thresholds_are_symmetric(self):
        assert BUY_THRESHOLD == -SELL_THRESHOLD

    def test_actionable_above_buy(self):
        assert ACTIONABLE_THRESHOLD > BUY_THRESHOLD

    def test_values(self):
        assert BUY_THRESHOLD == 0.30
        assert SELL_THRESHOLD == -0.30
        assert ACTIONABLE_THRESHOLD == 0.40


# ── classify_direction ───────────────────────────────────────────────────


class TestClassifyDirection:
    def test_strong_buy(self):
        direction, actionable = classify_direction(0.80)
        assert direction == "BUY"
        assert actionable is True

    def test_weak_buy(self):
        direction, actionable = classify_direction(0.35)
        assert direction == "BUY"
        assert actionable is False

    def test_exact_buy_threshold(self):
        direction, actionable = classify_direction(0.30)
        assert direction == "BUY"
        assert actionable is False

    def test_hold(self):
        direction, actionable = classify_direction(0.0)
        assert direction == "HOLD"
        assert actionable is False

    def test_hold_just_below_buy(self):
        direction, actionable = classify_direction(0.29)
        assert direction == "HOLD"
        assert actionable is False

    def test_hold_just_above_sell(self):
        direction, actionable = classify_direction(-0.29)
        assert direction == "HOLD"
        assert actionable is False

    def test_exact_sell_threshold(self):
        direction, actionable = classify_direction(-0.30)
        assert direction == "SELL"
        assert actionable is False

    def test_strong_sell(self):
        direction, actionable = classify_direction(-0.80)
        assert direction == "SELL"
        assert actionable is True

    def test_exact_actionable_threshold(self):
        direction, actionable = classify_direction(0.40)
        assert direction == "BUY"
        assert actionable is True

    def test_negative_actionable_threshold(self):
        direction, actionable = classify_direction(-0.40)
        assert direction == "SELL"
        assert actionable is True

    def test_extreme_values(self):
        d1, a1 = classify_direction(1.0)
        assert d1 == "BUY" and a1 is True
        d2, a2 = classify_direction(-1.0)
        assert d2 == "SELL" and a2 is True


# ── reclassify ───────────────────────────────────────────────────────────


def _make_sv(composite_score: float = 0.0) -> SignalVector:
    """Create a minimal SignalVector with a given composite score."""
    sv = SignalVector(
        sma_trend=SignalResult(0.0),
        mean_reversion_z=SignalResult(0.0),
        bollinger_pctb=SignalResult(0.0),
        rsi=SignalResult(0.0),
        obv_trend=SignalResult(0.0),
        atr_regime=SignalResult(0.0),
    )
    sv.composite_score = composite_score
    return sv


class TestReclassify:
    def test_buy(self):
        sv = _make_sv(0.50)
        reclassify(sv)
        assert sv.composite_direction == "BUY"
        assert sv.actionable is True

    def test_sell(self):
        sv = _make_sv(-0.50)
        reclassify(sv)
        assert sv.composite_direction == "SELL"
        assert sv.actionable is True

    def test_hold(self):
        sv = _make_sv(0.10)
        reclassify(sv)
        assert sv.composite_direction == "HOLD"
        assert sv.actionable is False

    def test_mutates_in_place(self):
        sv = _make_sv(0.50)
        sv.composite_direction = "HOLD"  # wrong initial state
        sv.actionable = False
        reclassify(sv)
        assert sv.composite_direction == "BUY"
        assert sv.actionable is True

    def test_preserves_other_fields(self):
        sv = _make_sv(0.50)
        sv.flags.append("test_flag")
        sv.earnings_rank_score = 0.75
        reclassify(sv)
        assert "test_flag" in sv.flags
        assert sv.earnings_rank_score == 0.75
        assert sv.composite_score == 0.50  # score not touched


# ── Integration: compute_composite uses reclassify ───────────────────────


class TestComputeCompositeIntegration:
    def test_compute_composite_sets_direction(self):
        sv = SignalVector(
            sma_trend=SignalResult(0.8),
            mean_reversion_z=SignalResult(0.6),
            bollinger_pctb=SignalResult(0.7),
            rsi=SignalResult(0.5),
            obv_trend=SignalResult(0.9),
            atr_regime=SignalResult(0.1),
        )
        sv.compute_composite()
        assert sv.composite_direction == "BUY"
        assert sv.actionable == True
        assert sv.composite_score > BUY_THRESHOLD

    def test_compute_composite_bearish(self):
        sv = SignalVector(
            sma_trend=SignalResult(-0.8),
            mean_reversion_z=SignalResult(-0.6),
            bollinger_pctb=SignalResult(-0.7),
            rsi=SignalResult(-0.5),
            obv_trend=SignalResult(-0.9),
            atr_regime=SignalResult(-0.1),
        )
        sv.compute_composite()
        assert sv.composite_direction == "SELL"
        assert sv.actionable == True

    def test_compute_composite_neutral(self):
        sv = SignalVector(
            sma_trend=SignalResult(0.1),
            mean_reversion_z=SignalResult(-0.1),
            bollinger_pctb=SignalResult(0.05),
            rsi=SignalResult(-0.05),
            obv_trend=SignalResult(0.0),
            atr_regime=SignalResult(0.0),
        )
        sv.compute_composite()
        assert sv.composite_direction == "HOLD"
        assert sv.actionable == False
