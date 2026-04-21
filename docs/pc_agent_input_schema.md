# Portfolio Construction Agent — Input / Output Schema

**Status:** Design document. Not yet implemented.
**Last updated:** 2026-04-16
**Purpose:** Define the structured data contracts the PC Agent consumes and emits.
All schemas are expressed in Python `TypedDict` notation for clarity and future implementation.

---

## Design Principles

1. **Quant signals are primary.** The `QuantSignalBundle` + XGBoost rank drive position sizing. LLM research outputs are confidence modifiers, not vetoes.
2. **No prose allowed in PC agent inputs.** Every agent must emit a typed struct. Prose is stored separately for the audit log but is never used in the decision loop.
3. **Price targets from LLM agents are intentionally excluded.** DCF price targets ignore leverage and multiples; they add hallucination risk without validated alpha.
4. **Explicit uncertainty.** Agents must distinguish "I have low confidence" from "this is a bad trade." The `uncertainty` flag captures the former; `top_risk_factor` captures the latter.
5. **Hard guardrails cannot be overridden by any agent.** The PC agent records which guardrail blocked a trade in `overriding_guardrail` so the decision is always auditable.

---

## 1. QuantSignalBundle

Per-stock structured signals from the quant pipeline. Emitted once per rebalance cycle for each stock in the universe.

```python
from typing import Literal, Optional
from typing_extensions import TypedDict

class QuantSignalBundle(TypedDict):
    # ── Identity ──────────────────────────────────────────────────────────────
    ticker: str
    # ISO 8601 timestamp of when signals were computed. Used to detect stale data.
    as_of_utc: str

    # ── Linear composite (primary ranking signal) ─────────────────────────────
    # Weighted sum of all sub-signals after cross-sectional z-score normalization.
    # Range: [-3, +3] in practice; unbounded in theory.
    composite_score: float

    # ── XGBoost meta-model rank ───────────────────────────────────────────────
    # Output of the trained XGBoost regressor on the full signal vector.
    # Range: [-1, +1]. Positive = model expects outperformance vs universe.
    # None if model is unavailable or feature vector is incomplete.
    xgb_rank_score: Optional[float]

    # ── Individual signals (all cross-sectionally normalized unless noted) ────
    # Analyst earnings revision momentum (IBES). IC ~0.06. Range: [-3, +3].
    earnings_rank: float

    # On-Balance Volume trend. Only technical signal with validated alpha.
    # Positive = accumulation, Negative = distribution. Range: [-3, +3].
    obv_trend: float

    # Composite fundamental quality: profitability, balance sheet, accruals.
    # Range: [-3, +3].
    quality: float

    # 1-month and 12-1 month price momentum, blended. Range: [-3, +3].
    price_momentum: float

    # News/social sentiment score (Finnhub + Alpaca). Range: [-1, +1].
    # Zero-weight in live model; retained for monitoring.
    sentiment: float

    # Net insider buying/selling over trailing 90 days. Range: [-3, +3].
    # Sparse; treat as supplemental, not primary.
    insider: float

    # PEAD (post-earnings announcement drift) + catalyst proximity signal.
    # Positive near upcoming catalyst, negative immediately post-announcement.
    # Currently zero-weighted in composite due to sparse signal.
    event_timing: float

    # Kalshi macro probability level (cross-stock, same value for all).
    # Derived from recession and rate-cut contract prices. Range: [-1, +1].
    # Positive = macro tailwind (rate cuts likely, recession unlikely).
    kalshi_macro_score: float

    # Kalshi event-specific probability for this stock's sector/catalyst.
    # Range: [-1, +1]. None if no relevant contract exists.
    kalshi_event_score: Optional[float]

    # Price regression score: distance of current price from regression trend.
    # Negative = price below trend (potential mean reversion up). Range: [-3, +3].
    price_regression_score: float

    # ARIMA 20-day forecast direction and magnitude. Range: [-1, +1].
    # Treat as weak directional prior, not a precision forecast.
    arima_forecast_score: float

    # Copper regime score: copper/gold ratio trend as cyclical indicator.
    # Positive = pro-cyclical environment. Range: [-1, +1].
    copper_regime_score: float

    # ── Signal completeness ───────────────────────────────────────────────────
    # Fraction of signals that are non-zero/non-None. Range: [0, 1].
    # PC agent should discount decisions when coverage < 0.6.
    signal_coverage: float

    # Number of trading days since the most recent earnings report.
    days_since_earnings: Optional[int]
```

