"""
Canonical metric computations for the backtest pipeline.

Single source of truth for Sharpe, Sortino, max drawdown, Calmar,
annual return, and alpha. All functions are pure — no I/O, no side effects.
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
    """Simple arithmetic alpha: strategy return minus benchmark return."""
    return round(total_return_pct - benchmark_return_pct, 2)
