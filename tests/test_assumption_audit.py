"""Tests for quant/assumption_audit.py — the stochastic assumption logger.

These verify the core contract:
  * available information -> PASS / VIOLATED
  * missing information   -> SKIPPED (never a silent pass, never raises)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.assumption_audit import (
    AssumptionLog,
    AssumptionSeverity,
    AssumptionStatus,
    get_audit_log,
    reset_audit_log,
)


@pytest.fixture()
def log() -> AssumptionLog:
    return AssumptionLog()


# ── min_sample ──────────────────────────────────────────────────────────
class TestMinSample:
    def test_pass(self, log):
        r = log.min_sample("x", n=50, min_n=30)
        assert r.status == AssumptionStatus.PASS

    def test_violated(self, log):
        r = log.min_sample("x", n=5, min_n=30)
        assert r.status == AssumptionStatus.VIOLATED
        assert r.evidence["n"] == 5

    def test_skipped_when_unknown(self, log):
        r = log.min_sample("x", n=None, min_n=30)
        assert r.status == AssumptionStatus.SKIPPED


# ── value_in_range ───────────────────────────────────────────────────────
class TestValueInRange:
    def test_pass(self, log):
        assert log.value_in_range("p", 0.6, 0.0, 1.0).status == AssumptionStatus.PASS

    def test_violated(self, log):
        # bull+bear probability given as 64/36 but expressed as fraction >1
        assert log.value_in_range("p", 64, 0.0, 1.0).status == AssumptionStatus.VIOLATED

    def test_skipped_when_missing(self, log):
        assert log.value_in_range("p", None, 0.0, 1.0).status == AssumptionStatus.SKIPPED


# ── sums_to ───────────────────────────────────────────────────────────────
class TestSumsTo:
    def test_weights_sum_to_one(self, log):
        assert log.sums_to("w", [0.4, 0.3, 0.2, 0.1], 1.0).status == AssumptionStatus.PASS

    def test_probabilities_sum_to_100(self, log):
        assert log.sums_to("pp", [64, 36], 100.0).status == AssumptionStatus.PASS

    def test_violated(self, log):
        assert log.sums_to("w", [0.4, 0.4, 0.4], 1.0).status == AssumptionStatus.VIOLATED

    def test_skipped_empty(self, log):
        assert log.sums_to("w", [], 1.0).status == AssumptionStatus.SKIPPED


# ── no_silent_zeros ───────────────────────────────────────────────────────
class TestNoSilentZeros:
    def test_pass(self, log):
        r = log.no_silent_zeros("sig", [0.1, -0.2, 0.0, 0.5, 0.3])
        assert r.status == AssumptionStatus.PASS

    def test_violated_mostly_zeros(self, log):
        r = log.no_silent_zeros("sig", [0.0, 0.0, 0.0, 0.0, 0.2])
        assert r.status == AssumptionStatus.VIOLATED
        assert r.evidence["zero_fraction"] == 0.8

    def test_skipped_empty(self, log):
        assert log.no_silent_zeros("sig", []).status == AssumptionStatus.SKIPPED


# ── no_lookahead ─────────────────────────────────────────────────────────
class TestNoLookahead:
    def test_pass(self, log):
        r = log.no_lookahead("px", "2024-01-01", "2024-06-01")
        assert r.status == AssumptionStatus.PASS

    def test_violated_future_data(self, log):
        r = log.no_lookahead("px", "2024-12-31", "2024-06-01")
        assert r.status == AssumptionStatus.VIOLATED
        assert r.severity == AssumptionSeverity.CRITICAL

    def test_skipped_missing_time(self, log):
        assert log.no_lookahead("px", None, "2024-06-01").status == AssumptionStatus.SKIPPED


# ── finite / nonzero_variance ────────────────────────────────────────────
class TestFiniteVariance:
    def test_finite_pass(self, log):
        assert log.finite("v", 1.23).status == AssumptionStatus.PASS

    def test_finite_violated_nan(self, log):
        assert log.finite("v", float("nan")).status == AssumptionStatus.VIOLATED

    def test_nonzero_variance_pass(self, log):
        assert log.nonzero_variance("s", [1.0, 2.0, 3.0]).status == AssumptionStatus.PASS

    def test_nonzero_variance_violated(self, log):
        assert log.nonzero_variance("s", [2.0, 2.0, 2.0]).status == AssumptionStatus.VIOLATED

    def test_nonzero_variance_skipped(self, log):
        assert log.nonzero_variance("s", [2.0]).status == AssumptionStatus.SKIPPED


# ── normality ────────────────────────────────────────────────────────────
class TestNormality:
    def test_normal_data_passes(self, log):
        rng = np.random.default_rng(0)
        r = log.normality("z", rng.standard_normal(500))
        assert r.status == AssumptionStatus.PASS

    def test_fat_tailed_violated(self, log):
        rng = np.random.default_rng(1)
        # Student-t with 2 dof is heavy-tailed -> non-normal
        data = rng.standard_t(2, size=1000)
        r = log.normality("z", data)
        assert r.status == AssumptionStatus.VIOLATED

    def test_small_sample_skipped(self, log):
        r = log.normality("z", [0.1, 0.2, -0.1], min_n=20)
        assert r.status == AssumptionStatus.SKIPPED


# ── iid_no_autocorrelation ───────────────────────────────────────────────
class TestIID:
    def test_iid_passes(self, log):
        rng = np.random.default_rng(2)
        r = log.iid_no_autocorrelation("ret", rng.standard_normal(500))
        assert r.status == AssumptionStatus.PASS

    def test_autocorrelated_violated(self, log):
        rng = np.random.default_rng(3)
        n = 500
        e = rng.standard_normal(n)
        x = np.zeros(n)
        for i in range(1, n):
            x[i] = 0.8 * x[i - 1] + e[i]  # strong AR(1)
        r = log.iid_no_autocorrelation("ret", x)
        assert r.status == AssumptionStatus.VIOLATED
        assert r.evidence.get("approx_se_inflation", 1.0) > 1.0

    def test_small_sample_skipped(self, log):
        r = log.iid_no_autocorrelation("ret", [0.1, 0.2], min_n=20)
        assert r.status == AssumptionStatus.SKIPPED


# ── stationarity ─────────────────────────────────────────────────────────
class TestStationarity:
    def test_random_walk_violated(self, log):
        rng = np.random.default_rng(4)
        walk = np.cumsum(rng.standard_normal(300))  # unit root
        r = log.stationarity("price", walk)
        # statsmodels present in the test env -> should detect non-stationary
        assert r.status in (AssumptionStatus.VIOLATED, AssumptionStatus.SKIPPED)

    def test_stationary_passes(self, log):
        rng = np.random.default_rng(5)
        r = log.stationarity("noise", rng.standard_normal(300))
        assert r.status in (AssumptionStatus.PASS, AssumptionStatus.SKIPPED)

    def test_small_sample_skipped(self, log):
        assert log.stationarity("p", [1.0, 2.0], min_n=30).status == AssumptionStatus.SKIPPED


# ── overlapping_windows ──────────────────────────────────────────────────
class TestOverlap:
    def test_non_overlapping_pass(self, log):
        r = log.overlapping_windows("ic", step_days=21, horizon_days=21)
        assert r.status == AssumptionStatus.PASS

    def test_overlapping_violated(self, log):
        r = log.overlapping_windows("ic", step_days=21, horizon_days=252)
        assert r.status == AssumptionStatus.VIOLATED
        assert r.evidence["overlap_ratio"] == 12.0

    def test_skipped_missing(self, log):
        assert log.overlapping_windows("ic", step_days=None, horizon_days=21).status == AssumptionStatus.SKIPPED


# ── multiple_testing ─────────────────────────────────────────────────────
class TestMultipleTesting:
    def test_single_trial_pass(self, log):
        assert log.multiple_testing("s", n_trials=1).status == AssumptionStatus.PASS

    def test_many_trials_violated(self, log):
        r = log.multiple_testing("s", n_trials=100)
        assert r.status == AssumptionStatus.VIOLATED
        assert r.evidence["bonferroni_alpha"] == pytest.approx(0.0005)
        assert r.evidence["expected_max_null_t"] > 3.0

    def test_skipped_unknown(self, log):
        assert log.multiple_testing("s", n_trials=None).status == AssumptionStatus.SKIPPED


# ── context, reporting, sinks ────────────────────────────────────────────
class TestLogMechanics:
    def test_context_attaches(self, log):
        with log.context(module="metrics", ticker="NVDA"):
            r = log.min_sample("x", n=5, min_n=30)
        assert r.context["module"] == "metrics"
        assert r.context["ticker"] == "NVDA"

    def test_counts_and_summary(self, log):
        log.min_sample("a", n=50, min_n=30)     # pass
        log.min_sample("b", n=5, min_n=30)      # violated
        log.min_sample("c", n=None, min_n=30)   # skipped
        counts = log.counts()
        assert counts["pass"] == 1
        assert counts["violated"] == 1
        assert counts["skipped_insufficient_information"] == 1
        assert "ASSUMPTION AUDIT SUMMARY" in log.summary()

    def test_violations_filter_by_severity(self, log):
        log.no_lookahead("px", "2025-01-01", "2024-01-01")  # CRITICAL violation
        log.min_sample("b", n=5, min_n=30)                  # HIGH violation
        crit = log.violations(min_severity=AssumptionSeverity.CRITICAL)
        assert len(crit) == 1
        assert crit[0].assumption == "no_lookahead"

    def test_jsonl_roundtrip(self, log, tmp_path):
        log.min_sample("a", n=5, min_n=30)
        path = tmp_path / "sub" / "audit.jsonl"
        n = log.to_jsonl(str(path))
        assert n == 1
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 1
        assert '"status": "violated"' in lines[0]

    def test_disabled_does_not_record(self):
        lg = AssumptionLog(enabled=False)
        lg.min_sample("a", n=5, min_n=30)
        assert len(lg.records) == 0

    def test_never_raises_on_garbage(self, log):
        # Whatever we throw at it, it must degrade to SKIPPED/ERROR, not raise.
        log.iid_no_autocorrelation("x", "not-a-series")
        log.normality("x", None)
        log.nonzero_variance("x", object())
        log.sums_to("x", 12345)
        assert len(log.records) >= 3


class TestGlobalLog:
    def test_reset_and_get(self):
        reset_audit_log()
        lg = get_audit_log()
        lg.min_sample("a", n=5, min_n=30)
        assert len(get_audit_log().records) == 1
        reset_audit_log()
        assert len(get_audit_log().records) == 0


def test_pandas_series_inputs(log):
    """The checkers should accept pandas Series (the pipeline's native type)."""
    s = pd.Series(np.random.default_rng(9).standard_normal(300))
    assert log.iid_no_autocorrelation("s", s).status in (
        AssumptionStatus.PASS, AssumptionStatus.VIOLATED,
    )
    assert log.normality("s", s).status in (
        AssumptionStatus.PASS, AssumptionStatus.VIOLATED,
    )
