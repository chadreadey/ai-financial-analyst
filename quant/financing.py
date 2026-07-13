"""
Spot-margin financing accrual for levered backtests.

Models the cost of borrowing dollars to fund core-book gross exposure
above 1.0x. Borrowed principal = (gross_exposure - 1.0) * NAV, accrued
daily at (FRED 3M SOFR + spread) / 252.

Also provides pre-declared guardrail evaluation (max-DD, stressed
single-day loss cap, financing-cost cap) — a CPCV path that breaches
any guardrail is marked structurally invalid.

Design notes:
  - SOFR is fetched once via the module-level CachedFREDClient
    (fred_client.CachedFREDClient) and reused for the run.
  - FRED series priority: SOFR90DAYAVG (90-day compound SOFR, the
    industry-standard 3M rate) → SOFR (overnight, pre-2018 gap unlikely) →
    DGS3MO (3M T-bill, documented fallback for pre-2018 dates).
  - Rates are quoted in percent by FRED (e.g. 4.3 for 4.3%) and are
    stored here as annualized decimals (0.043) for arithmetic.
  - The daily accrual uses a 252-day year (matches Sharpe scaling
    convention already in quant.metrics).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


DEFAULT_TRADING_DAYS_PER_YEAR = 252

# FRED series preference: 90-day SOFR average (the tradeable 3M SOFR proxy),
# then overnight SOFR, then 3M T-bill as documented pre-2018 fallback.
SOFR_FRED_SERIES = "SOFR90DAYAVG"
SOFR_FALLBACK_SERIES = "SOFR"
TBILL_FALLBACK_SERIES = "DGS3MO"


# Hard-coded broker-call proxy for any date with no FRED coverage at all
# (used only if FRED calls fail entirely — e.g. no API key). Approximates
# the long-run average of 3M T-bill for 2010–2020 (~1.0% annualized).
HARDCODED_BROKER_CALL_ANN_RATE = 0.02  # 2% ann.


# ── SOFR loader ─────────────────────────────────────────────────────────


def load_sofr_series(
    start_date: str,
    end_date: str,
    *,
    fred_client=None,
) -> pd.Series:
    """
    Return a daily annualized-decimal SOFR-equivalent rate series for
    the requested window, forward-filled to every calendar day and
    aligned to trading days by the caller.

    Fetch order:
      1. FRED SOFR90DAYAVG (3M compound SOFR)
      2. FRED SOFR (overnight, if 90-day avg gap for old dates)
      3. FRED DGS3MO (3M T-bill fallback for pre-2018 dates)
      4. Constant HARDCODED_BROKER_CALL_ANN_RATE (only if all FRED
         calls fail — e.g. no API key)

    Returns a pd.Series indexed by pd.Timestamp with values in
    annualized decimal (0.043 = 4.3%).
    """
    if fred_client is None:
        from fred_client import get_fred_client
        fred_client = get_fred_client()

    if fred_client is None:
        logger.warning(
            "FRED client unavailable — falling back to hardcoded "
            "broker-call proxy of %.2f%%",
            HARDCODED_BROKER_CALL_ANN_RATE * 100,
        )
        idx = pd.date_range(start_date, end_date, freq="B")
        return pd.Series(HARDCODED_BROKER_CALL_ANN_RATE, index=idx)

    # Widen fetch window so the series covers the whole backtest even
    # after forward-fill from the last observation prior to start_date.
    fetch_start = (pd.Timestamp(start_date) - pd.Timedelta(days=90)).strftime("%Y-%m-%d")

    combined: pd.Series = pd.Series(dtype=float)
    for series_id in (SOFR_FRED_SERIES, SOFR_FALLBACK_SERIES, TBILL_FALLBACK_SERIES):
        try:
            s = fred_client.get_series(
                series_id, observation_start=fetch_start, observation_end=end_date,
            )
        except Exception as exc:  # pragma: no cover - network path
            logger.debug("FRED %s failed: %s", series_id, exc)
            s = pd.Series(dtype=float)
        if s is None or s.empty:
            continue
        # FRED returns percent; convert to annualized decimal.
        s = s.astype(float) / 100.0
        if combined.empty:
            combined = s.copy()
        else:
            # Fill any dates missing from the higher-priority series.
            combined = combined.combine_first(s)

    if combined.empty:
        logger.warning(
            "All FRED SOFR/T-bill series empty — falling back to hardcoded "
            "broker-call proxy of %.2f%%",
            HARDCODED_BROKER_CALL_ANN_RATE * 100,
        )
        idx = pd.date_range(start_date, end_date, freq="B")
        return pd.Series(HARDCODED_BROKER_CALL_ANN_RATE, index=idx)

    combined = combined.sort_index()
    # Reindex to business-day frequency across full window and forward-fill
    # so every trading day sees the most recent observed rate.
    full_idx = pd.date_range(start_date, end_date, freq="B")
    combined = combined.reindex(combined.index.union(full_idx)).sort_index().ffill()
    combined = combined.loc[start_date:end_date]
    # Backfill any leading NaN with the first observed value (or the
    # broker-call proxy if the whole series is still NaN).
    if combined.isna().any():
        first_valid = combined.first_valid_index()
        if first_valid is not None:
            combined = combined.bfill()
        else:
            combined[:] = HARDCODED_BROKER_CALL_ANN_RATE
    return combined


# ── Daily accrual ───────────────────────────────────────────────────────


def compute_daily_financing_charge(
    borrowed_dollars: float,
    ann_rate_decimal: float,
    spread_bps: float,
    trading_days: int = DEFAULT_TRADING_DAYS_PER_YEAR,
) -> float:
    """
    Dollar cost of one trading day of financing on `borrowed_dollars`
    at (ann_rate + spread) / trading_days.

    Returns a positive dollar amount (a P&L drag; subtract from day_pnl).
    """
    if borrowed_dollars <= 0:
        return 0.0
    daily_rate = (ann_rate_decimal + spread_bps / 10_000.0) / trading_days
    return float(borrowed_dollars * daily_rate)


def compute_financing_series(
    daily_pnl: pd.Series,
    initial_capital: float,
    gross_exposure: float,
    sofr_series: pd.Series,
    spread_bps: float,
    trading_days: int = DEFAULT_TRADING_DAYS_PER_YEAR,
) -> pd.Series:
    """
    Return a Series of *positive* daily financing charges aligned to the
    dates in `daily_pnl`. Borrowed principal is recomputed each day as
    (gross_exposure - 1.0) * NAV_t, where NAV_t = initial_capital +
    cumulative daily_pnl up to but not including day t.

    Returns an empty Series if gross_exposure <= 1.0.
    """
    if gross_exposure <= 1.0 or daily_pnl.empty:
        return pd.Series(dtype=float)

    excess = gross_exposure - 1.0
    if sofr_series is None or sofr_series.empty:
        # Safe default — use hardcoded broker-call proxy for the whole span.
        sofr_series = pd.Series(HARDCODED_BROKER_CALL_ANN_RATE, index=daily_pnl.index)

    pnl_sorted = daily_pnl.sort_index()
    # NAV at start of each day = initial + cumsum of prior days' pnl
    nav_start_of_day = initial_capital + pnl_sorted.shift(1).fillna(0.0).cumsum()
    # SOFR aligned to trading days
    aligned = sofr_series.reindex(pnl_sorted.index).ffill().bfill()
    daily_rates = (aligned + spread_bps / 10_000.0) / trading_days
    borrowed = (nav_start_of_day * excess).clip(lower=0.0)
    return (borrowed * daily_rates).astype(float)


# ── Guardrails ──────────────────────────────────────────────────────────


@dataclass
class LeverageGuardrails:
    """
    Pre-declared risk gates. Written down before a policy runs; a breach
    in-sample or on any CPCV path fails that path structurally.

    Any field left as None disables the corresponding gate.
    """
    # Max acceptable peak-to-trough drawdown on the equity curve, as a
    # positive decimal fraction (0.25 = 25%).
    max_drawdown_pct: Optional[float] = None
    # Max acceptable NAV loss (positive decimal) for a hypothetical
    # -shock_return single-day market move at the policy's gross exposure.
    # Approximated as gross_exposure * |shock_return|.
    stressed_day_loss_pct: Optional[float] = None
    # Hypothetical market shock applied for the stressed-day test. Default
    # -8% matches the plan's rule of thumb ("−8% market day at policy gross
    # must not breach -15% NAV").
    stress_shock_pct: float = 0.08
    # Cap on financing cost as a fraction of realized excess return.
    # If financing_dollars / abs(excess_return_dollars) exceeds this, fail.
    financing_cost_cap_frac_of_excess_return: Optional[float] = None


@dataclass
class GuardrailEvaluation:
    """Result of running the guardrail checker for one backtest path."""

    passed: bool = True
    breaches: list[str] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "breaches": self.breaches, "stats": self.stats}


def evaluate_guardrails(
    equity_curve: pd.Series,
    daily_returns: pd.Series,
    financing_dollars_paid: float,
    initial_capital: float,
    gross_exposure: float,
    guardrails: LeverageGuardrails,
    benchmark_return_pct: float = 0.0,
) -> GuardrailEvaluation:
    """
    Run every configured guardrail. Return an evaluation with a pass/fail
    verdict and a list of breach descriptions.

    equity_curve: pd.Series of NAV over time (indexed by date).
    daily_returns: pd.Series of daily NAV returns (decimals).
    financing_dollars_paid: cumulative positive dollar financing drag.
    """
    ev = GuardrailEvaluation(passed=True, breaches=[], stats={})

    # Max drawdown
    if guardrails.max_drawdown_pct is not None and not equity_curve.empty:
        running_max = equity_curve.cummax()
        dd = (equity_curve / running_max - 1.0)
        max_dd = float(-dd.min()) if len(dd) else 0.0
        ev.stats["observed_max_drawdown"] = max_dd
        if max_dd > guardrails.max_drawdown_pct:
            ev.passed = False
            ev.breaches.append(
                f"max_drawdown {max_dd:.2%} > cap {guardrails.max_drawdown_pct:.2%}"
            )

    # Stressed single-day loss (analytical, not observed): a -shock% market
    # day at this gross would produce a NAV loss of gross * shock. If that
    # exceeds the cap, the policy is fragile by construction.
    if guardrails.stressed_day_loss_pct is not None:
        stressed_loss = float(gross_exposure) * float(guardrails.stress_shock_pct)
        ev.stats["stressed_day_loss"] = stressed_loss
        if stressed_loss > guardrails.stressed_day_loss_pct:
            ev.passed = False
            ev.breaches.append(
                f"stressed_day_loss {stressed_loss:.2%} "
                f"({guardrails.stress_shock_pct:.0%} shock × {gross_exposure:.2f}x gross) "
                f"> cap {guardrails.stressed_day_loss_pct:.2%}"
            )

    # Financing cap as fraction of realized excess return over the window.
    # If daily_returns has data, use its total return as the realized
    # strategy return; excess return = strategy_return - benchmark_return.
    if guardrails.financing_cost_cap_frac_of_excess_return is not None:
        if not daily_returns.empty and initial_capital > 0:
            strat_return_pct = float((1.0 + daily_returns).prod() - 1.0) * 100.0
            excess_pct = strat_return_pct - float(benchmark_return_pct)
            excess_dollars = excess_pct / 100.0 * initial_capital
            if excess_dollars > 0:
                frac = financing_dollars_paid / excess_dollars
                ev.stats["financing_as_frac_of_excess_return"] = frac
                if frac > guardrails.financing_cost_cap_frac_of_excess_return:
                    ev.passed = False
                    ev.breaches.append(
                        f"financing_frac_of_excess {frac:.2%} > cap "
                        f"{guardrails.financing_cost_cap_frac_of_excess_return:.2%}"
                    )
            else:
                # Negative excess return with any financing charge is itself
                # a breach of the cap (financing 'exceeds' the excess).
                if financing_dollars_paid > 0:
                    ev.stats["financing_as_frac_of_excess_return"] = float("inf")
                    ev.passed = False
                    ev.breaches.append(
                        f"financing_frac_of_excess undefined (excess return "
                        f"{excess_pct:.2f}% <= 0 with financing "
                        f"${financing_dollars_paid:,.0f})"
                    )
    return ev
