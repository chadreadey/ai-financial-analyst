---
title: "How Much Should You Discount an LLM Trading Backtest? A Contamination Gradient Across Universes"
date: 2026-09-21
revised: 2026-09-21 (v3 — LaTeX notation)
kind: paper-draft
status: DRAFT — abstract + methods only. Results sections are placeholders.
relates_to:
  - docs/eval/three_series_llm/latest.md (pilot result)
  - docs/audit/2026-08-25-hac-sharpe-validation.md (power calibration)
  - docs/audit/2026-08-25-rejudge/rejudgment.md (signal roster)
  - README.md §"Backtest bias disclosure"
---

# How Much Should You Discount an LLM Trading Backtest?
## A Contamination Gradient Across Universes

---

## Reading this draft

Two kinds of margin flags appear throughout.

| Flag | Meaning |
|---|---|
| 🟡 **RIGOR GAP** | Statistical work that does not yet exist and that the claim depends on. Nothing downstream of one of these is defensible until it is closed. |
| 🔴 **DEFENSE** | A place a referee or committee member will press. The design does not necessarily fail here, but you need the answer rehearsed before you present. |

Bracketed quantities — $[\hat\beta]$, $[\text{CI}]$, $[M]$ — are placeholders
the study must produce. Every unbracketed number is already measured and cited
to this repository.

### Notation

| Symbol | Meaning |
|---|---|
| $m$ | model index |
| $d$ | rebalance date (month) |
| $c$ | candidate-set condition (factorial cell, §2.5) |
| $r^{\mathrm{AI}}_{m,d,c}$ | holding-period return of model $m$'s portfolio |
| $r^{\mathrm{DET}}_{d,c}$ | holding-period return of the deterministic selector |
| $e_{m,d,c}$ | paired excess return, $r^{\mathrm{AI}} - r^{\mathrm{DET}}$ |
| $\hat c_m$ | estimated effective training cutoff of model $m$ |
| $C_{m,d}$ | contamination indicator |
| $k_m(d)$ | knowledge curve — measured recall of month $d$ by model $m$ |
| $\beta_c$ | contamination effect in condition $c$ |
| $D_c,\ D^{\%}_c$ | Sharpe discount, absolute and percentage |
| $\mathrm{SR}(\cdot)$ | annualized Sharpe ratio |

---

## Abstract

Historical backtests of LLM-driven investment agents are contaminated by
construction: the model chooses among securities over a period its training
data already covers. The field acknowledges this in limitations sections but
has no estimate of its magnitude, so a reader cannot discount a published
result by any principled amount. We supply that estimate, and show what
governs it.

We hold an investment pipeline fixed — a candidate rule narrows a universe to
50 names each month, and an LLM portfolio-construction agent selects 10 — and
manipulate two things. First, the language model: because models differ in
training cutoff, the same calendar month falls inside training data for some
models and outside it for others, yielding a staggered difference-in-differences
design in which model and month fixed effects absorb model skill and market
regime. Second, the candidate rule, along two axes that should govern how much
look-ahead is worth: **selectivity** — how tightly the candidate set is
pre-filtered, and therefore how much room foreknowledge has to change the
selection — and **salience** — how well represented the candidate names are in
training data, and therefore how much the model plausibly recalls.

We estimate the effect on paired monthly excess returns, where pairing against
a deterministic selector drawn from the identical candidate list removes the
common market component and makes the design powered; we then report it as a
**Sharpe discount** by constructing a de-contaminated return series and
bootstrapping the entire two-stage pipeline. This separation is deliberate: a
five-year daily Sharpe carries a standard error of approximately $0.45$, so
differencing two Sharpe estimates directly has almost no power, while a Sharpe
discount is the only form in which the result is usable by the audience that
needs it.

Our pilot motivates the question and supplies none of the answer. On 84 monthly
rebalances from 2018-02 to 2025-01 — a window lying almost entirely inside the
training data of the model used — the LLM-selected portfolio returned a Sharpe
of $1.01$ against the deterministic baseline's $1.15$. That difference is well
inside one standard error of zero, and in any case runs opposite to the
direction contamination predicts; it establishes only that the question is open.

We report the discount as $[D]$ Sharpe points, $[D^{\%}]$ in percentage terms,
and find it *[is / is not]* monotone in both selectivity and salience. We
release the harness, the recorded model responses, and the pre-registration.

