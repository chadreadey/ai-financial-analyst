# Monte Carlo validation — HAC IC t-stats (PR #12) and Lo (2002) Sharpe SE (PR #13)

Date: 2026-08-25
Status: both PRs merged to main after this validation.
Script: session scratchpad `statcheck/validate_stats.py` (simulation design below is reproducible from this doc).

## Why

PRs #12 and #13 add corrected significance statistics to the quant harness. Before
merging we validated them against ground truth: simulated data where the true
signal is known to be zero, so any rejection is a false positive.

## Design

- **IC overlap test:** a 12M forward-return IC sampled monthly has MA(11) serial
  dependence. Simulated as a 12-period moving average of IID N(0,1) shocks —
  zero true IC by construction. 3,000 sims, n = 96 monthly observations
  (8 years). Count how often each t-stat rejects at |t| > 1.96 (nominal 5%).
- **Cross-check:** `newey_west_variance` vs `statsmodels` OLS-on-constant with
  `cov_type="HAC"`, same series, same lag.
- **Sharpe SE:** 5,000 IID daily-return paths (5y each) with known true Sharpe;
  compare the Lo (2002) formula SE against the empirical std-dev of the Sharpe
  estimates, and measure the false-positive rate of the t-stat on zero-mean paths.

## Results

### 1. The naive t-stat in the current harness is badly broken under overlap

| Test (12M horizon / 1M step, zero true IC, nominal 5%) | Rejection rate |
|---|---|
| Naive `t = mean/(std/sqrt(n))` (harness today: `run_audit_ic.py`, `redundancy.py`) | **59.3%** |
| PR #12 HAC t | 18.7% |

A "significant at |t|>2" long-horizon signal from the current harness carries
almost no evidence: under the null it clears that bar ~6 times in 10.

### 2. PR #12's implementation is correct

Median relative difference vs statsmodels' Newey-West variance: **~9e-16**
(machine precision). The Bartlett-kernel HAC estimator is implemented exactly.

### 3. But even correct HAC over-rejects at our sample size — use calibrated critical values

Longer lag windows do not fix it (lag 18: 18.4%, lag 24: 20.6% at n=96) — this
is the known small-sample HAC problem (asymptotic normal critical values with a
heavily-estimated long-run variance). The practical fix is Monte Carlo
calibrated critical values at our exact sample geometry:

| n (monthly obs) | overlap 1 | overlap 3 | overlap 6 | overlap 12 |
|---|---|---|---|---|
| 96 (8y)  | 2.05 | 2.36 | 2.75 | **3.08** |
| 168 (14y, full WRDS window) | 2.02 | 2.29 | 2.57 | **2.87** |

**Rule going forward:** for a 12M-horizon signal on the 2012–2026 monthly
panel, require HAC |t| ≥ ~2.9 for 5% significance — not 1.96. For 3M horizons,
~2.3. Alternative: test significance on non-overlapping samples only, or use a
moving-block bootstrap p-value.

### 4. PR #13's Lo (2002) Sharpe SE matches the empirical sampling distribution

| Quantity (5y daily, true annualized SR = 1.0) | Value |
|---|---|
| Empirical SE of annualized Sharpe (5,000 paths) | 0.4478 |
| PR #13 `compute_sharpe_stats` formula SE | 0.4472 |
| False-positive rate for H0: SR=0 (nominal 5%) | 4.6% |

Correctly sized. Note the practical implication: a 5-year backtest Sharpe has a
standard error of ~0.45 — a measured Sharpe of 1.0 is only ~2.2 SEs from zero,
and differences between strategies of ±0.3 Sharpe are statistical noise at this
sample length.

## Follow-ups

1. Rewire `scripts/run_audit_ic.py` and `quant/redundancy.py` to use
   `quant.ic_stats.ic_summary` on the raw per-rebalance IC series (already
   collected by the harness), with the calibrated thresholds above.
2. Re-judge the signal roster. Expect long-horizon "significant" signals to be
   downgraded.
3. Report `compute_sharpe_stats` (Sharpe ± SE, t-stat) next to every headline
   Sharpe in backtest output.