---

## 2. ResearchAgentOutput

Each of the 6 LLM research agents must emit this structured schema **in addition to** their prose narrative. The prose is stored in the audit log. The PC agent consumes only the structured fields.

### 2a. Shared base (all agents)

```python
class ResearchAgentBase(TypedDict):
    agent_name: Literal[
        "DCFAgent", "EarningsAgent", "CompetitiveAgent",
        "MacroAgent", "RiskAgent", "PatternAgent"
    ]
    ticker: str
    as_of_utc: str

    # Probability-calibrated directional confidence.
    # bull_confidence + bear_confidence need not sum to 1
    # (the gap represents genuine uncertainty / "I don't know").
    # Range: [0, 1] each.
    bull_confidence: float
    bear_confidence: float

    # True when the agent's data is insufficient to form a view.
    # If True, PC agent treats this agent's output as abstention.
    is_uncertain: bool

    # Single most important risk this agent identified. Free text (short),
    # required even when is_uncertain=True. Max 120 chars.
    top_risk_factor: str

    # The single most load-bearing assumption in this agent's analysis.
    # Used in audit trail and for future model-learning. Max 120 chars.
    key_assumption: str

    # Qualitative stance summary for the audit log UI.
    stance: Literal["BULLISH", "NEUTRAL", "BEARISH", "UNCERTAIN"]
```

### 2b. DCFAgent output

**Current behavior:** Produces prose BUY/HOLD/SELL with a price target derived from a perpetuity growth model. The price target is explicitly excluded here because it ignores leverage, capital structure changes, and sector multiples.

```python
class DCFAgentOutput(ResearchAgentBase):
    agent_name: Literal["DCFAgent"]

    # Estimated WACC used in the agent's FCF analysis.
    # None if the agent could not estimate it. Range: [0.04, 0.20].
    estimated_wacc: Optional[float]

    # 5-year compound annual revenue growth rate assumed by the agent.
    # Range: [-0.30, 0.60]. Used to calibrate how aggressive the bull case is.
    assumed_revenue_cagr: Optional[float]

    # FCF yield implied by the agent's terminal value (FCF / enterprise value).
    # Range: [0, 0.25]. Low values (<0.02) signal expensive valuation.
    implied_fcf_yield: Optional[float]

    # Qualitative assessment of balance sheet capacity for the investment thesis.
    # Captures leverage risk without relying on the unreliable price target.
    balance_sheet_capacity: Literal["STRONG", "ADEQUATE", "STRETCHED", "DISTRESSED"]

    # Margin of safety in the agent's central DCF case.
    # Positive = stock appears cheap vs intrinsic value, Negative = expensive.
    # Range: [-1.0, +1.0]. PC agent should discount values beyond ±0.5 as noisy.
    margin_of_safety_estimate: Optional[float]
```

**Rationale:** DCF agents produce unreliable absolute price targets but have signal in WACC, growth assumptions, and FCF yield — these are extractable without trusting the point estimate.

### 2c. EarningsAgent output

**Current behavior:** Produces prose STRONG/STABLE/DETERIORATING/WEAK verdict with qualitative margin and EPS trajectory analysis.