🔴 **DEFENSE — "isn't this obvious? of course the model knows."** Have the
answer ready in one sentence: obviousness is not a magnitude, and no reader of
an LLM-trading paper can currently say whether to subtract $0.05$ or $0.8$ from
a reported Sharpe. The contribution is the number and its boundary conditions,
not the existence of the phenomenon.

**Keywords:** large language models, data contamination, backtest overfitting,
financial machine learning, agent evaluation, difference-in-differences

---

## 1. Motivation (condensed — expand in the full paper)

Two literatures meet here and neither covers the intersection. Financial
econometrics has a mature account of backtest bias — survivorship, look-ahead
in data construction, multiple testing, the probability of backtest
overfitting. LLM evaluation has a growing account of benchmark contamination,
measured by $n$-gram overlap or membership inference against a known corpus.

Neither transfers. Financial look-ahead controls assume look-ahead enters
through *data* you can timestamp and withhold; here it enters through model
weights, which you cannot. Contamination detection assumes access to the
training corpus or a planted canary; frontier corpora are undisclosed, and the
leaked quantity is not a string but diffuse knowledge of which companies
subsequently did well.

The practical consequence is that no reader of an LLM-trading paper can
currently answer "by how much should I discount this Sharpe?" That is the gap.

🔴 **DEFENSE — provenance of the research question.** This project began as an
attempt to determine whether LLM agents could select profitable equity
portfolios. The contamination question was formulated *after* observing a null
result, which is textbook HARKing if presented as prospective. Disclose the
sequence explicitly in §1 rather than letting a reader reconstruct it from the
repository history. The mitigation is that the pre-registration (§2.10) binds
before the post-cutoff months exist, so the confirmatory sample is genuinely
out of sample even though the question was not.

---

## 2. Methods

### 2.1 Design overview

The pipeline is fixed; two components are manipulated.

```
base universe  (per salience condition)
     │
     └──> candidate rule  (per selectivity condition)  ──>  50 names / month
              │
              ├──> top-10 by rule              = DETERMINISTIC arm   [no LLM]
              └──> LLM agent selects 10 of 50  = AI arm  (model × prompt arm)
```

Within a given month and candidate-set condition, every arm selects from an
*identical* 50-name list. The deterministic arm is a fixed function of that
list, so it is constant across models and serves as the within-month benchmark.
Any difference between an AI arm and the deterministic arm is therefore
attributable to the selection step alone.

The portfolio-construction agent holds 10 long-only equal-weight positions, at
most 4 per GICS sector, and may hold cash if fewer than 10 candidates clear its
bar (`agents/portfolio_construction.py`). Holding-period returns are computed
close-to-close and chained across rebalances (`quant/three_series_eval.py`).

**The screener's status in this paper.** The composite rule — QMJ, SUE and ERM
weighted by

$$w_i \;=\; \frac{\lvert t_i\rvert}{\sum_j \lvert t_j\rvert}$$

(`quant/screener.py`) — is used here as a *fixed, reproducible
candidate-generation rule* and is not claimed to generate alpha. This is a
deliberate change from how the repository describes it, forced by the new
design: the composite is now one rung on a selectivity ladder whose other rungs
are explicitly not alpha-generating. Identification does not require the rule
to have edge.

🔴 **DEFENSE — do not call this screener "IC-validated."** Across the $m = 44$
signal × horizon tests in `docs/audit/2026-08-25-rejudge/rejudgment.json`,
**zero survive Benjamini–Hochberg at $\alpha = 0.05$ or $\alpha = 0.10$, and
zero survive Bonferroni.** The BH rule rejects when

$$p_{(i)} \;\le\; \frac{i}{m}\,\alpha ,$$

so the rank-1 threshold is $\tfrac{1}{44}(0.05) \approx 0.0011$, against QMJ's
bootstrap $p = 0.0075$. The true testing family is larger still once composite
configurations, leverage sweeps and prior audit sessions on other universes are
counted. A reviewer can verify this in minutes from your own committed
$p$-values. The framing above removes the attack surface entirely at no cost to
the design — but the repository's own front-page claims must be reconciled too
(§2.11).

### 2.2 Identification

Let $r^{\mathrm{AI}}_{m,d,c}$ be the holding-period return of model $m$'s
portfolio formed at rebalance date $d$ under candidate-set condition $c$, and
$r^{\mathrm{DET}}_{d,c}$ the deterministic return from the same list. Define
the paired excess return

$$e_{m,d,c} \;=\; r^{\mathrm{AI}}_{m,d,c} \;-\; r^{\mathrm{DET}}_{d,c}$$

and the contamination indicator

