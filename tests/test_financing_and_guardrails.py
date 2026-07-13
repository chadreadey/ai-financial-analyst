"""
Tests for quant.financing — daily SOFR+spread accrual and pre-declared
guardrails.

Deliberately isolated from _compute_daily_portfolio_returns; those tests
would require a full price universe. The pieces here are the math the
engine relies on.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from quant.backtest import BacktestConfig
from quant.financing import (
    DEFAULT_TRADING_DAYS_PER_YEAR,
    HARDCODED_BROKER_CALL_ANN_RATE,
    LeverageGuardrails,
    compute_daily_financing_charge,
    compute_financing_series,
    evaluate_guardrails,
)


# ── config plumbing ─────────────────────────────────────────────────────

def test_backtest_config_has_financing_fields():
    c = BacktestConfig()
    assert c.gross_exposure == 1.0
    assert c.financing_spread_bps == 150.0
    assert c.leverage_max_drawdown_pct is None
    assert c.leverage_stressed_day_loss_pct is None
    assert c.leverage_stress_shock_pct == 0.08
    assert c.leverage_financing_cost_cap_frac_of_excess_return is None


# ── per-day accrual math ────────────────────────────────────────────────

def test_daily_financing_zero_when_no_borrow():
    assert compute_daily_financing_charge(0.0, 0.04, 150.0) == 0.0
    assert compute_daily_financing_charge(-1000.0, 0.04, 150.0) == 0.0


def test_daily_financing_matches_manual_calc():
    # $50k borrowed at 4% SOFR + 150bp = 5.5% annual / 252 = 0.02182% daily.
    # 50000 * 0.055 / 252 = 10.9127 dollars.
    charge = compute_daily_financing_charge(50_000.0, 0.04, 150.0)
    expected = 50_000.0 * (0.04 + 0.015) / DEFAULT_TRADING_DAYS_PER_YEAR
    assert charge == pytest.approx(expected)
    assert charge == pytest.approx(10.9126984, rel=1e-6)


def test_daily_financing_zero_spread():
    charge = compute_daily_financing_charge(100_000.0, 0.05, 0.0)
    assert charge == pytest.approx(100_000.0 * 0.05 / DEFAULT_TRADING_DAYS_PER_YEAR)


# ── series-level accrual over a synthetic period ────────────────────────

def _flat_sofr(dates, ann_rate: float = 0.04) -> pd.Series:
    return pd.Series(ann_rate, index=dates)


def test_financing_series_returns_empty_at_gross_1():
    dates = pd.date_range("2024-01-02", periods=5, freq="B")
    pnl = pd.Series([100.0, -50.0, 25.0, 0.0, 75.0], index=dates)
    out = compute_financing_series(
        daily_pnl=pnl, initial_capital=100_000.0,
        gross_exposure=1.0, sofr_series=_flat_sofr(dates),
        spread_bps=150.0,
    )
    assert out.empty


def test_financing_series_matches_manual_calc_constant_rate():
    # 5 trading days at flat 4% SOFR + 150bp spread, gross=1.5x.
    # Initial NAV = 100_000. Excess = 0.5x.
    # Day 1 borrow = 100_000 * 0.5 = 50_000 (pnl.shift(1) = 0)
    # Daily rate = (0.04 + 0.015)/252 = 0.0002182539...
    # Day 1 charge = 50_000 * 0.0002182539 ≈ 10.9126984
    dates = pd.date_range("2024-01-02", periods=5, freq="B")
    pnl = pd.Series([100.0, -50.0, 25.0, 0.0, 75.0], index=dates)
    fin = compute_financing_series(
        daily_pnl=pnl, initial_capital=100_000.0,
        gross_exposure=1.5, sofr_series=_flat_sofr(dates, 0.04),
        spread_bps=150.0,
    )
    daily_rate = (0.04 + 0.015) / DEFAULT_TRADING_DAYS_PER_YEAR
    # NAV_start_of_day includes cumulative prior pnl
    nav_starts = [100_000.0, 100_100.0, 100_050.0, 100_075.0, 100_075.0]
    expected = [nav * 0.5 * daily_rate for nav in nav_starts]
    for got, want in zip(fin.values, expected):
        assert got == pytest.approx(want, rel=1e-9)


def test_financing_series_scales_linearly_with_excess_gross():
    dates = pd.date_range("2024-01-02", periods=3, freq="B")
    pnl = pd.Series([0.0, 0.0, 0.0], index=dates)
    fin_15 = compute_financing_series(
        daily_pnl=pnl, initial_capital=100_000.0,
        gross_exposure=1.5, sofr_series=_flat_sofr(dates),
        spread_bps=150.0,
    )
    fin_20 = compute_financing_series(
        daily_pnl=pnl, initial_capital=100_000.0,
        gross_exposure=2.0, sofr_series=_flat_sofr(dates),
        spread_bps=150.0,
    )
    # 2.0x borrows 1.0*NAV, 1.5x borrows 0.5*NAV. Ratio should be 2:1.
    for a, b in zip(fin_20.values, fin_15.values):
        assert a == pytest.approx(b * 2.0)


def test_financing_series_uses_hardcoded_fallback_when_sofr_empty():
    dates = pd.date_range("2024-01-02", periods=3, freq="B")
    pnl = pd.Series([0.0, 0.0, 0.0], index=dates)
    fin = compute_financing_series(
        daily_pnl=pnl, initial_capital=100_000.0,
        gross_exposure=1.5, sofr_series=pd.Series(dtype=float),
        spread_bps=150.0,
    )
    daily_rate = (HARDCODED_BROKER_CALL_ANN_RATE + 0.015) / DEFAULT_TRADING_DAYS_PER_YEAR
    expected = 100_000.0 * 0.5 * daily_rate
    assert fin.iloc[0] == pytest.approx(expected, rel=1e-9)


# ── guardrail checker ───────────────────────────────────────────────────

def _synthetic_curve(drawdown_frac: float) -> tuple[pd.Series, pd.Series]:
    """Build a NAV curve with a peak then a defined drawdown."""
    dates = pd.date_range("2024-01-02", periods=10, freq="B")
    # Rise then fall
    nav = [100_000.0, 105_000.0, 110_000.0, 115_000.0, 120_000.0]
    trough = 120_000.0 * (1.0 - drawdown_frac)
    nav.extend([115_000.0, 108_000.0, 100_000.0, trough + 1_000.0, trough])
    equity = pd.Series(nav, index=dates)
    daily_rets = equity.pct_change().fillna(0.0)
    return equity, daily_rets


def test_guardrail_passes_when_no_gates_set():
    equity, rets = _synthetic_curve(0.10)
    ev = evaluate_guardrails(
        equity_curve=equity, daily_returns=rets,
        financing_dollars_paid=0.0, initial_capital=100_000.0,
        gross_exposure=1.5, guardrails=LeverageGuardrails(),
    )
    assert ev.passed
    assert ev.breaches == []


def test_guardrail_fails_on_max_drawdown_breach():
    equity, rets = _synthetic_curve(0.30)  # 30% drawdown
    ev = evaluate_guardrails(
        equity_curve=equity, daily_returns=rets,
        financing_dollars_paid=0.0, initial_capital=100_000.0,
        gross_exposure=1.5,
        guardrails=LeverageGuardrails(max_drawdown_pct=0.25),
    )
    assert not ev.passed
    assert any("max_drawdown" in b for b in ev.breaches)
    assert ev.stats["observed_max_drawdown"] == pytest.approx(0.30, rel=1e-6)


def test_guardrail_passes_when_max_drawdown_under_cap():
    equity, rets = _synthetic_curve(0.10)
    ev = evaluate_guardrails(
        equity_curve=equity, daily_returns=rets,
        financing_dollars_paid=0.0, initial_capital=100_000.0,
        gross_exposure=1.5,
        guardrails=LeverageGuardrails(max_drawdown_pct=0.25),
    )
    assert ev.passed


def test_guardrail_fails_stressed_day_at_2x_gross():
    # 2.0x gross × 8% shock = 16% NAV loss > 15% cap
    equity, rets = _synthetic_curve(0.05)
    ev = evaluate_guardrails(
        equity_curve=equity, daily_returns=rets,
        financing_dollars_paid=0.0, initial_capital=100_000.0,
        gross_exposure=2.0,
        guardrails=LeverageGuardrails(stressed_day_loss_pct=0.15),
    )
    assert not ev.passed
    assert any("stressed_day_loss" in b for b in ev.breaches)


def test_guardrail_passes_stressed_day_at_15x_gross():
    # 1.5x × 8% = 12% < 15% cap
    equity, rets = _synthetic_curve(0.05)
    ev = evaluate_guardrails(
        equity_curve=equity, daily_returns=rets,
        financing_dollars_paid=0.0, initial_capital=100_000.0,
        gross_exposure=1.5,
        guardrails=LeverageGuardrails(stressed_day_loss_pct=0.15),
    )
    assert ev.passed


def test_guardrail_financing_frac_of_excess_return_breach():
    # 10-day flat rise from 100k → 110k = +10%. Benchmark 5% → excess $5k.
    # Financing paid 2000 → 40% of excess > 30% cap.
    dates = pd.date_range("2024-01-02", periods=10, freq="B")
    equity = pd.Series(np.linspace(100_000, 110_000, 10), index=dates)
    rets = equity.pct_change().fillna(0.0)
    ev = evaluate_guardrails(
        equity_curve=equity, daily_returns=rets,
        financing_dollars_paid=2_000.0, initial_capital=100_000.0,
        gross_exposure=1.5,
        guardrails=LeverageGuardrails(financing_cost_cap_frac_of_excess_return=0.30),
        benchmark_return_pct=5.0,
    )
    assert not ev.passed
    assert any("financing_frac_of_excess" in b for b in ev.breaches)


def test_guardrail_strategy_return_pct_override_matches_reported_alpha():
    """
    When strategy_return_pct is explicitly passed, the checker must use it
    verbatim (not re-derive from daily_returns compounding). Regression
    guard: a run with alpha_pct = -100 (bench 200 - strat 100) must fail
    the fin/exc gate at any positive financing, matching the
    engine-reported alpha, not a compounded approximation.
    """
    dates = pd.date_range("2024-01-02", periods=10, freq="B")
    equity = pd.Series(np.linspace(100_000, 200_000, 10), index=dates)
    rets = equity.pct_change().fillna(0.0)
    ev = evaluate_guardrails(
        equity_curve=equity, daily_returns=rets,
        financing_dollars_paid=1_000.0, initial_capital=100_000.0,
        gross_exposure=1.5,
        guardrails=LeverageGuardrails(financing_cost_cap_frac_of_excess_return=0.30),
        benchmark_return_pct=200.0,
        strategy_return_pct=100.0,  # reported alpha = -100pp
    )
    assert not ev.passed
    assert any("financing_frac_of_excess" in b for b in ev.breaches)


def test_guardrail_financing_frac_pass():
    dates = pd.date_range("2024-01-02", periods=10, freq="B")
    equity = pd.Series(np.linspace(100_000, 110_000, 10), index=dates)
    rets = equity.pct_change().fillna(0.0)
    ev = evaluate_guardrails(
        equity_curve=equity, daily_returns=rets,
        financing_dollars_paid=500.0, initial_capital=100_000.0,
        gross_exposure=1.5,
        guardrails=LeverageGuardrails(financing_cost_cap_frac_of_excess_return=0.30),
        benchmark_return_pct=5.0,
    )
    assert ev.passed