```python
class EarningsAgentOutput(ResearchAgentBase):
    agent_name: Literal["EarningsAgent"]

    # Agent's qualitative verdict on earnings health.
    earnings_health: Literal["STRONG", "STABLE", "DETERIORATING", "WEAK"]

    # Whether the agent detected positive, neutral, or negative analyst revision momentum.
    revision_direction: Literal["UP", "FLAT", "DOWN", "UNKNOWN"]

    # Agent's assessment of cash conversion quality.
    # HIGH = OCF/NI > 1.0 consistently; LOW = accruals-inflated earnings.
    cash_conversion_quality: Literal["HIGH", "MEDIUM", "LOW", "UNKNOWN"]

    # Number of near-term earnings catalysts the agent identified (positive or negative).
    # Range: [0, 5].
    catalyst_count: int

    # True if the agent flagged a specific near-term earnings beat risk (upside).
    beat_risk_flag: bool

    # True if the agent flagged a specific near-term earnings miss risk (downside).
    miss_risk_flag: bool
```

**Rationale:** The earnings agent has direct view on revision momentum and cash conversion, which are the two signals with validated IC. Extracting these explicitly prevents the PC agent from having to parse prose.

### 2d. CompetitiveAgent output

**Current behavior:** Produces a Bain-style strategic verdict (DOMINANT/STRONG/AVERAGE/WEAK) with Porter's Five Forces assessment.

```python
class CompetitiveAgentOutput(ResearchAgentBase):
    agent_name: Literal["CompetitiveAgent"]

    # Overall competitive position assessment.
    competitive_position: Literal["DOMINANT", "STRONG", "AVERAGE", "WEAK"]

    # Moat durability — how likely is the competitive advantage to persist 3-5 years?
    moat_durability: Literal["DURABLE", "MODERATE", "FRAGILE", "NONE"]

    # Agent's assessment of pricing power based on margin trends.
    pricing_power: Literal["STRONG", "MODERATE", "WEAK", "NONE"]

    # Industry lifecycle stage. Drives terminal growth rate expectations.
    sector_stage: Literal["EARLY_GROWTH", "GROWTH", "MATURE", "DECLINING"]

    # True if the agent identified a material technology disruption risk within 3 years.
    disruption_risk: bool
```

**Rationale:** Competitive moat and pricing power are durable signals that complement the quant momentum signals. Sector stage informs how much weight to give long-duration DCF assumptions.

### 2e. MacroAgent output

**Current behavior:** Produces TAILWIND/NEUTRAL/HEADWIND verdict with narrative on rate sensitivity and geopolitical factors.

```python
class MacroAgentOutput(ResearchAgentBase):
    agent_name: Literal["MacroAgent"]

    # Agent's macro verdict for this specific stock given its sector and leverage profile.
    macro_verdict: Literal["TAILWIND", "NEUTRAL", "HEADWIND"]

    # Current macro regime as assessed by the agent (not the quant regime detector).
    # Kept separate so the PC agent can compare LLM regime read vs quant regime signals.
    macro_regime: Literal["EXPANSION", "LATE_CYCLE", "RECESSION", "RECOVERY", "UNKNOWN"]

    # Agent's assessment of this stock's sensitivity to rate changes.
    # HIGH = heavily debt-financed or rate-sensitive sector (e.g., REITs, banks).
    rate_sensitivity: Literal["HIGH", "MEDIUM", "LOW"]

    # True if the agent identified material FX or trade policy risk for this company.
    fx_trade_risk: bool

    # Months until the next macro event the agent flagged as material for this stock.
    # None if no specific event horizon identified.
    months_to_key_macro_event: Optional[int]
```

**Rationale:** The quant pipeline already computes copper_regime_score and Kalshi macro signals. The MacroAgent adds qualitative texture — particularly rate sensitivity and FX risk — that the quant signals don't capture at the stock level.

### 2f. RiskAgent output

**Current behavior:** Produces Bridgewater-style risk scores (1–10) across Financial, Operational, and Market risk dimensions with tail risk scenarios.

