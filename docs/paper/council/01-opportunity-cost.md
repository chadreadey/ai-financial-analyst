---
reviewer: Opportunity Cost Advisor
charge: "Is this the best use of the next several weeks, against the alternatives already in this repo?"
verdict: RESCOPE
provenance: "Subagent output, fresh context, reproduced verbatim. Citations unverified — see README.md."
---

# Opportunity-Cost Review — ai-financial-analyst

## VERDICT on the contamination paper: **RESCOPE**

Not kill. The design document is the best thing in the repository and the question is real. But as scoped it is a 3–6 month project with a $500–3,000 compute bill, a dependency on data that is not in the repository, and one inference problem the draft has not noticed that no amount of effort fixes. It cannot produce the stated deliverable — a short research presentation in the next several weeks — and two things sitting in the same repo can.

Rescope to: **write and timestamp the pre-registration now (cheap, and the only asset here that gets more valuable with delay), execute the knowledge-curve probe (§2.4) as a standalone result, and defer the portfolio DiD until the probe and a real power calculation say it is worth it.**

---

## First, a correction to the brief's premise

The brief says the study "requires waiting for post-training-cutoff months to accrue, which has a hard time floor independent of effort." **That is mostly wrong, and the paper's own §2.2 says why.** Identification comes only from cutoff-straddling months, `min_m ĉ_m < d ≤ max_m ĉ_m`. A panel spanning a 2023-vintage model to `claude-opus-5` (already the default in `modal_app/functions/ai_replay.py:51`, knowledge cutoff May 2026) gives roughly **30 straddling months that already exist today**. The identifying variation is available now.

What *does* have a calendar floor is narrower: the clean `C = 0` anchor (months after `max_m ĉ_m` — currently about four) and the genuinely-prospective confirmatory sample the pre-registration buys. So the sequencing argument is not "wait for the calendar." It is "the expensive part is expensive, and the cheap part is time-sensitive."

---

## The finding the draft missed, which drives my verdict

`C_{m,d} = 1[d ≤ ĉ_m]` is a **model-level treatment**. It varies across `m` only through `ĉ_m`. With model fixed effects `γ_{m,c}` absorbing each model's level, `β_c` is identified purely off between-model variation in cutoff timing — so **the effective number of treatment-assignment clusters is M ≈ 6–8, not M × D ≈ 300**.

Two-way clustering (§2.7 stage 1) with 7 clusters on one dimension is badly undersized; wild cluster bootstrap is fragile below ~12 clusters and its refinements are unreliable in exactly this range. The draft's power section (§2.9) computes an MDE from `N_eff` adjusted for serial correlation and straddling months but never confronts the cluster count. More dates, more cells, and more repeats do not fix it. Only more *models with distinct cutoffs* do — and every extra model tightens, not loosens, the capability×recency confound the draft already concedes it "cannot eliminate by design" (§5).

That is the argument I would press hardest in a defense, and the draft has no answer prepared for it. It is the difference between PURSUE and RESCOPE.

## Two secondary blockers, both verified

**The pilot's inputs do not exist in this checkout.** `runs/` is gitignored (`.gitignore:39`) and absent from disk, and so is `.wrds_pit.db`. The 84 candidate lists and the LLM picks behind `docs/eval/three_series_llm/latest.json` are gone. §2.9 requires estimating `σ_ε` "from the pilot's recorded responses" — those responses are not available, so the power analysis that gates panel sizing needs a replay run before it can even start. The draft flags the reproducibility half of this (§2.11 rigor gap) but not that it blocks its own critical path.

**Survivorship correction is unbounded.** §2.7 requires point-in-time index constituents. This has been an open caveat since `docs/PHASE_1_5_REVIEW_2026_07_20.md` ("Known caveats", filed for the next audit), is re-flagged as B6 [HIGH] in `docs/audit/session-4-statistical-rigor/README.md`, and depends on WRDS access — an institutional subscription tied to student status, i.e. outside their control and with an expiry date.

---

## Ranked alternatives

### 1. The statistical-hygiene case study — **already finished; 3–5 days to a presentation**

This is the highest-value item and it requires no new data, no API spend, and no experiment.

