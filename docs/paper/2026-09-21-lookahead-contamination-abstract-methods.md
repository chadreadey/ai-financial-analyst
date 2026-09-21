---
title: "Quantifying Training-Data Look-Ahead in LLM Financial Backtests"
date: 2026-09-21
kind: paper-draft
status: DRAFT — abstract + methods only. Results sections are placeholders.
relates_to:
  - docs/eval/three_series_llm/latest.md (pilot result)
  - docs/audit/2026-08-25-hac-sharpe-validation.md (power calibration)
  - README.md §"Backtest bias disclosure"
---

# Quantifying Training-Data Look-Ahead in LLM Financial Backtests

**Working title.** Alternative: *"The Model Already Knows: Measuring Look-Ahead
Contamination in LLM-Agent Trading Backtests."*

---

## Abstract

> Placeholder conventions: `[β̂]`, `[CI]`, `[N]` mark quantities the study must
> produce. Every number stated without brackets is already measured and cited.

Historical backtests of LLM-driven investment agents are contaminated by
construction: the model is asked to choose among securities over a period its
training data already covers. The field acknowledges this in limitations
sections but has no estimate of its magnitude, so readers cannot discount
published results by any principled amount. We supply that estimate.

We hold the investment pipeline fixed — a factor screener narrows a 495-name
universe to 50 candidates each month, and an LLM portfolio-construction agent
selects 10 — and vary only the language model. Because models differ in
training cutoff, the same calendar month is *inside* training data for some
models and *outside* it for others. This yields a staggered
difference-in-differences design in which model and month fixed effects absorb
model skill and market regime, and the coefficient on the pre-cutoff indicator
identifies the contamination effect. We strengthen the design in three ways:
we estimate each model's *effective* cutoff empirically with direct recall
probes rather than trusting self-reported cutoffs; we re-estimate as a
dose-response relationship on that continuous knowledge measure; and we
localize the mechanism with an entity-anonymization arm that strips tickers and
company names while preserving all numeric inputs.

Our pilot motivates the question. On 84 monthly rebalances from 2018-02 to
2025-01 — a window almost entirely inside the training data of the model used —
the LLM-selected portfolio returned a Sharpe of 1.01 against the quant
screener's 1.15 (ΔSharpe = −0.14). Since a five-year daily Sharpe carries a
standard error of approximately 0.45, this difference is statistically
indistinguishable from zero. The contaminated arm, with look-ahead working in
its favor, failed to beat the deterministic baseline it selected from.

We report the contamination effect as `[β̂]` percentage points of monthly excess
return `[CI]` and as `[Δ]` in ex-post-winner selection rate, and we find that
explicit prompt-level guardrails against using post-date knowledge
`[do / do not]` attenuate it. We release the harness, the recorded model
responses, and the pre-registration.

**Keywords:** large language models, data contamination, backtest overfitting,
financial machine learning, agent evaluation, difference-in-differences

---

## 1. Motivation (condensed — expand in the full paper)

Two literatures meet here and neither covers the intersection. Financial
econometrics has a mature account of backtest bias — survivorship, look-ahead
in data construction, multiple testing, and the probability of backtest
overfitting. LLM evaluation has a growing account of benchmark contamination,
measured by n-gram overlap or membership inference against a *known* corpus.

Neither transfers. Financial look-ahead controls assume look-ahead enters
through *data* you can timestamp and withhold; here it enters through model
weights, which you cannot. Contamination detection assumes access to the
training corpus or a canary string; frontier model corpora are undisclosed, and
the leaked quantity is not a string but diffuse knowledge of which companies
subsequently did well.

The practical consequence is that no reader of an LLM-trading paper can
currently answer "by how much should I discount this Sharpe?" That is the gap.

---

## 2. Methods

### 2.1 Design overview

The pipeline is held fixed and the language model is the only manipulated
component:

```
495-ticker PIT universe
    └─> screener composite (QMJ, SUE, ERM; IC-t-stat weights)   [deterministic]
        └─> top-50 candidate list, per monthly rebalance        [deterministic]
            ├─> top-10 by composite            = QUANT-ONLY arm [deterministic]
            └─> LLM agent selects 10 of 50     = AI arm, per model × prompt arm
```

Every arm selects from an *identical* candidate list at every rebalance. The
quant-only arm is a deterministic function of that list, so it is constant
across models and serves as the within-month benchmark. Any difference between
an AI arm and the quant-only arm at month *d* is attributable to the selection
step alone.

The screener retains only signals that survive overlap-corrected significance
testing on the 495-name universe: QMJ and SUE at the one-month horizon and ERM
at three months, weighted by `|t| / Σ|t|` rather than hand-tuning
(`quant/screener.py`). The portfolio-construction agent holds 10 long-only,
equal-weight positions with a maximum of 4 per GICS sector and may hold cash
if fewer than 10 candidates clear its quality bar
(`agents/portfolio_construction.py`). Returns are computed from close-to-close
prices over each holding period and chained across rebalances
(`quant/three_series_eval.py`).

### 2.2 Identification

Let `r^{AI}_{m,d}` be the holding-period return of model *m*'s portfolio formed
at rebalance date *d*, and `r^{Q}_d` the quant-only return from the same
candidate list. Define the paired excess return

```
e_{m,d} = r^{AI}_{m,d} − r^{Q}_d
```

and the contamination indicator `C_{m,d} = 1[d ≤ ĉ_m]`, where `ĉ_m` is model
*m*'s estimated effective training cutoff (§2.4). The primary specification is

```
e_{m,d} = α + β·C_{m,d} + γ_m + δ_d + ε_{m,d}
```

with model fixed effects `γ_m` and rebalance-date fixed effects `δ_d`. Standard
errors are two-way clustered on model and date. `β` is the contamination
effect: the excess return a model earns on months it has seen, over and above
its own general skill (`γ_m`) and whatever that month offered every selector
(`δ_d`).

Three properties of this design are worth stating explicitly.

**Date fixed effects absorb the confounds that sink naive comparisons.**
Survivorship bias in the candidate list, market regime, and the screener's
own time-varying quality are all common to every model at date *d*, so they
load entirely on `δ_d` and cannot bias `β`. This is why the design tolerates a
candidate list that is *not* survivorship-corrected, though we correct it
anyway (§2.6) because it still biases the reported levels. Note that with
`δ_d` included, regressing `r^{AI}` directly is numerically equivalent to
regressing `e`; we difference for interpretability, not identification.

**Identification comes only from cutoff-straddling months.** For a month before
every model's cutoff, `C_{m,d} = 1` for all *m*; for a month after every
cutoff, `C_{m,d} = 0` for all *m*. In both cases `C` has no within-date
variation and the month contributes nothing to `β`. **Only months lying between
the earliest and latest cutoff in the model panel identify the effect.** This
is the binding design constraint, and it reverses the natural instinct to
replay as much history as possible: a 2018–2024 replay against models cutting
off in 2025 has *zero* identifying variation. The sample must be built around
the cutoff spread, not around history (§2.3).

**The identifying assumption** is that, conditional on `γ_m` and `δ_d`, model
skill at selecting from a candidate list does not change discontinuously at its
own training cutoff for reasons other than knowledge of outcomes. The principal
threat is a model × recency interaction: a newer model may be better at recent
months for legitimate reasons — familiarity with newly listed companies,
changed business models, shifted sector composition — rather than because it
recalls returns. §2.5 addresses this with an arm that removes entity identity
while preserving the numbers, and §2.7 with a placebo that removes the LLM.

### 2.3 Sample construction

Because only cutoff-straddling months identify `β`, the model panel and the
replay window are chosen jointly:

1. **Model panel.** Select `[M ≈ 6–8]` models whose effective cutoffs are
   spread as widely as possible across the replay window, spanning at least two
   providers and including at least one open-weights model whose training
   corpus is documented and inspectable. The harness reaches any of these
   through one of two providers (`llm/providers.py`): the Anthropic client, or
   an OpenAI-compatible client that accepts a `base_url` override and therefore
   serves self-hosted and third-party endpoints without code changes.