```python
class RiskAgentOutput(ResearchAgentBase):
    agent_name: Literal["RiskAgent"]

    # Composite risk rating. Range: [1, 10]. 1 = very low, 10 = extreme.
    composite_risk_score: float

    # Financial risk sub-score (leverage, liquidity). Range: [1, 10].
    financial_risk_score: float

    # Operational risk sub-score (margin volatility, concentration). Range: [1, 10].
    operational_risk_score: float

    # Market risk sub-score (macro sensitivity, cyclicality). Range: [1, 10].
    market_risk_score: float

    # Agent's assessment of balance sheet stress capacity.
    # Can the company survive a 30% revenue decline for 2 years?
    balance_sheet_resilience: Literal["HIGH", "MEDIUM", "LOW", "CRITICAL"]

    # True if the agent flagged off-balance-sheet risks (leases, guarantees, SPVs).
    off_balance_sheet_flag: bool
```

**Rationale:** The Risk agent's numeric scores (1–10) are directly usable as position size dampeners. A composite_risk_score > 7 should trigger a hard position cap in the PC agent's guardrails.

### 2g. PatternAgent output

**Current behavior:** Already emits a JSON block with signal_vector, pattern_classification, and confidence. This is the most compatible agent for structured extraction.

```python
class PatternAgentOutput(ResearchAgentBase):
    agent_name: Literal["PatternAgent"]

    # Price pattern type as classified by the agent.
    pattern_classification: Literal["TRENDING", "MEAN_REVERTING", "BREAKOUT", "RANGE_BOUND"]

    # Agent's interpretation of OBV vs. fundamentals alignment.
    # ALIGNED = both point same direction; CONFLICTED = divergence detected.
    primary_signal_alignment: Literal["ALIGNED", "CONFLICTED", "NEUTRAL"]

    # The most important signal conflict the agent identified, if any.
    # Max 120 chars. None if no material conflict.
    key_conflict: Optional[str]

    # Agent's read of fundamental patterns (revenue/earnings/margin trajectory).
    fundamental_trend: Literal["ACCELERATING", "STABLE", "DECELERATING", "DETERIORATING"]

    # Agent-level confidence in the pattern read.
    # Note: this is separate from bull_confidence/bear_confidence — it measures
    # signal clarity, not directional strength.
    pattern_confidence: Literal["HIGH", "MEDIUM", "LOW"]
```

**Rationale:** PatternAgent already has the most structured output of all six agents. These fields map directly from the JSON it already emits, requiring minimal change.

---

## 3. MacroContext

Regime-level signals shared across all stocks. Emitted once per rebalance cycle. These are computed by the quant pipeline and Kalshi integrations — not by LLM agents.

```python
class MacroContext(TypedDict):
    as_of_utc: str

    # VIX regime state from the VIX 30/40 model (the gold-standard baseline).
    # NORMAL = VIX < 20; ELEVATED = VIX 20-30; RISK_OFF_30 = VIX >= 30;
    # EXTREME = VIX >= 40.
    vix_state: Literal["NORMAL", "ELEVATED", "RISK_OFF_30", "EXTREME"]

    # Raw VIX level at signal computation time.
    vix_level: float

    # VIX / 20-day moving average ratio. >1.3 triggers the risk_off signal.
    vix_ratio: float

    # True if copper/gold ratio is in a declining trend (cyclical headwind).
    copper_bearish: bool

    # SPY price relative to its 200-day SMA. Positive = above (risk-on).
    spy_sma200_gap_pct: float

    # Portfolio turbulence index. >1.5x historical mean = elevated correlation breakdown.
    turbulence_index: Optional[float]

    # Hard risk-off flag. True when vix_ratio > 1.3 OR vix_level >= 30.
    # When True: PC agent must reduce gross exposure to max_gross_exposure_risk_off.
    risk_off: bool

    # Soft caution flag. True when vix_ratio > 1.1 OR copper_bearish.
    # When True: PC agent should not add new positions > 5% single-stock.
    cautious: bool

    # ── Kalshi macro signals ─────────────────────────────────────────────────
    # Current Kalshi macro probability level score. Range: [-1, +1].
    # Derived from recession and rate-cut contract prices.
    # Positive = macro tailwind (rate cuts likely, recession unlikely).
    kalshi_macro_level: float

    # Rate of change of kalshi_macro_level over the trailing 5 trading days.
    # Positive = macro outlook improving. Range: [-0.5, +0.5] in practice.
    # The key signal for the Cornwall Capital options layer: sustained spike
    # in momentum that is not yet priced into IV is the trigger condition.
    kalshi_macro_momentum: float

    # True if kalshi_macro_momentum has been positive for >= 3 consecutive days.
    kalshi_momentum_sustained: bool

    # The macro regime as identified by the quant pipeline.
    quant_regime: Literal["RISK_ON", "CAUTIOUS", "RISK_OFF", "EXTREME_RISK_OFF"]
```

