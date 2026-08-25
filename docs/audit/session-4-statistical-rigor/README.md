# Statistical-Rigor Audit — Session 4

**Date:** 2026-07-04
**Scope:** Quantitative quality, data-science rigor, the data→AI interface, AI
reasoning/interpretation, position sizing, self-tracking, failure attribution,
and a stochastic assumption-logging system.
**Prior sessions:** 1–3 audited fundamentals/pricing and signal IC. This session
is orthogonal: it audits the *statistics and stochastics*, not the software.

This document is the narrative findings report. Two companion deliverables ship
in the same PR:

1. **`quant/assumption_audit.py`** — a runtime "assumption logger" that lets any
   statistical routine declare the assumption it relies on and have it checked
   *against the information available at that moment* (PASS / VIOLATED /
   SKIPPED-for-lack-of-information). This is the "logging system to check
   assumptions made against information whenever available" that the audit asked
   for on the stochastic front.
2. **`scripts/run_statistical_rigor_audit.py`** + **`assumption_report.md`** /
   **`assumption_log.jsonl`** — the batch side, which runs those checks over the
   system's *own* evidence artifacts and produces a reproducible ledger.

---

## Executive summary (TL;DR)

The system is unusually self-aware for a solo quant stack: it has CPCV, purge/
embargo, an IC harness, Newey-West in one place, and an honest habit of writing
down what it disproved. But the **statistical inferences that the whole edifice
rests on are systematically over-confident**, and the failure mode is always the
same: *a number is produced under an assumption that is never checked.* The five
load-bearing problems:

1. **Overlapping-return t-stats are inflated and drive the signal roster.**
   IC and long-horizon significance are computed on monthly-sampled 3M/6M/12M
   forward returns as if the observations were independent. The batch auditor
   re-derived the deflation: **of the signals the IC tables flag as significant
   at 3M–12M, essentially none survive an overlap correction** (e.g. `qmj@6M`
   t=3.71 → ~1.52; `piotroski@12M` t=−4.73 → ~1.36; `insider_mspr@6M` t=−3.03 →
   ~1.24). See `redundancy.py:503-539`, `scripts/run_audit_ic.py`, and the
   machine report.

2. **Production signal weights were chosen by the outcome they were tested on.**
   `DEFAULT_COMPOSITE_WEIGHTS` (`cross_sectional.py:133-146`) and the earnings
   blend were selected because "zeroing them in walk-forward improved aggregate
   Sharpe" across a dozen configs — with **no multiple-testing correction and no
   held-out final split**. `institutional_flow` keeps a 10% weight while its own
   comment says "no measured IC … retained — believed to work," directly
   contradicting the stated "we don't use signals we can't validate" principle.

3. **The AI's "systematic" verdict is a hand-scored LLM sum wearing a
   deterministic mask.** The "deterministic verdict override"
   (`orchestrator.py:877-907`) only thresholds a scalar `weighted_score` that the
   *LLM itself* produced; the code never recomputes it from parsed agent scores,
   never checks the weights sum to 1, and the report-trimming
   (`context_budget.py:12-13`) frequently deletes the very `SIGNAL_SCORE` lines
   synthesis is told to trust. Half the agents (Risk, Macro, Pattern) emit no
   mechanical score at all.

4. **Position sizing has no statistical basis.** Live/paper orders use a fixed
   `paper_default_qty` (`backend/paper_scheduler.py:78`, `orchestrator.py:293`).
   Conviction only gates go/no-go; it does not scale size. There is no
   volatility targeting, no Kelly, no risk parity — so realized portfolio risk
   is an uncontrolled function of whatever names pass the threshold.

5. **The feedback loop cannot tell whether the system is calibrated.**
   `history_outcomes.py` marks an outcome by comparing *the current quote* to a
   target/stop at query time — path-dependent and point-in-time-unaware — and
   nothing compares realized outcomes to the pre-trade `prior_bull_probability`,
   conviction, or predicted rank. There is no Brier score, no reliability curve,
   no max-adverse-excursion. The system "tracks itself" descriptively but cannot
   answer "am I well-calibrated?" or "which agent is actually right?"

