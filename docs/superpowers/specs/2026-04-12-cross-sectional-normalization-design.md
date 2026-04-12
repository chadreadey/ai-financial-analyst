# Cross-Sectional Signal Normalization

## Goal

Replace raw signal scores with sector-adjusted, winsorized z-scores so that the signal pipeline generalizes across any universe size. A utility stock's exceptional OBV reading should outrank a tech stock's average OBV reading, even though the raw numbers favor tech.

## Architecture

New file `quant/cross_sectional.py` with one primary function:

```
normalize_signals_cross_sectionally(
    signals: dict[str, SignalVector],
    sector_fn: Callable[[str], str],
) -> dict[str, SignalVector]
```

Called once per rebalance date after all per-ticker signal scoring is complete, before composite construction.

## Normalization Algorithm (per signal, per rebalance date)

1. Collect raw scores: `{ticker: score}` for all tickers in the cross-section
2. Compute sector means: `{sector: mean_score}` via `sector_fn(ticker)`
3. Subtract sector mean from each ticker's score (sector-relative adjustment)
4. Winsorize adjusted scores at 2.5th / 97.5th percentile
5. Compute z-score: `(adjusted - mean) / std` (std of winsorized distribution)
6. Scale to [-1, +1]: `clip(z / 3.0, -1.0, 1.0)`
7. Write normalized score back to the SignalVector field

Minimum cross-section size: 10 tickers. Below that, skip normalization and use raw scores (not enough data for meaningful z-scores).

## Signals Normalized

| Signal | Source Field | Notes |
|--------|-------------|-------|
| OBV trend | `sv.obv_trend.score` | Technical, sector-sensitive |
| Earnings (blended) | `sv.earnings_rank_score` | ERM+SUE+Dispersion, set by blend_earnings |
| Institutional flow | `sv.institutional_flow_score` | Set by blend_institutional_flow |
| News sentiment | `sv.sentiment_score` (NEW field) | Set by blend_sentiment |

## Signals NOT Normalized

| Signal | Reason |
|--------|--------|
| ATR regime | Non-directional, used for position sizing |
| Macro regime | Time-series multiplier, not cross-sectional |
| Other dead technical signals (SMA, MR, BB, RSI, 52W) | Zeroed, not active |

## Pipeline Change

### Before (current)

Per-ticker signal compute → blend earnings into composite → blend inst flow into composite → blend sentiment into composite → FOMC → regime → portfolio

Each blend function modifies `sv.composite_score` directly with weighted average.

### After (new)

Per-ticker signal compute → set earnings_rank_score → set institutional_flow_score → set sentiment_score → **normalize all signals cross-sectionally** → **compute composite from normalized scores** → FOMC → regime → portfolio

Blend functions no longer touch `composite_score`. They only set their individual score fields. Composite is built once from normalized values.

## New Composite Construction

```python
def compute_normalized_composite(sv: SignalVector, weights: dict[str, float]) -> float:
    """Build composite from normalized signal fields."""
    total = 0.0
    total_w = 0.0
    for signal_name, weight in weights.items():
        score = getattr(sv, signal_name, 0.0)
        if isinstance(score, SignalResult):
            score = score.score
        total += score * weight
        total_w += weight
    if total_w > 0:
        return np.clip(total / total_w, -1.0, 1.0)
    return 0.0
```

Default weights:
- `obv_trend`: 0.40
- `earnings_rank_score`: 0.30
- `institutional_flow_score`: 0.15
- `sentiment_score`: 0.10
- (remaining 0.05 headroom for future signals)

These weights are normalized, not cumulative like the old sequential blend approach.

## Files to Create

| File | Responsibility |
|------|---------------|
| `quant/cross_sectional.py` | `normalize_signals_cross_sectionally()` + `compute_normalized_composite()` |
| `tests/test_cross_sectional.py` | Unit tests for normalization and composite |

## Files to Modify

| File | Change |
|------|--------|
| `quant/signals.py` | Add `sentiment_score: float = 0.0` field to SignalVector |
| `quant/backtest.py` | Restructure blend chain: blends set fields, then normalize, then composite |
| `quant/earnings_signals.py` | `blend_earnings_signals` sets `sv.earnings_rank_score` only, no composite modification |
| `quant/institutional_flow.py` | `blend_institutional_flow` sets `sv.institutional_flow_score` only, no composite modification |
| `quant/backtest.py` (sentiment blend) | `blend_sentiment_into_signals` sets `sv.sentiment_score` only, no composite modification |

## Backward Compatibility

- `SignalVector.compute_composite()` stays for the live analysis path (single-stock, no cross-section)
- `SignalVector.WEIGHTS` dict stays but is only used by the old `compute_composite()` path
- Backtest pipeline uses the new normalized composite path exclusively
- `BacktestConfig` gets no new fields — normalization is always on in the backtest

## Success Criteria

1. liquid_50 retains meaningful alpha (t > 1.5)
2. liquid_100 alpha improves from t=0.52 toward t > 1.0
3. Gap between liquid_50 and liquid_100 alpha narrows (currently 4:1 ratio)
4. All existing tests continue to pass
