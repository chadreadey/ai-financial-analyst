# Improvements from TradingAgents Architecture Review

**Created:** 2026-04-07
**Source:** https://github.com/TauricResearch/TradingAgents (Tauric Research, arXiv:2412.20138)
**Context:** Comparative analysis of TradingAgents vs our 6-agent platform. Three actionable improvements identified, ranked by value/effort.

---

## Improvement 1: Adversarial Bull/Bear Debate (HIGH VALUE, LOW EFFORT)

### What TradingAgents Does
Two separate LLM agents (bullish researcher, bearish researcher) debate analyst findings over N rounds, then a facilitator agent selects the prevailing perspective. This forces structured consideration of both sides before any trade decision.

### Why It Matters
LLMs have documented acquiescence bias — they confirm whatever hypothesis the prompt implies. If your synthesis agent sees 4/6 agents saying "buy," it will say "buy" without rigorously stress-testing the bear case. An adversarial structure counteracts this.

### Our Lightweight Version
We don't need 3 separate LLM calls (bull + bear + facilitator). Add structured adversarial reasoning to the **synthesis agent prompt**:

**File:** `prompts/synthesis.md` (or equivalent synthesis prompt template)

**Add this section before the final recommendation:**
```
## Adversarial Analysis (REQUIRED before issuing recommendation)

### BULL CASE
State the 3 strongest arguments FOR this position. Use specific data points from the analyst reports above. Include:
- The single most compelling quantitative evidence
- The scenario where this trade produces maximum return
- What the market is currently underpricing

### BEAR CASE
State the 3 strongest arguments AGAINST this position. Be genuinely adversarial — don't soften the bear case. Include:
- The single biggest risk that could wipe out the thesis
- What would make you wrong and how likely is it
- What the market knows that the bull case is ignoring

### CONVICTION ASSESSMENT
Which case is stronger and why? Rate conviction: HIGH (>80% confident in direction), MEDIUM (60-80%), LOW (<60%).
If LOW: recommend HOLD regardless of composite score.
If MEDIUM: reduce position size by 50%.
```

**Implementation:** ~30 minutes. Edit one prompt file. No new agents, no architectural changes. The synthesis agent already has all analyst reports in context — it just needs to be forced to argue against itself before deciding.

**Expected Impact:** Reduces false-positive buy signals from LLM acquiescence. The conviction gating (LOW → HOLD, MEDIUM → half-size) adds a natural risk layer without a separate risk module.

---

## Improvement 2: Multi-Perspective Risk Sizing (MODERATE VALUE, LOW EFFORT)

### What TradingAgents Does
3 separate risk agents (aggressive, neutral, conservative) each evaluate every trade proposal independently. This produces a spectrum of acceptable position sizes rather than a binary go/no-go.

### Why It Matters
Our current regime filter is binary: VIX < 28 → risk-on, VIX ≥ 28 → risk-off (with gradations at 20). This misses nuance. The tariff correction (Window 7, -8.9%) happened with VIX below 28 — the binary filter didn't trigger.

### Our Lightweight Version
Don't create 3 new agents. Add multi-perspective sizing to the **existing regime filter logic** in `quant/backtest.py`:

**File:** `quant/backtest.py` — in the regime determination function

**Concept:** Instead of discrete regime buckets, compute a continuous risk scalar from multiple inputs:

```python
def compute_risk_scalar(spy_data: pd.DataFrame, vix: float) -> float:
    """
    Multi-perspective risk sizing: blend aggressive, neutral, and conservative views.
    Returns scalar 0.0 (fully risk-off) to 1.0 (fully risk-on).
    """
    # Conservative view: VIX + trend
    conservative = 1.0 - min(1.0, max(0.0, (vix - 15) / 25))  # 0 at VIX=40, 1 at VIX=15
    
    # Neutral view: 200d SMA position
    sma200 = float(spy_data['close'].tail(200).mean())
    price = float(spy_data['close'].iloc[-1])
    neutral = min(1.0, max(0.0, (price / sma200 - 0.90) / 0.15))  # 0 at 10% below, 1 at 5% above
    
    # Aggressive view: short-term momentum + vol compression
    ret_20d = float(spy_data['close'].iloc[-1] / spy_data['close'].iloc[-20] - 1)
    aggressive = min(1.0, max(0.3, 0.5 + ret_20d * 5))  # biased toward staying in
    
    # Blend: equal weight
    return (conservative + neutral + aggressive) / 3
```

**Implementation:** ~2 hours. Replace the discrete regime buckets with this continuous scalar. No LLM calls needed — this is pure quant.

**Expected Impact:** Smoother position sizing. Would have reduced Window 7 losses (tariff correction) because the neutral/conservative views would have started scaling down before VIX hit 28.

---

## Improvement 3: Agent Disagreement as Signal (MODERATE VALUE, MODERATE EFFORT)

### What Neither Platform Does
When agents disagree sharply (fundamental says strong buy, technical says sell), both platforms average it out. But disagreement itself is informative — it often signals transitions, uncertainty, or mispricing.

### What to Build
Track the **dispersion** across agent scores, not just the mean:

**File:** `quant/signals.py` — add to `SignalVector`

```python
def compute_disagreement_score(self) -> float:
    """Standard deviation of directional signal scores. High = agents disagree."""
    scores = [
        self.sma_trend.score,
        self.mean_reversion_z.score,
        self.bollinger_pctb.score,
        self.rsi.score,
        self.obv_trend.score,
    ]
    return float(np.std(scores))
```

**How to use it:**
- High disagreement + positive composite → potential breakout (momentum building against resistance). Consider increasing size.
- High disagreement + negative composite → potential value trap. Consider reducing size or waiting.
- Low disagreement → consensus. Standard sizing.

**Implementation:** ~4 hours. Add the metric, add it to backtest logging, run walk-forward to see if it has predictive value for forward Sharpe.

---

## What NOT to Adopt from TradingAgents

| Feature | Why Skip |
|---------|----------|
| LangGraph framework | We already have a working async agent architecture. Migration adds no value. |
| Daily LLM inference for every decision | Cost-prohibitive ($1,900+/year for 10 stocks). Our quant signals are deterministic and free. |
| yfinance as sole data source | We have Alpaca, FMP, Finnhub, SEC Edgar, Tavily, FRED, and WRDS incoming. Far richer. |
| Their "technical analyst" agent | An LLM describing RSI in prose. Our RSI is computed deterministically with exact math. Strictly worse. |
| 3-month backtesting window | Insufficient for any statistical claim. We do 5+ years with 8 walk-forward windows. |
| No transaction cost modeling | Not production-viable. We're moving to IS decomposition. |