None of this means the strategy has no edge. It means **the reported evidence
for the edge is weaker than the numbers suggest**, and the system currently has
no instrument that flags when a statistic is being trusted beyond what its
assumptions support. The assumption logger is that instrument.

Severity tally (detailed findings below): **Critical 6 · High 18 · Medium 17 ·
Low 9**.

---

## Method

- Read the statistical primitives directly: `quant/metrics.py`, `quant/cpcv.py`,
  `quant/cross_sectional.py`, `quant/scoring.py`, `quant/redundancy.py`,
  `backend/history_outcomes.py`, `backend/paper_scheduler.py`.
- Three deep read-only passes over the larger subsystems (backtest engine,
  agents/orchestrator/enrichment, signals/ML/factor) with instructions to cite
  `file:line` and classify severity.
- Built the assumption logger and ran it against the real IC / walk-forward /
  composite artifacts in `docs/audit/` to convert qualitative concerns into
  reproducible, quantified findings.

Everything here is code-level and reproducible. Line numbers reference the state
of `main` at audit time; treat them as anchors, not exact addresses.

---

## A. Performance statistics (`quant/metrics.py`, `quant/cpcv.py`)

### A1 — [HIGH] Sharpe/IC t-stats assume IID; returns are not
`compute_sharpe` (`metrics.py:17-32`) annualises with `√252` and CPCV/IC t-stats
use `mean / (std/√n)`. Both assume serially-independent observations. Equity
returns exhibit volatility clustering and momentum, and the IC series is sampled
from overlapping windows (§C4). No autocorrelation adjustment (Lo 2002 for
Sharpe; Newey-West/HAC for IC) is applied anywhere in the core path.
**Effect:** Sharpe standard errors too small; t-stats too large; significance
overstated. **Fix:** Lo's autocorrelation-adjusted Sharpe SE; HAC t-stats for
IC; or sample non-overlapping. The assumption logger's
`iid_no_autocorrelation` now flags this at the call site.

### A2 — [MEDIUM] Sortino uses the wrong downside deviation
`compute_sortino` (`metrics.py:47-53`) computes `downside.std()` — the standard
deviation *of the negative returns only*, which subtracts the mean of the
negatives. The textbook downside deviation is `√(mean(min(r−MAR,0)²))` over the
**whole** sample against a minimum acceptable return. The current formula both
uses the wrong denominator population and drops the target-return concept.
**Effect:** Sortino is not comparable to any external Sortino and is biased
(usually upward). **Fix:** use the target-semideviation definition with MAR=0
(or the risk-free rate).

### A3 — [MEDIUM] No risk-free rate in Sharpe/Sortino
`metrics.py:17-53` uses raw mean return, not excess-over-Rf. In a 4–5% Rf
environment this materially overstates Sharpe. **Fix:** subtract a Rf series (the
system already pulls FRED DGS yields).

### A4 — [MEDIUM] "Alpha" is an arithmetic return spread, not alpha
`compute_alpha` (`metrics.py:91-93`) returns `strategy − benchmark`. It ignores
beta and factor exposure, so a high-beta book in a bull market shows large
negative "alpha" (see the −140pp figures in session-3 artifacts) that says
nothing about skill. **Fix:** Jensen's alpha from a CAPM/FF regression (the
FF5+Mom machinery in `factor_attribution.py` already exists — wire it in).

### A5 — [CRITICAL] PBO is not the Lopez de Prado statistic
`compute_pbo` (`cpcv.py:196-235`) has two branches: an "is_optimal" heuristic
("fraction of the top-half-IS combos whose OOS Sharpe ≤ 0") and, when IS Sharpes
are unavailable, "fraction of all OOS paths with Sharpe ≤ 0." Neither is the CSCV
PBO, which is the expected rank-logit of the IS-best configuration across
combinatorial splits **over a set of competing configurations**. With a single
configuration evaluated across CPCV paths, PBO in the LdP sense is undefined —
the paths are resamples of one strategy, not independent trials. The reported
"PBO 0%" therefore does not mean what a reader assumes. **Fix:** either implement
CSCV over the actual configuration set, or rename the metric to
"fraction of non-positive OOS paths" and stop describing it as PBO.

