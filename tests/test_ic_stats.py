"""Tests for quant/ic_stats.py — overlap-aware IC significance."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from quant.ic_stats import (
    bartlett_lag,
    effective_sample_size,
    format_ic_report,
    ic_summary,
    lag1_autocorr,
    newey_west_tstat,
    newey_west_variance,
    overlap_adjusted_ic_table,
)


def _ar1(n, rho, sigma=1.0, mean=0.0, seed=0):
    rng = np.random.default_rng(seed)
    e = rng.standard_normal(n) * sigma
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = rho * x[i - 1] + e[i]
    return x + mean


# ── HAC variance reduces to IID at lag 0 ─────────────────────────────────
def test_nw_variance_lag0_matches_iid():
    x = np.random.default_rng(1).standard_normal(200)
    nw = newey_west_variance(x, lag=0)
    iid = float(np.var(x)) / x.size  # /n biased var, matches implementation
    assert nw == pytest.approx(iid, rel=1e-9)


def test_bartlett_lag_uses_overlap():
    # 6M/1M overlap => at least ceil(6)-1 = 5 lags.
    assert bartlett_lag(120, horizon_over_step=6.0) >= 5
    # No overlap info => automatic rule, small but non-negative.
    assert bartlett_lag(120) >= 0


def test_lag1_autocorr_positive_for_ar1():
    x = _ar1(500, rho=0.7, seed=2)
    ac = lag1_autocorr(x)
    assert ac is not None and ac > 0.4


# ── HAC t-stat is smaller than naive for autocorrelated series ───────────
def test_hac_tstat_deflates_positive_autocorrelation():
    # Positively autocorrelated series with a small positive mean: the naive
    # t-stat overstates significance; HAC should shrink it.
    x = _ar1(240, rho=0.6, sigma=1.0, mean=0.15, seed=3)
    n = x.size
    mean = x.mean()
    std = x.std(ddof=1)
    t_naive = mean / (std / math.sqrt(n))
    t_hac, lag = newey_west_tstat(x, horizon_over_step=6.0)
    assert lag >= 5
    assert abs(t_hac) < abs(t_naive)


def test_effective_sample_size_below_n_for_autocorr():
    x = _ar1(300, rho=0.6, seed=4)
    n_eff = effective_sample_size(x)
    assert 1.0 <= n_eff < 300


def test_effective_sample_size_near_n_for_iid():
    x = np.random.default_rng(5).standard_normal(300)
    n_eff = effective_sample_size(x)
    assert n_eff > 200  # close to n for white noise


# ── ic_summary end to end ────────────────────────────────────────────────
class TestICSummary:
    def test_overlap_downgrades_significance(self):
        # Construct an IC series that is "significant" naively but driven by
        # autocorrelation from overlapping windows.
        ic = _ar1(120, rho=0.55, sigma=0.10, mean=0.02, seed=6)
        s = ic_summary(ic, signal="erm", horizon_days=126, step_days=21)
        assert s.n == 120
        assert s.overlap_ratio == pytest.approx(6.0)
        assert s.inflation_factor > 1.0
        # Naive t larger in magnitude than HAC t.
        assert abs(s.t_naive) >= abs(s.t_hac)

    def test_iid_series_survives(self):
        rng = np.random.default_rng(7)
        # Strong, clean signal with no autocorrelation.
        ic = rng.standard_normal(120) * 0.05 + 0.05
        s = ic_summary(ic, signal="clean", horizon_days=21, step_days=21)
        assert s.verdict_naive == "SIGNIFICANT"
        assert s.verdict_hac == "SIGNIFICANT"
        assert s.survives_correction is True

    def test_insufficient_sample(self):
        s = ic_summary([0.1, 0.2, 0.3], signal="x", min_n=36)
        assert s.verdict_naive == "INSUFFICIENT"
        assert s.verdict_hac == "INSUFFICIENT"

    def test_empty(self):
        s = ic_summary([], signal="x")
        assert s.n == 0
        assert not s.survives_correction

    def test_handles_nans(self):
        s = ic_summary([0.1, float("nan"), 0.2, 0.3, float("nan")], signal="x", min_n=2)
        assert s.n == 3


# ── table + report ───────────────────────────────────────────────────────
def test_overlap_adjusted_ic_table_and_report():
    dates = pd.date_range("2015-01-31", periods=120, freq="ME")
    df = pd.DataFrame(
        {
            "autocorr_sig": _ar1(120, rho=0.55, sigma=0.10, mean=0.02, seed=8),
            "clean_sig": np.random.default_rng(9).standard_normal(120) * 0.05 + 0.05,
            "noise": np.random.default_rng(10).standard_normal(120) * 0.10,
        },
        index=dates,
    )
    out = overlap_adjusted_ic_table(df, horizon_days=126, step_days=21)
    assert set(out.index) == {"autocorr_sig", "clean_sig", "noise"}
    for col in (
        "t_naive",
        "t_hac",
        "verdict_naive",
        "verdict_hac",
        "inflation_factor",
        "survives_correction",
    ):
        assert col in out.columns
    report = format_ic_report(out)
    assert "OVERLAP-CORRECTED IC SIGNIFICANCE" in report
    assert "t_HAC" in report