2. **Replay window.** Extend from the earliest model's cutoff to the present,
   so that recent months are post-cutoff for older models and pre-cutoff for
   newer ones. The pilot window (2018-02 → 2025-01, 84 monthly rebalances,
   1,759 trading days) is retained as an out-of-design descriptive sample but
   is, by the argument above, uninformative about `β` on its own.
3. **Forward extension.** Months accruing after the newest model's cutoff are
   clean for every model and accumulate at one observation per model per month.
   These anchor the `C = 0` level and grow the sample at no marginal
   contamination risk, so the study is designed to be re-run on a schedule
   rather than frozen at submission.

The open-weights model is load-bearing: it is the one arm where the mapping
from corpus to cutoff can be verified directly rather than inferred, which
calibrates how much to trust the estimated cutoffs of the closed models.

### 2.4 Estimating effective cutoffs

Self-reported cutoffs are approximate, are not always honored uniformly across
topics, and in some cases are not published at all. We therefore estimate each
model's effective knowledge empirically and use the estimate in place of the
reported date.

For a grid of (ticker, month) pairs drawn from the candidate lists, we query
the model directly for facts it would need in order to exploit look-ahead — the
sign and approximate magnitude of the security's forward return over the
holding period, and whether a major corporate event occurred in that window —
with scoring against realized data. This produces a per-model **knowledge
curve** `k_m(d) ∈ [0, 1]`: recall accuracy as a function of calendar month,
which should be high inside training data and decay to chance beyond it.

The knowledge curve serves two purposes:

- **`ĉ_m`** is the month at which `k_m(d)` crosses the midpoint between its
  in-sample plateau and its chance floor, used as the binary threshold in the
  primary specification.
- **Dose-response.** Replacing `C_{m,d}` with the continuous `k_m(d)` in the
  primary regression yields a secondary estimate that does not depend on
  locating a sharp threshold and that recovers identifying variation from
  months where models differ in degree of knowledge rather than in binary
  status. A monotone dose-response is materially more convincing than a
  threshold effect and is robust to cutoffs being fuzzy rather than sharp.

The probe measures whether a model *has* the information. The portfolio
regression measures whether it *uses* it. Reporting both separates capability
from exploitation, and the gap between them is itself a result: a model that
can recall forward returns but does not act on them is evidence that the
contamination channel is weaker than the capability implies.

### 2.5 Experimental arms

Each model is run under four prompt conditions against the same candidate
lists:

| Arm | Description | What it isolates |
|---|---|---|
| **Base** | The production prompt, unmodified | The headline quantity a practitioner would report |
| **Guardrail** | Base plus an explicit instruction that the as-of date is *d* and post-*d* knowledge must not be used | Whether prompting mitigates — the repo's disclosure asserts it cannot; this tests that assertion |
| **Anonymized** | Tickers replaced with arbitrary identifiers, company and sector names stripped, all numeric signal inputs preserved | The mechanism: if `β` collapses here, contamination flows through entity recognition, not numeric pattern-matching |
| **Deterministic** | The heuristic selector, no LLM in the loop | Placebo (§2.7) |

The anonymized arm is the mechanism test and the most informative of the four
for anyone designing a mitigation. If contamination survives anonymization, no
amount of entity masking helps and only post-cutoff evaluation is valid. If it
does not, masking becomes a practical, cheap control that the field can adopt.

### 2.6 Outcome measures

**Primary — paired monthly excess return.** `e_{m,d}` as defined in §2.2.
Chosen over a Sharpe comparison deliberately: the pilot's Sharpe standard error
of ≈0.45 (Monte Carlo, 5,000 paths, `docs/audit/2026-08-25-hac-sharpe-validation.md`)
means that comparing headline Sharpes across arms has essentially no power at
realistic sample lengths. Pairing against the quant-only arm removes the common
market component month by month and shifts the analysis to a panel with
`M × D` observations rather than a handful of Sharpe point estimates.