### A6 — [HIGH] Deflated Sharpe uses the wrong `n_obs` and a mismatched observed value
`CPCVResult.compute_summary_stats` (`cpcv.py:362-373`) calls
`compute_deflated_sharpe(observed=median_oos_sharpe, n_trials=n_combinations,
n_obs=max(len(oos_sharpes),10), …)`. Three problems:
  - `n_obs` should be the number of **return observations** in the track record,
    not the number of CV paths (often thousands). Since SE ∝ `1/√(n_obs−1)`,
    feeding thousands inflates DSR toward "significant."
  - `n_trials = n_combinations` treats CPCV paths as independent strategy trials.
    They are not; this inflates `E[max SR]` and pulls DSR the other way. The two
    errors interact unpredictably.
  - Deflating the **median** OOS Sharpe by `E[max SR]` compares a central value
    against an extreme-value benchmark — an apples-to-oranges subtraction.
**Fix:** DSR on the *selected* (max) Sharpe, `n_obs` = actual return count,
`n_trials` = number of distinct configs tried across all sessions.

### A7 — [LOW] `_expected_max_sharpe` drops its own correction terms
`cpcv.py:238-249` documents the Bailey–LdP `E[max]` with Euler–Mascheroni terms
but implements only `std·√(2 ln N)`, which overstates `E[max]` for small N.
Minor, but it biases DSR conservative in the small-N regime.

### A8 — [LOW] Metrics round to 2 decimals inside the primitive
`metrics.py:32,53,…` round Sharpe/Sortino to 2dp at the source, discarding
precision that DSR and downstream comparisons need. Round only at display.

---

## B. Validation methodology (`quant/backtest.py`, `backend/*`, `scripts/*`)

### B1 — [CRITICAL] Single-run backtests with IC calibration are in-sample
In `run_backtest` (`backtest.py:~2102-2131`) weights are calibrated from the IC
of the first `ic_trailing_periods` rebalances (which use **forward** returns) and
then applied to *all* periods, including the ones used to fit them. That is label
leakage; the headline single-run Sharpe is not out-of-sample. Walk-forward/CPCV
paths are better but see B2. **Fix:** calibrate strictly on data preceding each
trade; never trade a period whose labels informed the weights.

### B2 — [HIGH] Walk-forward train→test boundary has no purge/embargo
CPCV purges (`cpcv.py:103-193`), but the walk-forward split
(`backtest.py:~2807-2893`) sets `test_start == train_end` while calibrating on
21-day-forward IC labels. The last train labels reach ~21 days into the test
window → the test window leaks into the weights it is evaluated with. **Fix:**
embargo `forward_days + execution_delay` at every train/test seam.

### B3 — [HIGH] Purge/embargo width is calendar-fixed, not label-aligned
`apply_purge_embargo` uses `DateOffset(months=purge_months)` (default 1) rather
than tying the purge to the label horizon (`forward_days + execution_delay`).
One calendar month is a coincidental match for a 21-day label and is wrong for
any other horizon. **Fix:** derive purge/embargo from the horizon.

### B4 — [HIGH] Extensive config sweeps with no multiple-testing control
`scripts/run_audit_walkforward.py` defines many `COMPOSITE_WEIGHT_CONFIGS`
(v0/v2/v3/v4…), session-3 stores ~12 result files, and the production defaults
(`max_short_positions`, `enable_qmj_signal`, the weight vector) were flipped to
the winners. No Bonferroni/FDR, no locked final holdout. The batch auditor
quantifies the tax: for the 36-test IC sweep, the Bonferroni α is ~0.0014 and the
expected best-of-N `|t|` under the null is ~2.68 — so a lone `t≈2` is *not*
evidence. **Fix:** pre-register the config set, correct for it, and reserve an
untouched final period.

### B5 — [CRITICAL] Data-source paths that leak the future
Two provider paths inject non-point-in-time data into historical windows:
  - **FMP fundamentals** ignore `as_of_date` (`fundamentals.py:223-234`); with the
    default `fundamental_provider="fmp"`, historical rebalances see current/
    restated statements.
  - **Kalshi** signals use *live* prediction-market prices for all past windows
    (`kalshi_client.py:41-52`, `backtest.py:3423-3440`); `_date_override` only
    changes the cache filename. The code comments admit this.