$$C_{m,d} \;=\; \mathbf{1}\!\left[\,d \le \hat c_m\,\right],$$

where $\hat c_m$ is model $m$'s estimated effective cutoff (§2.4). Within each
condition $c$,

$$e_{m,d,c} \;=\; \alpha_c \;+\; \beta_c\,C_{m,d} \;+\; \gamma_{m,c} \;+\; \delta_{d,c} \;+\; \varepsilon_{m,d,c},$$

with model fixed effects $\gamma_{m,c}$ and rebalance-date fixed effects
$\delta_{d,c}$. The coefficient $\beta_c$ is the contamination effect in
condition $c$: the excess return a model earns on months it has seen, net of
its own general skill and of what that month offered every selector.

Three properties are worth stating explicitly.

**Date fixed effects absorb the confounds that sink naive comparisons.**
Survivorship bias in the candidate list, market regime, and the candidate
rule's own time-varying quality are common to every model at date $d$, so they
load on $\delta_{d,c}$ and cannot bias $\beta_c$. Note that with $\delta_{d,c}$
included, regressing $r^{\mathrm{AI}}$ directly is numerically equivalent to
regressing $e$; the differencing is for interpretability, not identification.

**Identification comes only from cutoff-straddling months.** For a month before
every cutoff, $C_{m,d} = 1$ for all $m$; after every cutoff, $C_{m,d} = 0$ for
all $m$. In both cases $C$ has no within-date variation and the month
contributes nothing. **Only months satisfying**

$$\min_m \hat c_m \;<\; d \;\le\; \max_m \hat c_m$$

**identify $\beta_c$.** This reverses the instinct to replay as much history as
possible: a 2018–2024 replay against models cutting off in 2025 has *zero*
identifying variation.

🔴 **DEFENSE — adding universes does not help identification.** The factorial
in §2.5 is a cross-sectional axis; the identification constraint is temporal
and entirely orthogonal. Three candidate-set conditions over 2018–2024 yield
three times the data with the same zero identifying variation. Both problems
must be solved independently, and a reviewer who understands the design will
check that you know this.

**The identifying assumption** is that, conditional on $\gamma_{m,c}$ and
$\delta_{d,c}$, model skill at selecting from a candidate list does not change
discontinuously at its own cutoff for reasons other than outcome knowledge.

🔴 **DEFENSE — cutoff is nearly collinear with capability.** Newer cutoff
implies stronger model, and within one model family the two are effectively
perfectly confounded. Fixed effects absorb the *level* of skill but not a
capability × recency interaction, which is precisely your identifying
variation. A reviewer will argue $\beta_c$ is simply "better models are better
at recent data." The design response is to include at least one **newer but
weaker** model — a recent small model — so that capability and cutoff are not
monotonically ordered across the panel. Without that inversion the objection
stands.

### 2.3 Sample construction

Because only cutoff-straddling months identify $\beta_c$, the model panel and
replay window are chosen jointly.

1. **Model panel.** $[M \approx 6\text{–}8]$ models with cutoffs spread as
   widely as possible across the window, spanning at least two providers,
   including at least one open-weights model with a documented and inspectable
   corpus, and including at least one newer-but-weaker model per the defense
   above. The harness reaches all of these through `llm/providers.py` — the
   Anthropic client, or an OpenAI-compatible client whose `base_url` override
   serves self-hosted and third-party endpoints without code changes.
2. **Replay window.** From $\min_m \hat c_m$ to the present, so that recent
   months are post-cutoff for older models and pre-cutoff for newer ones. The
   pilot window (2018-02 → 2025-01, 84 rebalances, 1,759 trading days) is
   retained as an out-of-design descriptive sample only.
3. **Forward extension.** Months accruing after $\max_m \hat c_m$ are clean for
   every model and anchor the $C = 0$ level. The study is designed to be re-run
   on a schedule rather than frozen at submission.

🟡 **RIGOR GAP — effective sample size.** The 84 rebalances are not 84
independent observations. Holdings overlap heavily month to month because QMJ,
SUE and ERM are persistent, so $e_{m,d,c}$ is serially correlated within model.
Two-way clustering does not fully address this. Required: measure the
month-to-month holdings overlap directly from the candidate and pick files,
report an effective $N_{\mathrm{eff}}$, and use a moving-block bootstrap with
block length at least the measured persistence. The implementation already
exists — `mbb_pvalue` in `scripts/rejudge_ic_signals.py` — and needs to be
applied here rather than rewritten.

### 2.4 Estimating effective cutoffs