**Co-primary — ex-post winner selection rate.** The fraction of a model's 10
picks that fall in the top decile of realized forward return *within that
month's 50-name candidate set*. This is a direct measure of the selection
behavior contamination should produce, it has clean binomial variance, and it
is not diluted by position sizing or by the return dispersion of a given month.
Under the null of no contamination the expected rate equals the base rate
implied by drawing 10 of 50.

**Secondary.**
- *Anachronism rate in rationales.* The agent emits a one-sentence rationale
  per pick. We grade each for reference to information dated after the as-of
  date. This is the interpretable, quotable contamination detector: an
  explicit citation of a post-date event is a smoking gun rather than a
  statistical inference.
- *Sharpe with standard errors.* Reported for continuity with the literature,
  using the Lo (2002) autocorrelation-adjusted standard error implemented in
  `quant/metrics.py:compute_sharpe_stats`, and reported *with* the error bar
  precisely to demonstrate why it cannot carry the argument alone.
- *Turnover and concentration*, to confirm arms are not differing through a
  mechanical channel.

**Survivorship correction.** Candidate lists are rebuilt from point-in-time
index constituents rather than the current universe. As argued in §2.2, date
fixed effects already protect `β` from this bias; the correction is required
for the reported *levels* to be meaningful and for the pilot's headline numbers
to be interpretable at all. The pilot's quant-only total return of 513.57%
against SPY's 140.81% is inflated by exactly this channel and is not reported
as a finding.

### 2.7 Placebo and robustness

- **Placebo.** The deterministic arm runs the identical pipeline with the LLM
  removed. It cannot be contaminated, so estimating the primary specification
  on it must yield `β ≈ 0`. A non-zero placebo coefficient indicates that the
  cutoff indicator is picking up a calendar artifact rather than model
  knowledge, and invalidates the design.
- **Regression discontinuity.** Restricting to a ±`[k]`-month window around
  each model's `ĉ_m` sharpens identification at the cost of sample size.
  Reported as a robustness check, not as the primary estimate: monthly data
  makes any usable bandwidth small.
- **Leave-one-model-out.** Re-estimate `β` dropping each model in turn, to
  confirm no single model drives the result.
- **Cutoff sensitivity.** Re-estimate with reported cutoffs substituted for
  estimated ones, and with `ĉ_m` shifted ±3 months, to show the estimate does
  not hinge on threshold placement.
- **Determinism.** All calls use `temperature = 0` where the model accepts a
  sampling parameter; several current models reject it and are run at provider
  default (`llm/providers.py`). Because temperature 0 is not a determinism
  guarantee, each configuration is repeated `[R]` times and we report
  within-configuration variance in selection and in `e`. This variance sets the
  floor on the smallest `β` the design can detect and is reported alongside it.

### 2.8 Power

The design is powered on the panel, not on Sharpe differences. With `M` models
× `D` rebalances and residual standard deviation `σ_ε` of the paired monthly
excess return, the minimum detectable effect at 80% power and 5% size is
approximately `2.8 · σ_ε · √(1/N_eff)`, where `N_eff` adjusts `M × D` for
two-way clustering and for the fact that only cutoff-straddling months
contribute. We estimate `σ_ε` from the pilot's recorded responses before
committing to the panel size, and report the realized MDE alongside `β̂`. If
the design is underpowered for the binary specification, the dose-response
estimate in §2.4 — which uses all months rather than only straddling ones — is
the fallback primary.

### 2.9 Reproducibility and cost

Every model call is recorded and replayable offline: the eval harness stores
responses as cassettes and re-grades them without API access
(`evals/`, `docs/EVALS.md`), and each run is stamped with a configuration hash
and git SHA (`quant/config_hash.py`, `quant/git_sha.py`). Replay is fanned out
one container per rebalance date on Modal, and the replay function fails loudly
rather than silently falling back to the heuristic selector when an LLM call
fails — a silent fallback would manufacture a spurious `Δ = 0`
(`modal_app/functions/ai_replay.py`).

