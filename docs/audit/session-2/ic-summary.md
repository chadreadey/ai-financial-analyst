# Audit Session 2 — Per-Signal IC Summary

**Generated**: 2026-04-28 02:44 UTC  
**Window**: 2015-01-01 → 2024-12-31  **Universe**: 495 tickers (WRDS ∩ price-cache)  
**Rebalance dates**: 120  **Walk-forward only** (no CPCV).  **Runtime**: 274.7s

## Universe Coverage
- WRDS PIT cache: 495 tickers
- Local price cache: 516 tickers
- Intersection (used for IC): 495 tickers

Tickers in WRDS but missing from the local price cache are EXCLUDED from the IC universe rather than faked. Per the `project_silent_zeros` discipline, missing data => NaN, never 0.

## Per-Signal Coverage

| Signal | Avg tickers/date | Max | % dates with data |
|---|---:|---:|---:|
| `erm` | 474.5 | 493 | 100.0% |
| `sue` | 473.8 | 491 | 100.0% |
| `analyst_dispersion` | 470.0 | 490 | 100.0% |
| `quality_score` | 480.1 | 495 | 100.0% |
| `price_momentum` | 303.1 | 490 | 100.0% |
| `insider_mspr` | 381.7 | 477 | 100.0% |
| `piotroski` | 472.8 | 492 | 100.0% |
| `qmj` | 475.7 | 493 | 100.0% |
| `hml_bm` | 319.4 | 463 | 100.0% |

## IC at 1M horizon

| Signal | N | Mean IC | Std | t-stat | %pos | LS ann. | LS hit-rate | LS MaxDD | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `qmj` | 120 | +0.0380 | 0.1125 | +3.70 | 66% | +8.4% | 80% | -24.7% | SIGNIFICANT |
| `sue` | 120 | +0.0276 | 0.1083 | +2.79 | 66% | +10.1% | 70% | -25.1% | SIGNIFICANT |
| `quality_score` | 120 | +0.0216 | 0.1130 | +2.09 | 61% | +1.5% | 30% | -37.4% | SIGNIFICANT |
| `erm` | 120 | +0.0196 | 0.1129 | +1.91 | 58% | +5.3% | 60% | -22.1% | marginal |
| `price_momentum` | 120 | +0.0056 | 0.2146 | +0.29 | 57% | +0.3% | 60% | -57.2% | NO_SIGNAL |
| `piotroski` | 120 | +0.0020 | 0.0943 | +0.24 | 50% | -1.9% | 60% | -38.4% | NO_SIGNAL |
| `hml_bm` | 120 | +0.0005 | 0.1514 | +0.04 | 46% | +6.6% | 60% | -33.0% | NO_SIGNAL |
| `analyst_dispersion` | 120 | -0.0071 | 0.1629 | -0.47 | 48% | -6.6% | 30% | -63.1% | NO_SIGNAL |
| `insider_mspr` | 120 | -0.0177 | 0.0938 | -2.06 | 40% | -2.0% | 40% | -45.6% | SIG_WRONG_SIGN |

## IC at 3M horizon

| Signal | N | Mean IC | Std | t-stat | %pos | LS ann. | LS hit-rate | LS MaxDD | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `qmj` | 120 | +0.0367 | 0.1111 | +3.62 | 62% | +6.2% | 80% | -20.7% | SIGNIFICANT |
| `sue` | 120 | +0.0241 | 0.1068 | +2.47 | 66% | +6.6% | 60% | -30.1% | SIGNIFICANT |
| `erm` | 120 | +0.0239 | 0.1037 | +2.52 | 60% | +5.0% | 70% | -22.7% | SIGNIFICANT |
| `quality_score` | 120 | +0.0158 | 0.1296 | +1.33 | 62% | +0.8% | 60% | -41.2% | NO_SIGNAL |
| `hml_bm` | 120 | -0.0012 | 0.1581 | -0.08 | 44% | +4.6% | 50% | -36.3% | NO_SIGNAL |
| `price_momentum` | 120 | -0.0027 | 0.1964 | -0.15 | 53% | +2.3% | 50% | -55.7% | NO_SIGNAL |
| `piotroski` | 120 | -0.0088 | 0.0859 | -1.12 | 47% | -2.9% | 40% | -31.1% | NO_SIGNAL |
| `analyst_dispersion` | 120 | -0.0164 | 0.1512 | -1.19 | 48% | -6.9% | 30% | -63.3% | NO_SIGNAL |
| `insider_mspr` | 120 | -0.0304 | 0.1080 | -3.09 | 37% | -3.4% | 30% | -31.2% | SIG_WRONG_SIGN |

## IC at 6M horizon

