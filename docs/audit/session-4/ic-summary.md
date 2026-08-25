# Audit Session 2 — Per-Signal IC Summary

**Generated**: 2026-07-14 23:43 UTC  
**Window**: 2015-01-01 → 2024-12-31  **Universe**: 495 tickers (WRDS ∩ price-cache)  
**Rebalance dates**: 120  **Walk-forward only** (no CPCV).  **Runtime**: 328.9s

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
| `price_momentum` | 459.1 | 488 | 98.3% |
| `insider_mspr` | 384.3 | 477 | 100.0% |
| `obv_trend` | 470.8 | 491 | 100.0% |
| `institutional_flow` | 83.2 | 87 | 100.0% |
| `piotroski` | 472.8 | 492 | 100.0% |
| `qmj` | 475.7 | 493 | 100.0% |
| `hml_bm` | 445.3 | 462 | 100.0% |

## IC at 1M horizon

| Signal | N | Mean IC | Std | t-stat | %pos | LS ann. | LS hit-rate | LS MaxDD | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `qmj` | 120 | +0.0245 | 0.0956 | +2.81 | 62% | +4.7% | 80% | -25.4% | KEEP |
| `quality_score` | 120 | +0.0191 | 0.1069 | +1.96 | 61% | +0.5% | 40% | -36.8% | MARGINAL |
| `sue` | 120 | +0.0179 | 0.0962 | +2.04 | 61% | +3.9% | 70% | -25.7% | KEEP |
| `erm` | 120 | +0.0144 | 0.1082 | +1.45 | 59% | +5.2% | 60% | -20.0% | MARGINAL |
| `price_momentum` | 118 | +0.0033 | 0.2074 | +0.17 | 54% | +0.9% | 60% | -57.6% | DROP |
| `institutional_flow` | 120 | +0.0010 | 0.1718 | +0.06 | 45% | +3.2% | 60% | -67.3% | DROP |
| `piotroski` | 120 | +0.0003 | 0.0797 | +0.04 | 50% | -1.9% | 40% | -31.3% | DROP |
| `analyst_dispersion` | 120 | -0.0017 | 0.1454 | -0.13 | 49% | -5.9% | 30% | -62.5% | DROP |
| `hml_bm` | 120 | -0.0059 | 0.1421 | -0.46 | 45% | +6.7% | 60% | -20.9% | DROP |
| `obv_trend` | 120 | -0.0081 | 0.1356 | -0.66 | 45% | +0.7% | 40% | -25.8% | DROP |
| `insider_mspr` | 120 | -0.0085 | 0.0837 | -1.11 | 49% | +0.8% | 60% | -22.1% | MARGINAL_WRONG_SIGN |

## IC at 3M horizon

| Signal | N | Mean IC | Std | t-stat | %pos | LS ann. | LS hit-rate | LS MaxDD | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `erm` | 120 | +0.0209 | 0.1008 | +2.27 | 59% | +5.0% | 60% | -18.5% | KEEP |
| `qmj` | 120 | +0.0203 | 0.1050 | +2.12 | 62% | +4.5% | 80% | -20.9% | KEEP |
| `quality_score` | 120 | +0.0194 | 0.1247 | +1.70 | 61% | +0.0% | 40% | -42.3% | MARGINAL |
| `sue` | 120 | +0.0133 | 0.1001 | +1.45 | 62% | +2.9% | 60% | -30.9% | MARGINAL |
| `institutional_flow` | 120 | +0.0016 | 0.1712 | +0.10 | 54% | +8.1% | 60% | -34.8% | DROP |
| `price_momentum` | 118 | -0.0001 | 0.1819 | -0.01 | 52% | +4.7% | 60% | -45.1% | DROP |
| `analyst_dispersion` | 120 | -0.0088 | 0.1374 | -0.70 | 49% | -5.6% | 30% | -61.8% | DROP |
| `obv_trend` | 120 | -0.0096 | 0.1241 | -0.85 | 43% | -4.8% | 50% | -54.5% | DROP |
| `hml_bm` | 120 | -0.0107 | 0.1501 | -0.78 | 38% | +3.9% | 40% | -36.2% | DROP |
| `piotroski` | 120 | -0.0133 | 0.0799 | -1.83 | 44% | -2.3% | 40% | -29.2% | MARGINAL_WRONG_SIGN |
| `insider_mspr` | 120 | -0.0150 | 0.0868 | -1.89 | 40% | -2.8% | 20% | -26.6% | MARGINAL_WRONG_SIGN |

