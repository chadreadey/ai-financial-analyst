# Signal Stack Stress Test — Implementation Plan

**Created:** 2026-04-07
**Goal:** Maximize Sharpe with Alpha >5% over S&P 500, quant signals only
**Approach:** Validate and fix the quant baseline FIRST, before layering in AI equity research agents. The agents get their own fine-tuning pass against a proven quant foundation.

---

## Current State Assessment

### What You Have
- **6 technical signals** in `quant/signals.py`: SMA trend (25%), mean reversion z-score (20%), Bollinger %B (20%), RSI (15%), OBV trend (20%), plus ATR regime (non-directional)
- **52-week high** signal implemented but disabled (weight=0.0) — pending validation
- **Gold standard result:** Sharpe 1.35, Sortino 2.02, 43.7% total return (10% annualized), 12.94% max DD
- **Walk-forward validated:** 8 windows, 2020-2026, 10-stock universe
- **Existing infrastructure:** CPCV in `quant/cpcv.py`, walk-forward engine, regime filter (VIX + SMA cross), sentiment overlay (disabled in gold standard)
- **10 bps flat transaction cost** — not IS-decomposed

### Critical Problems Identified

**Problem 1: Signal Redundancy (BLOCKER)**
4 of 5 active signals are transformations of the same close-price series:
- SMA: (P/SMA(L) - 1) — distance from moving average
- Mean Reversion: -(P - SMA(60))/σ — z-scored distance from moving average
- Bollinger %B: (P - Lower)/(Upper - Lower) — normalized distance from moving average bands
- RSI: function of recent gains/losses — smoothed recent return direction

These are NOT independent signals. They cluster into two families:
- **Trend family:** SMA, Bollinger (breakout mode)
- **Reversal family:** Mean reversion, RSI (oversold mode), Bollinger (mean-reversion mode)

OBV is the only signal using a second data modality (volume). Your "5-signal ensemble" is likely a ~2-signal ensemble with inflated confidence.

**Impact:** The composite score's diversification is illusory. The equal-weight scheme gives 80% weight to close-price-derived signals and 20% to volume. When signals agree, it feels like confirmation — it's actually redundancy.

**Problem 2: Mean Reversion vs. Monthly Rebalance (CONTRADICTION)**
Your mean reversion signal uses a 60-day window and produces z-scores that capture short-horizon (1-5 day) reversals. But you rebalance monthly. Academic evidence for mean reversion is strongest at 1-5 day horizons and weakest at monthly. You're using a daily-resolution indicator with a monthly-resolution execution — the signal has largely decayed by the time you act on it.

The stress test report confirmed this: "monthly implementation will alias short-horizon dependence." Your mean reversion signal scored highest in backtests likely because it's ALSO acting as a crude contrarian/value signal at monthly frequency — but that's a different and weaker effect than what it was designed to capture.

**Problem 3: No Factor Attribution (UNKNOWN ALPHA SOURCE)**
The gold standard Sharpe of 1.35 has not been decomposed against Fama-French factors. Without this, you don't know whether:
- The SMA signal is a momentum factor proxy (likely — trend-following ≈ time-series momentum)
- The mean reversion signal is a short-term reversal factor proxy (likely)
- The alpha is genuine stock-picking or just factor timing via the regime filter

If your Sharpe drops below 0.5 after factor adjustment, the "alpha" is just smart-beta you could replicate with ETFs.

**Problem 4: 10-Stock Universe (STATISTICAL POWER)**
The gold standard runs on 10 stocks. Cross-sectional tests (rank correlation, Fama-MacBeth) need N≥30 ideally N≥100 to have statistical power. With 10 stocks, your cross-sectional regressions have 10 observations per period — nearly worthless for inference. You need to validate signals on your larger universes (20-stock and 50-stock) even if you trade the 10-stock universe.

**Problem 5: Flat Cost Model (UNREALISTIC FOR HIGH-TURNOVER SIGNALS)**
10 bps flat round-trip doesn't account for market impact, which scales nonlinearly with trade size and is especially punishing for mean reversion (60-200% turnover). A proper IS decomposition might kill the mean reversion signal entirely.

---

## Implementation Sequence

### Phase 0: Quick-Kill Tests (THIS WEEK)

These tests determine whether the current signal stack has enough raw material for Alpha >5%. Each can kill the thesis — run them in order.

#### 0.1 Signal Rank Correlation Matrix
**File:** New function in `quant/signals.py` or new file `quant/redundancy.py`
**What to build:**
```python
def compute_signal_correlation_matrix(universe: list[str], dates: list[str]) -> pd.DataFrame:
    """
    At each rebalance date, compute all 5 signal scores cross-sectionally.
    Return time-averaged pairwise Spearman rho matrix.
    """
```
- Run on your 10-stock universe across all walk-forward dates
- Also run on a larger universe (20 or 50 stocks) for statistical power
- Output: 5x5 heatmap of average Spearman ρ
- **Kill threshold:** If SMA-Bollinger ρ > 0.5 AND SMA-MeanReversion |ρ| > 0.5, confirm the redundancy diagnosis

