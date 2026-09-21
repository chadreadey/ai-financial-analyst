---
reviewer: The Advocate
charge: "Build the strongest honest case FOR pursuing it."
verdict: RESCOPE
provenance: "Subagent output, fresh context, reproduced verbatim. Citations unverified — see README.md."
---

# THE ADVOCATE — Report

## VERDICT: **RESCOPE**

I was assigned to argue FOR. After reading the primary sources and the outside literature, I can make a real case — but **not for the paper as drafted**. The draft's load-bearing claim is factually dead, and I will not pretend otherwise. What survives underneath it is a narrower, genuinely defensible paper that this student is unusually well-positioned to write. That is a PURSUE-after-surgery, which is RESCOPE.

---

## What I verified in the repo (all claims in the brief check out)

| Claim | Status |
|---|---|
| Pilot: SPY 0.74 / quant 1.15 / AI 1.01, ΔSR = −0.14, 84 rebalances | **Verified**, `docs/eval/three_series_llm/latest.md` |
| Lo(2002) Sharpe SE 0.4472 formula vs 0.4478 empirical (5,000 paths) | **Verified**, `docs/audit/2026-08-25-hac-sharpe-validation.md` |
| Naive IC t-stat rejects 59.3% under a true null; HAC still 18.7%; calibrated 5% crit value 3.08 at n=96 | **Verified**, same file |
| "Zero of 44 signal×horizon tests survive Benjamini–Hochberg" | **Verified independently.** Best p is QMJ@1M MBB p=0.0075; BH rank-1 threshold is 0.05/44 = 0.00114 (and 0.00227 at α=0.10). Nothing survives. `docs/audit/2026-08-25-rejudge/rejudgment.json` |
| README contradicts its own audit | **Verified.** `README.md:211` — "OBV trend \| Validated \| Primary \| only technical signal with alpha"; rejudgment records `obv_trend` NO_SIGNAL at all four horizons, mean IC −0.0081 at 1M, p=0.524 |
| `runs/` gitignored, pilot not reproducible | **Verified.** `.gitignore:39`, no `runs/` directory exists |
| Pilot used one frontier model | **Verified.** `modal_app/functions/ai_replay.py:51` → `DEFAULT_MODEL = "claude-opus-5"`. The entire 2018-02→2025-01 window is pre-cutoff for it: **zero identifying variation**, as the draft itself concedes |
| Reusable machinery exists | **Verified.** `mbb_pvalue` (`scripts/rejudge_ic_signals.py:50`), `compute_sharpe_stats` with `risk_free_annual` + `autocorr_adjust` already parameterized (`quant/metrics.py:181`), `quant/universe.py:588` supports the whole salience ladder, cassette replay in `evals/`, config+SHA stamping, Modal fan-out. 60,758 Python LOC, 622 test functions, 183 commits 2026-04-05 → 2026-09-21 |

The draft is the most honestly self-attacking research document I have read in a student repo. It flags its own HARKing (§1), refuses to call its own screener "IC-validated," and tells the author to lead with the fact that the pilot points the *wrong way*. That matters for my verdict and I come back to it.

---

## The finding that forces the rescope

**The abstract's central claim is false as of today (2026-09-21).** It says the field "has no estimate of its magnitude, so a reader cannot discount a published result by any principled amount." There are now at least nine papers doing exactly that, several of which independently invented the draft's distinctive-sounding components:

| Prior work | Overlaps with |
|---|---|
| Glasserman & Lin, arXiv 2309.17322 (2023) | The **Anonymized arm** verbatim (company names → fictional placeholders), *and* the mega-cap salience finding. Their result: in-sample, anonymized headlines *outperform* — distraction beats look-ahead |
| Didisheim, Fraschini & Somoza, *Economics Letters* 256 (2025), "AI's predictable memory in financial analysis" | The **recall probe** and the **moderator gradient** (model size, data frequency, aggregation level), plus a portfolio-level Sharpe-nulling procedure |
| Roberts, Thakur, Herlihy, White & Dooley, **ICLR 2024**, "To the Cutoff… and Beyond?" | **Training cutoff as a natural experiment** across GPT-4/GPT-3.5/Code-Bison (code domain) |
| Gao, Jiang & Yan (CUHK), arXiv 2512.23847 | **Lookahead Propensity** = the draft's knowledge curve $k_m(d)$: date-only recall query, materially positive in-sample, collapsing to ~0 right after cutoff, interacted with forecast accuracy |
| Benhenda, Look-Ahead-Bench, arXiv 2601.13770 (Jan 2026) | **End-to-end agentic trading workflows** with alpha decay across regimes — the pilot's exact framing |
| MemGuard-Alpha, arXiv 2603.26797 | Membership inference + cross-model disagreement; reports 14.48bp clean vs 2.13bp tainted |
| "From Knowing to Doing," arXiv 2605.28359 | Memory-controlled benchmark separating recall from trading |
| **FinCAD / "Summoning the Oracle to Slay It," arXiv 2605.24564 — accepted EMNLP 2026 Main** | Entity- and date-adaptive memorization scaling; reports in-sample return inflation up to −67.1% on memorised dates, OOS Sharpe within 0.10 |
| HindsightBench, arXiv 2607.18867 (Jul 2026) | **"Behaviorally effective knowledge cutoff"** ($=\hat c_m$), **post-cutoff placebo**, and a **recall-accuracy dissociation coefficient** — the draft's line "the probe measures whether a model *has* it; the regression measures whether it *uses* it" |
| ChronoBERT / DatedGPT / StoriesLM (arXiv 2502.21206, 2603.11838) | The *solution* line — chronologically consistent pretraining |

A referee would reject the current draft on related work alone, and the student would look like they had not searched. **This must be fixed before anything else.**

---

## The three strongest arguments for pursuing (rescoped)

### 1. Every existing finance estimate is single-model, and therefore confounds contamination with market regime. The cross-model DiD is the fix, and nobody has run it in finance.

This is the real contribution and it is a genuine econometric improvement, not a repackaging. Gao et al., Look-Ahead-Bench and FinCAD all compare **one model's** pre-cutoff period against its post-cutoff period. That comparison is 2018–2024 versus 2025–2026 — two different market regimes, different volatility, different factor payoffs. Their "contamination effect" is not separable from "the recent market is harder." Roberts et al. (ICLR 2024) solved this with cross-model cutoff variation, but in code generation, where the confound barely bites; in finance it is the dominant threat.

The draft's §2.2 — $e_{m,d,c} = \alpha_c + \beta_c C_{m,d} + \gamma_{m,c} + \delta_{d,c} + \varepsilon$, with **date fixed effects** — is precisely the identification that the finance literature is missing. The draft even states the corollary its competitors do not: only months satisfying $\min_m \hat c_m < d \le \max_m \hat c_m$ identify $\beta_c$, and adding universes does not help because the constraint is temporal. That is an author who understands their own design better than the framing suggests.

**A short paper that does nothing but re-estimate the published magnitudes under date fixed effects, and shows how much of −67.1% or "7× difference" was regime, is publishable on its own.**

### 2. The pilot, plus Glasserman & Lin, point at a contrarian result the crowded literature has not tested cleanly — and this design can test it.

The literature has converged on "contamination is large" from underidentified single-model designs producing point estimates with no standard errors. Two independent pieces of evidence push back:

- The pilot: the contaminated AI arm **under**performed the deterministic arm drawn from the identical 50-name list (ΔSR = −0.14). Contamination predicts the opposite sign.
- Glasserman & Lin found that in-sample, *anonymizing away* the entity **improves** performance — distraction dominates look-ahead — and most strongly for mega-caps, i.e. exactly where recall is best.

Now combine with a number the student already Monte-Carlo-validated at machine precision: a 5-year daily Sharpe has SE ≈ 0.45. **Every published magnitude in this literature is a point estimate whose uncertainty nobody has propagated.** Demonstrating that the field's headline discounts are inside their own noise bands would be a real, citable, slightly uncomfortable finding — and §2.8's monotonicity test converts even a null into a bound: *"the discount is at most $[D]$ even in the most contamination-favorable configuration we could construct."* A single-condition null is an underpowered study; a monotone-ladder null is a result.

### 3. The selectivity axis is untaken, and it is the only part of this that yields a design rule rather than a number.

