---
reviewer: The Prosecution
charge: "Build the strongest honest case to KILL or radically rescope it."
verdict: RESCOPE
provenance: "Subagent output, fresh context, reproduced verbatim. Citations unverified — the reviewer states its own Argument 2 rests on search summaries, not read papers. See README.md."
---

# PROSECUTION BRIEF — `docs/paper/2026-09-21-lookahead-contamination-abstract-methods.md`

**VERDICT: RESCOPE** — kill the paper *as drafted* (the Sharpe-discount DiD with the candidate-set factorial). A genuinely novel, deliverable ~8-page paper survives inside it, but it is about **selection behavior**, not about a Sharpe discount, and it is roughly 15% of the proposed scope.

I want to be clear that I am not reaching for RESCOPE to avoid a hard call. Two of the four attack lines I was handed (HARKing; no institutional access) fail on the evidence and I say so below. The two that land, land hard enough that the drafted paper cannot be written.

---

## Argument 1 — The design's minimum detectable effect is larger than the entire quantity being measured. This is arithmetic, not opinion.

The draft concedes at §2.9 that "no power analysis exists yet, and the panel cannot be sized without one." I did it. It fails.

Estimating σ_ε from the repo's own pilot (`docs/eval/three_series_llm/latest.json`): AI arm vol = 24.53/1.01 = 24.3% ann, deterministic arm = 29.61/1.15 = 25.7% ann. Both are 10-name equal-weight books drawn from the *same* 50-name list, so ρ is high; at ρ=0.95, sd(e) = 8.0% ann → **σ_ε ≈ 2.3%/month**; at ρ=0.90, σ_ε ≈ 3.3%/month. (Cross-check: pilot ΔReturn −5.08pp/yr = −0.42%/mo over 84 months gives t ≈ −1.5 at σ_ε = 2.5%, consistent with the observed null.)

Now the two-way-FE DiD. I built C_{m,d} for M models with cutoffs evenly spread over a D-month straddle window, applied the within transformation on model and date FEs, and computed SE(β̂) = σ_ε/√Var(C̃), at σ_ε = 2.5%/mo:

| M models | D straddle months | SE(β̂) %/mo | **MDE₈₀ %/mo** | MDE in ann. pp |
|---|---|---|---|---|
| 6 | 24 | 0.74 | **2.07** | 24.8 |
| 8 | 30 | 0.57 | **1.59** | 19.1 |
| 12 | 36 | 0.42 | **1.17** | 14.1 |
| 20 | 36 | 0.32 | **0.91** | 10.9 |

A 30-month straddle window is already optimistic: usable cutoffs today run from roughly late-2023 open-weights to the ~May-2026 frontier, and `modal_app/functions/ai_replay.py:51` shows the pilot ran `claude-opus-5`, whose entire replay window is pre-cutoff.

Translate the MDE into the paper's own headline units. At the AI arm's 24.3% vol, **1.59%/month = 0.78 Sharpe points**. The study's realistic best case can only detect a contamination effect that would wipe out ~77% of the AI arm's Sharpe of 1.01. A 0.1–0.3 Sharpe discount — the range the abstract says readers need ("whether to subtract 0.05 or 0.8") — is 0.20–0.62%/month, i.e. **3× to 8× below the MDE**.

And that table is the *ceiling*, computed under assumptions the draft itself says are false:
- iid errors — §2.3 RIGOR GAP admits `e_{m,d,c}` is serially correlated because QMJ/SUE/ERM are persistent and holdings overlap. N_eff < N.
- no clustering penalty — treatment is assigned at the **model** level, so the binding cluster dimension is G = M ≈ 6–8. Cluster-robust inference at 8 clusters is not approximately valid; t₍.₉₇₅₎ at df=7 is 2.36, not 1.96, and wild-cluster bootstrap behaves poorly below ~15 clusters.
- one repeat — §2.8 RIGOR GAP admits run-to-run variance is unmeasured and "bounds everything." Whatever it is, it adds to σ_ε.
- σ_ε = 2.5% rather than 3.3%.
- **the whole budget in one cell.** The factorial splits it across 5 cells × 2–4 prompt arms. Each β_c gets a fraction of the above.
- **the monotonicity falsification test is the worst case of all.** §2.8 makes β*_{A3} < β*_{A2} < β*_{A1} the internal-validity linchpin. That is a test on *differences between three estimates each with SE ≈ 0.6%/mo*. Its power is essentially zero. The design's own falsification test cannot fire.