Cost is not a barrier and we state it to make the point that this study is
replicable by anyone: the pilot's 84 LLM calls cost on the order of $3–4, and
the full design at `[M]` models × 4 arms × `[D]` dates × `[R]` repeats is on
the order of `[$]` — dominated by the recall probes rather than the portfolio
calls.

The analysis is pre-registered before the post-cutoff months accrue, which is
the one part of the sample the authors cannot inspect in advance. The
pre-registration fixes the model panel, the cutoff-estimation procedure, the
primary and co-primary outcomes, and the specification.

---

## 3. Results

`[TO BE FILLED]`

Table 1 — model panel, reported vs. estimated cutoffs, knowledge-curve fit.
Table 2 — primary DiD estimates, by arm.
Table 3 — winner-selection rates, by arm and cutoff status.
Figure 1 — knowledge curves `k_m(d)` by model.
Figure 2 — dose-response of `e` on `k`.
Figure 3 — event study around `ĉ_m`.

## 4. Discussion

`[TO BE FILLED]` — the discount factor a reader should apply to published
LLM-trading Sharpes; whether guardrail prompting is a usable mitigation;
whether entity anonymization is; and the implication that forward shadow
evaluation is the only fully valid protocol.

## 5. Limitations

To be written against realized results, but the known ones are:

- Effective cutoffs are estimated, not known. The open-weights arm partially
  calibrates this; the closed models remain inferred.
- One pipeline, one asset class, one selection task. The estimate is an effect
  size for *this* design, and generalization to other LLM-trading architectures
  is an assumption.
- The model × recency confound is mitigated by the anonymization arm and the
  placebo but cannot be eliminated by design.
- Holding-period returns exclude transaction costs and execution delay in the
  current evaluator. These are common to all arms and difference out of `β`,
  but the reported levels are gross.
- Contamination is measured as it manifests in portfolio selection. A model
  might hold outcome knowledge it declines to act on, which the recall probes
  detect but the portfolio regression will not.

---

## Appendix A — What the pilot established

The measured quantities that motivate the study, all reproducible from this
repository:

| Quantity | Value | Source |
|---|---|---|
| Replay window | 2018-02-01 → 2025-01-30, 84 monthly rebalances | `docs/eval/three_series_llm/latest.json` |
| SPY Sharpe | 0.74 | same |
| Quant-only Sharpe | 1.15 | same |
| AI-augmented Sharpe | 1.01 | same |
| ΔSharpe (AI − quant) | −0.14 | same |
| Sharpe SE, 5y daily, true SR = 1.0 | 0.4472 (formula) vs 0.4478 (empirical, 5,000 paths) | `docs/audit/2026-08-25-hac-sharpe-validation.md` |
| Meta-model on AI picks, test AUC | 0.502 | `models/ai_pick_meta.pkl.metrics.json` |

The last row is a secondary motivation: a gradient-boosted classifier trained
to predict whether an AI pick would beat its sector over 21 days reached 0.89
train AUC and 0.502 test AUC, i.e. the AI selections carried no learnable
structure beyond the composite they were drawn from.

## Appendix B — Why the naive comparison fails

Stated for the paper's methods-contribution framing. The same repository's
statistical audit established that the naive t-statistic
`t = mean / (std/√n)`, applied to information coefficients sampled monthly from
12-month overlapping forward returns, rejects a true null **59.3%** of the time
at a nominal 5% level. A correctly implemented Newey–West HAC statistic reduces
this to 18.7% but still over-rejects at realistic sample sizes; Monte Carlo
calibration at the study's exact sample geometry gives a 5% critical value of
3.08 at n = 96, not 1.96. Re-judging the signal roster under the calibrated
thresholds reduced it from several signals significant at multiple horizons to
**two** — QMJ and SUE, at the one-month horizon only
(`docs/audit/2026-08-25-rejudge/rejudgment.md`).

This is the same failure mode the paper targets, one level up: a number
produced under an assumption that was never checked. The contamination estimate
is the assumption check that LLM-trading backtests currently lack.