Self-reported cutoffs are approximate, are not honored uniformly across topics,
and are sometimes unpublished. We estimate each model's effective knowledge
empirically.

For a grid of (ticker, month) pairs drawn from the candidate lists, we query
the model for facts it would need in order to exploit look-ahead: the sign and
approximate magnitude of the security's forward return over the holding period,
and whether a major corporate event occurred in that window. Scoring against
realized data produces a per-model **knowledge curve** $k_m(d) \in [0,1]$ —
recall accuracy by calendar month, high inside training data and decaying to
chance beyond it.

The curve serves two purposes. First, $\hat c_m$ is the month at which $k_m(d)$
crosses the midpoint between its in-sample plateau $k^{\max}_m$ and its chance
floor $k^{0}$:

$$\hat c_m \;=\; \min\left\{\, d \;:\; k_m(d) \;<\; \tfrac{1}{2}\left(k^{\max}_m + k^{0}\right) \right\}.$$

Second, replacing $C_{m,d}$ with the continuous $k_m(d)$ gives a
**dose-response** specification,

$$e_{m,d,c} \;=\; \alpha_c \;+\; \beta^{k}_c\,k_m(d) \;+\; \gamma_{m,c} \;+\; \delta_{d,c} \;+\; \varepsilon_{m,d,c},$$

which does not require locating a sharp threshold and recovers identifying
variation from months where models differ in *degree* of knowledge rather than
in binary status.

The probe measures whether a model *has* the information; the portfolio
regression measures whether it *uses* it. The gap between them is itself a
result.

🟡 **RIGOR GAP — the probe has two validity holes that must be closed before
$k_m(d)$ can carry the dose-response.** First, **refusal is not ignorance**:
models are trained to decline "what was $X$'s return after date $d$," and
scoring a refusal as $k = 0$ biases the curve downward differentially across
providers and alignment regimes. Refusals need their own category and a
sensitivity analysis under both codings. Second, **$k_m(d)$ is confounded with
market capitalization**: recall is far better for mega-caps, which is *also*
correlated with returns, so an uncorrected dose-response partly measures size.
Stratify the probe grid by size tercile and report $k_m(d)$ within stratum.

🔴 **DEFENSE — is a constant $\beta_c$ over the whole pre-cutoff era
plausible?** Almost certainly not: recall should decay with distance from the
cutoff, since recent data is more heavily represented and better retained. A
step function in $C_{m,d}$ is the wrong functional form. Pre-empt this by
reporting the event-study version — $\beta_c$ estimated in bins of
$d - \hat c_m$ — as a headline figure rather than a robustness check, and by
treating the dose-response specification as co-primary rather than secondary.

### 2.5 The candidate-set factorial

Two axes govern how much contamination should be worth. They are different
mechanisms and must not be varied together.

**Axis A — Selectivity.** How tightly the candidate set is pre-filtered, and
therefore how much room foreknowledge has. Base universe held fixed at the
495-name panel.

| Condition | Candidate rule | Room for look-ahead |
|---|---|---|
| **A1 — Random** | 50 drawn at random (seeded, reproducible) | Maximal |
| **A2 — Single-signal** | Top 50 by QMJ alone | Intermediate |
| **A3 — Composite** | Top 50 by the composite rule | Minimal — the pilot configuration |

**Axis B — Salience.** How well represented the candidate names are in training
data, and therefore how much the model plausibly recalls. Selectivity held
fixed at A1 (random draw), so selection pressure does not vary.

| Condition | Base universe | Expected recall |
|---|---|---|
| **B1 — Mega-cap** | `sp500_top50` | Highest |
| **B2 — Mixed** | Full 495-name panel *(= A1, shared hinge cell)* | Middle |
| **B3 — Tail** | Smallest-capitalization tercile of the panel | Lowest |

`quant/universe.py:get_universe` already supports `sp500`,
`sp500_top50/100/200` and `liquid_10` through `liquid_200`, so axis B costs
little to implement.

**Design economy.** A full $3 \times 3$ crossing is unaffordable once
multiplied by models, prompt arms, dates and repeats. We run a staircase: the
selectivity ladder at fixed mid-salience and the salience ladder at fixed
random selectivity, sharing the A1/B2 cell as the hinge — five cells rather
than nine. The four prompt arms of §2.6 run in full only in the hinge cell;
elsewhere only *base* and *guardrail* run.