What exists, complete and validated:
- `/home/user/ai-financial-analyst/docs/audit/2026-08-25-hac-sharpe-validation.md` — 3,000-path Monte Carlo showing the harness's naive t-statistic rejects a true null **59.3%** of the time at nominal 5% under 12M/1M overlap; correct HAC still rejects 18.7%; longer lags do not help (18.4% at lag 18, 20.6% at lag 24). Calibrated critical values by `n` × overlap (**3.08** at n=96, overlap 12, against 1.96). Cross-checked against statsmodels to ~9e-16.
- `/home/user/ai-financial-analyst/docs/audit/2026-08-25-rejudge/rejudgment.md` — the full 11-signal × 4-horizon before/after roster. Of 44 tests, **two** survive (QMJ and SUE, 1M only), and as the paper's own §2.1 notes, **zero survive Benjamini–Hochberg at α = 0.05 or 0.10 and zero survive Bonferroni** (rank-1 BH threshold ≈ 0.0011 vs QMJ's p = 0.0075).
- Working code: `quant/ic_stats.py:174` (`ic_summary`), `scripts/rejudge_ic_signals.py:50` (`mbb_pvalue`), `quant/metrics.py:181` (`compute_sharpe_stats`, Lo 2002).

Time to credible result: **zero — the result is done.** 3–5 days to build three figures (rejection rate vs. overlap; the calibrated critical-value surface; the before/after roster) and a talk.

Probability of a presentable outcome: ~99%. Dependencies: none. Degrades gracefully: there is nothing to fail.

What it demonstrates: that this person checked the size of their own test statistic, found it was garbage, and let it destroy a signal roster they had spent months building. Professors respond to that more strongly than to almost anything else a student can show them. It also pre-empts the first question any quant-adjacent professor asks about the contamination paper — "what are your standard errors doing?" — with a measured answer.

Honest limitation, state it in the talk: small-sample HAC over-rejection is known (Kiefer–Vogelsang, Andrews). The contribution is not the phenomenon; it is the calibration **at this exact sample geometry** plus the demonstrated consequence on a real roster. That is a case study, not a methods paper, and it is exactly the right size for a short presentation.

### 2. The judge-free agent evaluation — **2–3 weeks to a genuine empirical result**

The methodological claim in `/home/user/ai-financial-analyst/docs/EVALS.md` §1 is sound and well-argued: `prompts/synthesis.md` specifies a *procedure* (copy `SIGNAL_SCORE` verbatim, multiply by fixed weights, apply the 0.7 macro multiplier, threshold to a verdict), so given the inputs the correct verdict is computable by `evals/contracts.py:ExpectedDecision.from_signals`. No human labels, no LLM judge, no judge variance to debug.

What exists: 54 grader functions in `evals/checks.py`, contract constants parsed *out of the prompt markdown* and cross-checked against three implementations in `tests/test_evals_contracts.py`, cassette record/replay, `evals/gates.json` merge gating, and mutation tests in `tests/test_evals_checks.py` that break one thing at a time and assert exactly one check fires.

What does not exist: **11 cases total** (`evals/cases/*.jsonl`), **2 cassettes**, no `evals/baselines/`, no multi-model run. The methodology is far ahead of the dataset. That gap is the project.

The work: expand to ~50 cases, run 6–8 models (including cheap and open-weights ones) at `--repeats 5`, and report a model × check matrix. Cost: roughly $50–150, versus $500–3,000 for the contamination design. Time to result: 2–3 weeks. Probability of something presentable: ~90%, and a null is publishable ("frontier models conform at >98%; the interesting variance is elsewhere").

The two sharpest measurements are already specified and unbuilt:
- **Faithfulness** (§3.2): did the model copy the supplied `SIGNAL_SCORE` or silently re-derive it from prose? The right answer is printed in the input. That is about as clean an instruction-following probe as exists.
- **Fabrication under withheld inputs** (§3.3): strip the balance-sheet lines needed for a Beneish M-Score and assert `null` comes back rather than an invented number. Domain-relevant and quotable.
- Plus **run-to-run variance at temperature 0** (§3.5), which is not a bonus — see sequencing below.

Novelty, honestly: "programmatic grading beats LLM judges when ground truth is computable" is not new in general. What is defensible is narrower and still interesting — an entire *production* financial-analysis agent whose prompts happen to be written as procedures, therefore gradeable end to end without labels, plus the prompt/code drift test that parses the decision table out of the markdown and forces three implementations to agree. Frame it as an experience report and it holds up. Frame it as a methods contribution and a referee will push back.

This is also the most transferable thing on the list. "I built a label-free, judge-free eval harness for an LLM agent system and measured eight models on it" is a more employable sentence than anything else in this repository.

### 3. Forward shadow mode — **start it this week; harvest in 12–24 months**