#### 0.2 Incremental IC (Fama-MacBeth)
**File:** New function in `quant/redundancy.py`
**What to build:**
```python
def fama_macbeth_incremental_ic(
    signal_scores: pd.DataFrame,  # columns = signals, rows = stock-dates
    forward_returns: pd.Series,
    periods: list[str]
) -> dict:
    """
    Cross-sectional regression of next-month returns on all signals.
    Returns time-averaged slopes and HAC t-stats per signal.
    """
```
- Each month: regress next-month returns on [SMA, MR, BB, RSI, OBV] scores simultaneously
- Average slopes across months
- Newey-West t-stats (4 lags for monthly)
- **Kill threshold:** If any signal has conditional t < 2, it adds nothing. If 3+ signals have t < 2, the ensemble is fundamentally broken.

#### 0.3 Factor Attribution
**File:** New script `quant/factor_attribution.py`
**What to build:**
```python
def factor_regression(
    strategy_returns: pd.Series,
    factor_data: pd.DataFrame  # FF5 + UMD
) -> dict:
    """
    Regress strategy excess returns on Fama-French 5 + Momentum.
    Returns alpha, factor loadings, R², t-stats.
    """
```
- Pull FF5 + momentum factor data from Ken French's data library (free download)
- Regress your gold standard OOS returns on the 6 factors
- **Kill threshold:** If alpha t-stat < 2 after factor adjustment, stop. You don't have alpha — you have factor exposure.

#### Phase 0 Decision Gate
After running 0.1-0.3, you'll know:
- How many independent signals you actually have
- Whether the alpha survives factor adjustment
- Which signals to keep, drop, or replace

**If the thesis survives:** proceed to Phase 1
**If it doesn't:** skip to Phase 2 (Signal Replacement) immediately

---

### Phase 1: Fix the Signal Weights and Redundancy (1-2 WEEKS)

Only proceed here if Phase 0 shows at least 2 independent signal dimensions with factor-adjusted alpha.

#### 1.1 Orthogonalize the Signal Stack
For each signal, regress on all others and keep residuals. The residual IS the unique information.

```python
# Pseudocode
for signal in [SMA, MR, BB, RSI, OBV]:
    residual = signal - regression_on(other_4_signals)
    residual_IC = spearman(residual, forward_returns)
    if residual_IC t-stat < 2:
        DROP signal
```

Likely outcome: you keep SMA (or BB, not both), OBV, and maybe RSI divergence. Mean reversion gets dropped or replaced.

#### 1.2 Re-weight Based on Residual IC
Replace the hardcoded weights in `SignalVector.WEIGHTS` with weights proportional to residual IC (with shrinkage toward equal weight):

```python
# In signals.py
WEIGHTS = {
    "sma_trend": residual_ic_weight_sma,     # probably increases to 0.30-0.35
    "mean_reversion_z": 0.0,                  # probably dropped
    "bollinger_pctb": residual_ic_weight_bb,  # probably 0.0 if redundant with SMA
    "rsi": residual_ic_weight_rsi,            # probably 0.10-0.15 (divergence only)
    "obv_trend": residual_ic_weight_obv,      # probably increases to 0.25-0.30
    "high_52w": residual_ic_weight_52w,       # ENABLE THIS — test it
}
```

#### 1.3 Enable and Validate 52-Week High
George & Hwang (2004) showed 52-week high proximity generates ~2x momentum returns with less crash exposure. It's already implemented in your code but disabled. This is likely your highest-value addition that requires zero new development:
- It's INDEPENDENT of the other close-price signals (it's a level, not a change)
- It has strong academic support and survives factor adjustment
- It's low-turnover (stocks near their 52-week high tend to stay there)

Test it with the same Phase 0 diagnostics. If incremental IC is significant, enable it.

#### 1.4 Validate on Larger Universe
Run the trimmed signal set on 50 stocks minimum. The 10-stock universe is too small for cross-sectional inference. Even if you trade 10 stocks, validate the signals on 50+.

---

### Phase 2: Signal Replacement (2-3 WEEKS)

Replace dropped signals with sources that are genuinely independent.

#### 2.1 Replace Mean Reversion with 12-1 Month Momentum
The academic evidence for 12-month momentum (skip the most recent month) is far stronger than mean reversion at monthly frequency. It's:
- Well-documented (Jegadeesh & Titman 1993, hundreds of replications)
- Independent of your SMA signal (SMA is short-term trend, 12-1 is intermediate-term momentum)
- Low turnover at monthly rebalance
- Works cross-sectionally in your framework

Implementation:
```python
def compute_momentum_12_1(close: pd.Series) -> SignalResult:
    """12-month cumulative return, skipping the most recent month."""
    if len(close) < 252:
        return SignalResult(0.0, "insufficient data")
    ret_12m = close.iloc[-21] / close.iloc[-252] - 1  # skip last month
    # Cross-sectional z-score happens at ensemble level
    score = float(np.clip(ret_12m / 0.30, -1.0, 1.0))  # normalize
    return SignalResult(score, f"12-1mo momentum: {ret_12m:.1%}")
```