🔴 **DEFENSE — a staircase cannot detect a selectivity × salience
interaction.** If contamination requires *both* room and recall, the effect
could be large in a cell the staircase never visits — a random draw over
mega-caps is visited, but a composite screen over the small-cap tail is not.
State this as a design limitation explicitly and, if budget allows, add the
single missing corner cell rather than claiming the interaction is absent.

🟡 **RIGOR GAP — selectivity is confounded with portfolio quality.** Moving
from A3 to A1 does not only increase room for look-ahead; it also lowers the
average quality of the candidate set, which changes return dispersion and
therefore the scale of $e_{m,d,c}$. A raw comparison of $\beta_{A1}$ against
$\beta_{A3}$ conflates the two. Required: report the standardized effect

$$\beta^{\ast}_c \;=\; \frac{\beta_c}{\operatorname{sd}_c\!\left(r^{\mathrm{DET}}\right)}$$

— the contamination effect per unit of achievable spread — alongside the raw
estimate, and run the monotonicity test of §2.8 on $\beta^{\ast}_c$, not
$\beta_c$.

### 2.6 Prompt arms

Each model runs under four prompt conditions against identical candidate lists.

| Arm | Description | What it isolates |
|---|---|---|
| **Base** | Production prompt, unmodified | The headline quantity a practitioner would report |
| **Guardrail** | Base plus an explicit as-of date and instruction not to use post-date knowledge | Whether prompting mitigates — the repository's disclosure asserts it cannot |
| **Anonymized** | Tickers replaced with arbitrary identifiers, company and sector names stripped, all numeric inputs preserved | Mechanism: if the effect collapses, contamination flows through entity recognition rather than numeric pattern-matching |
| **Deterministic** | Heuristic selector, no LLM | Placebo (§2.8) |

🟡 **RIGOR GAP — anonymization must be verified, not assumed.** Sector plus
QMJ/SUE/ERM values plus an exact month is frequently enough to re-identify a
mega-cap, and the candidate list itself is a fingerprint. Required: a
re-identification probe asking the model to name the anonymized security, with
the arm's validity reported as measured re-identification accuracy against
chance. If re-identification succeeds materially above chance, the arm does not
test what it claims and the mega-cap cells must be interpreted accordingly.

### 2.7 Outcomes: a two-stage estimand

The quantity the audience needs (a Sharpe discount) and the quantity the data
can measure precisely (a paired monthly effect) are not the same. We separate
them.

**Stage 1 — estimate where the power is.** $\beta_c$ from §2.2, on paired
monthly excess returns, with model and date fixed effects, two-way clustered
and block-bootstrapped. This is the inferential object; all significance claims
live here.

**Stage 2 — report where the audience is.** For each model and condition,
construct a de-contaminated series by removing the estimated effect from the
months the model had seen,

$$\tilde r^{\mathrm{AI}}_{m,d,c} \;=\; r^{\mathrm{AI}}_{m,d,c} \;-\; \hat\beta_c\,C_{m,d},$$

then report the absolute and percentage Sharpe discount

$$D_c \;=\; \mathrm{SR}\!\left(r^{\mathrm{AI}}_c\right) - \mathrm{SR}\!\left(\tilde r^{\mathrm{AI}}_c\right),
\qquad
D^{\%}_c \;=\; \frac{D_c}{\mathrm{SR}\!\left(r^{\mathrm{AI}}_c\right)} .$$

Construction is preferred to an analytic delta-method because removing the
effect from a *subset* of months changes the shape of the return series, not
merely its level, so the induced Sharpe change is **not**
$\hat\beta_c\sqrt{12}/\sigma$.

Report $D^{\%}_c$ as the primary headline: a percentage transfers across
strategies with different baseline Sharpes, whereas an absolute $0.3$ does not.

🟡 **RIGOR GAP — stage-1 uncertainty must propagate into stage 2.**
$\hat\beta_c$ is estimated with error and is then subtracted from many months
at once, so a plug-in interval on $D_c$ will be far too narrow. Required: a
single bootstrap that resamples rebalance months in blocks,
**re-estimates $\hat\beta_c$ inside every replicate**, and recomputes $D_c$ end
to end, reporting the percentile interval of the full pipeline. Do not
bootstrap stage 2 alone.

🔴 **DEFENSE — why not just difference the two Sharpes?** Because you cannot.
Monte Carlo on 5,000 simulated five-year daily paths gives an annualized Sharpe
standard error of $0.4478$ empirically against $0.4472$ from the Lo (2002)
formula

$$\operatorname{SE}\!\left(\widehat{\mathrm{SR}}\right) \;=\; \sqrt{\frac{1 + \tfrac{1}{2}\mathrm{SR}^2}{n}}$$

