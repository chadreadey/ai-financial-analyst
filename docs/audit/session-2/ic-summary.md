# Audit Session 2 — Per-Signal IC Summary

**Generated**: 2026-04-27 20:25 UTC  
**Window**: 2015-01-01 → 2024-12-31  **Universe**: 194 tickers (WRDS ∩ price-cache)  
**Rebalance dates**: 120  **Walk-forward only** (no CPCV).  **Runtime**: 80.8s

## Universe Coverage
- WRDS PIT cache: 495 tickers
- Local price cache: 215 tickers
- Intersection (used for IC): 194 tickers

Tickers in WRDS but missing from the local price cache are EXCLUDED from the IC universe rather than faked. Per the `project_silent_zeros` discipline, missing data => NaN, never 0.

## Per-Signal Coverage

| Signal | Avg tickers/date | Max | % dates with data |
|---|---:|---:|---:|
| `erm` | 193.2 | 194 | 100.0% |
| `sue` | 192.7 | 194 | 100.0% |
| `analyst_dispersion` | 192.6 | 194 | 100.0% |
| `quality_score` | 193.6 | 194 | 100.0% |
| `price_momentum` | 159.9 | 194 | 100.0% |
| `insider_mspr` | 0.0 | 0 | 0.0% |
| `piotroski` | 193.2 | 194 | 100.0% |
| `qmj` | 193.4 | 194 | 100.0% |
| `hml_bm` | 160.0 | 184 | 100.0% |

## IC at 1M horizon

| Signal | N | Mean IC | Std | t-stat | %pos | LS ann. | LS hit-rate | LS MaxDD | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `qmj` | 120 | +0.0382 | 0.1342 | +3.12 | 62% | +7.1% | 80% | -31.9% | SIGNIFICANT |
| `erm` | 120 | +0.0277 | 0.1309 | +2.32 | 58% | +6.7% | 60% | -39.7% | SIGNIFICANT |
| `quality_score` | 120 | +0.0270 | 0.1396 | +2.12 | 58% | +3.2% | 60% | -47.6% | SIGNIFICANT |
| `sue` | 120 | +0.0218 | 0.1324 | +1.80 | 60% | +7.3% | 80% | -29.4% | marginal |
| `price_momentum` | 120 | +0.0053 | 0.2382 | +0.25 | 52% | +2.9% | 70% | -49.9% | NO_SIGNAL |
| `hml_bm` | 120 | +0.0003 | 0.1729 | +0.02 | 46% | +8.1% | 70% | -32.7% | NO_SIGNAL |
| `piotroski` | 120 | -0.0004 | 0.1119 | -0.04 | 47% | +1.3% | 70% | -22.6% | NO_SIGNAL |
| `analyst_dispersion` | 120 | -0.0032 | 0.1971 | -0.18 | 48% | -7.1% | 50% | -66.0% | NO_SIGNAL |
| `insider_mspr` | 0 | n/a | n/a | +0.00 | 0% | n/a | n/a | n/a | INSUFFICIENT |

## IC at 3M horizon

| Signal | N | Mean IC | Std | t-stat | %pos | LS ann. | LS hit-rate | LS MaxDD | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `qmj` | 120 | +0.0420 | 0.1394 | +3.30 | 63% | +6.2% | 80% | -32.0% | SIGNIFICANT |
| `erm` | 120 | +0.0325 | 0.1080 | +3.30 | 61% | +2.5% | 80% | -30.9% | SIGNIFICANT |
| `quality_score` | 120 | +0.0291 | 0.1586 | +2.01 | 62% | +1.8% | 60% | -46.4% | SIGNIFICANT |
| `sue` | 120 | +0.0170 | 0.1381 | +1.35 | 59% | +5.0% | 80% | -36.0% | NO_SIGNAL |
| `price_momentum` | 120 | +0.0060 | 0.2240 | +0.29 | 55% | +4.8% | 60% | -51.8% | NO_SIGNAL |
| `hml_bm` | 120 | -0.0019 | 0.1718 | -0.12 | 47% | +6.7% | 60% | -36.7% | NO_SIGNAL |
| `piotroski` | 120 | -0.0102 | 0.1115 | -1.00 | 50% | +0.8% | 60% | -24.9% | NO_SIGNAL |
| `analyst_dispersion` | 120 | -0.0134 | 0.1769 | -0.83 | 48% | -6.5% | 40% | -65.3% | NO_SIGNAL |
| `insider_mspr` | 0 | n/a | n/a | +0.00 | 0% | n/a | n/a | n/a | INSUFFICIENT |

