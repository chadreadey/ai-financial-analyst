"""
Stochastic assumption-logging system.

Statistical code is full of *silent* assumptions: that a Sharpe ratio is
computed on IID returns, that a z-score is applied to roughly-normal data,
that an ARIMA fit sees a stationary series, that a "probability" lives in
[0, 1], that weights sum to one, that a value is point-in-time and not a
peek into the future. When those assumptions are wrong the number still
comes out — it is just meaningless. Nothing in the pipeline records that it
was meaningless.

This module is a small, dependency-light instrument that lets any piece of
quant / data-science / AI-glue code *declare* the assumption it is relying
on at the exact point it relies on it, and then have that assumption
**checked against the information that is actually available at that moment**.

The governing contract — the thing the audit specifically asked for — is:

    "check assumptions made against information whenever available"

So every checker has three (not two) outcomes:

    PASS      — the information was available and the assumption holds.
    VIOLATED  — the information was available and the assumption is false.
    SKIPPED   — the information needed to test the assumption was NOT
                available (too few points, missing series, optional test
                library absent). This is logged explicitly with a reason.
                It is never treated as a pass and never raises.

Design constraints
------------------
* No heavy imports at module load. ``scipy`` / ``statsmodels`` are imported
  lazily inside the checkers that need them, so importing this module is
  free and it degrades gracefully (``SKIPPED``) where a library is missing.
* No imports from other ``quant`` modules — this must be safe to import from
  anywhere (``quant.metrics``, ``quant.cross_sectional``, ``orchestrator``)
  without creating an import cycle.
* Checkers never raise on bad input and never change the caller's numbers.
  They only observe and record. Instrumentation must be inert.
* Thread-safe append so it can be used from the async orchestrator and the
  Modal/CPCV fan-out.

Typical use
-----------
    from quant.assumption_audit import get_audit_log, AssumptionSeverity

    log = get_audit_log()
    with log.context(module="metrics.compute_sharpe", ticker="NVDA"):
        log.min_sample("sharpe_input", n=len(returns), min_n=30)
        log.iid_no_autocorrelation("sharpe_returns", returns)

    print(log.summary())          # human-readable
    log.to_jsonl("assumptions.jsonl")
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable, Optional, Sequence


# ── Taxonomy ───────────────────────────────────────────────────────────────
class AssumptionStatus(str, Enum):
    """Outcome of a single assumption check."""

    PASS = "pass"
    VIOLATED = "violated"
    # Information required to evaluate the assumption was not available.
    SKIPPED = "skipped_insufficient_information"
    # The checker itself failed (a bug in the check, not in the data).
    ERROR = "error"


class AssumptionSeverity(str, Enum):
    """How much a violation of this assumption should worry you."""

    CRITICAL = "critical"   # invalidates the inference (e.g. look-ahead)
    HIGH = "high"           # materially biases the number
    MEDIUM = "medium"       # meaningful but bounded distortion
    LOW = "low"             # cosmetic / precision-level


@dataclass
class AssumptionRecord:
    """One logged assumption check."""

    assumption: str          # short machine id, e.g. "iid_no_autocorrelation"
    target: str              # what was checked, e.g. "sharpe_returns"
    status: AssumptionStatus
    severity: AssumptionSeverity
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["severity"] = self.severity.value
        return d

    @property
    def failed(self) -> bool:
        return self.status == AssumptionStatus.VIOLATED


# ── The log ─────────────────────────────────────────────────────────────────
class AssumptionLog:
    """Collects :class:`AssumptionRecord` objects.

    All the ``check_*`` / convenience methods return the record they logged
    so callers can inspect it, but the common pattern is fire-and-forget.
    """

    def __init__(
        self,
        *,
        max_records: int = 100_000,
        jsonl_path: Optional[str] = None,
        enabled: bool = True,
    ) -> None:
        self._records: list[AssumptionRecord] = []
        self._max_records = max_records
        self._jsonl_path = jsonl_path
        self._enabled = enabled
        self._ctx_stack: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    # -- configuration ------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, value: bool) -> None:
        self._enabled = bool(value)

    def set_jsonl_path(self, path: Optional[str]) -> None:
        self._jsonl_path = path

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    @property
    def records(self) -> list[AssumptionRecord]:
        with self._lock:
            return list(self._records)

    # -- scoped context -----------------------------------------------------
    @contextmanager
    def context(self, **ctx: Any):
        """Attach key/value context (module, ticker, as_of date, run_id ...)
        to every record logged inside the ``with`` block. Nestable."""
        with self._lock:
            self._ctx_stack.append(ctx)
        try:
            yield self
        finally:
            with self._lock:
                self._ctx_stack.pop()

    def _current_context(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for layer in self._ctx_stack:
            merged.update(layer)
        return merged

    # -- low-level record ---------------------------------------------------
    def record(
        self,
        assumption: str,
        target: str,
        status: AssumptionStatus,
        severity: AssumptionSeverity,
        message: str,
        evidence: Optional[dict[str, Any]] = None,
    ) -> AssumptionRecord:
        rec = AssumptionRecord(
            assumption=assumption,
            target=target,
            status=status,
            severity=severity,
            message=message,
            evidence=evidence or {},
            context=self._current_context(),
        )
        if not self._enabled:
            return rec
        with self._lock:
            self._records.append(rec)
            if len(self._records) > self._max_records:
                # Drop oldest to bound memory; keep it simple.
                self._records = self._records[-self._max_records:]
            if self._jsonl_path:
                self._append_jsonl(rec, self._jsonl_path)
        return rec

    @staticmethod
    def _append_jsonl(rec: AssumptionRecord, path: str) -> None:
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec.to_dict()) + "\n")
        except Exception:
            # Logging must never break the caller.
            pass

    # ── Checkers ──────────────────────────────────────────────────────────
    # Each checker follows the same contract: available info -> PASS/VIOLATED,
    # missing info -> SKIPPED, internal failure -> ERROR. Never raises.

    def min_sample(
        self,
        target: str,
        n: Optional[int],
        min_n: int,
        *,
        severity: AssumptionSeverity = AssumptionSeverity.HIGH,
    ) -> AssumptionRecord:
        """Assumption: there are at least ``min_n`` observations behind the
        statistic. This is the most common silent failure — a Sharpe or a
        z-score computed on a handful of points."""
        if n is None:
            return self.record(
                "min_sample", target, AssumptionStatus.SKIPPED, severity,
                "sample size unknown — cannot verify adequacy",
                {"min_n": min_n},
            )
        if n >= min_n:
            return self.record(
                "min_sample", target, AssumptionStatus.PASS, severity,
                f"n={n} >= min_n={min_n}", {"n": n, "min_n": min_n},
            )
        return self.record(
            "min_sample", target, AssumptionStatus.VIOLATED, severity,
            f"n={n} < min_n={min_n}: statistic is dominated by sampling noise",
            {"n": n, "min_n": min_n},
        )

    def value_in_range(
        self,
        target: str,
        value: Optional[float],
        lo: float,
        hi: float,
        *,
        severity: AssumptionSeverity = AssumptionSeverity.HIGH,
    ) -> AssumptionRecord:
        """Assumption: ``value`` lies in [lo, hi] (probabilities in [0,1] or
        [0,100], scores in [-1,1], etc.)."""
        v = _as_float(value)
        if v is None:
            return self.record(
                "value_in_range", target, AssumptionStatus.SKIPPED, severity,
                "value is missing — cannot verify range", {"lo": lo, "hi": hi},
            )
        if lo <= v <= hi:
            return self.record(
                "value_in_range", target, AssumptionStatus.PASS, severity,
                f"{v} in [{lo}, {hi}]", {"value": v, "lo": lo, "hi": hi},
            )
        return self.record(
            "value_in_range", target, AssumptionStatus.VIOLATED, severity,
            f"{v} outside [{lo}, {hi}]", {"value": v, "lo": lo, "hi": hi},
        )

    def sums_to(
        self,
        target: str,
        values: Optional[Iterable[float]],
        expected: float = 1.0,
        *,
        tol: float = 1e-6,
        severity: AssumptionSeverity = AssumptionSeverity.MEDIUM,
    ) -> AssumptionRecord:
        """Assumption: the components sum to ``expected`` (weights sum to 1,
        bull_prob + bear_prob = 100, sector allocations = 1.0)."""
        vals = _to_float_list(values)
        if vals is None or not vals:
            return self.record(
                "sums_to", target, AssumptionStatus.SKIPPED, severity,
                "no components provided — cannot verify sum",
                {"expected": expected},
            )
        total = float(sum(vals))
        if abs(total - expected) <= tol:
            return self.record(
                "sums_to", target, AssumptionStatus.PASS, severity,
                f"sum={total:.6g} ~= {expected}",
                {"sum": total, "expected": expected, "n": len(vals)},
            )
        return self.record(
            "sums_to", target, AssumptionStatus.VIOLATED, severity,
            f"sum={total:.6g} != {expected} (tol={tol})",
            {"sum": total, "expected": expected, "n": len(vals)},
        )

    def no_silent_zeros(
        self,
        target: str,
        values: Optional[Sequence[float]],
        *,
        max_zero_fraction: float = 0.5,
        severity: AssumptionSeverity = AssumptionSeverity.HIGH,
    ) -> AssumptionRecord:
        """Assumption: exact zeros in this vector are genuine neutral readings,
        not missing data coerced to 0.

        The project has an explicit rule against "silent zeros" (missing ->
        0.0) because a 0 signal and an absent signal are then
        indistinguishable in the composite. When the zero fraction exceeds
        ``max_zero_fraction`` that is a strong smell of coercion."""
        arr = _to_float_list(values)
        if arr is None or not arr:
            return self.record(
                "no_silent_zeros", target, AssumptionStatus.SKIPPED, severity,
                "no vector provided — cannot inspect for coerced zeros", {},
            )
        n = len(arr)
        n_zero = sum(1 for v in arr if v == 0.0)
        frac = n_zero / n
        ev = {"n": n, "n_zero": n_zero, "zero_fraction": round(frac, 4),
              "max_zero_fraction": max_zero_fraction}
        if frac <= max_zero_fraction:
            return self.record(
                "no_silent_zeros", target, AssumptionStatus.PASS, severity,
                f"{n_zero}/{n} zeros ({frac:.0%}) within tolerance", ev,
            )
        return self.record(
            "no_silent_zeros", target, AssumptionStatus.VIOLATED, severity,
            f"{n_zero}/{n} values are exactly 0 ({frac:.0%}) — likely missing "
            "data coerced to zero rather than genuine neutral signal", ev,
        )

    def no_lookahead(
        self,
        target: str,
        data_time: Any,
        as_of: Any,
        *,
        severity: AssumptionSeverity = AssumptionSeverity.CRITICAL,
    ) -> AssumptionRecord:
        """Assumption: the datum used at decision time ``as_of`` was actually
        observable then, i.e. ``data_time <= as_of``. A violation is a
        point-in-time / look-ahead leak."""
        dt = _to_timestamp(data_time)
        ao = _to_timestamp(as_of)
        if dt is None or ao is None:
            return self.record(
                "no_lookahead", target, AssumptionStatus.SKIPPED, severity,
                "missing data_time or as_of — cannot verify point-in-time",
                {"data_time": str(data_time), "as_of": str(as_of)},
            )
        ev = {"data_time": str(dt), "as_of": str(ao)}
        if dt <= ao:
            return self.record(
                "no_lookahead", target, AssumptionStatus.PASS, severity,
                "datum observable at as_of", ev,
            )
        return self.record(
            "no_lookahead", target, AssumptionStatus.VIOLATED, severity,
            "datum timestamped AFTER as_of — look-ahead leak", ev,
        )

    def finite(
        self,
        target: str,
        value: Optional[float],
        *,
        severity: AssumptionSeverity = AssumptionSeverity.MEDIUM,
    ) -> AssumptionRecord:
        """Assumption: value is a finite real number (not NaN / inf)."""
        if value is None:
            return self.record(
                "finite", target, AssumptionStatus.SKIPPED, severity,
                "value is None — cannot verify finiteness", {},
            )
        try:
            v = float(value)
        except (TypeError, ValueError):
            return self.record(
                "finite", target, AssumptionStatus.SKIPPED, severity,
                "value is non-numeric", {"value": repr(value)},
            )
        if math.isfinite(v):
            return self.record(
                "finite", target, AssumptionStatus.PASS, severity,
                "finite", {"value": v},
            )
        return self.record(
            "finite", target, AssumptionStatus.VIOLATED, severity,
            "value is NaN or infinite", {"value": v},
        )

    def nonzero_variance(
        self,
        target: str,
        data: Optional[Sequence[float]],
        *,
        severity: AssumptionSeverity = AssumptionSeverity.MEDIUM,
    ) -> AssumptionRecord:
        """Assumption: the sample has non-degenerate variance (needed before
        z-scoring, correlation, regression)."""
        arr = _to_float_array(data)
        if arr is None or arr.size < 2:
            return self.record(
                "nonzero_variance", target, AssumptionStatus.SKIPPED, severity,
                "fewer than 2 finite observations — cannot assess variance",
                {"n": 0 if arr is None else int(arr.size)},
            )
        std = float(arr.std(ddof=1))
        if std > 1e-12:
            return self.record(
                "nonzero_variance", target, AssumptionStatus.PASS, severity,
                f"std={std:.6g}", {"std": std, "n": int(arr.size)},
            )
        return self.record(
            "nonzero_variance", target, AssumptionStatus.VIOLATED, severity,
            "sample is (near) constant — downstream z-score/correlation undefined",
            {"std": std, "n": int(arr.size)},
        )

    def normality(
        self,
        target: str,
        data: Optional[Sequence[float]],
        *,
        alpha: float = 0.05,
        min_n: int = 20,
        severity: AssumptionSeverity = AssumptionSeverity.MEDIUM,
    ) -> AssumptionRecord:
        """Assumption: the sample is approximately normal.

        Relevant wherever mean/std are used as if Gaussian: z-scores,
        Sharpe-ratio standard errors, parametric confidence intervals.
        Uses D'Agostino-Pearson (``scipy.stats.normaltest``) when available
        and n is large enough; otherwise reports skew/kurtosis heuristically
        or SKIPS."""
        arr = _to_float_array(data)
        if arr is None or arr.size < min_n:
            return self.record(
                "normality", target, AssumptionStatus.SKIPPED, severity,
                f"n={0 if arr is None else int(arr.size)} < min_n={min_n} — "
                "normality test not reliable",
                {"n": 0 if arr is None else int(arr.size), "min_n": min_n},
            )
        try:
            from scipy import stats as _stats  # lazy
        except Exception:
            # Fall back to a skew/kurtosis heuristic with no p-value.
            sk, ku = _skew_kurtosis(arr)
            ok = abs(sk) < 1.0 and abs(ku) < 3.0
            return self.record(
                "normality", target,
                AssumptionStatus.PASS if ok else AssumptionStatus.VIOLATED,
                severity,
                "scipy unavailable — skew/excess-kurtosis heuristic",
                {"skew": sk, "excess_kurtosis": ku, "test": "heuristic"},
            )
        try:
            stat, p = _stats.normaltest(arr)
            sk, ku = _skew_kurtosis(arr)
            ev = {"stat": float(stat), "p_value": float(p), "alpha": alpha,
                  "skew": sk, "excess_kurtosis": ku, "n": int(arr.size),
                  "test": "dagostino_pearson"}
            if p >= alpha:
                return self.record(
                    "normality", target, AssumptionStatus.PASS, severity,
                    f"cannot reject normality (p={p:.3g})", ev,
                )
            return self.record(
                "normality", target, AssumptionStatus.VIOLATED, severity,
                f"non-normal (p={p:.3g}, skew={sk:.2f}, exkurt={ku:.2f}); "
                "mean/std-based inference (z-scores, Sharpe SE) is biased", ev,
            )
        except Exception as exc:  # pragma: no cover - defensive
            return self.record(
                "normality", target, AssumptionStatus.ERROR, severity,
                f"normality test raised: {exc}", {},
            )

    def iid_no_autocorrelation(
        self,
        target: str,
        series: Optional[Sequence[float]],
        *,
        lags: int = 5,
        alpha: float = 0.05,
        min_n: int = 20,
        severity: AssumptionSeverity = AssumptionSeverity.HIGH,
    ) -> AssumptionRecord:
        """Assumption: observations are serially independent.

        This is the assumption behind annualising a Sharpe with sqrt(252) and
        behind IC t-stats computed as mean/SE. Overlapping forward-return
        windows and momentum both break it, inflating significance. Uses the
        Ljung-Box test (``statsmodels``) when available, else a lag-1
        autocorrelation z-test, else SKIPS."""
        arr = _to_float_array(series)
        if arr is None or arr.size < min_n:
            return self.record(
                "iid_no_autocorrelation", target, AssumptionStatus.SKIPPED,
                severity,
                f"n={0 if arr is None else int(arr.size)} < min_n={min_n} — "
                "autocorrelation test not reliable",
                {"n": 0 if arr is None else int(arr.size), "min_n": min_n},
            )
        use_lags = max(1, min(lags, arr.size // 5))
        # Preferred: Ljung-Box joint test.
        try:
            from statsmodels.stats.diagnostic import acorr_ljungbox  # lazy
            lb = acorr_ljungbox(arr, lags=[use_lags], return_df=True)
            p = float(lb["lb_pvalue"].iloc[-1])
            stat = float(lb["lb_stat"].iloc[-1])
            ac1 = _lag1_autocorr(arr)
            ev = {"test": "ljung_box", "lags": use_lags, "lb_stat": stat,
                  "p_value": p, "alpha": alpha, "lag1_autocorr": ac1,
                  "n": int(arr.size)}
            if p >= alpha:
                return self.record(
                    "iid_no_autocorrelation", target, AssumptionStatus.PASS,
                    severity, f"no significant autocorrelation (p={p:.3g})", ev,
                )
            deflation = _autocorr_se_inflation(ac1)
            ev["approx_se_inflation"] = deflation
            return self.record(
                "iid_no_autocorrelation", target, AssumptionStatus.VIOLATED,
                severity,
                f"serial dependence (Ljung-Box p={p:.3g}, lag1={ac1:.2f}); "
                f"IID t-stats/Sharpe overstate significance by ~{deflation:.2f}x", ev,
            )
        except Exception:
            pass
        # Fallback: lag-1 autocorrelation z-test (no statsmodels).
        ac1 = _lag1_autocorr(arr)
        if ac1 is None:
            return self.record(
                "iid_no_autocorrelation", target, AssumptionStatus.SKIPPED,
                severity, "could not compute lag-1 autocorrelation", {},
            )
        se = 1.0 / math.sqrt(arr.size)
        z = ac1 / se if se > 0 else 0.0
        ev = {"test": "lag1_z", "lag1_autocorr": ac1, "z": z,
              "n": int(arr.size)}
        if abs(z) < 1.96:
            return self.record(
                "iid_no_autocorrelation", target, AssumptionStatus.PASS,
                severity, f"lag-1 autocorr not significant (z={z:.2f})", ev,
            )
        ev["approx_se_inflation"] = _autocorr_se_inflation(ac1)
        return self.record(
            "iid_no_autocorrelation", target, AssumptionStatus.VIOLATED,
            severity,
            f"lag-1 autocorrelation {ac1:.2f} significant (z={z:.2f}); "
            "IID assumption behind annualised Sharpe / IC t-stat is violated", ev,
        )

    def stationarity(
        self,
        target: str,
        series: Optional[Sequence[float]],
        *,
        alpha: float = 0.05,
        min_n: int = 30,
        severity: AssumptionSeverity = AssumptionSeverity.HIGH,
    ) -> AssumptionRecord:
        """Assumption: the series is (weakly) stationary.

        Relevant for ARIMA / OLS-trend / mean-reversion signals fit on raw
        price levels. Uses the Augmented Dickey-Fuller test (``statsmodels``)
        when available, else SKIPS (a lag-1 heuristic cannot substitute for a
        unit-root test)."""
        arr = _to_float_array(series)
        if arr is None or arr.size < min_n:
            return self.record(
                "stationarity", target, AssumptionStatus.SKIPPED, severity,
                f"n={0 if arr is None else int(arr.size)} < min_n={min_n} — "
                "ADF unit-root test not reliable",
                {"n": 0 if arr is None else int(arr.size), "min_n": min_n},
            )
        try:
            from statsmodels.tsa.stattools import adfuller  # lazy
        except Exception:
            return self.record(
                "stationarity", target, AssumptionStatus.SKIPPED, severity,
                "statsmodels unavailable — cannot run ADF unit-root test", {},
            )
        try:
            stat, p, *_ = adfuller(arr, autolag="AIC")
            ev = {"test": "adf", "adf_stat": float(stat), "p_value": float(p),
                  "alpha": alpha, "n": int(arr.size)}
            if p < alpha:
                return self.record(
                    "stationarity", target, AssumptionStatus.PASS, severity,
                    f"reject unit root -> stationary (p={p:.3g})", ev,
                )
            return self.record(
                "stationarity", target, AssumptionStatus.VIOLATED, severity,
                f"cannot reject unit root (p={p:.3g}); series is likely "
                "non-stationary — models fit on levels are mis-specified", ev,
            )
        except Exception as exc:  # pragma: no cover - defensive
            return self.record(
                "stationarity", target, AssumptionStatus.ERROR, severity,
                f"ADF raised: {exc}", {},
            )

    def overlapping_windows(
        self,
        target: str,
        *,
        step_days: Optional[float],
        horizon_days: Optional[float],
        severity: AssumptionSeverity = AssumptionSeverity.HIGH,
    ) -> AssumptionRecord:
        """Assumption: successive observations do not overlap in time.

        When forward-return labels of ``horizon_days`` are sampled every
        ``step_days`` and ``step_days < horizon_days`` the samples share data
        and IID inference (IC t-stats, Sharpe) is invalid. Reports the
        approximate variance-inflation / effective-sample deflation factor."""
        if step_days is None or horizon_days is None:
            return self.record(
                "overlapping_windows", target, AssumptionStatus.SKIPPED,
                severity, "step or horizon unknown — cannot assess overlap",
                {"step_days": step_days, "horizon_days": horizon_days},
            )
        if step_days <= 0 or horizon_days <= 0:
            return self.record(
                "overlapping_windows", target, AssumptionStatus.SKIPPED,
                severity, "non-positive step/horizon", {},
            )
        overlap = horizon_days / step_days  # ~ how many samples share a window
        ev = {"step_days": step_days, "horizon_days": horizon_days,
              "overlap_ratio": round(overlap, 3),
              "approx_var_inflation": round(overlap, 3)}
        if overlap <= 1.0 + 1e-9:
            return self.record(
                "overlapping_windows", target, AssumptionStatus.PASS, severity,
                f"step ({step_days}d) >= horizon ({horizon_days}d): "
                "non-overlapping samples", ev,
            )
        return self.record(
            "overlapping_windows", target, AssumptionStatus.VIOLATED, severity,
            f"horizon {horizon_days}d > step {step_days}d: samples overlap "
            f"~{overlap:.1f}x. IID t-stats inflated ~{math.sqrt(overlap):.2f}x; "
            "use Newey-West/HAC or non-overlapping sampling", ev,
        )

    def multiple_testing(
        self,
        target: str,
        *,
        n_trials: Optional[int],
        alpha: float = 0.05,
        severity: AssumptionSeverity = AssumptionSeverity.HIGH,
    ) -> AssumptionRecord:
        """Assumption: the reported significance was not selected from many
        trials (configs / weightings / signals). Records the number of trials
        and the Bonferroni / Sidak-adjusted threshold and expected best-of-N
        t-stat under the null, so a lone t>2 can be judged in context."""
        if n_trials is None or n_trials <= 0:
            return self.record(
                "multiple_testing", target, AssumptionStatus.SKIPPED, severity,
                "number of trials unknown — cannot contextualise significance",
                {"alpha": alpha},
            )
        bonferroni = alpha / n_trials
        sidak = 1.0 - (1.0 - alpha) ** (1.0 / n_trials)
        # Expected maximum |t| under the null across n_trials ~ sqrt(2 ln N).
        exp_max_t = math.sqrt(2.0 * math.log(n_trials)) if n_trials > 1 else 0.0
        ev = {"n_trials": n_trials, "alpha": alpha,
              "bonferroni_alpha": bonferroni, "sidak_alpha": sidak,
              "expected_max_null_t": round(exp_max_t, 3)}
        if n_trials == 1:
            return self.record(
                "multiple_testing", target, AssumptionStatus.PASS, severity,
                "single trial — no multiple-testing adjustment needed", ev,
            )
        return self.record(
            "multiple_testing", target, AssumptionStatus.VIOLATED, severity,
            f"{n_trials} trials: naive alpha={alpha} should be tightened to "
            f"~{bonferroni:.2g} (Bonferroni); expected best-of-N |t| under the "
            f"null is ~{exp_max_t:.2f}. A single t>2 is not significant here.",
            ev,
        )

    # ── Reporting ──────────────────────────────────────────────────────────
    def counts(self) -> dict[str, int]:
        with self._lock:
            recs = list(self._records)
        out = {s.value: 0 for s in AssumptionStatus}
        for r in recs:
            out[r.status.value] += 1
        return out

    def violations(
        self,
        *,
        min_severity: Optional[AssumptionSeverity] = None,
    ) -> list[AssumptionRecord]:
        order = {
            AssumptionSeverity.LOW: 0,
            AssumptionSeverity.MEDIUM: 1,
            AssumptionSeverity.HIGH: 2,
            AssumptionSeverity.CRITICAL: 3,
        }
        threshold = order[min_severity] if min_severity else -1
        return [
            r for r in self.records
            if r.status == AssumptionStatus.VIOLATED
            and order[r.severity] >= threshold
        ]

    def to_jsonl(self, path: str) -> int:
        recs = self.records
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r.to_dict()) + "\n")
        return len(recs)

    def summary(self) -> str:
        recs = self.records
        counts = self.counts()
        lines = [
            "=" * 72,
            "  ASSUMPTION AUDIT SUMMARY",
            "=" * 72,
            f"  checks logged : {len(recs)}",
            f"  pass          : {counts[AssumptionStatus.PASS.value]}",
            f"  VIOLATED      : {counts[AssumptionStatus.VIOLATED.value]}",
            f"  skipped(no info): {counts[AssumptionStatus.SKIPPED.value]}",
            f"  error         : {counts[AssumptionStatus.ERROR.value]}",
        ]
        sev_order = [AssumptionSeverity.CRITICAL, AssumptionSeverity.HIGH,
                     AssumptionSeverity.MEDIUM, AssumptionSeverity.LOW]
        viols = self.violations()
        if viols:
            lines.append("")
            lines.append("  Violations by severity:")
            for sev in sev_order:
                group = [v for v in viols if v.severity == sev]
                if not group:
                    continue
                lines.append(f"    [{sev.value.upper()}] {len(group)}")
                for v in group[:50]:
                    ctx = v.context.get("module") or v.context.get("ticker") or ""
                    ctx = f" ({ctx})" if ctx else ""
                    lines.append(f"      - {v.assumption}:{v.target}{ctx}: {v.message}")
        else:
            lines.append("")
            lines.append("  No violations recorded.")
        lines.append("=" * 72)
        return "\n".join(lines)


# ── Helpers ──────────────────────────────────────────────────────────────
def _as_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return v


def _to_float_list(values: Any) -> Optional[list[float]]:
    if values is None:
        return None
    try:
        out = []
        for v in values:
            f = _as_float(v)
            if f is not None:
                out.append(f)
        return out
    except TypeError:
        return None


def _to_float_array(data: Any):
    """Return a 1-D numpy array of finite floats, or None. Lazily imports numpy."""
    if data is None:
        return None
    try:
        import numpy as np
    except Exception:
        return None
    try:
        arr = np.asarray(list(data), dtype="float64") if not hasattr(data, "dtype") \
            else np.asarray(data, dtype="float64")
        arr = arr[np.isfinite(arr)]
        return arr
    except Exception:
        return None


def _skew_kurtosis(arr) -> tuple[float, float]:
    """Sample skew and *excess* kurtosis (0 == normal)."""
    import numpy as np
    x = np.asarray(arr, dtype="float64")
    n = x.size
    if n < 3:
        return 0.0, 0.0
    m = x.mean()
    s = x.std(ddof=0)
    if s <= 0:
        return 0.0, 0.0
    z = (x - m) / s
    skew = float(np.mean(z ** 3))
    exkurt = float(np.mean(z ** 4) - 3.0)
    return skew, exkurt


def _lag1_autocorr(arr) -> Optional[float]:
    try:
        import numpy as np
        x = np.asarray(arr, dtype="float64")
        if x.size < 3:
            return None
        x0 = x[:-1] - x[:-1].mean()
        x1 = x[1:] - x[1:].mean()
        denom = math.sqrt(float((x0 ** 2).sum()) * float((x1 ** 2).sum()))
        if denom <= 0:
            return None
        return float((x0 * x1).sum() / denom)
    except Exception:
        return None


def _autocorr_se_inflation(ac1: Optional[float]) -> float:
    """Rough standard-error inflation factor from AR(1)-like dependence:
    sqrt((1+rho)/(1-rho)). Bounded for stability."""
    if ac1 is None:
        return 1.0
    rho = max(-0.95, min(0.95, ac1))
    try:
        return round(math.sqrt((1.0 + rho) / (1.0 - rho)), 3)
    except Exception:
        return 1.0


def _to_timestamp(x: Any):
    """Best-effort conversion to something orderable (pandas Timestamp)."""
    if x is None:
        return None
    try:
        import pandas as pd
        ts = pd.Timestamp(x)
        if pd.isna(ts):
            return None
        return ts
    except Exception:
        # Fall back to raw comparable (e.g. already a date/int).
        return x


# ── Global default log ───────────────────────────────────────────────────
_default_log: Optional[AssumptionLog] = None
_default_lock = threading.Lock()


def get_audit_log() -> AssumptionLog:
    """Return the process-wide default log.

    Honours two environment variables so instrumentation can be toggled
    without code changes:
      ASSUMPTION_AUDIT_ENABLED  ("0"/"false" disables recording)
      ASSUMPTION_AUDIT_JSONL    (path to stream records to)
    """
    global _default_log
    if _default_log is None:
        with _default_lock:
            if _default_log is None:
                enabled_env = os.getenv("ASSUMPTION_AUDIT_ENABLED", "1").lower()
                enabled = enabled_env not in ("0", "false", "no")
                jsonl = os.getenv("ASSUMPTION_AUDIT_JSONL") or None
                _default_log = AssumptionLog(enabled=enabled, jsonl_path=jsonl)
    return _default_log


def reset_audit_log() -> AssumptionLog:
    """Replace the default log with a fresh one (useful in tests)."""
    global _default_log
    with _default_lock:
        _default_log = AssumptionLog()
    return _default_log
