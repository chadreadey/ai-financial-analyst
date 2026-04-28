# Audit Session 2 — Walk-Forward Comparison

**Generated**: 2026-04-28 06:36 UTC
**Window**: 2015-01-01 → 2024-12-31  **Universe**: 200 tickers (WRDS ∩ price-cache, top-200 alphabetical (sample reduction))  **Rebalance**: monthly  (walk-forward train=24m / test=6m)  **Walk-forward only** (no CPCV).

## Question

Does the IC-derived earnings reweight (v2) produce better aggregate strategy alpha than the prior hand-tuned weights (v0)?

## Earnings sub-blend configs under test

| Config | ERM | SUE | Dispersion | Source |
|---|---:|---:|---:|---|
| v0 (hand-tuned) | 0.4000 | 0.3500 | 0.2500 | Pre-audit defaults |
| v2 (IC-derived) | 0.4846 | 0.4654 | 0.0500 | Audit ic-summary.md (495-universe, 1M/3M/6M IC means + 50% shrinkage + 0.95/0.05 dispersion floor) |

## Aggregate metrics

| Metric | v0 (hand-tuned) | v2 (IC-weighted) | Δ (v2 − v0) |
|---|---:|---:|---:|
| Total return % | +84.55 | +83.57 | -0.98 |
| Annualized return % | +8.15 | +8.07 | -0.08 |
| Sharpe ratio | +0.950 | +0.970 | +0.02 |
| Sortino ratio | +1.270 | +1.280 | +0.01 |
| Max drawdown % | +15.95 | +15.37 | -0.58 |
| Win rate % | +47.20 | +47.00 | -0.20 |
| Total trades | 848 | 834 | -14.00 |
| Avg holding days | 22.7 | 22.8 | +0.10 |
| Benchmark return % | +239.88 | +239.88 | +0.00 |
| Alpha vs benchmark % | -155.33 | -156.31 | -0.98 |

| Year-by-year hit rate (vs SPY) | 50.0% | 50.0% | +0.0pp |

### Bonus: v2 with insider_mspr zeroed in DEFAULT_COMPOSITE_WEIGHTS

| Metric | v2 (IC-weighted) | v2-no-insider | Δ (no-insider − v2) |
|---|---:|---:|---:|
| Total return % | +83.57 | +98.68 | +15.11 |
| Annualized return % | +8.07 | +9.17 | +1.10 |
| Sharpe ratio | +0.970 | +1.000 | +0.03 |
| Sortino ratio | +1.280 | +1.330 | +0.05 |
| Max drawdown % | +15.37 | +18.86 | +3.49 |
| Win rate % | +47.00 | +49.00 | +2.00 |
| Alpha vs benchmark % | -156.31 | -141.20 | +15.11 |

## Year-by-year strategy returns

| Year | v0 | v2 | v2-no-insider | SPY |
|---|---|---|---|---|
| 2017 | +28.23% | +24.49% | +36.22% | +20.78% |
| 2018 | +8.69% | +6.10% | +10.46% | -5.24% |
| 2019 | +7.07% | +6.20% | +9.90% | +31.09% |
| 2020 | +0.81% | -0.61% | -5.02% | +17.28% |
| 2021 | +10.68% | +12.28% | +8.72% | +30.52% |
| 2022 | -8.63% | -9.18% | -9.01% | -18.64% |
| 2023 | -6.39% | -1.74% | -3.67% | +26.72% |
| 2024 | +27.88% | +28.39% | +30.54% | +25.59% |

## Interpretation

- **v2 vs v0**: Sharpe Δ +0.020, Alpha Δ -0.98pp, MaxDD Δ -0.58pp. **v2 does NOT strictly beat v0**.
- **v2 vs SPY**: Alpha -156.31%. Negative alpha — strategy underperforms buy-and-hold.
- **v0 vs SPY**: Alpha -155.33%. Negative alpha — strategy underperforms buy-and-hold.
- **Economic significance**: Δ Sharpe and Δ Alpha both small. The IC-level signal advantage is largely **invisible at the composite level** — consistent with the fact that earnings is a 30%-weight overlay on a 10-signal composite and the dispersion contribution that v0 contained was already weak (NO_SIGNAL at 1M, marginal at 6M).
- **Bonus (v2-no-insider)**: Sharpe Δ +0.030, Alpha Δ +15.11pp vs v2. Removing insider_mspr **helps**.

## Methodology notes

- **Walk-forward only** via `run_walk_forward()`. `run_cpcv()` is never called.
- Universe: WRDS PIT cache ∩ local price cache (matches `scripts/run_audit_ic.py:get_audit_universe`).
- Earnings sub-blend weights are passed via new `BacktestConfig.earnings_*_weight` fields, threaded through to `compute_earnings_signal_scores()` at the run_walk_forward call site (quant/backtest.py). The committed `EARNINGS_BLEND_WEIGHTS` constant is unchanged.
- Bonus run zeroes `insider_score` in `DEFAULT_COMPOSITE_WEIGHTS` (in-process mutation, restored after the run) and redistributes its 10% proportionally to the other non-zero composite weights.