## IC at 6M horizon

| Signal | N | Mean IC | Std | t-stat | %pos | LS ann. | LS hit-rate | LS MaxDD | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `erm` | 120 | +0.0263 | 0.1139 | +2.53 | 57% | +4.2% | 60% | -21.6% | KEEP |
| `qmj` | 120 | +0.0183 | 0.1115 | +1.80 | 61% | +4.8% | 80% | -19.4% | MARGINAL |
| `quality_score` | 120 | +0.0130 | 0.1270 | +1.12 | 62% | +0.5% | 40% | -36.1% | MARGINAL |
| `institutional_flow` | 120 | +0.0095 | 0.1556 | +0.67 | 49% | +4.6% | 60% | -25.4% | DROP |
| `sue` | 120 | +0.0069 | 0.1132 | +0.67 | 58% | +3.4% | 80% | -26.6% | DROP |
| `obv_trend` | 120 | +0.0032 | 0.1222 | +0.28 | 53% | +0.6% | 60% | -24.8% | DROP |
| `price_momentum` | 118 | +0.0023 | 0.1894 | +0.13 | 54% | +3.6% | 70% | -35.6% | DROP |
| `hml_bm` | 120 | -0.0147 | 0.1595 | -1.01 | 38% | +4.0% | 50% | -34.2% | MARGINAL_WRONG_SIGN |
| `insider_mspr` | 120 | -0.0166 | 0.0954 | -1.91 | 38% | -2.1% | 50% | -21.8% | MARGINAL_WRONG_SIGN |
| `analyst_dispersion` | 120 | -0.0181 | 0.1435 | -1.38 | 48% | -6.8% | 40% | -60.9% | MARGINAL_WRONG_SIGN |
| `piotroski` | 120 | -0.0215 | 0.0824 | -2.85 | 42% | -2.8% | 40% | -27.5% | KEEP_WRONG_SIGN |

## IC at 12M horizon

| Signal | N | Mean IC | Std | t-stat | %pos | LS ann. | LS hit-rate | LS MaxDD | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `qmj` | 120 | +0.0188 | 0.0795 | +2.60 | 61% | +8.3% | 60% | -6.1% | KEEP |
| `quality_score` | 120 | +0.0168 | 0.1222 | +1.51 | 63% | -0.8% | 40% | -22.2% | MARGINAL |
| `erm` | 120 | +0.0118 | 0.1158 | +1.11 | 61% | +8.0% | 70% | -30.8% | MARGINAL |
| `sue` | 120 | +0.0050 | 0.0974 | +0.56 | 58% | +2.7% | 60% | -20.3% | DROP |
| `obv_trend` | 120 | -0.0010 | 0.1117 | -0.10 | 51% | +3.1% | 70% | -35.0% | DROP |
| `institutional_flow` | 120 | -0.0051 | 0.1631 | -0.34 | 52% | -5.9% | 20% | -55.2% | DROP |
| `hml_bm` | 120 | -0.0093 | 0.1635 | -0.62 | 48% | +5.8% | 60% | -23.8% | DROP |
| `price_momentum` | 118 | -0.0115 | 0.1772 | -0.70 | 51% | +2.3% | 67% | -52.5% | DROP |
| `analyst_dispersion` | 120 | -0.0170 | 0.1568 | -1.19 | 48% | -11.7% | 40% | -80.3% | MARGINAL_WRONG_SIGN |
| `insider_mspr` | 120 | -0.0279 | 0.1030 | -2.97 | 35% | -3.0% | 20% | -25.6% | KEEP_WRONG_SIGN |
| `piotroski` | 120 | -0.0336 | 0.0697 | -5.28 | 36% | -2.7% | 30% | -27.8% | KEEP_WRONG_SIGN |

## 3M Decision Summary

**Piotroski floor IC at 3M**: -0.0133

| Signal | 3M Mean IC | Beats Piotroski? |
|---|---:|---|
| `erm` | +0.0209 | **YES** |
| `quality_score` | +0.0194 | **YES** |
| `sue` | +0.0133 | **YES** |
| `institutional_flow` | +0.0016 | **YES** |
| `price_momentum` | -0.0001 | **YES** |
| `analyst_dispersion` | -0.0088 | **YES** |
| `obv_trend` | -0.0096 | **YES** |
| `insider_mspr` | -0.0150 | no |

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