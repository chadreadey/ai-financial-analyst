```json
{
  "verdict": "SELL",
  "conviction": "MEDIUM",
  "conviction_score": 0.492,
  "time_horizon": "short-term",
  "primary_horizon_days": 40,
  "signal_breakdown": {
    "dcf": {"score": -0.5, "weight": 0.17},
    "risk": {"score": -0.7, "weight": 0.17},
    "earnings": {"score": -0.6, "weight": 0.22},
    "competitive": {"score": -0.3, "weight": 0.14},
    "pattern": {"score": -0.5, "weight": 0.18},
    "macro": {"score": -0.2, "weight": 0.12}
  },
  "weighted_score": -0.492,
  "prior_bull_probability": 26,
  "prior_bear_probability": 74,
  "entry_price": 21.8,
  "price_target": 17.4,
  "price_target_sources": {
    "dcf_intrinsic": 16.9,
    "peer_multiples": null,
    "analyst_consensus": null,
    "technical_resistance": 24.6
  },
  "stop_loss": {
    "value": 23.7,
    "unit": "price"
  },
  "sizing_guidance": "1.0x_base_weight",
  "review_triggers": [
    "Q3 earnings release",
    "Foundry external anchor customer announcement",
    "18A node milestone confirmation"
  ],
  "signal_conflicts": [],
  "health_scores": {
    "valuation": 3,
    "risk_profile": 2,
    "earnings_quality": 2,
    "competitive_position": 3,
    "quantitative_signals": 3,
    "macro_environment": 4,
    "overall": 3
  }
}
```

### Verdict & Price Target

SELL Intel Corporation (INTC) with a $17.40 target against a $21.80 entry, an implied
downside of 20.2% over 40 days. All six signals are negative and three of them are severely
so. The single most important reason is earnings quality: revenue down 8.4% in a fifth
consecutive declining quarter, gross margin down 620bps, and OCF/NI at 0.61 then 0.58 is a
deteriorating business converting a shrinking profit into progressively less cash.

### Bull Case

The strongest argument for the long side is that the market has already priced much of this.
A 62% max drawdown and RSI at 34.1 mean positioning is washed out, and a foundry announcement
naming an external anchor customer at volume would re-rate the equity violently. The stop at
$23.70 exists to cap that specific risk.

Government subsidy support and the strategic value of domestic leading-edge capacity provide
a floor that pure financial analysis understates. A sovereign-backed balance sheet backstop
changes the distribution of outcomes even when it does not change the central case.

### Bear Case

The accrual signal is the most damning number in the file. Inventory days rising from 118 to
141 while revenue falls means production is outrunning demand and the gap is sitting on the
balance sheet waiting to be written down. OCF/NI below 0.62 for two quarters confirms the
earnings are not cash.

Competitive erosion is structural rather than cyclical. Server CPU share has gone from 92% to
roughly 76% in three years against AMD, ARM-based hyperscaler silicon is taking incremental
sockets, and process leadership was lost and has not been recovered. Negative ASP trends into
a mix shift mean there is no pricing lever to pull.

Financing risk compounds both. Net debt/EBITDA of 4.6x is rising because EBITDA is falling,
$25B of annual foundry capex keeps free cash flow negative through the explicit forecast, and
the 66% dividend cut removed the income buyer. A further node slip pushes breakeven past the
cash runway, and the 5th-percentile scenario at $12.40 is 43% below entry.

### Key Catalyst & Review Trigger

Q3 earnings is the confirming event; the thesis requires inventory days to keep rising and
gross margin to stay below 40%. Cover immediately on an external foundry anchor customer at
volume or on confirmed 18A milestone delivery, both of which would invalidate the competitive
leg. Otherwise review at 40 days.

### Signal Conflicts

None. All six signals agree on direction, ranging from -0.20 on macro to -0.70 on risk. The
spread reflects severity, not disagreement: macro is the mildest because the semiconductor
capex cycle is only mildly adverse for this issuer, while risk is the harshest because
leverage and a binary execution dependency stack on top of the operating decline.