| Signal | N | Mean IC | Std | t-stat | %pos | LS ann. | LS hit-rate | LS MaxDD | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `qmj` | 120 | +0.0428 | 0.1265 | +3.71 | 66% | +7.0% | 80% | -16.1% | SIGNIFICANT |
| `erm` | 120 | +0.0353 | 0.1215 | +3.18 | 61% | +4.3% | 60% | -27.8% | SIGNIFICANT |
| `sue` | 120 | +0.0210 | 0.1231 | +1.87 | 62% | +4.5% | 70% | -28.0% | marginal |
| `quality_score` | 120 | +0.0127 | 0.1359 | +1.02 | 60% | +2.0% | 50% | -34.6% | NO_SIGNAL |
| `price_momentum` | 120 | -0.0002 | 0.2028 | -0.01 | 56% | +1.5% | 50% | -37.7% | NO_SIGNAL |
| `hml_bm` | 120 | -0.0066 | 0.1748 | -0.41 | 40% | +4.7% | 60% | -26.6% | NO_SIGNAL |
| `piotroski` | 120 | -0.0118 | 0.0840 | -1.53 | 49% | -4.6% | 40% | -37.1% | marginal |
| `analyst_dispersion` | 120 | -0.0232 | 0.1524 | -1.67 | 45% | -9.3% | 30% | -68.2% | marginal |
| `insider_mspr` | 120 | -0.0299 | 0.1083 | -3.03 | 34% | -2.7% | 50% | -24.9% | SIG_WRONG_SIGN |

## IC at 12M horizon

| Signal | N | Mean IC | Std | t-stat | %pos | LS ann. | LS hit-rate | LS MaxDD | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `qmj` | 120 | +0.0419 | 0.1005 | +4.57 | 67% | +11.7% | 80% | -5.4% | SIGNIFICANT |
| `erm` | 120 | +0.0188 | 0.1288 | +1.60 | 60% | +7.1% | 60% | -36.2% | marginal |
| `sue` | 120 | +0.0167 | 0.1120 | +1.64 | 63% | +4.7% | 60% | -17.2% | marginal |
| `quality_score` | 120 | +0.0090 | 0.1262 | +0.78 | 58% | +2.0% | 50% | -23.4% | NO_SIGNAL |
| `hml_bm` | 120 | +0.0048 | 0.1878 | +0.28 | 49% | +6.3% | 40% | -18.6% | NO_SIGNAL |
| `price_momentum` | 120 | -0.0132 | 0.1890 | -0.76 | 49% | +2.1% | 50% | -58.6% | NO_SIGNAL |
| `piotroski` | 120 | -0.0315 | 0.0729 | -4.73 | 34% | -2.8% | 30% | -33.9% | SIG_WRONG_SIGN |
| `analyst_dispersion` | 120 | -0.0316 | 0.1697 | -2.04 | 44% | -11.5% | 40% | -79.6% | SIG_WRONG_SIGN |
| `insider_mspr` | 120 | -0.0374 | 0.1033 | -3.97 | 31% | -5.8% | 30% | -50.6% | SIG_WRONG_SIGN |

## 3M Decision Summary

**Piotroski floor IC at 3M**: -0.0088

| Signal | 3M Mean IC | Beats Piotroski? |
|---|---:|---|
| `sue` | +0.0241 | **YES** |
| `erm` | +0.0239 | **YES** |
| `quality_score` | +0.0158 | **YES** |
| `price_momentum` | -0.0027 | **YES** |
| `analyst_dispersion` | -0.0164 | no |
| `insider_mspr` | -0.0304 | no |

## Methodology

- **Walk-forward only**, NO CPCV (per user direction).
- Monthly rebalance dates (last trading day of each month).
- IC = Spearman rank correlation between signal and forward return.
- IC is computed at every monthly rebalance (overlap is fine for IC averaging).
- Long-short = top-decile mean minus bottom-decile mean.
- LS sampled on **non-overlapping** windows (every horizon-many months).
- Annualized LS = `(1 + mean_ls) ** (12/horizon_months) - 1` (no overlap-compounding).
- Yearly hit rate = fraction of calendar years with positive mean LS.
- t-stat = `mean_ic / (std_ic / sqrt(N))` over rebalance-period ICs.
- Verdict thresholds: |t|≥2 SIGNIFICANT; |t|≥1.5 marginal; else NO_SIGNAL; N<10 INSUFFICIENT.

## Audit Notes

- `insider_mspr` is INSUFFICIENT: requires Finnhub MSPR cache which is not on disk locally. Code path is wired through `compute_insider_scores` and would activate when the cache lands. Computed coverage above will read 0%.
- The runner uses the **WRDS ∩ price-cache** intersection. To expand coverage to the full 495 WRDS universe, prefetch prices (`scripts/prefetch_*.py`) for the missing tickers. Until then, tickers without price data are EXCLUDED rather than faked.
- Piotroski with <9 valid sub-tests is scaled up linearly to the [0, 9] range. Documented simplification in `quant/factor_baselines.py`.
- QMJ payout pillar is proxied by ROA (we have no dividend data in the WRDS PIT store). Documented simplification.