(`docs/audit/2026-08-25-hac-sharpe-validation.md`). A direct Sharpe difference
has essentially no power at any realistic sample length, which is exactly why
the estimand is split. Lead with this rather than waiting to be asked; it is
the strongest methodological justification in the paper.

**Co-primary — ex-post winner selection rate.** The fraction of a model's 10
picks falling in the top decile of realized forward return *within that month's
own 50-name candidate set*. A direct measure of the behavior contamination
should produce, with clean binomial variance, undiluted by position sizing or
by a given month's return dispersion. Under the null of no contamination the
expected count is

$$\mathbb{E}[\,\text{top-decile picks}\,] \;=\; 10 \times \tfrac{5}{50} \;=\; 1,$$

i.e. a rate of $0.10$.

**Secondary.**

- *Anachronism rate in rationales.* The agent emits a one-sentence rationale
  per pick; each is graded for reference to information dated after the as-of
  date. The interpretable, quotable detector — an explicit citation of a
  post-date event is a smoking gun rather than a statistical inference.
- *Sharpe with standard errors*, via `quant/metrics.py:compute_sharpe_stats`
  (Lo 2002), reported *with* the error bar precisely to demonstrate why it
  cannot carry the argument alone.
- *Turnover and concentration*, confirming arms do not differ mechanically.

🟡 **RIGOR GAP — three known-broken metrics are still in the pipeline.** From
this repository's own audit, unfixed: Sortino uses $\operatorname{sd}$ of
negative returns rather than target semideviation
$\sqrt{\mathbb{E}\!\left[\min(r - \mathrm{MAR},\,0)^2\right]}$ (§A2); Sharpe
subtracts no risk-free rate (§A3), material over 2018–2025 at 4–5%; and
"alpha" is an arithmetic spread $\bar r_s - \bar r_b$ rather than a
factor-model intercept (§A4). `three_series_eval.py` additionally applies no
transaction costs and no execution delay. Costs and delay difference out of
$\beta_c$ and are acceptable for the estimand, but every reported *level* is
gross and must be labeled as such. **Do not report Sortino at all until §A2 is
fixed** — it is not comparable to any external Sortino.

**Survivorship correction.** Candidate lists are rebuilt from point-in-time
index constituents rather than the current universe. Date fixed effects already
protect $\beta_c$ from this bias; the correction is required for reported
levels to mean anything. The pilot's deterministic-arm total return of 513.57%
against SPY's 140.81% is inflated by exactly this channel and is not reported
as a finding.

### 2.8 Falsification, placebo, robustness

**Monotonicity as internal falsification.** This is what the factorial buys
beyond a point estimate. If contamination is real, the standardized effect must
satisfy

$$\beta^{\ast}_{A3} \;<\; \beta^{\ast}_{A2} \;<\; \beta^{\ast}_{A1}
\qquad\text{and}\qquad
\beta^{\ast}_{B3} \;<\; \beta^{\ast}_{B2} \;<\; \beta^{\ast}_{B1}.$$

A flat, non-monotone or randomly ordered gradient is evidence that $\beta_c$ is
an artifact of $C_{m,d}$ capturing capability drift rather than outcome
knowledge. The design can visibly fail on its own terms — state the predicted
ordering in the pre-registration so the test is confirmatory.

This also converts a null into a publishable result: *the discount is bounded
above by $[D]$ even in the most contamination-favorable configuration we could
construct* is a finding. A single-condition null is merely an underpowered
study.

**Placebo.** The deterministic arm cannot be contaminated, so estimating the
primary specification on it must yield $\beta_c \approx 0$. A non-zero placebo
coefficient indicates that $C_{m,d}$ is capturing a calendar artifact and
invalidates the design.

**Additional robustness.** Regression discontinuity in a $\pm[k]$-month window
around each $\hat c_m$ (reported as a check, not the primary — monthly data
makes any usable bandwidth small); leave-one-model-out; cutoff sensitivity with
reported cutoffs substituted for estimated ones and $\hat c_m$ shifted
$\pm 3$ months; subsample stability excluding 2020, since a concentrated
10-name long-only book across March 2020 can dominate an otherwise quiet panel.

**Determinism.** All calls use temperature $0$ where the model accepts a
sampling parameter; several current models reject it and run at provider
default (`llm/providers.py`).