I searched specifically for this and found nothing. Everyone varies *salience* (model size, entity prominence, aggregation level — Didisheim et al., Glasserman & Lin). Nobody varies **how much room the pipeline leaves the model**: random-50 vs top-50-by-one-signal vs top-50-by-composite, base universe held fixed (§2.5 Axis A). The claim "if your candidate rule pre-filters hard, contamination buys the model less, because the names it would have front-run are already in the set" is an actionable architectural recommendation to the 77-study agentic-trading literature ("Agentic Trading: When LLM Agents Meet Financial Markets," arXiv 2605.19337, screened through 2026-03-09, median backtest window **1.3 years**, mostly 2020–2024 — i.e. essentially all of it inside training data and all of it needing this number).

And §2.7's standardized $\beta^{\ast}_c = \beta_c / \operatorname{sd}_c(r^{\mathrm{DET}})$ already anticipates the obvious objection that selectivity also changes return dispersion. That flag is in the draft as a RIGOR GAP the author raised against themselves.

**The positional advantage is real and I want to be concrete about it.** Someone starting fresh needs 4–6 months to build: a 495-name PIT panel, a monthly screener, an LLM selection agent, a Modal fan-out replay that fails loudly rather than silently falling back to the heuristic (`modal_app/functions/ai_replay.py` — and the draft correctly notes a silent fallback would manufacture a spurious $\beta_c = 0$), cassette recording for offline re-grading, config-hash + git-SHA stamping, and a validated stats layer. This student has all of it, plus a moving-block bootstrap, calibrated HAC critical values, and a Lo(2002) Sharpe SE verified against statsmodels to ~9e-16 and against 5,000 simulated paths. Marginal cost of the study is not the issue: **84 LLM calls cost USD 3–4.** The binding constraints are power and time, not money or engineering.

And the rarest asset: this student ran an audit that **destroyed their own signal roster** (44 tests → zero survive BH) and then wrote a paper draft that attacks their own README on page one. That disposition is what makes a contamination paper credible and is why I would not kill this.

---

## Realistic best-case outcome

**Venue.** I checked the actual calendar and it is tight:
- **ICAIF '26** (ACM, Milan, Nov 14–17 2026): main track deadline was **Aug 2, 2026 — closed**. **Workshop papers open until Oct 1, 2026** — ten days from now. Not realistic against six open rigor gaps, and a rushed submission with a refuted related-work section would be actively harmful.
- **FinNLP 2026** (@ EMNLP, Budapest): deadline Aug 11, notification Sept 1 — **closed**.
- Realistic targets: **ICAIF '27** main or workshop track (deadline ~Aug 2027, 8 pages ACM two-column — a good size fit); **FinNLP 2027** (@ ACL/EMNLP); a **CONDA-style data-contamination workshop** at ACL if it runs again.
- **Journal route is the better-calibrated one.** Didisheim, Fraschini & Somoza got a directly comparable contribution into ***Economics Letters*** (vol. 256, 2025) — short-format, empirical, single clean point. That is the precedent to aim at. *Journal of Financial Data Science* is the practitioner analogue.

**Realistic best case:** an arXiv preprint in Q1 2027, an ICAIF '27 or FinNLP 2027 workshop/short paper, ~10–30 citations over two years from the agentic-trading literature that currently has no defensible discount to apply, and the harness itself becoming the artifact people reuse. A solo undergraduate/master's student with a first-authored ICAIF paper and a public, reproducible harness is a strong outcome; this is a good PhD-application or quant-research-job artifact.

**What it is not:** this will not land in *RFS*, *JF* or *JFE*, and it will not be the definitive number. FinCAD already has EMNLP Main. The "flagship contamination paper" slot is gone.

**Timeline, honestly:** the draft lists **six open RIGOR GAPs** (effective sample size, probe refusal/size confounding, anonymization verification, stage-1→stage-2 uncertainty propagation, run-to-run variance, no power analysis at all) plus three broken metrics (Sortino denominator, no risk-free rate, "alpha" as an arithmetic spread) plus non-reproducible pilot artifacts plus a README that contradicts its own audits. That is 3–5 months of solo work before a credible submission, and the power analysis must come **first** because it may kill the project.

---

## The single strongest argument against that I could NOT defeat

**The design may have no power, and nobody knows, because the power analysis does not exist — and the same repo already proved this exact failure mode is fatal.**

Identification comes only from cutoff-straddling months. Realistically that window is ~18–30 monthly rebalances across 6–8 models. Then apply the deflations this repo documented on itself: holdings overlap month-to-month because QMJ/SUE/ERM are persistent (§2.3 gap, unmeasured); two-way clustering does not fully absorb it; and run-to-run variance at temperature 0 is unmeasured and is a hard floor on the smallest detectable $\beta_c$ (§2.8 gap). The MDE could easily exceed any plausible effect, and the student would discover this **after** spending months building the panel.