**Effect:** look-ahead when those flags are enabled. **Fix:** gate both behind an
explicit "PIT unavailable — do not use in backtest" guard, or only run them with
a pre-built per-date cache.

### B6 — [HIGH] Survivorship bias in the universe
`sp500*` universes are built from *today's* constituents
(`universe_provider.py:218-260`); audit universes are `WRDS ∩ local price cache`
(`run_audit_ic.py:452-456`), which silently drops delisted/data-less names. No
delisting returns. **Effect:** results are conditional on survival — upward
biased. **Fix:** point-in-time membership + delisting returns, or state the bias
prominently on every artifact.

### B7 — [HIGH] Sharpe on trade-level / stale-capital returns
The legacy `BacktestEngine` computes Sharpe on overlapping *trade* returns with
`min_observations=2` and mis-scales annualisation (`backtest_engine.py:253-259`);
the quant engine divides daily PnL by *initial* capital, not current equity
(`backtest.py:~2561`), biasing Sharpe as equity drifts. **Fix:** daily portfolio
returns on marked-to-market equity; drop the trade-level Sharpe.

### B8 — [HIGH] CPCV combinations accept 2 observations
`compute_sharpe_from_returns` passes `min_observations=2` (`cpcv.py:304-313`), so
a combination can "complete" on a handful of daily PnL points and still feed the
OOS-Sharpe distribution, median, PBO and DSR. **Fix:** require a horizon-based
minimum (e.g. ≥ 24 monthly or ≥ 60 daily obs) per combination.

### B9 — [MEDIUM] Costs are a flat 10bps; no slippage, impact, or intraday fills
`transaction_cost_bps=10` round-trip regardless of ADV/spread
(`backtest.py:66-67`); stops evaluated on daily close only
(`backtest.py:1886-1906`); ETF hedge legs fill same-day while equities honor
`execution_delay` (`backtest.py:2488-2499`). **Effect:** optimistic and
inconsistent execution assumptions. **Fix:** ADV-scaled cost model, next-open
fills, consistent delay for all legs.

### B10 — [MEDIUM] `config_hash` misses module-level weight mutations
Audit harnesses mutate `cross_sectional.DEFAULT_COMPOSITE_WEIGHTS` in-process
(`run_audit_walkforward.py:~514`), but those weights are not in `BacktestConfig`,
so `config_hash()` cannot distinguish v3/v4 experiments. Reproducibility and the
`n_trials` count DSR needs are both compromised.

---

## C. Signal construction & data science (`quant/*signals*.py`, `quant/xgb_*`)

### C1 — [HIGH] Silent zeros pervade signal construction (violates the project's own rule)
`factor_baselines.py:40-41` explicitly rejects silent zeros, yet earnings/flow/
Kalshi/quality signals return `0.0` on missing data
(`earnings_signals.py:106,205,274`; `institutional_flow.py:48`;
`kalshi_signal.py:66`), and the composite treats a stored 0 as a genuine neutral
(`cross_sectional.py:192-196,243-253` skip only when *all* values are 0). A
missing signal and a truly-neutral signal are then indistinguishable, and the
composite is biased toward 0 with a weight still consumed in the denominator.
**Effect:** silent dilution + inability to audit coverage. **Fix:** propagate NaN,
renormalize weights over present signals only. The logger's `no_silent_zeros`
detects the smell (zero-fraction over threshold).

### C2 — [HIGH] Small-sample z-scores treated as reliable
SUE standardizes on ≤4 seasonal diffs (`earnings_signals.py:220-235`); sector
momentum z-scores across ~11 ETFs (`sector_momentum.py:78-96`); price-momentum
cross-sections as small as 5 names (`additional_signals.py:134-156`);
institutional flow QoQ on ≥3 holders (`institutional_flow.py:29`). Sample std on
n∈[2,11] is dominated by noise and (with `ddof=0`) biased low. **Fix:** minimum-N
gates that emit NaN, shrinkage/robust scale (MAD), and `min_sample` logging.