`README.md:251` already states the correct position: "The honest measurement of AI value over the quant baseline is forward shadow mode: LLM picks recorded at rebalance time from now on, scored against the quant-only series as real time passes." `plans/PLAN_TWO_STAGE_PIPELINE.md` Phase 6 specifies `quant/shadow_tracker.py` at ~3 hours of work, and `backend/paper_scheduler.py` already runs a monthly cron with a documented fail-closed safety model.

Time to a Sharpe-level claim: 12–24 months minimum. The repo proved why — Lo (2002) SE on a five-year daily Sharpe is 0.45, so a ±0.3 difference is noise. The better-powered outcome is the winner-selection rate (binomial, null = 0.10), and that still wants ~24–36 rebalances.

So this is not a presentation. It is 1–2 days of work and ~$4/month that starts a clock, and it makes *either* of the two talks above land better: "here is the measurement problem, here is the only uncontaminated instrument, here is the date I started it." Not starting it this week costs a month of data that can never be recovered.

### 4. Contamination study, rescoped to the knowledge-curve probe — **1 week, standalone result**

§2.4 does not need portfolios, the DiD, the factorial, the two-stage estimand, or the cluster-count problem. It needs a grid of (ticker, month) pairs, a recall question per pair, and scoring against realized data, producing `k_m(d)` per model. It is the paper's **Figure 1**, it is the most visually compelling artifact in the whole design, and it stands entirely alone: *here is empirically where each model's knowledge of the market ends, and it is not where the model card says it is.*

It also resolves the paper's own gating uncertainty. Do the two validity holes the draft already names (refusal ≠ ignorance, `k_m(d)` confounded with market cap) actually sink it? Does the curve separate cleanly enough for a dose-response? Those are answerable in a week for a couple hundred dollars, and the answer determines whether the full study is worth three months.

### 5. Fix the known-broken internals — **a mandatory 3–5 day subset, not a project**

Not a presentation, but part of it is not optional. In priority order:

- **`README.md:211` and `NORTHSTAR.md:17` are contradicted by this repository's own committed data.** The README calls OBV trend "Validated | Primary | only technical signal with alpha"; NORTHSTAR calls it "the sole survivor." The re-judgment records `obv_trend` as **NO_SIGNAL at all four horizons**, mean IC −0.0081 at 1M, bootstrap p = 0.524. ERM is claimed at IC 0.04–0.08 and measured at +0.0144 to +0.0263. The "PBO 0%" claim survives on the front page after A5 [CRITICAL] established that `compute_pbo` is not the López de Prado statistic. **Fix this before showing the repo to anyone.** It costs an hour and it is the single highest-risk item in the entire inventory — a professor who reads page one and then page forty stops evaluating the work and starts evaluating the author.
- A2/A3/A4 in `quant/metrics.py` (Sortino uses `std` of negative returns; Sharpe subtracts no risk-free rate; "alpha" is an arithmetic spread) — required before *any* reported level means anything, in any of these projects.
- D1 [CRITICAL] in the session-4 audit: `context_budget.trim_text` keeps the prefix, and the DCF/Earnings/Competitive prompts put `SIGNAL_SCORE` at the end — so synthesis frequently reasons on prose while the scores it is instructed to trust have been truncated away. This one also *contaminates the eval project*, because it means the production path and the eval path may not be measuring the same thing.
- `quant/three_series_eval.py:312` auto-generates verdict strings ("agents aren't earning their cost") from a bare ±0.10 threshold on a quantity whose standard error this repo measured at ≈0.45. Delete or qualify.

### 6. Ship the product — **wrong target for the stated goal**

The README describes it as live on Vercel + Railway. But per D1 above, the deployed system emits verdicts through a synthesis step that may not be seeing its own inputs, and `docs/EVALS.md` §6.1 reports that with `enable_macro_agent` off the weight table covers 0.88 rather than 1.0, compressing every weighted score toward zero and biasing every verdict toward HOLD. Building more product on that is building on sand. More to the point: a professor does not grade a web app. Ranked last **for the stated goal only** — if the goal changes to "show an employer," it moves up sharply.

---

## Recommended sequence

**Days 1–2**
Reconcile `README.md:211` / `NORTHSTAR.md:17` against `docs/audit/2026-08-25-rejudge/rejudgment.md`, or mark both superseded. Stand up shadow mode on the existing monthly cron so the clock starts. Write and timestamp the §2.10 pre-registration — it is a document, it costs nothing, and it is the one asset that strictly appreciates with delay.

**Days 3–8 — this is the presentation**
Build the statistical-hygiene talk from artifacts that already exist. Three figures, fifteen minutes, one sentence of thesis: *the number that selected my signals had a 59.3% false-positive rate, and when I fixed it, nothing survived.* Ship this before starting anything new. It is the only item on the list with essentially zero execution risk, and having a finished talk in week one changes the risk profile of everything after it.

