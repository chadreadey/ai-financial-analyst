from __future__ import annotations

import numpy as np


def extract_signals(
    current_value: float,
    point_forecast: list[float],
    quantiles: dict[str, list[float]],
) -> dict:
    p10 = quantiles["p10"]
    p50 = quantiles["p50"]
    p90 = quantiles["p90"]
    n = len(point_forecast)

    steps = np.arange(n, dtype=float)
    coeffs = np.polyfit(steps, point_forecast, 1)
    slope = coeffs[0]
    slope_pct = slope / point_forecast[0] if point_forecast[0] != 0 else 0.0

    if slope_pct > 0.005:
        trend_direction = "bullish"
    elif slope_pct < -0.005:
        trend_direction = "bearish"
    else:
        trend_direction = "neutral"

    raw_momentum = (
        (point_forecast[-1] - point_forecast[0]) / point_forecast[0]
        if point_forecast[0] != 0
        else 0.0
    )
    momentum_score = max(-1.0, min(1.0, raw_momentum))

    volatility_proxy = (p90[-1] - p10[-1]) / p50[-1] if p50[-1] != 0 else 0.0

    downside_risk_pct = (
        (p10[-1] - current_value) / current_value * 100 if current_value != 0 else 0.0
    )

    upside_target = p90[-1]

    confidence_band = [
        {"step": i + 1, "p10": p10[i], "p50": p50[i], "p90": p90[i]} for i in range(n)
    ]

    return {
        "trend_direction": trend_direction,
        "momentum_score": round(momentum_score, 4),
        "volatility_proxy": round(volatility_proxy, 4),
        "downside_risk_pct": round(downside_risk_pct, 2),
        "upside_target": round(upside_target, 2),
        "confidence_band": confidence_band,
    }
