# Audit Session 2 — Cross-Signal Correlation Matrix

**Generated**: 2026-04-28 00:55 UTC  
**Window**: 2015-01-01 → 2024-12-31  **Universe**: 495 tickers (WRDS ∩ price-cache)  
**Rebalance dates**: 120  **Method**: pairwise Spearman rank correlation, time-averaged.  **Runtime**: 223.2s

**Effective dimensionality**: 7.85 (of 9 nominal signals)

## Exclusions

- `insider_mspr` — 0% coverage (Finnhub MSPR cache not on disk).
- `institutional_flow` — Excluded for honesty — partial cache only.

## Per-Signal Coverage (rebalances with ≥1 non-NaN value)

| Signal | % of rebalance dates with data |
|---|---:|
| `erm` | 100.0% |
| `sue` | 100.0% |
| `analyst_dispersion` | 100.0% |
| `quality_score` | 100.0% |
| `price_momentum` | 100.0% |
| `piotroski` | 100.0% |
| `qmj` | 100.0% |
| `hml_bm` | 100.0% |
| `obv_trend` | 100.0% |

## Mean Spearman Rank Correlation (time-averaged)

|      | `erm` | `sue` | `analyst_di` | `quality_sc` | `price_mome` | `piotroski` | `qmj` | `hml_bm` | `obv_trend` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **`erm`** | +1.00 | +0.27 | +0.05 | +0.13 | +0.34 | +0.18 | +0.23 | -0.12 | +0.05 |
| **`sue`** | +0.27 | +1.00 | +0.12 | +0.25 | +0.26 | +0.44 | +0.54* | -0.12 | +0.04 |
| **`analyst_dispersion`** | +0.05 | +0.12 | +1.00 | +0.20 | +0.06 | +0.09 | +0.07 | -0.25 | +0.03 |
| **`quality_score`** | +0.13 | +0.25 | +0.20 | +1.00 | +0.11 | +0.12 | +0.31 | -0.29 | +0.02 |
| **`price_momentum`** | +0.34 | +0.26 | +0.06 | +0.11 | +1.00 | +0.16 | +0.22 | -0.19 | +0.02 |
| **`piotroski`** | +0.18 | +0.44 | +0.09 | +0.12 | +0.16 | +1.00 | +0.28 | -0.05 | +0.03 |
| **`qmj`** | +0.23 | +0.54* | +0.07 | +0.31 | +0.22 | +0.28 | +1.00 | -0.10 | +0.03 |
| **`hml_bm`** | -0.12 | -0.12 | -0.25 | -0.29 | -0.19 | -0.05 | -0.10 | +1.00 | -0.03 |
| **`obv_trend`** | +0.05 | +0.04 | +0.03 | +0.02 | +0.02 | +0.03 | +0.03 | -0.03 | +1.00 |

`*` = |ρ| > 0.50 (redundancy candidate)

## Std-Dev of Correlation Across Dates

|      | `erm` | `sue` | `analyst_di` | `quality_sc` | `price_mome` | `piotroski` | `qmj` | `hml_bm` | `obv_trend` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **`erm`** | 0.00 | 0.09 | 0.15 | 0.07 | 0.09 | 0.08 | 0.10 | 0.08 | 0.10 |
| **`sue`** | 0.09 | 0.00 | 0.11 | 0.08 | 0.10 | 0.07 | 0.20 | 0.09 | 0.09 |
| **`analyst_dispersion`** | 0.15 | 0.11 | 0.00 | 0.06 | 0.20 | 0.08 | 0.13 | 0.07 | 0.13 |
| **`quality_score`** | 0.07 | 0.08 | 0.06 | 0.00 | 0.13 | 0.08 | 0.10 | 0.06 | 0.11 |
| **`price_momentum`** | 0.09 | 0.10 | 0.20 | 0.13 | 0.00 | 0.10 | 0.12 | 0.19 | 0.19 |
| **`piotroski`** | 0.08 | 0.07 | 0.08 | 0.08 | 0.10 | 0.00 | 0.14 | 0.07 | 0.08 |
| **`qmj`** | 0.10 | 0.20 | 0.13 | 0.10 | 0.12 | 0.14 | 0.00 | 0.10 | 0.10 |
| **`hml_bm`** | 0.08 | 0.09 | 0.07 | 0.06 | 0.19 | 0.07 | 0.10 | 0.00 | 0.14 |
| **`obv_trend`** | 0.10 | 0.09 | 0.13 | 0.11 | 0.19 | 0.08 | 0.10 | 0.14 | 0.00 |