### C3 — [HIGH] Time-series models fit without stationarity checks
ARIMA(1,1,1) on 60 log-prices with only a vol gate — no ADF/KPSS, no order
selection, no residual diagnostics, and the training window *excludes* the last
`horizon` days so the forecast origin lags the rebalance
(`arima_signal.py:49-71`). The "regression signal" gates on R² and calls it
"statistically significant" with no slope p-value and no HAC on autocorrelated
log-price residuals (`regression_signal.py:33-49`). LSTM shuffles overlapping
60-day windows into the same batch (`lstm/model.py:201`). **Fix:** ADF/KPSS before
fitting on levels; slope significance + HAC for the trend signal; purged,
un-shuffled sequence splits for the LSTM. The logger's `stationarity` check
covers the first.

### C4 — [HIGH] IC is computed on overlapping windows and pooled across time
`redundancy.compute_signal_ic_table` and the audit runner compute Spearman IC at
each monthly rebalance against 3M/6M/12M forward returns and then take
`mean/SE√n` (`redundancy.py:503-506`), and `xgb_ranker` pools all validation rows
across dates before one Spearman (`xgb_ranker.py:122`). Overlapping labels make
consecutive ICs strongly autocorrelated; the t-stat is inflated by roughly
`√(horizon/step)`. **This is the single most consequential statistical error in
the stack** because the signal roster and weights are chosen from these t-stats.
The batch auditor quantifies it per signal (see `assumption_report.md`). **Fix:**
Newey-West on the IC series, or non-overlapping sampling, before any "significant"
verdict.

### C5 — [CRITICAL] XGBoost train/serve skew and label overlap
`xgb_features.py:54-57,175-187` hard-codes `sentiment`, `price_regression`,
`arima_forecast` to 0.0 in the offline feature matrix while live inference
populates them — the model learns garbage weights for three columns and the
serving distribution differs from training. Training rows near the split carry
21-day forward labels that reach into the validation window with no embargo
(`xgb_features.py:151-163`, `xgb_ranker.py:103-117`). **Fix:** identical feature
construction offline/online; purge+embargo the ranking labels.

### C6 — [HIGH] Signals weighted despite documented "no IC" / "wrong sign"
`institutional_flow` keeps 10% with the comment "no measured IC … believed to
work" (`cross_sectional.py:120,135`); `analyst_dispersion` is reintroduced at 5%
after the audit zeroed it for `|t|<1` (`earnings_signals.py:44,76-79`). This is
weight-vs-evidence mismatch and undermines the "we don't use signals we can't
validate" belief in `NORTHSTAR.md`. **Fix:** zero or validate.

### C7 — [MEDIUM] Correlation matrices averaged without Fisher-z; F-score/quality rescaling
Spearman matrices are averaged elementwise across dates (`redundancy.py:299-301`)
without a Fisher-z transform (biases the mean and breaks PSD); Piotroski scales
partial tests up to 0–9 (`factor_baselines.py:228-236`) and quality uses a single
quarter's NI×4 instead of TTM (`additional_signals.py:63`). **Fix:** Fisher-z
average; report coverage instead of rescaling; TTM sums.

### C8 — [MEDIUM] Factor attribution sums daily % returns to "monthly"
`factor_attribution.py:272-275` uses `resample("ME").sum()` on daily percentage
returns (an approximation to compounding) before the FF5+Mom regression, biasing
alpha/beta/R². HAC *is* correctly applied (a genuine bright spot,
`factor_attribution.py:161-164`), but the HLZ `|t|≥3` gate is reported, not
enforced (`factor_attribution.py:223-227`). **Fix:** compound to monthly; enforce
HLZ across the rolling-window multiple tests.

---

## D. The data → AI interface (`market_enrichment.py`, `orchestrator.py`, `prompts/`)

