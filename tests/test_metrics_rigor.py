"""Tests for the rigor layer added to quant/metrics.py (audit A1-A4).

These cover the new, opt-in functions only. The legacy compute_sharpe /
compute_sortino behavior is covered (and must stay unchanged) by
tests/test_metrics.py.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from quant.metrics import (
    compute_downside_deviation,
    compute_information_ratio,
    compute_sharpe,
    compute_sharpe_stats,
    compute_sortino,
    compute_sortino_target,
    sharpe_standard_error,
)


@pytest.fixture()
def rng():
    return np.random.default_rng(42)


# ── legacy functions are untouched ───────────────────────────────────────
def test_legacy_sharpe_still_works(rng):
    r = pd.Series(rng.standard_normal(252) * 0.01 + 0.0003)
    assert compute_sharpe(r) is not None
    assert compute_sortino(r) is not None


# ── Sharpe standard error / t-stat ───────────────────────────────────────
class TestSharpeStats:
    def test_returns_dict_with_error_bars(self, rng):
        r = pd.Series(rng.standard_normal(252) * 0.01 + 0.0005)
        stats = compute_sharpe_stats(r, autocorr_adjust=False)
        assert stats is not None
        assert set(stats) >= {"sharpe", "se", "t_stat", "n", "autocorr_inflation"}
        assert stats["n"] == 252
        assert stats["se"] > 0
        # t-stat consistency: sharpe / se within rounding.
        assert stats["t_stat"] == pytest.approx(stats["sharpe"] / stats["se"], rel=1e-2)

    def test_lo_se_formula(self):
        # SE = sqrt((1 + 0.5 SR^2)/n)
        se = sharpe_standard_error(100, 0.2)
        assert se == pytest.approx(math.sqrt((1 + 0.5 * 0.04) / 100), rel=1e-9)

    def test_autocorr_inflates_se(self):
        # Positively autocorrelated returns -> larger SE, smaller |t| than IID.
        n = 500
        e = np.random.default_rng(1).standard_normal(n) * 0.01
        x = np.zeros(n)
        for i in range(1, n):
            x[i] = 0.5 * x[i - 1] + e[i] + 0.0004
        r = pd.Series(x)
        iid = compute_sharpe_stats(r, autocorr_adjust=False)
        adj = compute_sharpe_stats(r, autocorr_adjust=True)
        assert adj["autocorr_inflation"] > 1.0
        assert adj["se"] > iid["se"]
        assert abs(adj["t_stat"]) < abs(iid["t_stat"])

    def test_risk_free_reduces_sharpe(self, rng):
        r = pd.Series(rng.standard_normal(252) * 0.01 + 0.001)
        no_rf = compute_sharpe_stats(r, risk_free_annual=0.0, autocorr_adjust=False)
        with_rf = compute_sharpe_stats(r, risk_free_annual=0.05, autocorr_adjust=False)
        assert with_rf["sharpe"] < no_rf["sharpe"]

    def test_too_few_obs(self):
        assert compute_sharpe_stats(pd.Series([0.01, 0.02]), min_observations=10) is None


# ── downside deviation / target Sortino ──────────────────────────────────
class TestSortinoTarget:
    def test_downside_deviation_definition(self):
        # Known series: returns [-0.02, 0.01, -0.01, 0.03], MAR=0
        r = pd.Series([-0.02, 0.01, -0.01, 0.03])
        dd = compute_downside_deviation(r, mar_annual=0.0)
        expected = math.sqrt(((-0.02) ** 2 + 0.0 + (-0.01) ** 2 + 0.0) / 4)
        assert dd == pytest.approx(expected, rel=1e-9)

    def test_differs_from_legacy_sortino(self, rng):
        # The corrected Sortino should generally differ from the legacy one.
        r = pd.Series(rng.standard_normal(252) * 0.01 + 0.0004)
        legacy = compute_sortino(r)
        target = compute_sortino_target(r)
        assert legacy is not None and target is not None
        assert legacy != target

    def test_all_positive_returns_no_downside(self):
        r = pd.Series([0.01] * 50)
        assert compute_downside_deviation(r) == 0.0
        # zero downside deviation -> ratio undefined -> None
        assert compute_sortino_target(r) is None

    def test_too_few_obs(self):
        assert compute_sortino_target(pd.Series([0.01, 0.02]), min_observations=10) is None


# ── information ratio ─────────────────────────────────────────────────────
class TestInformationRatio:
    def test_zero_when_identical(self, rng):
        r = pd.Series(rng.standard_normal(252) * 0.01)
        assert compute_information_ratio(r, r.copy()) is None  # zero TE -> undefined

    def test_positive_when_outperforming(self, rng):
        b = pd.Series(rng.standard_normal(252) * 0.01)
        r = b + 0.001  # constant outperformance -> zero TE though
        # add noise so tracking error is nonzero
        r = b + rng.standard_normal(252) * 0.002 + 0.0005
        ir = compute_information_ratio(r, b)
        assert ir is not None
        assert ir > 0

    def test_index_alignment(self, rng):
        idx = pd.date_range("2024-01-01", periods=300, freq="B")
        r = pd.Series(rng.standard_normal(300) * 0.01 + 0.0004, index=idx)
        b = pd.Series(rng.standard_normal(300) * 0.01, index=idx)
        # misaligned subset should still align on the intersection
        ir_full = compute_information_ratio(r, b)
        ir_sub = compute_information_ratio(r, b.iloc[50:])
        assert ir_full is not None and ir_sub is not None