## IC at 6M horizon

| Signal | N | Mean IC | Std | t-stat | %pos | LS ann. | LS hit-rate | LS MaxDD | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `erm` | 120 | +0.0518 | 0.1375 | +4.13 | 63% | +6.0% | 80% | -26.4% | SIGNIFICANT |
| `qmj` | 120 | +0.0471 | 0.1554 | +3.32 | 64% | +7.2% | 70% | -23.9% | SIGNIFICANT |
| `quality_score` | 120 | +0.0311 | 0.1603 | +2.12 | 66% | +0.2% | 60% | -45.9% | SIGNIFICANT |
| `sue` | 120 | +0.0185 | 0.1498 | +1.35 | 60% | +6.3% | 60% | -31.2% | NO_SIGNAL |
| `price_momentum` | 120 | +0.0170 | 0.2331 | +0.80 | 60% | +2.7% | 60% | -40.1% | NO_SIGNAL |
| `hml_bm` | 120 | -0.0049 | 0.1807 | -0.30 | 43% | +6.8% | 70% | -29.9% | NO_SIGNAL |
| `piotroski` | 120 | -0.0151 | 0.0985 | -1.68 | 50% | +0.0% | 50% | -23.8% | marginal |
| `analyst_dispersion` | 120 | -0.0245 | 0.1708 | -1.57 | 50% | -9.3% | 30% | -68.9% | marginal |
| `insider_mspr` | 0 | n/a | n/a | +0.00 | 0% | n/a | n/a | n/a | INSUFFICIENT |

## IC at 12M horizon

| Signal | N | Mean IC | Std | t-stat | %pos | LS ann. | LS hit-rate | LS MaxDD | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `qmj` | 120 | +0.0492 | 0.1350 | +3.99 | 59% | +11.9% | 90% | -9.5% | SIGNIFICANT |
| `erm` | 120 | +0.0344 | 0.1392 | +2.71 | 64% | +4.5% | 70% | -46.6% | SIGNIFICANT |
| `quality_score` | 120 | +0.0293 | 0.1425 | +2.25 | 68% | -0.5% | 70% | -62.0% | SIGNIFICANT |
| `sue` | 120 | +0.0120 | 0.1347 | +0.98 | 62% | +3.8% | 60% | -24.6% | NO_SIGNAL |
| `hml_bm` | 120 | +0.0084 | 0.1841 | +0.50 | 52% | +6.6% | 60% | -15.1% | NO_SIGNAL |
| `price_momentum` | 120 | -0.0043 | 0.2144 | -0.22 | 52% | -1.3% | 60% | -73.4% | NO_SIGNAL |
| `piotroski` | 120 | -0.0337 | 0.0986 | -3.75 | 35% | -0.4% | 40% | -28.3% | SIG_WRONG_SIGN |
| `analyst_dispersion` | 120 | -0.0375 | 0.1893 | -2.17 | 46% | -12.4% | 20% | -78.3% | SIG_WRONG_SIGN |
| `insider_mspr` | 0 | n/a | n/a | +0.00 | 0% | n/a | n/a | n/a | INSUFFICIENT |

## 3M Decision Summary

**Piotroski floor IC at 3M**: -0.0102

| Signal | 3M Mean IC | Beats Piotroski? |
|---|---:|---|
| `erm` | +0.0325 | **YES** |
| `quality_score` | +0.0291 | **YES** |
| `sue` | +0.0170 | **YES** |
| `price_momentum` | +0.0060 | **YES** |
| `analyst_dispersion` | -0.0134 | no |

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