### D1 — [CRITICAL] Report trimming deletes the scores synthesis is told to trust
`trim_text` keeps the **prefix** and drops the suffix (`context_budget.py:12-13`,
`orchestrator.py:671-675`), but DCF/Earnings/Competitive prompts put the required
`SIGNAL_SCORE`/JSON at the **end**. With `synthesis_report_max_chars≈4500`,
synthesis often reasons on prose while the mechanical scores it is instructed to
use (`prompts/synthesis.md:17`) have been truncated away. **Fix:** tail-preserving
trim, or extract scores before trimming.

### D2 — [HIGH] Structured earnings output is parsed then not passed to synthesis
`_extract_earnings_structured` fills `AgentReport.structured` and it is persisted,
but `run_phase2` forwards only trimmed prose (`orchestrator.py:788-793`), so
synthesis' access to structured earnings depends on the JSON surviving inside the
prose (see D1). **Fix:** pass structured fields explicitly into the synthesis
context.

### D3 — [MEDIUM] Numbers reach the LLM without dates, units, or provenance
Yahoo/FMP price blocks lack as-of timestamps (`market_enrichment.py:52-55`); FRED
macro lines omit observation dates and release lags (`market_enrichment.py:
626-633`); the "Latest Annual" SEC block omits fiscal period/filing date
(`sec/xbrl_parser.py:656-661`); peer medians omit sample size/dispersion
(`peer_enrichment.py:436-458`); RAG passes an uncalibrated Pinecone `_score` as
"relevance" on 400-char truncations (`rag_enrichment.py:117-129`). The model
cannot distinguish stale from fresh, point-in-time from restated, or well-sampled
from thin. **Fix:** attach `(value, unit, as_of, source, n)` to every injected
statistic; the model should never see a bare number.

### D4 — [HIGH] The signals the LLM reasons about carry no IC/confidence
IC figures appear only as prose asides (`agents/earnings.py:114`); the synthesis
weights (Earnings 0.22, Pattern 0.18…) are hard-coded in markdown
(`prompts/synthesis.md:30-36`) with no linkage to the measured IC table — and
Pattern is weighted as "well-validated" even though `signals.py:56-66` zeroed
every technical indicator except OBV for having no IC. **Fix:** inject the live IC
table (value, t, N) and derive weights from it, or stop citing IC as the basis.

---

## E. AI reasoning & aggregation (`orchestrator.py`, `prompts/`)

### E1 — [CRITICAL] The "deterministic verdict" only thresholds an LLM-produced scalar
`orchestrator.py:877-907` takes `weighted_score` straight from the LLM's JSON and
maps it through fixed thresholds. It never recomputes it from `signal_breakdown`
or parsed agent scores, never verifies the reliability weights were applied or
sum to 1, and never applies the prompt's own "×0.7 adverse-macro" rule in code
(`prompts/synthesis.md:40`). The verdict/conviction look mechanical but inherit
the full LLM aggregation error, and they drive auto-paper-trading. **Fix:**
compute `weighted_score` in Python from validated component scores; treat the LLM
output as an input to be checked, not the answer.

### E2 — [HIGH] Half the agents have no mechanical score; the rest are LLM rubrics
Only DCF/Earnings/Competitive emit `SIGNAL_SCORE`; Risk/Macro/Pattern do not, so
synthesis invents −1..+1 scores for them (`prompts/synthesis.md:17-22`). The ones
that do exist are LLM-counted rubrics ("STRONG moat = +0.2",
`prompts/competitive.md:54`) or "score each dimension mentally"
(`prompts/earnings.md`) with no code deriving them from data and no check that
`SIGNAL_SCORE == mean(verdict_breakdown)`. **Fix:** derive scores
deterministically from the enrichment where possible; validate consistency where
not.

### E3 — [HIGH] Correlated macro evidence is double/triple counted
Macro enters DCF, Risk and Pattern contexts, the Macro agent produces its own
verdict, *and* synthesis both weights macro 0.12 and applies a macro multiplier
(`agents/macro.py`, `prompts/synthesis.md:36-40`). The same regime signal is
counted several times with no correlation adjustment, inflating its influence.
**Fix:** single macro entry point; treat regime as a multiplier *or* an additive
factor, not both.

