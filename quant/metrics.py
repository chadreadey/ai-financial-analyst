"""
Canonical metric computations for the backtest pipeline.

Single source of truth for Sharpe, Sortino, max drawdown, Calmar,
annual return, and alpha. All functions are pure — no I/O, no side effects.

Rigor layer (added by the statistical-harness work)
---------------------------------------------------
The original ``compute_sharpe`` / ``compute_sortino`` are kept byte-for-byte
backward compatible (existing backtests and reproducibility tests depend on
them). Alongside them this module now provides correctly-specified, opt-in
statistics that address the Session-4 audit findings A1–A4:

  * :func:`sharpe_standard_error` / :func:`sharpe_tstat` / :func:`compute_sharpe_stats`
    — Lo (2002) standard error and significance for a Sharpe ratio, with an
    optional autocorrelation adjustment (a Sharpe with no error bar is not a
    result).
  * :func:`compute_downside_deviation` / :func:`compute_sortino_target`
    — the textbook target-semideviation Sortino (the legacy ``compute_sortino``
    uses the std of only-negative returns, which is a different, biased
    quantity — see audit A2).
  * :func:`compute_information_ratio` — risk-adjusted active return vs a
    benchmark (the honest cousin of the arithmetic "alpha" in
    :func:`compute_alpha`; see audit A4).

All of these accept an optional annual risk-free rate so Sharpe/Sortino can be
computed on *excess* returns (audit A3).
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd


def compute_sharpe(
    daily_returns: pd.Series,
    annual_factor: float = 252.0,
    min_observations: int = 10,
) -> Optional[float]:
    """Annualized Sharpe ratio from a daily return series.

    Formula: (mean_daily / std_daily) * sqrt(annual_factor)
    """
    if daily_returns is None or len(daily_returns) < min_observations:
        return None
    mean_ret = float(daily_returns.mean())
    std_ret = float(daily_returns.std())
    if std_ret == 0 or np.isnan(std_ret):
        return None
    return round(mean_ret / std_ret * math.sqrt(annual_factor), 2)


def compute_sortino(
    daily_returns: pd.Series,
    annual_factor: float = 252.0,
    min_observations: int = 10,
) -> Optional[float]:
    """Annualized Sortino ratio from a daily return series.

    Uses downside deviation (std of negative returns only).
    """
    if daily_returns is None or len(daily_returns) < min_observations:
        return None
    mean_ret = float(daily_returns.mean())
    downside = daily_returns[daily_returns < 0]
    if len(downside) < 2:
        return None
    down_std = float(downside.std())
    if down_std == 0 or np.isnan(down_std):
        return None
    return round(mean_ret / down_std * math.sqrt(annual_factor), 2)


def compute_max_drawdown(equity_curve: pd.Series) -> float:
    """Maximum drawdown as a positive percentage (0-100).

    Args:
        equity_curve: Cumulative equity series (e.g. starting at initial_capital).

    Returns:
        Max drawdown percentage (e.g. 15.3 means -15.3% peak-to-trough).
    """
    if equity_curve is None or len(equity_curve) < 2:
        return 0.0
    running_max = equity_curve.cummax()
    drawdown = (equity_curve - running_max) / running_max
    return round(abs(float(drawdown.min())) * 100, 2)


def compute_calmar(annual_return_pct: float, max_drawdown_pct: float) -> Optional[float]:
    """Calmar ratio: annualized return / max drawdown."""
    if max_drawdown_pct <= 0:
        return None
    return round(annual_return_pct / max_drawdown_pct, 2)


def compute_annual_return(
    equity_curve: pd.Series,
    initial_capital: float,
) -> float:
    """CAGR as a percentage from an equity curve."""
    if equity_curve is None or len(equity_curve) < 2:
        return 0.0
    final_equity = float(equity_curve.iloc[-1])
    n_years = max((equity_curve.index[-1] - equity_curve.index[0]).days / 365.25, 0.1)
    return round(((final_equity / initial_capital) ** (1 / n_years) - 1) * 100, 2)


def compute_alpha(total_return_pct: float, benchmark_return_pct: float) -> float:
    """Simple arithmetic alpha: strategy return minus benchmark return.

    NOTE (audit A4): this is a raw return spread, not a risk-adjusted or
    beta-neutral alpha. For a risk-adjusted comparison use
    :func:`compute_information_ratio`, and for a factor alpha use the FF5+Mom
    regression in ``quant/factor_attribution.py``.
    """
    return round(total_return_pct - benchmark_return_pct, 2)


# ── Rigor layer: Sharpe with error bars (Lo 2002) ─────────────────────────
def _excess_per_period(
    daily_returns: pd.Series,
    annual_factor: float,
    risk_free_annual: float,
) -> Optional[np.ndarray]:
    """Return finite per-period *excess* returns as a numpy array, or None."""
    if daily_returns is None:
        return None
    arr = np.asarray(daily_returns, dtype="float64")
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return None
    if risk_free_annual:
        rf_period = risk_free_annual / annual_factor
        arr = arr - rf_period
    return arr


def sharpe_standard_error(
    n: int,
    periodic_sharpe: float,
    *,
    autocorr_inflation: float = 1.0,
) -> Optional[float]:
    """Standard error of an estimated (periodic) Sharpe ratio.

    Lo (2002) IID asymptotic result: ``Var(SR_hat) = (1 + 0.5*SR^2) / n``.
    ``autocorr_inflation`` (>= 1) scales the SE up to account for serial
    correlation in returns (see :func:`compute_sharpe_stats`).
    """
    if n is None or n < 2 or not math.isfinite(periodic_sharpe):
        return None
    se = math.sqrt((1.0 + 0.5 * periodic_sharpe**2) / n)
    return se * max(1.0, autocorr_inflation)


def _autocorr_inflation(excess: np.ndarray, max_lag: int = 10) -> float:
    """Newey-West-style SE inflation for the mean from serial correlation:
    sqrt(1 + 2*sum_k (1-k/(L+1)) rho_k), floored at 1.0."""
    n = excess.size
    if n < 5:
        return 1.0
    xc = excess - excess.mean()
    denom = float(np.dot(xc, xc))
    if denom <= 0:
        return 1.0
    L = max(1, min(max_lag, n - 2))
    s = 0.0
    for k in range(1, L + 1):
        rho_k = float(np.dot(xc[k:], xc[:-k]) / denom)
        w = 1.0 - k / (L + 1.0)  # Bartlett weight
        s += 2.0 * w * rho_k
    factor = 1.0 + s
    return math.sqrt(factor) if factor > 1.0 else 1.0


def compute_sharpe_stats(
    daily_returns: pd.Series,
    annual_factor: float = 252.0,
    *,
    risk_free_annual: float = 0.0,
    min_observations: int = 10,
    autocorr_adjust: bool = True,
) -> Optional[dict]:
    """Annualized Sharpe *with a standard error and t-stat*.

    Returns a dict::

        {
          "sharpe": annualized Sharpe (excess if risk_free_annual given),
          "se": annualized standard error of the Sharpe estimate,
          "t_stat": Sharpe / SE  (H0: true Sharpe == 0),
          "n": number of observations,
          "annual_factor": ...,
          "autocorr_inflation": SE inflation applied (1.0 if none/off),
        }

    A t_stat with ``|t| >= ~2`` is the minimum bar for a Sharpe to be
    distinguishable from zero at this sample size. This is the piece the
    original ``compute_sharpe`` omits (audit A1).
    """
    excess = _excess_per_period(daily_returns, annual_factor, risk_free_annual)
    if excess is None or excess.size < min_observations:
        return None
    mean = float(excess.mean())
    std = float(excess.std(ddof=1))
    if std <= 0 or not math.isfinite(std):
        return None
    n = int(excess.size)
    periodic_sr = mean / std
    inflation = _autocorr_inflation(excess) if autocorr_adjust else 1.0
    se_periodic = sharpe_standard_error(n, periodic_sr, autocorr_inflation=inflation)
    if se_periodic is None or se_periodic <= 0:
        return None
    scale = math.sqrt(annual_factor)
    # t-stat is scale-invariant (numerator and SE both scale by `scale`).
    t_stat = periodic_sr / se_periodic
    return {
        "sharpe": round(periodic_sr * scale, 4),
        "se": round(se_periodic * scale, 4),
        "t_stat": round(t_stat, 4),
        "n": n,
        "annual_factor": annual_factor,
        "autocorr_inflation": round(inflation, 4),
    }


# ── Rigor layer: proper (target-semideviation) Sortino ────────────────────
def compute_downside_deviation(
    daily_returns: pd.Series,
    mar_annual: float = 0.0,
    annual_factor: float = 252.0,
) -> Optional[float]:
    """Target semideviation against a Minimum Acceptable Return (MAR).

    ``sqrt(mean(min(r - mar_period, 0)^2))`` over the WHOLE sample — the
    denominator the Sortino ratio is actually defined with. Contrast the legacy
    :func:`compute_sortino`, which uses ``std`` of only the negative returns
    (a different, biased quantity). Returns the *per-period* downside deviation
    (not annualized) so callers can annualize consistently.
    """
    if daily_returns is None:
        return None
    arr = np.asarray(daily_returns, dtype="float64")
    arr = arr[np.isfinite(arr)]
    if arr.size < 2:
        return None
    mar_period = mar_annual / annual_factor if mar_annual else 0.0
    shortfall = np.minimum(arr - mar_period, 0.0)
    dd = math.sqrt(float(np.mean(shortfall**2)))
    return dd


def compute_sortino_target(
    daily_returns: pd.Series,
    annual_factor: float = 252.0,
    *,
    mar_annual: float = 0.0,
    risk_free_annual: float = 0.0,
    min_observations: int = 10,
) -> Optional[float]:
    """Annualized Sortino using the correct target-semideviation denominator.

    Numerator is the mean excess-over-``risk_free_annual`` return; denominator
    is the target semideviation against ``mar_annual`` (audit A2/A3).
    """
    excess = _excess_per_period(daily_returns, annual_factor, risk_free_annual)
    if excess is None or excess.size < min_observations:
        return None
    dd = compute_downside_deviation(
        pd.Series(excess), mar_annual=mar_annual, annual_factor=annual_factor
    )
    if dd is None or dd <= 0:
        return None
    mean = float(excess.mean())
    return round(mean / dd * math.sqrt(annual_factor), 4)


# ── Rigor layer: information ratio ────────────────────────────────────────
def compute_information_ratio(
    daily_returns: pd.Series,
    benchmark_daily_returns: pd.Series,
    annual_factor: float = 252.0,
    min_observations: int = 10,
) -> Optional[float]:
    """Annualized information ratio: mean active return / tracking error.

    Active return = strategy - benchmark, aligned by index where both are
    pandas Series. This is the risk-adjusted alternative to the arithmetic
    "alpha" spread (audit A4).
    """
    if daily_returns is None or benchmark_daily_returns is None:
        return None
    r = pd.Series(daily_returns, dtype="float64")
    b = pd.Series(benchmark_daily_returns, dtype="float64")
    if r.index.equals(b.index):
        active = (r - b).dropna()
    else:
        aligned = pd.concat([r, b], axis=1, join="inner").dropna()
        if aligned.empty:
            return None
        active = aligned.iloc[:, 0] - aligned.iloc[:, 1]
    if len(active) < min_observations:
        return None
    te = float(active.std(ddof=1))
    if te <= 0 or not math.isfinite(te):
        return None
    return round(float(active.mean()) / te * math.sqrt(annual_factor), 4)