#### 2.2 Add a Fundamental Quality Signal (Quant-Only Version)
You already have `quant/fundamentals.py` and FMP data. Build a simple composite:
- ROE z-score
- Debt/Equity z-score (inverted)
- Earnings growth z-score

This is INDEPENDENT of all price-based signals and adds a genuinely new data dimension. Your backtests already show fundamental weights of 5-20% improve results (`dow25_fund_w0.10.json`).

#### 2.3 Implement IS Cost Model
Replace the flat 10 bps with the power-law impact model:
```python
def implementation_shortfall(
    trade_value: float,
    adv: float,
    volatility: float,
    commission_per_share: float = 0.001,
    half_spread_bps: float = 5.0
) -> float:
    """Total cost in bps including nonlinear market impact."""
    participation = trade_value / adv
    impact = 100 * (participation ** 0.5) * (volatility / 0.20)  # simplified
    spread = half_spread_bps
    commission = commission_per_share * 10000 / (trade_value / shares)  # bps equiv
    return spread + impact + commission
```

Run the backtest at [0, 5, 10, 15, 20, 30, 50] bps to find break-even.

---

### Phase 3: Statistical Hardening (1-2 WEEKS)

#### 3.1 Deflated Sharpe Ratio
Count your total trials (conservatively 100-500 depending on grid search history). Compute DSR on the best walk-forward result. If DSR < 0.5, the strategy doesn't survive multiple-testing correction.

#### 3.2 CPCV / PBO
You already have `quant/cpcv.py`. Run it on the final signal set (not the original 5). PBO > 40% = high overfitting risk.

#### 3.3 Regime Filter Sensitivity
Vary VIX thresholds ±5 around current values (20, 28). If Sharpe changes by more than 0.3, the filter is fragile. Test probabilistic scaling:
```python
# Instead of binary risk-off at VIX >= 28:
regime_scalar = 1.0 - min(1.0, max(0.0, (vix - 18) / 20))
# Smooth ramp from 100% at VIX=18 to 0% at VIX=38
```

---

### Phase 4: Benchmark Validation (1 WEEK)

Before declaring the quant baseline ready for AI overlay:

1. **Run final walk-forward** on the trimmed, re-weighted signal set
2. **Compare to gold standard:** Sharpe should be ≥1.0 (may be lower than 1.35 if you've removed redundant pseudo-diversification, but that's honest)
3. **Factor-adjusted alpha must be positive** with t > 2
4. **DSR must be > 0.5**
5. **PBO must be < 0.40**
6. **Cost break-even must be > 15 bps**

If all gates pass: **this is your validated quant baseline.** It's the foundation the AI equity research agents will be fine-tuned against.

---

## Revised Signal Architecture (Target)

| Signal | Weight | Source | Independence |
|---|---|---|---|
| **SMA Trend** | 25-30% | Close price | Trend family (keep 1) |
| **12-1 Month Momentum** | 20-25% | Close price (different horizon) | Momentum family (NEW) |
| **OBV Trend** | 20-25% | Volume + close | Volume family (only member) |
| **52-Week High** | 15-20% | Close price (level, not change) | Anchor family (ENABLE) |
| **Fundamental Quality** | 10-15% | FMP fundamentals | Fundamental family (NEW) |
| **RSI Divergence** | 5-10% | Close price (conditional) | Keep only if incremental IC significant |

**Dropped:** Mean reversion (subsumed by SMA + wrong frequency), Bollinger %B (redundant with SMA)

**Key change:** From 5 signals in 2 families → 5-6 signals in 4-5 families. Genuine diversification instead of redundancy.

---

## File Checklist

| File | Action | Phase |
|---|---|---|
| `quant/redundancy.py` | CREATE — correlation matrix, Fama-MacBeth, orthogonalization | 0 |
| `quant/factor_attribution.py` | CREATE — FF5+Mom regression, per-signal decomposition | 0 |
| `quant/signals.py` | MODIFY — re-weight, enable 52w high, add momentum signal | 1-2 |
| `quant/fundamentals.py` | MODIFY — add cross-sectional quality composite | 2 |
| `quant/backtest.py` | MODIFY — IS cost model, larger universe support | 2-3 |
| `quant/cpcv.py` | USE — run on final signal set | 3 |
| `backtests/GOLD_STANDARD.md` | UPDATE — after Phase 4 validation | 4 |

---

## What This Does NOT Cover (Intentionally)

- **AI equity research agent integration** — saved for after the quant baseline is validated
- **Sentiment overlay (Finnhub/VADER)** — treat as a separate signal layer, not part of quant baseline
- **LSTM/TimesFM ML signals** — same; validate quant first
- **GraphRAG knowledge graph** — infrastructure for the agents, not the quant stack

The AI agents are your game-changer. But a game-changer needs a game to change. The quant baseline IS that game — get it right first, then the agents have a high-quality foundation to improve upon rather than papering over quant signal problems.