The draft's escape hatch — "a null converts to *the discount is bounded above by [D] even in the most contamination-favorable configuration*" — does not work either. The upper CI bound would be ≈ +1.6%/month ≈ **+0.8 Sharpe**. "Contamination inflates Sharpe by at most 0.8" is a bound looser than the prior, and looser than point estimates already in print (Argument 2). That is not a publishable null; it is an expensive restatement of ignorance.

The cruel irony: the draft's single best methodological move — §2.7's "you cannot difference two Sharpes, SE ≈ 0.4478" — is correct, is verified in `docs/audit/2026-08-25-hac-sharpe-validation.md`, and is the reason the panel estimand exists. But the panel estimand inherits the same problem one level down. Splitting the estimand relocated the power failure; it did not fix it.

---

## Argument 2 — The gap the abstract claims does not exist. The literature review has not been done, and the specific deliverable is already in print.

The abstract asserts: *"The field acknowledges this in limitations sections but has no estimate of its magnitude, so a reader cannot discount a published result by any principled amount. We supply that estimate."* §1 cites only two generic literatures ("financial econometrics" and "n-gram overlap contamination detection") and claims "neither transfers."

That is false as of today. Searching the obvious terms returns, among others:

- **Li & Zeng et al., "Profit Mirage: Revisiting Information Leakage in LLM-based Financial Agents"** (arXiv 2510.07920, Oct 2025; FinLake-Bench). Reports exactly the draft's stated primary headline D^%_c: **Sharpe decay across the knowledge cutoff of 51.48% (QuantAgent) to 62.23% (FinCON); total-return decay 50.18% (TradingAgents) to 71.85% (FinMem)**, framed as "dazzling back-tested returns evaporate once the model's knowledge window ends." The draft says "Report D^%_c as the primary headline: a percentage transfers across strategies." That number has been published for eleven months.
- **Gao, Jiang & Yan, "Detecting Lookahead Bias in LLM Forecasts"** (arXiv 2512.23847 / SSRN 5985277, Dec 2025). Their **Lookahead Propensity (LAP)** is the draft's §2.4 knowledge curve k_m(d), built the same way (date-only recall query on a firm-date pair), shown to be "materially positive throughout the in-sample period and collapse essentially to zero right after the training-data cutoff," and used in an interaction regression — i.e. the draft's dose-response specification.
- **"Look-Ahead-Bench: a Standardized Benchmark of Look-ahead Bias in Point-in-Time LLMs for Finance"** (arXiv 2601.13770, Jan 2026; code at github.com/benstaf/lookaheadbench). End-to-end **agentic trading workflows**, alpha-decay measurement across memorized vs unseen regimes, with quantitative baselines as thresholds. This is the draft's pipeline design, benchmarked.
- **"HindsightBench: A Black-Box Behavioral Audit Protocol for Parametric Hindsight in Time-Indexed LLM Decision Tasks"** (arXiv 2607.18867, Jul 2026). **15 models from seven vendors.** Its six per-model metrics include "**behaviorally effective knowledge cutoff**" (= the draft's ĉ_m), "**post-cutoff placebo**" (= §2.8's placebo), "**outcome recall**" probes (= §2.4), and a recall-accuracy dissociation coefficient (= the draft's "gap between having and using the information… is itself a result"). At probe-level cost, no backtests.
- **Cross-Model Memorization Disagreement (CMMD)**, which "exploits naturally occurring variations in training cutoffs across multiple LLMs as a control group" — the draft's core identification strategy, already used and published.
- **Glasserman & Lin (arXiv 2309.17322, 2023)** — the anonymization arm (§2.6), already done, with the important finding that the **distraction effect dominated look-ahead bias** (see Argument 3).
- **"All Leaks Count, Some Count More"** (2602.17234), **"Summoning the Oracle to Slay It"** (2605.24564), **"A Fast and Effective Solution to the Problem of Look-ahead Bias in LLMs"** (2512.06607), **MemGuard-Alpha** (2603.26797), **"Debiasing LLMs by Fine-tuning"** (2604.02921), **Chronologically Consistent LLMs / ChronoBERT-ChronoGPT** (2502.21206), and commercial point-in-time model serving (PiT-Inference).

Two consequences.

**(a) The contribution claim cannot be made.** A referee who spends ten minutes on Google Scholar finds a published Sharpe-discount percentage, a published cutoff-estimation probe, a published cross-model-cutoff control design, and a published anonymization arm. The draft does not cite any of them. A submission whose stated gap is refuted by the fourth search result does not survive desk review, regardless of how careful the internals are.

**(b) The practitioner question is closed, and the author closed it himself.** `README.md:235-253`:

> *"No prompt guardrail can remove knowledge baked into the model weights, so a historical replay systematically overstates AI value… The honest measurement of AI value over the quant baseline is **forward shadow mode**… Post-training-cutoff replay months are the only trustworthy historical window."*

That is the operational answer, written on this repo's front page, and it is **invariant to the magnitude**. §4 of the draft says the Discussion will conclude "forward shadow evaluation is the only fully valid protocol" — the paper's conclusion is already the repo's stated policy and does not depend on β. Meanwhile the field is shipping chronologically-consistent models, which makes the number a dated artifact of the 2023–2026 model generation rather than a durable constant. The abstract's pre-rehearsed defense ("obviousness is not a magnitude") answers the wrong objection: the objection is not that it's obvious, it's that the decision rule does not change across the plausible range of the answer.

---

## Argument 3 — The identifying assumption is defeated by a confound the draft does not name, and published evidence already contradicts it.

The draft flags the capability×recency confound (§2.2 DEFENSE) and proposes one mitigation: include a "newer but weaker" model. That is one unit in a panel of six to eight, and "weaker on general benchmarks" is not "weaker at constrained 10-of-50 portfolio selection." It does not break the collinearity; it perturbs it.

But there is a larger, unnamed confound that runs in the same direction as the hypothesis:

**Entity unfamiliarity on post-cutoff candidate lists.** For d > ĉ_m, the 50-name list contains companies a 2023-cutoff model has never encountered — new index entrants, IPOs, ticker changes, renamed entities. Its selection degrades for reasons that have nothing to do with outcome knowledge. This is precisely Glasserman & Lin's **distraction effect**, and their headline result is that **it was larger than look-ahead bias** in their setting. β̂_c therefore mixes contamination with entity familiarity, with the same sign. The anonymization arm cannot separate them: it strips entity information from pre- *and* post-cutoff months symmetrically, so it removes the contrast rather than isolating it. The draft's §5 limitation says the capability confound "is mitigated by the anonymization arm, the placebo and the newer-but-weaker model" — the anonymization arm does not mitigate it.

Three further cracks:

1. **ĉ_m is not a stable object.** The repo pins `claude-sonnet-4-20250514` but also calls floating `claude-opus-5` (`llm/providers.py:40-53`, `modal_app/functions/ai_replay.py:51`). Models are updated in place under one API string; post-training adds recent data; several models in the harness already reject `temperature` and run at provider default. ĉ_m estimated in month 1 need not equal ĉ_m in month 6, and the treatment variable is a function of it.
2. **Refusal bias is not fixable by sensitivity analysis.** §2.4 flags it, but the proposed remedy — code refusals separately, report both codings — yields a *bracket*. If refusal rates correlate with provider **and** with recency (they do), the bracket on ĉ_m will be wider than the ±3-month shift the draft treats as its robustness range, and therefore wider than the effect.
3. **HindsightBench's published finding is the counter-hypothesis, empirically confirmed.** Its headline: the date-trigger reflex "tracks training **generation**, not scale — absent across the 2024 open-weight generation from 1B to 70B, present in every 2026-generation model tested down to 3B active parameters, and switching on within a single vendor lineage." That is direct evidence that temporal-reasoning behavior is a discontinuous *generational* artifact confounded with cutoff. A referee will cite it against §2.2, and the "newer but weaker" model does not answer it, because generation — not size — is the confounding variable and it is exactly what cutoff indexes.

**Supplementary (Stage 2 is unsound independently of β).** The de-contaminated series r̃ is built on levels the repo itself disclaims. `README.md:240-243` admits candidate lists were built from the *current* WRDS PIT universe and already contain APP, SMCI, AXON; `quant/fundamentals.py` still carries live comments reading `# as_of_date ignored — FMP cache is a static snapshot (no point-in-time)` — the session-4 **[CRITICAL] B5** finding is unfixed as of this commit. The draft is right that date FEs protect β̂ from these. It does not follow that D_c and D^%_c are interpretable: they are a percentage of a Sharpe the repository says is "an upper bound, not a measurement." A paper about look-ahead contamination whose instrument has admitted uncorrected *data* look-ahead invites the obvious review comment, and the obvious comment is correct about the deliverable even though it is wrong about the estimand.

---

## Two attacks I was asked to make that I cannot honestly make

**HARKing.** The draft handles it better than most published work. §1 DEFENSE discloses the sequence in plain language, and the §2.10 pre-registration binds before the post-cutoff months physically exist — that confirmatory sample is genuinely unavailable to inspect. Appendix A goes further and volunteers that the pilot runs *against* the hypothesis (contamination predicts over-performance; the AI arm under-performed by 0.14 Sharpe) and instructs the author to say so first. I cannot find a stronger disclosure protocol to demand.

**No institutional data access.** `quant/wrds_store.py`, `docs/paper/PLAN_WRDS_INTEGRATION.md`, `PLAN_WRDS_DATA_EXPANSION.md` and `README.md:241`'s "current WRDS PIT universe" show WRDS access, which implies affiliation. Data access is not the binding constraint; power is. And `git log --format=%an` showing 164/183 commits from one author is normal for a first-year project, not a defect.

**One thing I will press that is neither of those:** the repository's front page is, today, inconsistent with its own August audit. `README.md:211` lists **OBV trend | Validated | Primary | "only technical signal with alpha"** and `NORTHSTAR.md:17` calls OBV "the sole survivor," while `docs/audit/2026-08-25-rejudge/rejudgment.md` records `obv_trend` as **NO_SIGNAL at all four horizons**, mean IC −0.0081 at 1M, MBB p = 0.524. NORTHSTAR claims ERM IC 0.04–0.08; measured +0.0144 to +0.0263. NORTHSTAR claims "VIX 30/40… Sharpe 1.04, **PBO 0%**" after session-4 **[CRITICAL] A5** established `compute_pbo` is not the López de Prado statistic and is undefined for a single configuration. And I verified the draft's own multiple-testing claim directly from `rejudgment.json`: across m = 44 signal × horizon tests, the smallest MBB p is 0.0075 against a BH rank-1 threshold of 0.05/44 = 0.00114 — **zero survive BH at α = 0.05, and the draft's §2.1 says so honestly.** The draft is more rigorous than the repository it sits in. That gap is the credibility risk, and §2.11's DEFENSE already names it. It is a one-hour fix and it should happen before anything is shown to anyone.

---

## If RESCOPE: the specific smaller thing that IS worth doing

**Drop:** the Sharpe discount D_c / D^%_c, the two-stage estimand, the full two-stage bootstrap, the 5-cell factorial, the monotonicity falsification test, and the phrase "difference-in-differences." All of them are downstream of a β̂ the design cannot resolve.

**Keep, and make the whole paper:** the draft's own *co-primary* outcome, which is the only quantity in it with real power.

**Paper: "Do LLMs over-select ex-post winners from months inside their training data?"**

1. **Outcome: ex-post winner-selection rate.** Fraction of a model's 10 picks landing in the top decile of realized forward return *within that month's own 50-name candidate list*. Sharp binomial null: E = 10 × 5/50 = 1, rate 0.10. This strips out return magnitude — the entire source of the σ_ε = 2.5%/month noise floor that kills Argument 1's regression. With M ≈ 8 models × D ≈ 30 straddle months × 10 picks = 2,400 Bernoulli draws per condition; clustering by (model, month) gives 240 clusters, and at a within-month design effect of 3–5 the effective SE on the rate is ≈ 1.1–1.3pp. **That detects 0.10 → 0.13, versus the return regression's 0.78-Sharpe floor.** Report the clustered rate, not the naive binomial SE — the design effect must be measured, not assumed.
2. **Co-outcome: anachronism rate in rationales.** The agent already emits one sentence per pick. Grade each for reference to post-as-of-date information. Interpretable, quotable, cheap, and a direct smoking gun rather than a statistical inference. This is the most under-weighted item in the draft — it is listed as "secondary."
3. **One cell, not five.** The hinge cell (A1/B2, random 50 from the 495 panel) maximizes room for look-ahead and is the cheapest to build. Two prompt arms — base and anonymized — not four.
4. **Cite the field.** Position against Profit Mirage / Look-Ahead-Bench / LAP / HindsightBench explicitly, and make the honest, defensible novelty claim, which is this: **existing work compares pre-cutoff to post-cutoff calendar periods, confounding contamination with market regime; this design holds the candidate list, the month, and the deterministic benchmark fixed and varies only which model is looking.** That is a real methodological improvement and it is small enough to be true.
5. **Start the forward shadow log this week.** Zero marginal cost, `README.md:250` already commits to it, and it is the one series nobody can scoop. Be honest in writing that it is *not* the paper: at σ_ε = 2.5%/month, detecting a 0.5%/month effect at 80% power needs ≈ 196 months. It is a decade-scale asset, not a result.
6. **Before any of it:** reconcile `README.md:211` / `NORTHSTAR.md:17` with `rejudgment.md`, and commit `runs/candidates/` + `runs/ai_picks_llm/` under dated immutable paths (§2.11 RIGOR GAP — `runs/` is at `.gitignore:39`, so the pilot is currently unreproducible). Also delete the auto-generated verdict string at `quant/three_series_eval.py:312-318`, which prints "agents aren't earning their cost" from a bare ±0.10 threshold on a statistic with SE ≈ 0.45.

Target: a workshop paper or a short methods note. Not a job-market paper.

---

## The single strongest argument for pursuing that I could NOT defeat

**The published magnitudes are measured under a design that confounds contamination with market regime, and this design does not.** Profit Mirage's 51–62% Sharpe decay, and Look-Ahead-Bench's alpha decay, both compare a model's performance in a *pre-cutoff calendar period* against a *post-cutoff calendar period*. Those are different markets. 2019–2023 and 2024–2026 differ in dispersion, breadth, factor payoffs and concentration; a large part of the reported "decay" may be regime, not memory. Nobody has cleanly separated them.

The draft's core move genuinely does. Within a single month, with a single fixed 50-name candidate list, with a deterministic selector drawn from that identical list as the within-month benchmark, the *only* thing varying across models is whether that month is inside their training data. Date fixed effects absorb regime, survivorship in the candidate list, and the screener's own time-varying quality — all of which are common to every model at date d. That is a structurally better instrument than what is in print, and the §2.7 justification for why the estimand must be split (grounded in the repo's own verified Monte Carlo, `docs/audit/2026-08-25-hac-sharpe-validation.md`: 0.4478 empirical vs 0.4472 Lo formula) reflects better statistical judgment than most of the papers it would be competing with.

My answer is only that the instrument is too blunt for the effect at the return level — which is a power argument, not a design argument. It is why my verdict is RESCOPE and not KILL: move the same clean identification onto the winner-selection rate, where the noise floor is 20–40× lower, and the design's real advantage survives.

---

## What would change my verdict

**To PURSUE the paper roughly as drafted, I would need any one of:**

1. **A power analysis that beats my table.** Specifically: measured σ_ε from the pilot's recorded per-month `e_{m,d}` (not my ρ-based reconstruction — `latest.json` stores only summary stats, and `runs/` is gitignored, so nobody can currently check this), measured month-to-month holdings overlap and N_eff per §2.3, measured run-to-run variance per §2.8, and a realized MDE below **0.6%/month** in at least one cell. If σ_ε turns out to be ~1%/month because the AI and deterministic books overlap far more than I assumed (ρ > 0.98), the whole first argument collapses and I would switch to PURSUE. **This is one afternoon's work on data the author already has, and it should be done before anything else in this brief is acted on.**
2. **A model panel of M ≥ 20 with genuinely spread, independently verified cutoffs** — e.g. by leaning on open-weights families with inspectable corpora, which also fixes the ĉ_m-stability problem and gives ≥ 20 clusters for inference. M = 20 / D = 36 gets the MDE to 0.91%/mo; still not to 0.3, but it changes the conversation.
3. **A documented literature search that I am wrong about** — i.e. that Profit Mirage's 51–62% figure is confined to a setting (news-sentiment day-trading agents on a handful of tickers) narrow enough that a portfolio-selection estimate is a distinct contribution, *and* that the draft says so in §1 with citations. I could not verify the internals: arxiv.org, lookaheadbench.com, themoonlight.io and awesomepapers.io are all blocked by this environment's egress proxy, so **my Argument 2 rests on search-result summaries, not on reading the papers.** That is the weakest evidentiary link in this brief and the author should check it before conceding to it.

**To move me to outright KILL:** if (1) comes back with σ_ε ≥ 3%/month *and* the winner-selection rate's within-month design effect proves large enough to push its effective SE above ~2pp, then nothing in the draft is deliverable at any budget the author has, and the correct output is the forward shadow log plus the README reconciliation — no paper this year.

**One thing that would not change my verdict:** adding cells to the factorial, or lengthening the replay window backwards. §2.2's own DEFENSE is correct that neither creates identifying variation, and the draft deserves credit for already knowing it.

---

## Postscript added by the orchestrating session

The reviewer's condition (1) was executed after this brief was filed, using
`docs/eval/three_series_llm/daily_returns.csv`, which is committed even though
`runs/` is not. Measured: ρ = 0.960 monthly, **σ_ε = 2.103 %/month**, lag-1
autocorrelation of `e` = +0.077.

This is *below* the 2.5 %/month the brief assumed but well above the ~1 %/month
its collapse condition required (ρ > 0.98). The MDE table rescales to 0.68
Sharpe at M=8/D=30 and 0.38 at M=20/D=36 — still 3–8× above the middle of the
range the abstract says readers need. **Argument 1 survives**, slightly softened.

One assumption in the brief is measurably wrong in the design's favor: the
serial-correlation deflation of `N_eff` is small, not large (lag-1 = +0.077).
See `README.md` in this directory and `power-analysis.py`.