## Top 5 Highest |corr| Pairs

| Rank | Pair | mean ρ | std ρ | std / |mean| |
|---:|---|---:|---:|---:|
| 1 | `sue` ↔ `qmj` | +0.535 | 0.198 | 0.37 |
| 2 | `sue` ↔ `piotroski` | +0.435 | 0.070 | 0.16 |
| 3 | `erm` ↔ `price_momentum` | +0.338 | 0.087 | 0.26 |
| 4 | `quality_score` ↔ `qmj` | +0.310 | 0.097 | 0.31 |
| 5 | `quality_score` ↔ `hml_bm` | -0.292 | 0.065 | 0.22 |

## Redundancy Candidates (|mean ρ| > 0.5)

| Pair | mean ρ | std ρ | Suggested treatment |
|---|---:|---:|---|
| `sue` ↔ `qmj` | +0.535 | 0.198 | (a) Keep both, IC-weight the composite — overlap is real but not crippling. |

## Top 5 Most Unstable Pairs (divergence-as-signal candidates)

Pairs whose correlation has high variability across dates relative to its average. Stable redundancy (low std) means the same thing is being measured twice; unstable redundancy (high std) means the RELATIONSHIP itself moves through time and the divergence between the two signals could be a separate alpha source.

| Rank | Pair | mean ρ | std ρ | std / |mean| |
|---:|---|---:|---:|---:|
| 1 | `analyst_dispersion` ↔ `price_momentum` | +0.062 | 0.199 | 3.23 |
| 2 | `erm` ↔ `analyst_dispersion` | +0.053 | 0.154 | 2.92 |
| 3 | `analyst_dispersion` ↔ `qmj` | +0.067 | 0.131 | 1.97 |
| 4 | `quality_score` ↔ `price_momentum` | +0.110 | 0.126 | 1.15 |
| 5 | `price_momentum` ↔ `hml_bm` | -0.187 | 0.187 | 1.00 |

**Filter**: only pairs with |mean ρ| ≥ 0.05 are included (otherwise ratio is dominated by floating-point noise on near-zero correlations).

## Targeted Pair Discussion

| Pair | mean ρ | std ρ | Comment |
|---|---:|---:|---|
| `qmj` ↔ `quality_score` | +0.310 | 0.097 | Both quality factors. QMJ profitability pillar uses gross-profit/assets; quality_score uses gross margin + ROIC. Likely to overlap meaningfully. Moderate overlap. |
| `erm` ↔ `sue` | +0.267 | 0.090 | Both earnings-based but different mechanisms (consensus revisions vs actual quarterly surprise). Should be moderately correlated, not redundant. Mildly related. |
| `piotroski` ↔ `qmj` | +0.285 | 0.141 | Both fundamental quality formulations. Piotroski is a 9-binary score across profitability/leverage/efficiency; QMJ is z-scored across four pillars. Cross-sectionally these often disagree. Mildly related. |
| `price_momentum` ↔ `erm` | +0.338 | 0.087 | Price momentum vs earnings revisions — testing whether revisions front-run price (or vice versa). Moderate overlap. |
| `price_momentum` ↔ `qmj` | +0.216 | 0.116 | Momentum vs quality — should be near-zero (orthogonal academic factors). Mildly related. |
| `price_momentum` ↔ `obv_trend` | +0.017 | 0.188 | Both technical, but OBV adds volume. Should be modestly correlated. ~Orthogonal. |
| `hml_bm` ↔ `qmj` | -0.100 | 0.096 | Value (HML) vs quality (QMJ) — academic factor stack should show small or negative correlation. Mildly related. |

## Methodology

- **Walk-forward only**, NO CPCV.
- Monthly rebalance dates (last trading day of each month), matching `scripts/run_audit_ic.py`.
- At each date, every signal is scored cross-sectionally with missing values propagated as **NaN** (never silently zeroed — see `project_silent_zeros` memory rule).
- Pairwise Spearman rank correlation per date (pandas `.corr(method='spearman')` is NaN-aware: pairs with NaN on either side are dropped).
- Mean and std are taken across the rebalance dates.
- Effective dimensionality = `exp(-Σ pᵢ log pᵢ)` where `p` is the normalized eigenvalue spectrum of the mean-correlation matrix. A value near `nominal_signals` ⇒ orthogonal stack; a value much smaller ⇒ multiple signals collapse onto a single principal axis.
