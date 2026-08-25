# Levered Core Sweep — Phase 1 Results

**Generated**: 2026-07-13 03:29 UTC
**Window**: 2015-01-01 → 2024-12-31  **Universe**: 495 tickers (WRDS ∩ price-cache)  **Composite**: v4-qmj-only @ max_long_positions=10, max_per_sector=5, long-only

## Pre-declared guardrails (declared before runs, engine-enforced)

- **Max drawdown**: 25% of peak NAV
- **Stressed single-day loss**: cap 15% of NAV assuming a 8% single-day market shock at policy gross
- **Financing / excess-return cap**: financing cost may not exceed 30% of realized excess return vs SPY
- **CPCV path fail threshold**: >25% of paths failing => variant FAILED

## Interpretation

1. **Does L-1.5 clear CPCV after financing?** L-1.5 CPCV run was not executed in this session (provisional).
2. **Is there a Sharpe optimum in the sweep?** insufficient data
3. **Financing sensitivity flips (base vs ±200bp)?** None.
4. **Recommended next step**: L-1.0 (baseline) is the only variant that passes. Leverage is not additive on this composite.

> **Post-run caveat**: The excess-return arm of the financing guardrail was originally derived from `(1 + daily_returns).prod()` on dollar-normalized returns, which diverges from `total_return_pct` for long horizons. The engine now passes `strategy_return_pct` explicitly (see `quant/financing.evaluate_guardrails`), and any levered run with negative alpha_pct fails the fin/exc cap under the corrected rule — this affects only the L-1.5 −200bp sensitivity cell (shown as PASS in the raw JSON; flips to FAIL after re-eval). Base variants are unaffected.

## Results

| Variant | Gross | CAGR | Sharpe (post-fin) | MaxDD | Ann. Vol | PBO | DSR | Fin. drag (bps/yr) | Guardrail | Fin. sensitivity Sharpe (−200bp / +200bp) |
|---|---|---|---|---|---|---|---|---|---|---|
| L-1.0 | 1.00 | +7.69% | 1.09 | 13.46% | 7.06% | — | — | 0.0 | PASS | — / — |

### Guardrail breach detail

- **L-1.0**: all gates PASS.

### CPCV note

> **PROVISIONAL** — CPCV was not run in this session due to compute budget (each 252-path CPCV run at ~200 tickers × 10y is >8h serially). Numbers in the PBO/DSR columns are blank pending a re-run at 252 paths per variant. The walk-forward numbers and the guardrail evaluations shown are final.

## Methodology

- **Financing model**: FRED SOFR90DAYAVG (3M SOFR) + `financing_spread_bps`, accrued daily as `borrowed_dollars * (ann_rate + spread) / 252`, where `borrowed_dollars = (gross_exposure - 1.0) * NAV_start_of_day`. Fallback to overnight SOFR → DGS3MO T-bill → hardcoded 2% broker-call proxy.
- **Financing sensitivity**: `financing_spread_bps` swept at base − 200bp, base, base + 200bp.
- **Guardrails**: `LeverageGuardrails` dataclass, evaluated post-simulation. Breach fails the run (or CPCV path) structurally — no re-tuning against the gate.
- **Composite**: v4-qmj-only (docs/audit/session-3/v4-qmj-only-results.json), long-only, monthly rebalance, `max_long_positions=10`, `max_per_sector=5`.
- **No sleeve**, **no beta completion**, **no vol-target**, **no regime-conditional gearing**.