Worse, the failure would be invisible in the direction the student wants: a null would be indistinguishable from an underpowered design. The monotonicity ladder is the proposed defense, but a ladder of five underpowered cells is five noisy estimates whose ordering is itself noise.

And this is not hypothetical for this repo. `docs/audit/session-4-statistical-rigor/README.md` diagnoses the identical pathology — *"a number is produced under an assumption that was never checked"* — as the root cause of the entire signal roster collapsing. The contamination study is currently one more number produced under an unchecked assumption, and that assumption is $N_{\mathrm{eff}}$.

I cannot defeat this. The only answer is: **do the power analysis before anything else, on the pilot's already-recorded responses, and be willing to kill the project on its result.** The draft says exactly this in §2.9 — the student already knows. That it remains undone after the paper draft was written is the strongest evidence for the other side.

---

## What would change my verdict

**To PURSUE (full confidence):**
1. Power analysis returns MDE below ~0.3% monthly paired excess return at the realistic panel size, computed from measured holdings overlap and measured run-to-run variance on the existing pilot responses. **Cheap: uses recorded data, no new API spend, one to two weeks.**
2. A model panel exists with cutoffs genuinely spread across ≥18 straddling months, ≥2 providers, ≥1 open-weights model, and ≥1 **newer-but-weaker** model — without that capability/recency inversion, §2.2's identifying assumption is indefensible and a referee will say so.
3. The related-work section is rewritten around the nine papers above and the claim becomes *"existing estimates are single-model and confounded with regime; we identify off cross-model variation with date fixed effects, propagate uncertainty, and show the effect is governed by candidate-set design"* — not *"no estimate exists."*

**To KILL:**
1. Power analysis returns an MDE larger than the published effect sizes (FinCAD's in-sample inflation, Didisheim et al.'s magnitudes). Then the study cannot distinguish the literature's claims from zero, and the honest output is a two-page note, not a paper.
2. Fewer than ~12 straddling months are achievable with accessible models — the design then has no identifying variation and collapses to another single-model pre/post comparison, i.e. a worse version of Gao et al.
3. Run-to-run selection-overlap variance at temperature 0 is large enough to swamp plausible $\beta_c$. §2.8 flags this and it is measurable today from the pilot cassettes.

**Sequencing recommendation, if the council votes to proceed:** do items 1–3 of the PURSUE list *before* writing another line of the paper, and in parallel fix the README/NORTHSTAR contradictions (`README.md:211` OBV "only technical signal with alpha"; ERM claimed at IC 0.04–0.08 vs measured +0.0144–0.0263; the "PBO 0%" claim that `docs/audit/session-4-statistical-rigor/README.md` §A5 establishes is not the López de Prado statistic) and commit the `runs/candidates/` and `runs/ai_picks_llm/` artifacts under immutable dated paths. A contamination-honesty paper published from a repository whose front page asserts a signal its own appendix disproves is a reviewer gift, and it is the one problem that costs days rather than months.

**Sources:** [Glasserman & Lin 2023](https://arxiv.org/abs/2309.17322) · [Gao, Jiang & Yan 2512.23847](https://arxiv.org/abs/2512.23847) · [Roberts et al., ICLR 2024](https://openreview.net/forum?id=m2NVG4Htxs) · [Didisheim, Fraschini & Somoza, Economics Letters 2025](https://www.sciencedirect.com/science/article/pii/S0165176525004392) · [Look-Ahead-Bench 2601.13770](https://arxiv.org/abs/2601.13770) · [FinCAD / EMNLP 2026 Main](https://arxiv.org/abs/2605.24564) · [HindsightBench 2607.18867](https://arxiv.org/abs/2607.18867) · [MemGuard-Alpha 2603.26797](https://arxiv.org/pdf/2603.26797) · [When Alpha Disappears 2605.23959](https://arxiv.org/abs/2605.23959) · [Agentic Trading survey 2605.19337](https://arxiv.org/html/2605.19337v1) · [ICAIF '26 CFP](https://icaif2026.org/call-for-papers.html) · [FinNLP 2026](https://sigfintech.github.io/finnlp2026/) · [CONDA workshop](https://conda-workshop.github.io/)