🟡 **RIGOR GAP — run-to-run variance is unmeasured and bounds everything.**
Temperature $0$ is not a determinism guarantee. Required: repeat each
configuration $[R]$ times and report within-configuration variance in selection
overlap and in $e_{m,d,c}$. That variance is the floor on the smallest
$\beta_c$ the design can detect and must be reported next to $\hat\beta_c$, not
buried. If verdict-level instability is high, no effect smaller than it is
claimable.

### 2.9 Power

The design is powered on the panel, not on Sharpe differences. With $M$ models
and $D$ rebalances per condition, and residual standard deviation
$\sigma_\varepsilon$ of the paired monthly excess return, the minimum
detectable effect at 80% power and 5% size is approximately

$$\mathrm{MDE} \;\approx\; 2.8\,\sigma_\varepsilon\,\sqrt{\frac{1}{N_{\mathrm{eff}}}},$$

where $N_{\mathrm{eff}}$ adjusts $M \times D$ for two-way clustering, for
serial correlation, and for the fact that only cutoff-straddling months
contribute.

🟡 **RIGOR GAP — no power analysis exists yet, and the panel cannot be sized
without one.** Required, in order: estimate $\sigma_\varepsilon$ from the
pilot's recorded responses; compute $N_{\mathrm{eff}}$ using the measured
holdings overlap from the gap flagged in §2.3; derive the MDE per condition;
and only then fix $M$, $D$ and $R$. Report the realized MDE beside
$\hat\beta_c$ in every results table. If the binary specification proves
underpowered, the dose-response of §2.4 — which uses all months rather than
only straddling ones — becomes the primary and the binary version demotes to
robustness.

### 2.10 Pre-registration

The analysis is pre-registered before the post-cutoff months accrue, which is
the one part of the sample the authors cannot inspect in advance. The
registration fixes: the model panel and the newer-but-weaker inclusion; the
cutoff-estimation procedure including refusal coding; the five factorial cells;
the primary, co-primary and secondary outcomes; the two-stage estimand and the
bootstrap; the predicted monotone ordering of §2.8; and the decision rule for
demoting the binary specification in favor of dose-response.

### 2.11 Reproducibility

Every model call is recorded and replayable offline: the eval harness stores
responses as cassettes and re-grades them without API access (`evals/`,
`docs/EVALS.md`), and runs are stamped with a configuration hash and git SHA
(`quant/config_hash.py`, `quant/git_sha.py`). Replay fans out one container per
rebalance date on Modal, failing loudly rather than silently falling back to
the heuristic selector — a silent fallback would manufacture a spurious
$\beta_c = 0$ (`modal_app/functions/ai_replay.py`).

Cost is not a barrier, and we state it to establish that the study is
replicable: the pilot's 84 calls cost on the order of USD 3–4; the full design
at $[M]$ models × 5 cells × prompt arms × $[D]$ dates × $[R]$ repeats is on the
order of $[\text{USD}]$, dominated by the recall probes rather than the
portfolio calls.