---

## 4. OptionsSignal

Per-stock signal for the Cornwall Capital directional bet layer. Only generated when a stock passes the options screening criteria (signal_reliability_tier = HIGH or MED, days_to_earnings <= 21, earnings_beat_confidence >= 0.65).

```python
from typing import Literal, Optional
from typing_extensions import TypedDict

class OptionsSignal(TypedDict):
    ticker: str
    as_of_utc: str

    # ── Reliability tier (trust calibration) ─────────────────────────────────
    # Criteria:
    #   HIGH:  Large cap (market cap > $10B), 30-day realized vol < 30%,
    #          earnings history >= 3 years (12+ quarters reported).
    #   MED:   Mid cap ($2B–$10B) OR < 3 years earnings history OR
    #          30-day realized vol 30–50%.
    #   LOW:   Small cap (< $2B), 30-day realized vol > 50%,
    #          < 1 year earnings history, OR any crypto-adjacent revenue > 20%.
    # The PC agent should NOT initiate options positions for LOW tier stocks.
    signal_reliability_tier: Literal["HIGH", "MED", "LOW"]

    # ── Beat / miss probability ───────────────────────────────────────────────
    # Our model's estimate of P(earnings beat consensus by >= 1 standard deviation).
    # Derived from: EarningsAgent.beat_risk_flag, earnings_rank signal,
    # event_timing signal, and historical beat rate for this ticker.
    # Range: [0, 1].
    implied_beat_prob: float

    # Market's implied probability of a beat, derived from:
    # (a) Kalshi event contract for this earnings date if available, or
    # (b) options-implied move vs. historical realized post-earnings move.
    # Range: [0, 1]. None if no reliable market proxy exists.
    market_implied_prob: Optional[float]

    # IV percentile vs. trailing 252-day IV for the nearest ATM options.
    # Range: [0, 100]. High IV (> 75th pct) = expensive options, lower edge.
    iv_percentile: Optional[float]

    # Days until next scheduled earnings announcement.
    days_to_earnings: Optional[int]

    # Directional suggestion based on implied_beat_prob vs. market_implied_prob gap.
    # CALL = our model significantly more bullish than market (gap > 0.15)
    # PUT  = our model significantly more bearish than market (gap < -0.15)
    # NONE = insufficient edge or LOW tier
    suggested_direction: Literal["CALL", "PUT", "NONE"]

    # Overall confidence in the options signal.
    # Combines: signal_reliability_tier, edge magnitude, IV environment.
    # Range: [0, 1]. PC agent should not act below 0.60.
    confidence_score: float

    # True if kalshi_macro_momentum is sustained AND iv_percentile < 50.
    # This is the Cornwall Capital trigger: macro momentum spike not priced in IV.
    cornwall_trigger: bool

    # Maximum acceptable loss as a fraction of portfolio NAV if trade is entered.
    # PC agent enforces this as a hard limit. Range: [0.005, 0.03].
    max_loss_pct_nav: float
```

### Signal Reliability Tier — Implementation Criteria

| Tier | Market Cap | Realized Vol (30d) | Earnings History | Crypto-Adjacent Revenue |
|------|-----------|-------------------|-----------------|------------------------|
| HIGH | > $10B    | < 30%             | >= 3 years (12+ quarters) | < 5% |
| MED  | $2B–$10B  | 30–50%            | 1–3 years       | < 20% |
| LOW  | < $2B     | > 50%             | < 1 year        | >= 20% |

**Rule:** If ANY criterion places a stock in a lower tier, use the lower tier. Tier is re-evaluated each rebalance cycle and stored in the audit log.