### E4 — [HIGH] LLM probabilities/targets used unvalidated; uncertainty is discouraged
`prior_bull_probability`/`prior_bear_probability` are LLM point integers persisted
without checking they sum to 100 or match the verdict (`orchestrator.py:918-936`);
`price_target` is an LLM weighted-average with no validation
(`prompts/synthesis.md:57-65`); `health_scores` are uncalibrated 1–10 ordinals.
Meanwhile the prompt forbids hedging ("No 'however'… you are committing capital",
`prompts/synthesis.md:13,144`), systematically biasing the model toward
overconfident point estimates. **Fix:** validate ranges/sums; require and store
calibratable probabilities; allow explicit uncertainty and data-gap flags.

### E5 — [HIGH] ATR stop-loss policy not enforced on the live path
The "compute stop from 2×ATR, never trust LLM" block depends on `_signal_vector`,
which is assigned *after* a `return` on the live SEC path (dead code,
`orchestrator.py:567-594`) so stops fall back to a fixed 8%; and even when set, an
LLM stop that passes a loose sanity band is not overridden
(`orchestrator.py:809-861`). **Fix:** wire the signal vector on all paths; enforce
the computed stop.

---

## F. Position sizing (`orchestrator.py`, `backend/paper_scheduler.py`, `config.py`)

### F1 — [HIGH] Sizing has no statistical basis
Orders use a constant `paper_default_qty` (`orchestrator.py:293`,
`paper_scheduler.py:78`); conviction only gates entry via
`auto_paper_trade_min_conviction` (`paper_scheduler.py:68`). `sizing_guidance`
("1.5x_base_weight") is stored but never actuated. There is no volatility target,
no conviction→notional map, no Kelly fraction, no per-name risk budget, no
correlation/exposure cap at the portfolio level. **Effect:** realized risk per
position is arbitrary and portfolio risk is uncontrolled — a high-ATR name and a
low-ATR name get the same dollar exposure. **Fix:** volatility-scaled sizing
(target risk per position ∝ 1/σ), a conviction multiplier with caps, and a
portfolio-level exposure/correlation constraint. NORTHSTAR already envisions
"conviction-weighted within regime scalar"; it is unimplemented.

---

## G. Self-tracking & failure attribution (`backend/history_outcomes.py`)

### G1 — [HIGH] Outcome classification is path-dependent and not point-in-time
`compute_outcome_metrics` fetches the *current* quote and compares it to the
target/stop at query time (`history_outcomes.py:47-73`). A target hit then
reversed is missed; a stop touched intraday between checks is missed; return uses
raw last/close with no dividend adjustment. Outcomes therefore depend on *when the
function happens to run.* **Fix:** evaluate against the full daily path between
entry and horizon; use total-return series.

### G2 — [HIGH] No calibration or attribution loop
Nothing compares realized outcomes to the pre-trade `conviction_score`,
`prior_bull_probability`, or predicted rank. There is no Brier score, no
reliability diagram, no per-agent directional hit-rate, no max-adverse-excursion,
no "did the challenger/catalyst play out." The NORTHSTAR "Agent Accuracy Tracker"
and "Auto-grade engine" are unbuilt. **Effect:** the system cannot answer whether
its probabilities are calibrated or which agent adds value — so the hand-tuned
weights can never become earned weights. **Fix:** persist pre-trade predictions
and grade them against realized paths; compute calibration (Brier/reliability) and
per-agent accuracy. The assumption logger can carry the pre-trade record so
calibration is checkable later.

---

## The stochastic assumption-logging system (delivered)