🟡 **RIGOR GAP — the pilot result is not currently reproducible from this
repository.** `runs/` is gitignored, so `runs/candidates/` and
`runs/ai_picks_llm/` — the inputs that produced the committed `latest.json` —
are not in version control, and `docs/eval/*/latest.md` is overwritten in place
rather than dated. Required before any external release: commit the candidate
and pick artifacts, freeze results under immutable dated paths, and remove or
qualify the auto-generated verdict strings in
`quant/three_series_eval.py:312`, which assert conclusions ("agents aren't
earning their cost") from a bare threshold on a quantity whose standard error
is $\approx 0.45$.

🔴 **DEFENSE — the repository contradicts itself on the front page.**
`README.md:211` describes OBV trend as *"Validated | Primary | only technical
signal with alpha"*; the re-judgment records `obv_trend` as **NO_SIGNAL at all
four horizons with a negative mean IC at 1M**
($\overline{\mathrm{IC}} = -0.0081$, bootstrap $p = 0.524$).
`NORTHSTAR.md:17` calls OBV "the sole
survivor." ERM is claimed at $\mathrm{IC} \in [0.04, 0.08]$ and measured at
$+0.0144$ to $+0.0263$ — overstated two to three times. The VIX-gating
"PBO 0%" claim survives on the front page after the audit established that the
PBO implementation is not the López de Prado statistic. A reader who goes
README → audit finds a signal asserted to work on page one and disproven on
page forty. Reconcile or mark superseded before showing this to anyone.

---

## 3. Results

`[TO BE FILLED]`

- **Table 1** — model panel; reported vs. estimated $\hat c_m$; knowledge-curve fit.
- **Table 2** — $\beta_c$ by factorial cell and prompt arm, raw and standardized ($\beta^{\ast}_c$).
- **Table 3** — Sharpe discount $D_c$ and $D^{\%}_c$, with full two-stage bootstrap intervals.
- **Table 4** — winner-selection rates by cell, arm and cutoff status, against the $0.10$ null.
- **Figure 1** — knowledge curves $k_m(d)$ by model, stratified by size tercile.
- **Figure 2** — event study: $\beta_c$ by distance to cutoff $d - \hat c_m$.
- **Figure 3** — the gradient: $\beta^{\ast}_c$ across the selectivity and salience ladders, with the predicted monotone ordering overlaid.

## 4. Discussion

`[TO BE FILLED]` — the discount a reader should apply to published LLM-trading
Sharpes and how it varies with design; whether guardrail prompting or entity
anonymization is a usable mitigation; and the implication that forward shadow
evaluation is the only fully valid protocol.

## 5. Limitations

- Effective cutoffs $\hat c_m$ are estimated, not known. The open-weights arm
  partially calibrates this; closed models remain inferred.
- One pipeline, one asset class, one selection task, long-only, monthly, US
  equities. The estimate is an effect size for this design; generalization is
  an assumption, which the factorial bounds but does not eliminate.
- The staircase design cannot detect a selectivity × salience interaction.
- The capability × recency confound is mitigated by the anonymization arm, the
  placebo and the newer-but-weaker model, but cannot be eliminated by design.
- Reported levels are gross of transaction costs and execution delay.
- Contamination is measured as it manifests in selection. A model may hold
  outcome knowledge it declines to act on — the probes detect this, the
  portfolio regression does not.

---

## Appendix A — What the pilot established

| Quantity | Value | Source |
|---|---|---|
| Replay window | 2018-02-01 → 2025-01-30, 84 monthly rebalances | `docs/eval/three_series_llm/latest.json` |
| $\mathrm{SR}(\text{SPY})$ | $0.74$ | same |
| $\mathrm{SR}(\text{deterministic})$ | $1.15$ | same |
| $\mathrm{SR}(\text{AI-augmented})$ | $1.01$ | same |
| $\Delta\mathrm{SR}$ (AI − deterministic) | $-0.14$ | same |
| $\operatorname{SE}(\widehat{\mathrm{SR}})$, 5y daily, true $\mathrm{SR}=1.0$ | $0.4472$ formula vs $0.4478$ empirical (5,000 paths) | `docs/audit/2026-08-25-hac-sharpe-validation.md` |
| Meta-model on AI picks, test AUC | $0.502$ | `models/ai_pick_meta.pkl.metrics.json` |

🔴 **DEFENSE — the pilot points the wrong way, and you must say so first.**
Contamination predicts the AI arm *over*-performs; it *under*-performed. The
pilot is therefore, if anything, weak evidence against a large contamination
effect in the A3 configuration — which is exactly what the selectivity ladder
predicts, since A3 leaves the least room. Frame it that way deliberately: the
pilot is the minimal-room cell of the factorial, observed in advance. Any
sentence that lets a reader believe $\Delta\mathrm{SR} = -0.14$ supports the
contamination hypothesis will be attacked, and correctly.

The $0.502$ test AUC is a secondary motivation: a gradient-boosted classifier
trained to predict whether an AI pick would beat its sector over 21 days
reached $0.89$ train AUC and $0.502$ test AUC — the selections carried no
learnable structure beyond the composite they were drawn from.

## Appendix B — Why the naive comparison fails

The naive statistic

$$t \;=\; \frac{\bar x}{s/\sqrt{n}},$$

applied to information coefficients sampled monthly from 12-month overlapping
forward returns, rejects a true null **59.3%** of the time at a nominal 5%
level. A correctly implemented Newey–West HAC statistic reduces this to 18.7%
but still over-rejects at realistic sample sizes; Monte Carlo calibration at
this study's exact sample geometry gives a 5% critical value of **3.08** at
$n = 96$, not $1.96$. Re-judging the signal roster under calibrated thresholds
reduced it from several signals significant at multiple horizons to two — QMJ
and SUE, at the one-month horizon only
(`docs/audit/2026-08-25-rejudge/rejudgment.md`) — and, as §2.1 notes, even
those do not survive correction for the size of the testing family.

This is the same failure mode the paper targets, one level up: a number
produced under an assumption that was never checked. The contamination estimate
is the assumption check that LLM-trading backtests currently lack.
