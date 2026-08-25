"""Tests for cross-sectional signal normalization."""

import numpy as np
import pytest
from quant.signals import SignalResult, SignalVector


def _make_sv(obv=0.0, earnings=0.0, inst_flow=0.0, sentiment=0.0):
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
    def test_normalization_centers_scores(self):
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
            "AAPL": "Tech",
            "MSFT": "Tech",
            "GOOGL": "Tech",
            "JPM": "Financials",
            "BAC": "Financials",
            "GS": "Financials",
            "XOM": "Energy",
            "CVX": "Energy",
            "KO": "Staples",
            "PG": "Staples",
        }[t]

        result = normalize_signals_cross_sectionally(signals, sector_fn)

        obv_scores = [sv.obv_trend.score for sv in result.values()]
        assert abs(np.mean(obv_scores)) < 0.15

    def test_sector_adjustment_reranks(self):
        from quant.cross_sectional import normalize_signals_cross_sectionally

        signals = {
            "AAPL": _make_sv(obv=0.35),
            "MSFT": _make_sv(obv=0.40),
            "GOOGL": _make_sv(obv=0.30),
            "DUK": _make_sv(obv=0.25),
            "SO": _make_sv(obv=0.05),
            "AEP": _make_sv(obv=0.00),
            "JPM": _make_sv(obv=0.10),
            "BAC": _make_sv(obv=0.15),
            "KO": _make_sv(obv=0.05),
            "PG": _make_sv(obv=0.00),
        }

        sector_fn = lambda t: {
            "AAPL": "Tech",
            "MSFT": "Tech",
            "GOOGL": "Tech",
            "DUK": "Utilities",
            "SO": "Utilities",
            "AEP": "Utilities",
            "JPM": "Financials",
            "BAC": "Financials",
            "KO": "Staples",
            "PG": "Staples",
        }[t]

        result = normalize_signals_cross_sectionally(signals, sector_fn)

        duk_obv = result["DUK"].obv_trend.score
        aapl_obv = result["AAPL"].obv_trend.score
        assert duk_obv > aapl_obv, f"DUK ({duk_obv:.3f}) should outrank AAPL ({aapl_obv:.3f})"

    def test_scores_bounded(self):
        from quant.cross_sectional import normalize_signals_cross_sectionally

        signals = {f"T{i}": _make_sv(obv=float(i) / 10 - 0.5) for i in range(15)}

        result = normalize_signals_cross_sectionally(signals, lambda t: "Same")

        for sv in result.values():
            assert -1.0 <= sv.obv_trend.score <= 1.0

    def test_skip_if_too_few_tickers(self):
        from quant.cross_sectional import normalize_signals_cross_sectionally

        signals = {
            "AAPL": _make_sv(obv=0.8),
            "MSFT": _make_sv(obv=0.2),
        }

        result = normalize_signals_cross_sectionally(signals, lambda t: "Tech")

        assert result["AAPL"].obv_trend.score == 0.8
        assert result["MSFT"].obv_trend.score == 0.2


class TestComputeNormalizedComposite:
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
        expected = (0.8 * 0.40 + 0.4 * 0.30 + 0.2 * 0.15 + 0.1 * 0.10) / (0.40 + 0.30 + 0.15 + 0.10)
        assert abs(score - expected) < 0.01

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
        from quant.cross_sectional import compute_normalized_composite

        sv = _make_sv(obv=0.6, earnings=0.0, inst_flow=0.0, sentiment=0.0)

        weights = {
            "obv_trend": 0.40,
            "earnings_rank_score": 0.30,
            "institutional_flow_score": 0.15,
            "sentiment_score": 0.10,
        }

        score = compute_normalized_composite(sv, weights)
        expected = (0.6 * 0.40) / (0.40 + 0.30 + 0.15 + 0.10)
        assert abs(score - expected) < 0.01
