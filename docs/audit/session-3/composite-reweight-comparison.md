# Audit Session 3 — Composite Reweight Comparison

**Generated**: 2026-04-28
**Window**: 2015-01-01 → 2024-12-31
**Universe**: 200 tickers (WRDS ∩ price-cache, top-200 alphabetical)
**Walk-forward only** (no CPCV). 16 windows, train=24m, test=6m, monthly rebalance.

## Question being answered

After Session 2's IC findings and the v0/v2/v2-no-insider baseline, three composite-level reweights:

1. **v3-ic-tilted** — heavy weights on IC-measured signals (earnings 0.40, quality 0.25) and minimal weight on unmeasured ones
2. **v3-no-noise** — zero out unmeasured signals (sentiment, regression, ARIMA), redistribute proportionally
3. **v3-fundamental-stack** — most extreme: zero everything except earnings (0.40), quality (0.30), obv (0.20), institutional (0.10)

Plus the bull-year question: **does removing noise signals fix the strategy's defensive tilt?**

## Aggregate metrics (all 6 configs)

| Config | Annual | Sharpe | Sortino | MaxDD | Win % | Trades | Alpha vs SPY |
|---|---:|---:|---:|---:|---:|---:|---:|
| v0 (hand-tuned) | +8.15% | 0.95 | 1.27 | -15.95% | 47.2% | 848 | -155% |
| v2 (IC-derived earnings) | +8.07% | 0.97 | 1.28 | -15.37% | 47.0% | 834 | -156% |
| v2-no-insider | +9.17% | 1.00 | 1.33 | -18.86% | 49.0% | ~810 | -141% |
| **v3-ic-tilted** | **+6.88%** | **0.86** | **1.11** | **-16.88%** | **48.2%** | **812** | **-172%** |
| **v3-no-noise** | **+9.04%** | **1.00** | **1.32** | **-18.92%** | **48.9%** | **801** | **-143%** |
| **v3-fundamental-stack** | **+8.05%** | **1.04** | **1.37** | **-16.66%** | **49.1%** | **806** | **-157%** |

## Year-by-year strategy returns (selected configs)

| Year | v0 | v2-no-insider | v3-ic-tilted | v3-no-noise | v3-fundamental-stack | SPY | Bull/bear |
|---|---:|---:|---:|---:|---:|---:|---|
| 2017 | +28% | +28% | +17% | +36% | +25% | +21% | bull |
| 2018 | +9% | +10% | +12% | +9% | +11% | -5% | **bear** |
| 2019 | +7% | +10% | +4% | +10% | +5% | +31% | bull |
| 2020 | +1% | -5% | -5% | -5% | -7% | +17% | bull |
| 2021 | +11% | +9% | +14% | +9% | +14% | +30% | bull |
| 2022 | -9% | -9% | -10% | -9% | -8% | -19% | **bear** |
| 2023 | -6% | -4% | -1% | -4% | -0% | +27% | bull |
| 2024 | +28% | +31% | +26% | +31% | +27% | +26% | bull |

## Findings

### 1. v3-ic-tilted is WORSE than every other config

Heavy concentration on the 2 highest-IC signals (earnings + quality) produced the lowest Sharpe (0.86), lowest annual return (+6.88%), and worst alpha (-172%) of any config tested. **Ship-don't.**

The loss is structural: concentrating ~65% of weight on 2 signals destroys cross-signal diversification benefits. Measured IC is real but it doesn't compound the way naive intuition suggests when you concentrate.

### 2. v3-no-noise ≈ v2-no-insider — removing more signals doesn't help

Sharpe 1.00, alpha -143% (v3-no-noise) vs Sharpe 1.00, alpha -141% (v2-no-insider). **Identical risk-adjusted performance.** Removing sentiment + regression + ARIMA on top of insider provided NO additional improvement.

The "noise signals are dragging the strategy in bull years" hypothesis is **not supported**. The strategy's bull-year drag is a structural property of the long/short composite architecture, not a consequence of noise pollution from unmeasured signals.

### 3. v3-fundamental-stack has the BEST Sharpe (1.04)

The most extreme config — zeroing everything except earnings, quality, obv, and institutional — produced the highest Sharpe (1.04) and highest Sortino (1.37). Slightly lower absolute return (+8.05% vs +9.17% for v2-no-insider) but materially better risk-adjusted return.

**Risk-adjusted winner.** Trades 1.1pp of annual return for 0.04 Sharpe and 2.2pp tighter drawdown. Cleanest expression of the audit's IC findings.

### 4. The bull-year drag is structural, not signal-driven

Across ALL 6 configs (v0 through v3-fundamental-stack), the strategy massively underperforms in bull years 2019/2020/2021/2023:

| Year | Best config (% vs SPY) | Worst config | SPY | Drag |
|---|---:|---:|---:|---:|
| 2019 | +9.9% (v3-no-noise) | +3.9% (v3-ic-tilted) | +31.1% | -21 to -27pp |
| 2020 | -4.6% (v3-ic-tilted) | -6.9% (v3-fund-stack) | +17.3% | -22 to -24pp |
| 2021 | +14.5% (v3-fund-stack) | +8.7% (v3-no-noise) | +30.5% | -16 to -22pp |
| 2023 | -0.1% (v3-fund-stack) | -6.4% (v0) | +26.7% | -27 to -33pp |

**Across 4 bull years × 6 configs = 24 chances**, the strategy beat SPY in **0 of them**.

The same architecture beats SPY consistently in bear/volatile years (2018, 2022) and is competitive in 2024.

### Bull-year drag root cause (hypothesis based on evidence)

The strategy's defensive tilt is a property of the architecture itself, not the weights:
- **Long/short structure**: top-decile minus bottom-decile portfolio. In a strong bull market, even the bottom-decile names go up; the short side is a negative-carry drag.
- **Position limits** (max_long_positions=10, max_short_positions=10): caps participation in broad rallies.
- **Signal mix is value/quality-tilted**: ERM, SUE, Quality, OBV, Institutional Flow are all classic defensive/value-style signals. None of them have measured momentum/growth IC at short horizons that we can use to rotate into bull-market leaders.
- **Long_threshold=0.20 / short_threshold=-0.40**: asymmetric thresholds favor short signals during sell-offs but don't aggressively reduce shorts in rallies.
- **Regime filter is enabled** but its calibration may not be aggressive enough in trending bulls.

## Recommendations

### What to ship (and what NOT to ship)

| Config | Recommendation |
|---|---|
| v0 | Already production baseline (pre-audit). Replaced by current state. |
| v2 (earnings IC reweight) | **Already shipped** as `EARNINGS_BLEND_WEIGHTS` in `quant/earnings_signals.py`. Keep. |
| v2-no-insider (insider zeroed) | **Already shipped** as `DEFAULT_COMPOSITE_WEIGHTS["insider_score"] = 0` in `quant/cross_sectional.py`. Keep. |
| v3-ic-tilted | **DO NOT SHIP.** Worse than every alternative. Concentration without compensation. |
| v3-no-noise | **Optional ship.** Marginally same as v2-no-insider; removes sentiment/regression/ARIMA which had no measured IC. Safer code surface. Acceptable to ship as a code-cleanup move. |
| v3-fundamental-stack | **Best risk-adjusted candidate.** Sharpe 1.04 is the highest measured. Trade-off: -1.1pp annual return vs v2-no-insider for +0.04 Sharpe and tighter drawdown. Decision is qualitative — defensive enough? |

### Bull-year drag — what would actually move the needle

Composite reweighting cannot fix this. Three approaches in order of expected leverage:

1. **Add a regime overlay** that toggles between "defensive composite" (current architecture) and "long-only momentum" or "long-only quality" in trending bull regimes. Use HY OAS / VIX / 200dma slope as regime indicators.

2. **Add a working momentum signal**. The current `price_momentum_score` has near-zero IC. Either fix it (e.g., 12-1 month relative momentum, sector-relative momentum) or replace with QMJ-as-composite-signal (which had IC +0.042 t=4.57 at 12M — strongest in the entire IC table).

3. **Restructure as long-only or long-biased**. The short side is a negative-carry drag in bull years. Either shrink max_short_positions in favor of cash, or remove shorts entirely and accept lower Sharpe in down years for less bull-year drag.

### Recommended next-session priorities

1. **Lock in v3-fundamental-stack as the candidate next production config** (after a confirming run on the full 495-ticker universe via the new Modal walk-forward infrastructure)
2. **Build a regime overlay** — explicit goal: turn off / shrink the short book when SPY's 200dma slope is positive and VIX is below 18
3. **QMJ-as-composite-signal** infrastructure (extend `SignalVector` and `cross_sectional.py:SIGNAL_FIELDS`)
4. **Investigate insider_mspr wrong-sign root cause** (still open from Session 2)

## Methodology notes

- All 3 v3 runs used identical universe, window, walk-forward parameters
- All used the v2 IC-derived earnings sub-blend (ERM 0.4846 / SUE 0.4654 / Dispersion 0.05) — earnings is held constant; only the composite-level weights vary across v3 configs
- DEFAULT_COMPOSITE_WEIGHTS is mutated in-process per-run and restored — committed file is unchanged
- Insider_score is held at 0.0 across all v3 configs (per the production-state `cross_sectional.py` after commit `bc202e0`)
- Walk-forward only. NO CPCV.
- 200-ticker sample reduction (vs full 495 universe) for runtime control. Full-universe confirmation runs are queued for the Modal walk-forward fan-out (commits on `modal/walkforward-fanout` branch).

## Raw output files

- `docs/audit/session-3/v3-ic-tilted-results.json`
- `docs/audit/session-3/v3-no-noise-results.json`
- `docs/audit/session-3/v3-fundamental-stack-results.json`
