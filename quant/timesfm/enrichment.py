from __future__ import annotations


def format_price_signals(ticker: str, signals: dict) -> str:
    if not signals:
        return ""

    lines = [f"=== TimesFM Price Forecast ({ticker.upper()}) ==="]

    try:
        lines.append(f"  Trend Direction: {signals['trend_direction']}")
    except KeyError:
        pass
    try:
        ms = signals["momentum_score"]
        lines.append(f"  Momentum Score: {ms:+.2f}")
    except KeyError:
        pass
    try:
        vp = signals["volatility_proxy"]
        lines.append(f"  Volatility Proxy (P90-P10)/P50: {vp:.2f}")
    except KeyError:
        pass
    try:
        dr = signals["downside_risk_pct"]
        lines.append(f"  Downside Risk (P10 vs current): {dr:+.1f}%")
    except KeyError:
        pass
    try:
        ut = signals["upside_target"]
        lines.append(f"  Upside Target (P90, horizon end): ${ut:.2f}")
    except KeyError:
        pass

    band = signals.get("confidence_band", [])
    if band:
        lines.append("  Confidence Band:")
        for entry in band[:5]:
            lines.append(
                f"    Step {entry['step']}:  P10=${entry['p10']:.2f}  "
                f"P50=${entry['p50']:.2f}  P90=${entry['p90']:.2f}"
            )

    return "\n".join(lines)


def format_eps_signals(ticker: str, signals: dict) -> str:
    if not signals:
        return ""

    lines = [f"=== TimesFM EPS Forecast ({ticker.upper()}) ==="]

    try:
        lines.append(f"  Trend Direction: {signals['trend_direction']}")
    except KeyError:
        pass

    band = signals.get("confidence_band", [])
    if band:
        p50_vals = [e["p50"] for e in band[:4]]
        lines.append(f"  Forward EPS P50 (next {len(p50_vals)} steps): {[round(v, 2) for v in p50_vals]}")

    try:
        dr = signals["downside_risk_pct"]
        lines.append(f"  Downside Risk (P10 vs current): {dr:+.1f}%")
    except KeyError:
        pass
    try:
        ut = signals["upside_target"]
        lines.append(f"  Upside (P90, final step): ${ut:.2f}")
    except KeyError:
        pass

    return "\n".join(lines)
