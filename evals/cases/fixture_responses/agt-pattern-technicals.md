```json
{
  "signal_vector": {
    "sma_trend": {"score": 1.0, "detail": "price 138.60 > 50d 135.20 > 200d 121.40 — strong uptrend, golden cross structure intact"},
    "mean_reversion_z": {"score": 0.0, "z_score": null, "detail": "insufficient_data — no 60-day mean or standard deviation supplied"},
    "bollinger_pctb": {"score": -0.26, "pct_b": 0.63, "detail": "upper half of the 20d band, mild overbought contribution"},
    "rsi": {"score": -0.17, "rsi_value": 58.4, "detail": "neutral, no divergence detected"},
    "obv_trend": {"score": 0.7, "detail": "OBV rising and confirming price over 60 sessions — accumulation"},
    "atr_regime": {"score": 0.0, "atr_pct": 3.8, "volatility_regime": "high_vol"}
  },
  "composite_score": 0.31,
  "composite_direction": "HOLD",
  "actionable": false,
  "flags": ["insufficient_data_mean_reversion", "high_vol_regime"],
  "technical_levels": {
    "support_1": 126.4,
    "resistance_1": 153.1,
    "stop_loss_atr2x": 128.2
  },
  "pattern_classification": "TRENDING",
  "confidence": "MEDIUM"
}
```

### Quantitative Summary

SMA trend at +1.00 is the dominant signal: price at $138.60 sits above the 50-day at $135.20
and the 200-day at $121.40, a clean trend structure with no gate suppression. OBV at +0.70
confirms it with rising volume over 60 sessions. The two mean-reversion inputs pull the other
way — Bollinger %B of 0.63 scores -0.26 and RSI of 58.4 scores -0.17 — netting a composite of
0.31. That sits below the 0.40 actionable threshold, so this is a trend to hold rather than an
entry to take. The 60-day mean reversion z-score could not be computed and was set to 0.0 with
an insufficient_data flag; supplying it is the single change most likely to move the composite
across the threshold. ATR at 3.8% of price with 41.2% realised volatility places this in the
high-volatility regime, which halves any position that does get taken.

### Technical Narrative

The stock is in a confirmed uptrend rather than a breakout or a reversal. Price above both
moving averages with the 50-day above the 200-day is the strongest of the four SMA
configurations, and the 2.5% gap between price and the 50-day means the trend is being
extended gradually rather than in a vertical move. Over the last six months price has advanced
from the low $90s toward $138.60 against a 52-week range of $75.61 to $153.13, so the current
level is in the upper third of the annual range but has not made a new high.

Resistance at $153.10 coincides with the 52-week high, which makes it a level the market has
already rejected once. Support at $126.40 sits 8.8% below current price and above the 200-day
at $121.40, so the two form a support zone rather than a single line. The 2x ATR stop at
$128.20 falls inside that zone, meaning a stop-out and a support break would be close to
simultaneous — an efficient placement.

Volume is the constructive part of the picture. OBV rising in step with price over 60 sessions
is confirmed accumulation, not a divergence, and it is the signal this pipeline has validated
as carrying alpha. Nothing in the volume record suggests the trend is exhausting. The
constraint on this setup is entry quality, not trend quality: Bollinger %B at 0.63 and RSI at
58.4 both say the entry point is mid-range rather than favourable, and at 3.8% daily ATR the
cost of a poorly timed entry is large. A pullback toward the $126.40 support zone would move
%B toward 0.2 and lift the composite above the actionable threshold.

No near-term catalyst identified.