---

## 5. PCAgentDecision

The structured output the PC agent emits for each stock after consuming all inputs. One decision per stock per rebalance cycle. All decisions are written to the audit log with full input state attached.

```python
from typing import Literal, Optional, List
from typing_extensions import TypedDict

class ReasoningStep(TypedDict):
    # Which input drove this reasoning step.
    signal_source: str  # e.g., "QuantSignalBundle.composite_score", "RiskAgent.composite_risk_score"
    # The value observed.
    observed_value: str
    # What this implies for the decision.
    implication: str

class PCAgentDecision(TypedDict):
    ticker: str
    decision_utc: str

    # ── Position action ───────────────────────────────────────────────────────
    # BUY          = initiate or increase equity position
    # SELL         = reduce or close equity position
    # HOLD         = no change to current position
    # OPEN_OPTION  = initiate a directional options position (defined-risk)
    # CLOSE_OPTION = close an existing options position
    # HOLD_OPTION  = no change to existing options position
    # BLOCKED      = trade was prevented by a hard guardrail (see overriding_guardrail)
    position_action: Literal[
        "BUY", "SELL", "HOLD",
        "OPEN_OPTION", "CLOSE_OPTION", "HOLD_OPTION",
        "BLOCKED"
    ]

    # Target position size as a percentage of portfolio NAV.
    # For equity: range [0, 0.15]. For options (notional): range [0, 0.05].
    # Zero for SELL/CLOSE/BLOCKED (target = 0).
    size_pct: float

    # Change in position size from current. Positive = adding, Negative = reducing.
    size_delta_pct: float

    # ── Structured reasoning (NOT prose) ─────────────────────────────────────
    # Ordered list of the inputs that most influenced the decision.
    # Minimum 3 steps, maximum 8. Each step names a specific signal and value.
    reasoning_steps: List[ReasoningStep]

    # ── Confidence and uncertainty ────────────────────────────────────────────
    # PC agent's overall confidence in the decision. Range: [0, 1].
    # Below 0.5 = agent is uncertain; PC agent should reduce size by 50%.
    decision_confidence: float

    # True when the PC agent is explicitly flagging uncertainty rather than
    # a directional view. Distinct from a bearish view.
    is_uncertain: bool

    # ── Guardrails ────────────────────────────────────────────────────────────
    # The specific hard guardrail that blocked or modified a trade.
    # None if no guardrail was triggered.
    # Examples:
    #   "MAX_SINGLE_STOCK_5PCT"    — single-stock cap in cautious regime
    #   "RISK_OFF_NO_NEW_LONGS"    — no new long positions in risk_off regime
    #   "MAX_POSITION_15PCT"       — absolute single-stock size limit
    #   "RISK_SCORE_7_CAP_3PCT"    — RiskAgent composite_risk_score > 7 cap
    #   "LOW_SIGNAL_COVERAGE"      — signal_coverage < 0.6, size halved
    #   "LOW_TIER_NO_OPTIONS"      — signal_reliability_tier = LOW, options blocked
    #   "MIN_OPTION_CONFIDENCE"    — options confidence_score < 0.60
    #   "MAX_OPTION_LOSS_PCT_NAV"  — max_loss_pct_nav cap enforced
    overriding_guardrail: Optional[str]

    # True if the guardrail modified the trade (e.g., reduced size) rather than blocked it.
    guardrail_modified_not_blocked: bool

    # ── Review schedule ───────────────────────────────────────────────────────
    # ISO 8601 date of the next scheduled review for this position.
    # Standard = next monthly rebalance. Accelerated = earnings or event within 21 days.
    next_review_date: str

    # True if the next review is accelerated due to a near-term catalyst.
    accelerated_review: bool

    # ── Audit ─────────────────────────────────────────────────────────────────
    # Hash of all input signals used. Enables exact replay of the decision.
    input_state_hash: str

    # Version of the PC agent that produced this decision.
    pc_agent_version: str
```

---

## 6. Hard Guardrail Registry

