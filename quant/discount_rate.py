"""
Discount rate helpers using scipy for yield curve interpolation
and numpy for bond present value calculations.

Replaces the need for QuantLib with lightweight equivalents that
are practically identical for equity research discount rate estimation.
"""

import logging
from typing import Dict, Optional, Tuple

import numpy as np

from config import settings
from fred_client import TREASURY_SERIES, get_fred_client

logger = logging.getLogger(__name__)


def get_risk_free_rate(
    maturity_years: float = 10.0,
    fred_api_key: Optional[str] = None,
) -> Optional[float]:
    """
    Interpolate the risk-free rate from the Treasury yield curve.

    Returns the annualized yield as a decimal (e.g. 0.045 for 4.5%),
    or None if data is unavailable.
    """
    client = get_fred_client(fred_api_key)
    if client is None:
        return None

    try:
        from scipy.interpolate import interp1d

        curve = client.get_yield_curve()
        if curve is None or len(curve) < 3:
            return None

        maturities = sorted(curve.keys())
        yields_pct = [curve[m] for m in maturities]

        maturities_arr = np.array(maturities)
        yields_arr = np.array(yields_pct)

        interp_fn = interp1d(
            maturities_arr,
            yields_arr,
            kind="cubic" if len(maturities) >= 4 else "linear",
            fill_value="extrapolate",
        )

        clamped_maturity = max(min(maturity_years, max(maturities)), min(maturities))
        rate_pct = float(interp_fn(clamped_maturity))
        return rate_pct / 100.0

    except (ImportError, ValueError) as exc:
        logger.debug("Risk-free rate computation failed: %s", exc)
        return None


def get_yield_curve_snapshot(
    fred_api_key: Optional[str] = None,
) -> Optional[Dict[float, float]]:
    """
    Return the full yield curve as {maturity_years: yield_pct}.
    Useful for DCF agent context injection.
    """
    client = get_fred_client(fred_api_key)
    if client is None:
        return None

    try:
        return client.get_yield_curve()
    except (ImportError, ValueError) as exc:
        logger.debug("Yield curve snapshot failed: %s", exc)
        return None


def pv_of_debt(
    coupon_rate: float,
    face_value: float,
    maturity_years: float,
    yield_to_maturity: float,
    frequency: int = 2,
) -> float:
    """
    Calculate the present value of a bond using standard bond math.
    """
    if maturity_years <= 0:
        return face_value

    n_periods = int(maturity_years * frequency)
    periodic_rate = yield_to_maturity / frequency
    periodic_coupon = (coupon_rate * face_value) / frequency

    if periodic_rate == 0:
        return periodic_coupon * n_periods + face_value

    pv_coupons = periodic_coupon * (1 - (1 + periodic_rate) ** -n_periods) / periodic_rate
    pv_face = face_value / (1 + periodic_rate) ** n_periods

    return pv_coupons + pv_face


def estimate_wacc(
    risk_free_rate: float,
    beta: float,
    equity_risk_premium: float = 0.055,
    cost_of_debt_pretax: float = 0.05,
    tax_rate: float = 0.21,
    debt_ratio: float = 0.3,
) -> Tuple[float, Dict[str, float]]:
    """
    Estimate WACC from component inputs.

    Returns (wacc, components_dict) where components_dict
    contains the intermediate values for transparency.
    """
    cost_of_equity = risk_free_rate + beta * equity_risk_premium
    cost_of_debt_aftertax = cost_of_debt_pretax * (1 - tax_rate)
    equity_ratio = 1 - debt_ratio

    wacc = equity_ratio * cost_of_equity + debt_ratio * cost_of_debt_aftertax

    components = {
        "risk_free_rate": risk_free_rate,
        "beta": beta,
        "equity_risk_premium": equity_risk_premium,
        "cost_of_equity": cost_of_equity,
        "cost_of_debt_pretax": cost_of_debt_pretax,
        "cost_of_debt_aftertax": cost_of_debt_aftertax,
        "tax_rate": tax_rate,
        "debt_ratio": debt_ratio,
        "equity_ratio": equity_ratio,
        "wacc": wacc,
    }

    return wacc, components


def format_wacc_context(
    ticker: str,
    risk_free_rate: Optional[float],
    yield_curve: Optional[Dict[float, float]],
) -> str:
    """Format WACC-related data into a text block for the DCF agent context."""
    lines = ["=== Discount Rate Data ==="]

    if risk_free_rate is not None:
        lines.append(f"  Risk-Free Rate (10Y interpolated): {risk_free_rate*100:.2f}%")

    if yield_curve:
        lines.append("  Treasury Yield Curve:")
        for mat in sorted(yield_curve.keys()):
            lines.append(f"    {mat:.1f}Y: {yield_curve[mat]:.2f}%")

        if 2.0 in yield_curve and 10.0 in yield_curve:
            spread = yield_curve[10.0] - yield_curve[2.0]
            state = "INVERTED" if spread < 0 else "NORMAL"
            lines.append(f"  2s10s Spread: {spread:+.2f}pp ({state})")

    return "\n".join(lines)