**`quant/assumption_audit.py`** implements the "check assumptions against
information whenever available" requirement. It is dependency-light (lazy-imports
scipy/statsmodels), import-safe from anywhere in the tree, thread-safe, and inert
(it never changes a caller's numbers and never raises). Every check has three
outcomes:

- **PASS** — the information was available and the assumption holds.
- **VIOLATED** — the information was available and the assumption is false.
- **SKIPPED** — the information required to test it was not available (too few
  points, missing series, optional library absent). Logged with a reason, never a
  silent pass.

Checkers provided: `min_sample`, `value_in_range`, `sums_to`, `no_silent_zeros`,
`no_lookahead`, `finite`, `nonzero_variance`, `normality` (D'Agostino–Pearson),
`iid_no_autocorrelation` (Ljung-Box → lag-1 fallback, reports SE inflation),
`stationarity` (ADF), `overlapping_windows` (reports variance inflation),
`multiple_testing` (Bonferroni/Šidák + expected best-of-N null t). Records carry
severity, evidence (test stat, p-value, n), and scoped context (module, ticker,
as-of date, run id), stream to JSONL, and roll up in `summary()`.

**Usage in-pipeline:**

```python
from quant.assumption_audit import get_audit_log

log = get_audit_log()
with log.context(module="metrics.compute_sharpe", ticker=ticker):
    log.min_sample("sharpe_returns", n=len(returns), min_n=252)
    log.iid_no_autocorrelation("sharpe_returns", returns)   # → flags A1/C4
    log.normality("sharpe_returns", returns)                # → flags A2/A3 context
```

Toggle with `ASSUMPTION_AUDIT_ENABLED=0`; stream with `ASSUMPTION_AUDIT_JSONL=...`.
Covered by 44 tests in `tests/test_assumption_audit.py`.

**`scripts/run_statistical_rigor_audit.py`** runs the checks over the system's own
artifacts (`docs/audit/**/*.json`) and writes `assumption_log.jsonl` +
`assumption_report.md`. It exits non-zero on any HIGH/CRITICAL violation, so it
can gate CI. On the current artifacts it logged **212 checks (77 pass / 85
violated / 50 skipped)** and, most usefully, re-derived that the long-horizon IC
"significance" that selects the signal roster does not survive an overlap
correction (§C4). Re-run any time:

```bash
python3 scripts/run_statistical_rigor_audit.py --audit-dir docs/audit \
    --out docs/audit/session-4-statistical-rigor
```

---

## Prioritized remediation

**Tier 1 — inferences that are currently wrong (do first):**
1. Overlap-correct all IC t-stats (Newey-West or non-overlapping) and re-derive
   the signal roster/weights from the corrected numbers (§C4, A1).
2. Fix DSR `n_obs`/`n_trials`/observed, and either implement CSCV PBO or rename it
   (§A5, A6).
3. Recompute `weighted_score` deterministically in Python; validate weights sum to
   1 and enforce the macro multiplier in code (§E1).
4. Close the FMP/Kalshi look-ahead paths and the single-run IC-calibration leak
   (§B5, B1).

**Tier 2 — evidence hygiene:**
5. Multiple-testing correction + locked final holdout for all config sweeps (§B4).
6. Purge/embargo aligned to label horizon in walk-forward and CPCV (§B2, B3).
7. NaN-propagation instead of silent zeros, renormalized weights (§C1).
8. Attach `(value, unit, as_of, source, n)` to every number the LLM sees (§D3);
   tail-preserving trim (§D1).

**Tier 3 — build the missing statistics:**
9. Volatility-scaled, conviction-weighted position sizing with portfolio caps
   (§F1).
10. Calibration + per-agent attribution loop (Brier, reliability, MAE, hit-rate)
    grading pre-trade predictions against realized paths (§G1, G2).
11. Correct Sortino/alpha/Rf; Lo-adjusted Sharpe SE (§A2–A4).

**Cross-cutting:** instrument the Tier-1 call sites with the assumption logger so
these never silently regress, and add `scripts/run_statistical_rigor_audit.py` to
CI as a gate.

---

## Appendix — what's already good

Credit where due: per-rebalance (not full-sample) winsorization/z-scoring
(`cross_sectional.py:173-217`); Newey-West HAC in factor attribution
(`factor_attribution.py:161-164`); explicit 13F filing-lag PIT guards
(`institutional_flow.py:124-155`); non-overlapping sampling for the long-short
decile compounding in the IC runner; the honest habit of writing down disproven
beliefs (`NORTHSTAR.md`) and documenting known leaks in comments. The gap is not
awareness — it is that the safeguards are applied unevenly and the headline
statistics are trusted beyond what their assumptions support. The assumption
logger exists to make that trust explicit and checkable everywhere.