The following guardrails are **non-negotiable**. The PC agent must check each one in order before emitting a decision. If triggered, the agent records the guardrail name in `overriding_guardrail` and either blocks the trade (`BLOCKED`) or reduces size to the guardrail limit.

| Guardrail ID | Condition | Action |
|---|---|---|
| `MAX_POSITION_15PCT` | Any single equity position > 15% NAV | Cap to 15% |
| `RISK_OFF_NO_NEW_LONGS` | `MacroContext.risk_off = True` AND `size_delta_pct > 0` | BLOCK new longs |
| `MAX_SINGLE_STOCK_5PCT` | `MacroContext.cautious = True` AND new position > 5% NAV | Cap to 5% |
| `RISK_SCORE_7_CAP_3PCT` | `RiskAgentOutput.composite_risk_score > 7` | Cap to 3% NAV |
| `LOW_SIGNAL_COVERAGE` | `QuantSignalBundle.signal_coverage < 0.6` | Halve target size |
| `LOW_TIER_NO_OPTIONS` | `OptionsSignal.signal_reliability_tier = "LOW"` | BLOCK options trade |
| `MIN_OPTION_CONFIDENCE` | `OptionsSignal.confidence_score < 0.60` | BLOCK options trade |
| `MAX_OPTION_LOSS_PCT_NAV` | Options position max loss would exceed `max_loss_pct_nav` | BLOCK or resize |
| `VIX_EXTREME_NO_OPTIONS` | `MacroContext.vix_state = "EXTREME"` | BLOCK all options |

---

## 7. Data Flow Summary

```
┌─────────────────────────────────────────────────┐
│              Quant Pipeline                      │
│  composite_score, xgb_rank, OBV, earnings_rank  │
│  kalshi_macro_score, kalshi_macro_momentum...    │
└────────────────────┬────────────────────────────┘
                     │  QuantSignalBundle (per stock)
                     ▼
┌─────────────────────────────────────────────────┐
│         6 LLM Research Agents                    │
│  DCF / Earnings / Competitive /                  │
│  Macro / Risk / Pattern                          │
└────────────────────┬────────────────────────────┘
                     │  ResearchAgentOutput × 6 (per stock)
                     ▼
┌─────────────────────────────────────────────────┐
│         Regime Detection + Kalshi Layer          │
└────────────────────┬────────────────────────────┘
                     │  MacroContext (shared, all stocks)
                     ▼
┌─────────────────────────────────────────────────┐
│         Options Screening Layer                  │
└────────────────────┬────────────────────────────┘
                     │  OptionsSignal (per eligible stock)
                     ▼
┌═════════════════════════════════════════════════╗
║       Portfolio Construction Agent               ║
║  Applies guardrails → emits PCAgentDecision      ║
╚═════════════════════════════════════════════════╝
                     │  PCAgentDecision (per stock)
                     ▼
            Audit Log + Execution Layer
```

---

## 8. Implementation Notes

- **Agent migration path:** Each existing agent needs a structured output section appended to its prompt. The prose narrative remains but the JSON block becomes the source of truth for PC agent consumption.
- **PatternAgent:** Already emits JSON; migration is a schema alignment task only.
- **RiskAgent:** Risk scores (1–10) are already in the prompt; structured extraction is straightforward.
- **DCFAgent price target:** Intentionally not included. If future versions want to use it, it should go through a separate valuation-calibration layer with a demonstrated IC before the PC agent consumes it.
- **Kalshi momentum:** `kalshi_macro_momentum` is the key new signal. It should be computed as the 5-day rate of change of the raw Kalshi macro probability, not the normalized score, to preserve velocity information.
- **XGBoost fallback:** When `xgb_rank_score` is None, the PC agent falls back to `composite_score` for ranking. Both should never be None simultaneously.
- **`input_state_hash`:** Compute as SHA-256 of the JSON-serialized inputs (QuantSignalBundle + 6 ResearchAgentOutputs + MacroContext) before the decision is made. Enables exact decision replay for backtesting.
