"""
Overlap-aware Information Coefficient (IC) statistics.

The IC harness (``quant/redundancy.py``, ``scripts/run_audit_ic.py``) samples a
cross-sectional rank IC at every monthly rebalance and then tests significance
with a naive ``t = mean / (std / sqrt(n))``. When the forward-return horizon is
longer than the sampling step — a 3M / 6M / 12M label sampled monthly — the IC
observations are **serially dependent**: consecutive ICs are built from
overlapping return windows. Under overlap the naive t-stat is inflated by
roughly ``sqrt(horizon / step)``, which is exactly what selected several of the
system's "significant" long-horizon signals.

This module provides the corrected statistics:

* :func:`newey_west_tstat` — HAC (Newey-West) t-statistic for the mean of a
  serially-correlated series, with an automatic Bartlett lag rule.
* :func:`effective_sample_size` — the autocorrelation-deflated effective N.
* :func:`ic_summary` — a drop-in richer summary for a single IC series that
  reports the naive t, the HAC t, the overlap-implied inflation, and a verdict
  that only fires when significance survives the correction.
* :func:`overlap_adjusted_ic_table` — apply :func:`ic_summary` across a table of
  IC series (dates x signals) and return a tidy per-signal DataFrame.

It is deliberately self-contained (only numpy / pandas / scipy, all already in
``requirements.txt``) and has no import-time dependency on the rest of ``quant``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import pandas as pd


# ── Core HAC machinery ───────────────────────────────────────────────────
def bartlett_lag(n: int, horizon_over_step: Optional[float] = None) -> int:
    """Choose a Newey-West truncation lag.

    Two rules, take the larger (more conservative):
      * the standard automatic rule ``floor(4 * (n/100)^(2/9))`` (Newey-West 1994);
      * ``ceil(horizon/step) - 1`` when the overlap ratio is known, since
        overlapping windows induce an MA(overlap-1) dependence structure.
    Clamped to ``[0, n-1]``.
    """
    if n <= 2:
        return 0
    auto = int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))
    lag = auto
    if horizon_over_step and horizon_over_step > 1.0:
        overlap_lag = int(math.ceil(horizon_over_step)) - 1
        lag = max(lag, overlap_lag)
    return max(0, min(lag, n - 1))


def newey_west_variance(x: np.ndarray, lag: int) -> float:
    """Newey-West HAC estimator of the variance of the *sample mean* of ``x``.

    Returns ``Var(mean(x))`` accounting for autocovariances up to ``lag`` with
    Bartlett weights. For ``lag=0`` this reduces to ``var(x)/n`` (the IID case).
    """
    x = np.asarray(x, dtype="float64")
    x = x[np.isfinite(x)]
    n = x.size
    if n < 2:
        return float("nan")
    xc = x - x.mean()
    gamma0 = float(np.dot(xc, xc) / n)  # sample variance (biased, /n)
    var = gamma0
    for k in range(1, min(lag, n - 1) + 1):
        w = 1.0 - k / (lag + 1.0)  # Bartlett weight
        gamma_k = float(np.dot(xc[k:], xc[:-k]) / n)
        var += 2.0 * w * gamma_k
    # Guard against tiny negative HAC variance from finite-sample noise.
    var = max(var, 0.0)
    return var / n


def lag1_autocorr(x: np.ndarray) -> Optional[float]:
    x = np.asarray(x, dtype="float64")
    x = x[np.isfinite(x)]
    if x.size < 3:
        return None
    xc = x - x.mean()
    denom = float(np.dot(xc, xc))
    if denom <= 0:
        return None
    return float(np.dot(xc[1:], xc[:-1]) / denom)


def effective_sample_size(x: np.ndarray) -> float:
    """Autocorrelation-deflated effective sample size.

    Uses the classic AR(1)-style deflation ``n_eff = n * (1 - rho) / (1 + rho)``
    on the lag-1 autocorrelation, clamped to ``[1, n]``. This is what makes the
    inflation of the naive t-stat explicit: ``t_naive / t_hac ~= sqrt(n/n_eff)``.
    """
    x = np.asarray(x, dtype="float64")
    x = x[np.isfinite(x)]
    n = x.size
    if n < 3:
        return float(n)
    rho = lag1_autocorr(x)
    if rho is None:
        return float(n)
    rho = max(-0.99, min(0.99, rho))
    n_eff = n * (1.0 - rho) / (1.0 + rho)
    return float(max(1.0, min(n, n_eff)))


def newey_west_tstat(
    x: np.ndarray,
    horizon_over_step: Optional[float] = None,
    lag: Optional[int] = None,
) -> tuple[float, int]:
    """HAC t-statistic for H0: mean(x) == 0. Returns ``(t_stat, lag_used)``."""
    x = np.asarray(x, dtype="float64")
    x = x[np.isfinite(x)]
    n = x.size
    if n < 2:
        return float("nan"), 0
    if lag is None:
        lag = bartlett_lag(n, horizon_over_step)
    var_mean = newey_west_variance(x, lag)
    if not math.isfinite(var_mean) or var_mean <= 0:
        return float("nan"), lag
    t = float(x.mean() / math.sqrt(var_mean))
    return t, lag


# ── Verdicts ─────────────────────────────────────────────────────────────
def _verdict(t_stat: float, n: int, min_n: int = 36) -> str:
    if n < min_n:
        return "INSUFFICIENT"
    if not math.isfinite(t_stat):
        return "UNDEFINED"
    at = abs(t_stat)
    if at >= 2.0:
        return "SIGNIFICANT"
    if at >= 1.5:
        return "marginal"
    return "NO SIGNAL"


@dataclass
class ICSummary:
    """Overlap-aware summary of a single IC series."""

    signal: str
    n: int
    mean_ic: float
    std_ic: float
    pct_positive: float
    # Naive (IID) inference — what the current harness reports.
    t_naive: float
    verdict_naive: str
    # HAC / overlap-corrected inference.
    lag: int
    t_hac: float
    verdict_hac: str
    # Diagnostics.
    lag1_autocorr: Optional[float]
    n_effective: float
    inflation_factor: float  # t_naive / t_hac (how overstated)
    overlap_ratio: Optional[float]  # horizon / step, when known
    survives_correction: bool  # was SIGNIFICANT, still SIGNIFICANT?

    def to_dict(self) -> dict:
        return asdict(self)


def ic_summary(
    ic_series,
    *,
    signal: str = "signal",
    horizon_days: Optional[float] = None,
    step_days: Optional[float] = None,
    min_n: int = 36,
) -> ICSummary:
    """Compute an overlap-aware summary for one IC series.

    Args:
        ic_series: iterable / Series of per-date rank ICs (NaNs allowed).
        horizon_days, step_days: label horizon and sampling step. If both are
            given the overlap ratio drives a minimum HAC lag; otherwise the lag
            is chosen from the data's own autocorrelation via the Bartlett rule.
    """
    x = pd.Series(list(ic_series), dtype="float64").dropna().to_numpy()
    n = int(x.size)
    overlap = None
    if horizon_days and step_days and step_days > 0:
        overlap = float(horizon_days) / float(step_days)

    if n == 0:
        return ICSummary(
            signal=signal,
            n=0,
            mean_ic=float("nan"),
            std_ic=float("nan"),
            pct_positive=float("nan"),
            t_naive=float("nan"),
            verdict_naive="INSUFFICIENT",
            lag=0,
            t_hac=float("nan"),
            verdict_hac="INSUFFICIENT",
            lag1_autocorr=None,
            n_effective=0.0,
            inflation_factor=1.0,
            overlap_ratio=overlap,
            survives_correction=False,
        )

    mean_ic = float(np.mean(x))
    std_ic = float(np.std(x, ddof=1)) if n > 1 else 0.0
    pct_pos = float(np.mean(x > 0) * 100.0)

    # Naive IID t-stat (matches the existing harness).
    t_naive = mean_ic / (std_ic / math.sqrt(n)) if std_ic > 1e-12 and n > 1 else float("nan")

    # HAC t-stat.
    t_hac, lag = newey_west_tstat(x, horizon_over_step=overlap)

    rho1 = lag1_autocorr(x)
    n_eff = effective_sample_size(x)
    if math.isfinite(t_naive) and math.isfinite(t_hac) and abs(t_hac) > 1e-9:
        inflation = abs(t_naive) / abs(t_hac)
    else:
        inflation = 1.0

    v_naive = _verdict(t_naive, n, min_n)
    v_hac = _verdict(t_hac, n, min_n)
    survives = (v_naive == "SIGNIFICANT") and (v_hac == "SIGNIFICANT")

    return ICSummary(
        signal=signal,
        n=n,
        mean_ic=round(mean_ic, 6),
        std_ic=round(std_ic, 6),
        pct_positive=round(pct_pos, 1),
        t_naive=round(t_naive, 3),
        verdict_naive=v_naive,
        lag=lag,
        t_hac=round(t_hac, 3),
        verdict_hac=v_hac,
        lag1_autocorr=(round(rho1, 4) if rho1 is not None else None),
        n_effective=round(n_eff, 1),
        inflation_factor=round(inflation, 3),
        overlap_ratio=(round(overlap, 3) if overlap else None),
        survives_correction=survives,
    )


def overlap_adjusted_ic_table(
    ic_table: pd.DataFrame,
    *,
    horizon_days: Optional[float] = None,
    step_days: Optional[float] = None,
    min_n: int = 36,
) -> pd.DataFrame:
    """Apply :func:`ic_summary` to every column of an IC table.

    Args:
        ic_table: DataFrame indexed by date with one column per signal, cells are
            per-date rank ICs (the shape produced by
            ``redundancy.compute_signal_ic_table``).

    Returns:
        DataFrame indexed by signal with the :class:`ICSummary` fields, sorted so
        the signals whose significance *does not survive* the correction surface
        first.
    """
    rows = []
    for col in ic_table.columns:
        summ = ic_summary(
            ic_table[col],
            signal=str(col),
            horizon_days=horizon_days,
            step_days=step_days,
            min_n=min_n,
        )
        rows.append(summ.to_dict())
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).set_index("signal")
    # Surface the signals that looked significant but fail HAC first.
    df["_downgraded"] = (df["verdict_naive"] == "SIGNIFICANT") & (~df["survives_correction"])
    df = df.sort_values(["_downgraded", "inflation_factor"], ascending=[False, False])
    return df.drop(columns=["_downgraded"])


def format_ic_report(df: pd.DataFrame) -> str:
    """Human-readable report for :func:`overlap_adjusted_ic_table` output."""
    if df is None or df.empty:
        return "No IC series to report."
    lines = [
        "",
        "=" * 92,
        "  OVERLAP-CORRECTED IC SIGNIFICANCE (Newey-West HAC)",
        "=" * 92,
        f"  {'signal':<20s}{'n':>5s}{'meanIC':>9s}{'t_naive':>9s}"
        f"{'t_HAC':>8s}{'infl':>7s}{'n_eff':>8s}  {'naive->HAC':<22s}",
        "  " + "-" * 88,
    ]
    for sig, r in df.iterrows():
        transition = f"{r['verdict_naive']} -> {r['verdict_hac']}"
        flag = (
            "  <== downgraded"
            if (r["verdict_naive"] == "SIGNIFICANT" and not r["survives_correction"])
            else ""
        )
        lines.append(
            f"  {str(sig):<20s}{int(r['n']):>5d}{r['mean_ic']:>9.4f}"
            f"{r['t_naive']:>9.2f}{r['t_hac']:>8.2f}{r['inflation_factor']:>7.2f}"
            f"{r['n_effective']:>8.1f}  {transition:<22s}{flag}"
        )
    lines.append("  " + "-" * 88)
    lines.append("  A signal is only credited when it is SIGNIFICANT under the HAC t-stat.")
    lines.append("=" * 92)
    return "\n".join(lines)