**Weeks 2–4 — the paper**
Judge-free eval: expand 11 → ~50 cases, run 6–8 models × 5 repeats, produce the model × check matrix and the temperature-0 variance floor. This becomes talk v2 and the write-up.

**Weeks 3–5, parallel**
Knowledge-curve probe. One week of work. It is a slide in either talk and the gate on everything below.

**Month 2+, decision point**
Revisit contamination holding four things the study currently lacks: a measured `σ_ε`, a measured `k_m(d)`, a measured run-to-run variance, and an honest cluster-count-aware power calculation. Decide then, with numbers instead of intentions.

**The sequencing is not a compromise.** Three of the contamination study's seven open rigor gaps are closed as by-products of work that is worth doing anyway: run-to-run variance (§2.8) is `--repeats N` in the eval project; the moving-block bootstrap and `N_eff` (§2.3) reuse `scripts/rejudge_ic_signals.py:50`, which the stats talk forces you to re-read; and the probe validity holes (§2.4) are what the week-4 probe exists to resolve. Nothing here is abandoned. It is reordered so that the cheap, certain results land first and the expensive, uncertain one starts from measured inputs instead of placeholders.

---

## The strongest argument for just doing the contamination paper, which I could not defeat

It is the only item on this list that is a **research question**. The statistics case study is a replication of known small-sample HAC behavior on one person's data. The eval study is an experience report on a benchmark built from one person's own prompts. Both are excellent craft and neither asks anything nobody knows.

The contamination study asks something nobody has answered and attaches a number a reader would actually use. If the goal is to get a professor to say "this is a research project I would supervise," it is the only one where the professor's response is about *the question* rather than about the workmanship — and "I have a question worth three years" opens doors that "I have very good hygiene" does not.

Two specifics sharpen this. First, the §2.7 two-stage estimand — the recognition that you cannot difference two Sharpes when each carries SE ≈ 0.45, so you must estimate where the power is and report where the audience is — is a genuinely sophisticated piece of design that a professor will not expect from a student, and it is already written. Second, the §2.8 monotonicity test converts a null into a finding: *the discount is bounded above by D even in the most contamination-favorable configuration we could construct.* Most student projects have no such escape hatch.

I cannot defeat this, and I am not trying to. My answer is that it argues for **writing the pre-registration in week one**, not for spending weeks two through twenty on execution. The intellectual contribution — the question, the identification strategy, the estimand split, the falsification design — is already on paper and costs nothing more to bank. The execution is what is expensive, and the execution is what is not time-sensitive.

---

## What would change my ranking

**Moves contamination up:**
- `.wrds_pit.db` exists and works on their machine, *and* a point-in-time constituent history is obtainable. Survivorship correction stops being unbounded. This is the single biggest swing factor and I could not verify it from this checkout.
- A real budget: $1–3k in API credits, a provider grant, or university compute. The current draft treats cost as a non-issue ("the pilot's 84 calls cost USD 3–4"); the full factorial is two to three orders of magnitude larger and §2.11 concedes the probes dominate.
- The knowledge-curve probe returns sharp, well-separated crossings for ≥5 models with refusal rates under ~10%. Then the identifying variation is demonstrably real, and I would move to PURSUE.
- A co-author. Not for labor — for the M ≈ 7-cluster problem, a second pair of eyes on inference, and because a staggered-DiD design with a treatment nearly collinear with a model-level trait deserves someone to argue with.

**Moves contamination down, to KILL:**
- Probe refusal rates above ~30%, or knowledge curves that do not separate across models. The dose-response is then unavailable and the binary specification is left with ~7 clusters and no fallback.
- No resolution to the cluster-count problem after honestly confronting it.

**Changes the ordering of 1 and 2:**
- Professor's field. An econometrician or empirical-finance person: statistics case study first, contamination second, eval last. An ML-systems or NLP person: eval first, contamination second. If they have a specific professor in mind, that single fact reorders the top two.

**Collapses everything to item 1:**
- A deadline inside two weeks. Then the stats case study is the only option that reliably exists on presentation day, and it is a good one.

**Changes nothing:**
- More models, more dates, more factorial cells, or more repeats. None of those touch the cluster count, and the draft's §2.5 defense already recognizes the cross-sectional analogue of this point ("adding universes does not help identification"). The temporal version of that argument has a twin the draft has not yet written down, and it is about `M`, not `D`.
