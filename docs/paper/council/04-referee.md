---
reviewer: The Referee
charge: "Simulate peer review. Find real venues. Independent novelty search."
verdict: RESCOPE
provenance: "Subagent output, fresh context, reproduced verbatim. The reviewer states up front that arxiv and the major indexers were egress-blocked and its citations come from abstracts, not full texts. See README.md."
---

# REFEREE REPORT — "How Much Should You Discount an LLM Trading Backtest?"

**Access caveat up front:** arxiv.org, semanticscholar, huggingface, sciencedirect, alphaxiv and repec are all egress-blocked from this environment. Every citation below comes from search-result abstracts and indexer summaries, which I cross-checked across multiple independent queries. Titles, arXiv IDs, authors and dates are reliable; my characterizations of method detail are from abstracts, not full texts. **The author must pull these papers himself before doing anything else.** That verification is the single highest-value hour available to this project.

---

## VERDICT: **RESCOPE** (the paper as drafted is close to KILL)

Two independent things sink it, and they are not the things the draft's own 🟡/🔴 flags anticipate:

1. **The stated gap does not exist.** The central novelty claim — "the field acknowledges this in limitations sections but has no estimate of its magnitude" — was true when it was probably formulated (mid-2025) and is false as of September 2026. At least a dozen papers between Dec 2025 and Aug 2026 attack exactly this, several with the same instruments, and some already publish the magnitude number.
2. **The design cannot resolve the quantity it exists to measure.** By the draft's own arithmetic, the minimum detectable effect is larger than the range of Sharpe discounts the paper says readers need distinguished. This is derivable today, without running anything, and it is what I would lead a review with.

The draft is unusually self-aware — the flag system is better epistemic hygiene than most submitted papers have — but it audits the *execution* and never audits the *premise*. There is no related-work search in it. That is the failure.

---

## 1. Venues — what is real and currently open

| Venue | Status as of 2026-09-21 | Bar | Fit |
|---|---|---|---|
| **ICLR 2027** | **Dead.** Abstract registration was 2026-09-18 (3 days ago); full paper 2026-09-25. Missing abstract reg = cannot submit. | Top-tier | Would have been a reject anyway |
| **ICAIF '26** (7th ACM Intl. Conf. on AI in Finance, Bocconi/Milan, Nov 14–17 2026) | **Main track closed** (deadline 2026-08-02). **Workshop track open to 2026-10-01** — 10 days. | Main track: 8pp ACM, no appendices, ~25-30% accept, reviewers are quant practitioners + AI-finance academics. Workshops: much softer, non-archival-ish. | Best topical fit. Results do not exist; 10 days is not enough. |
| **ICAIF '27** | ~Aug 2027 deadline | As above | **The realistic conference target.** ~11 months of runway. |
| **ACL Rolling Review** | Oct 2026 cycle closes 2026-10-12 (→ NAACL/COLING 2027); **Jan 2027 cycle → ACL 2027** | *ARR is now capacity-capped with a reciprocal-reviewing requirement from Oct 2026 — a solo student author has a service obligation to meet.* | Would land at **Findings** or the **FinNLP** workshop, not main. Finance specificity is a liability with ACL reviewers. |
| **TMLR** | Rolling, no deadline. Active. | **Explicitly excludes novelty and significance from the accept/reject decision.** Criteria: (i) claims supported by convincing evidence; (ii) some portion of the audience would be interested. Tightened writing-clarity bar Sept 2026. | **This is the best realistic venue** — see below. |
| **NeurIPS 2027 D&B** | ~May 2027 | Benchmark/dataset contribution required | Only if repositioned as a released harness |
| **AAAI-27 workshops** | Workshop CFPs typically Oct–Nov 2026; workshops Feb 22–23 2027 | Low | Plausible fallback |
| **Finance Research Letters / Journal of Financial Data Science / Digital Finance / Quantitative Finance** | Rolling | FRL: short, fast, tolerant of measurement notes. JFDS: practitioner-facing, likes exactly this question. | Good home for the *rescoped* paper (§6) |

### Best realistic venue: **TMLR**, and the acceptance case is specific

TMLR is the only venue whose stated criteria survive contact with this paper's actual situation. It does not ask "is this novel?" — which is the question this paper now loses. It asks "are the claims supported?" That is answerable if, and only if, the claims are cut down to what the design can carry.

The TMLR-acceptable version is: *"We run a pre-registered cross-model staggered-cutoff design on a fixed portfolio-selection pipeline. Our minimum detectable effect is X Sharpe points. We find the contamination discount is bounded above by X in the most contamination-favorable configuration we could construct; we cannot resolve anything smaller, and we show why no design at monthly frequency on public model panels can."* That is an honest, evidence-backed, negative-result paper with a real methodological payload (the two-stage estimand, the power analysis, the released harness). TMLR accepts those. ICAIF and ACL do not.

The draft already contains the seed of this in §2.8 ("this converts a null into a publishable result"). It just has not noticed that the bound is the paper, not a consolation prize.

---

## 2. Novelty — the gap has closed, and it closed fast

This is the finding that matters most. I searched five different ways and kept hitting the same wall. Ordered by how directly each kills a component of the draft:

**Directly pre-empts §2.4 (cutoff estimation via recall probes):**
- **Gao, Zhenyu; Jiang, Wenxi; Yan, Yutong — "Detecting Lookahead Bias in LLM Forecasts," arXiv:2512.23847** (Dec 2025, revised June 2026). Defines **Lookahead Propensity (LAP)**: a date-only recall query per firm-date pair estimating whether the model internalized the realized outcome. LAP is "materially positive throughout the in-sample period and collapses essentially to zero right after the training-data cutoff." They regress forecast accuracy on LAP × LLM-forecast and show the interaction vanishes post-cutoff, on news-headline→stock-return and earnings-call→capex tasks. **This is the draft's knowledge curve $k_m(d)$, the dose-response specification, and the cutoff natural experiment, published nine months before this draft.**
- **arXiv:2607.18867 — "HindsightBench: A Black-Box Behavioral Audit Protocol for Parametric Hindsight in Time-Indexed LLM Decision Tasks"** (July 2026). Four-arm date-manipulation matrix (revealed/date-only/masked/transplanted), dual memory probes, **post-cutoff placebo**, and a **"behaviorally effective knowledge cutoff"** metric — applied to **15 models from seven vendors**. This is §2.4's $\hat c_m$ and §2.6's prompt arms and §2.8's placebo, at 2× the model panel the draft proposes, already done. Its headline finding is directly load-bearing against the draft's feasibility (see §4).

**Directly pre-empts §2.6 (anonymization arm):**
- **Glasserman, Paul; Lin, Caden — "Assessing Look-Ahead Bias in Stock Return Predictions Generated By GPT Sentiment Analysis," arXiv:2309.17322 / SSRN 4586726** (2023). Separates look-ahead bias from a "distraction effect," and finds anonymizing company identifiers *improves* performance. The draft's Anonymized arm is this, three years later, without citation. The distraction-effect result is also a direct threat to the draft's interpretation: if anonymization changes performance for non-contamination reasons, the arm does not isolate what §2.6 claims.

**Directly pre-empts the portfolio-level estimand:**
- **Zhu, Taojie et al. — "From Knowing to Doing: A Memory-Controlled Benchmark for LLM Trading Agents on Stock Markets" (KTD-Fin), arXiv:2605.28359** (May 2026). Ten frontier LLM agents, end-to-end trading, CSI300, 2024–2026. Data-side **masking protocol** anonymizing identifiers and calendar info across prompts and tools, explicitly "separating historical market memory from investment decision-making." Attribution analysis shows agent cumulative returns under leakage control are "largely explained by passive market and style exposure, with limited evidence of persistent stock-selection alpha." **The title is literally the draft's §2.4 sentence "the probe measures whether a model *has* the information; the portfolio regression measures whether it *uses* it."**

**Directly pre-empts the "hold pipeline fixed, toggle one thing" logic:**
- **Zhang, Fan; Li, Zhen; Peng, Sijia; Chen, Yu — "When Alpha Disappears: A One-Switch Benchmark for Decision-Time Leakage in Financial Backtests," arXiv:2605.23959** (May 2026). Estimates **protocol-induced inflation** by toggling one evaluation convention at a time around a clean reference, holding data panel, split, model family, horizon, portfolio rule and cost convention fixed. Two equity panels, six model families, 2016–2024. Finds inflation is "highly selective." This is the draft's identification philosophy, executed.

**Directly pre-empts the moderator/gradient contribution (§2.5):**
- **"AI's predictable memory in financial analysis," Economics Letters (ScienceDirect S0165176525004392, 2025).** Finds look-ahead bias "varies markedly with data frequency, granularity, and model size," and concludes reliable LLM backtesting is feasible with appropriate setup. Granularity and model size are two of the three moderators the draft's factorial proposes to discover.

**Already publishes the magnitude the draft says nobody has:**
- Reported in this literature: a backtest re-run on decision-time-available values only "kept ~73% of its returns and ~82% of its Sharpe" (≈ **18–27% Sharpe discount** — precisely $D^{\%}$).
- **MemGuard-Alpha, arXiv:2603.26797** — clean vs. tainted signals: 14.48 bps vs 2.13 bps daily; CMMD achieves 49% Sharpe improvement over raw alpha.
- Contamination proportion varies by model: for GPT-4.1, the share of observations needing exclusion to kill spurious Sharpe rises from 3.5% baseline to 22% with same-day market return context; GPT-4.1-nano shows none.

**Mitigation, benchmarks and infrastructure, all 2026:**
- **arXiv:2605.24564** "Summoning the Oracle to Slay It" — FinCAD, inference-time suppression of historical-outcome memory.
- **arXiv:2602.17234** "All Leaks Count, Some Count More: Interpretable Temporal Contamination Detection and Mitigation in LLM Backtesting."
- **arXiv:2605.18843** TEMPO — temporal enforcement for trustworthy LLM backtesting.
- **arXiv:2601.13770** Look-Ahead-Bench (Benhenda) — standardized look-ahead benchmark, code at github.com/benstaf/lookaheadbench.
- **arXiv:2608.09988** OpenPM — auditable point-in-time eval for LLM portfolio agents, with a **"contamination certificate."**
- **arXiv:2606.29771** CLQT — per-model eligibility filtering so backtest data postdates each model's cutoff; canary documents + future-shift leakage probes.
- **arXiv:2605.27887** PortBench; **arXiv:2607.04958** "Look-Ahead-Freedom as Temporal Non-Interference"; **arXiv:2602.14233** "Evaluating LLMs in Finance Requires Explicit Bias Consideration."

**What is actually left.** I could not find a paper doing the specific thing: **a cross-model staggered DiD with model × date fixed effects on paired portfolio excess returns from an identical candidate list.** The existing work is (a) within-model LAP-interaction regressions, (b) data-masking comparisons, or (c) restrict-to-post-cutoff windows. The date-FE-absorbs-regime argument in §2.2 is econometrically cleaner than what LAP does, and the paired-against-deterministic-selector-from-the-same-50 construction is a genuinely nice variance reduction I did not see elsewhere.

But that is a **refinement of an estimator**, not an open question. A reviewer will write: "the authors propose a better identification strategy for a quantity three other papers have already estimated, and do not show their estimate differs." That is a weak-accept at TMLR and a reject at ICAIF.

Note also that a substantial fraction of the 2026 arXiv items above look like rapid-fire, possibly low-quality preprints. **Discount half of them and the novelty claim still dies**, because Glasserman–Lin (2023), Gao–Jiang–Yan (2512.23847), and the Economics Letters paper are enough on their own.

---

## 3. The review I would write — the three findings driving my score

### Finding 1 (fatal, and derivable today): the MDE exceeds the range of interest

The paper's reason for existing is in the abstract: *"no reader of an LLM-trading paper can currently say whether to subtract 0.05 or 0.8 from a reported Sharpe."* So the design must resolve differences within [0.05, 0.8]. It cannot.

Referee back-of-envelope, using the draft's own MDE formula $\mathrm{MDE} \approx 2.8\sigma_\varepsilon/\sqrt{N_{\mathrm{eff}}}$:

- $\sigma_\varepsilon$: $e$ is the difference of two 10-name equal-weight long-only baskets drawn from the same 50, sharing perhaps 3–5 names. The non-overlapping residual is ~6 vs ~6 names of largely idiosyncratic risk. Monthly $\sigma_\varepsilon$ is plausibly **3–6%**; take 4%.
- Straddling months: HindsightBench's own measurement is that **behaviorally effective cutoffs span 22 months across vendors** (and precede vendor-reported dates by up to 8 months). So $D_{\text{straddle}} \approx 22$, not 84.
- With $M = 7$: raw $N = 154$ per cell. The draft's §2.3 gap correctly notes heavy month-to-month holdings overlap from persistent QMJ/SUE/ERM; $N_{\mathrm{eff}} \approx 60\text{–}150$.

$\mathrm{MDE} = 2.8 \times 0.04/\sqrt{80} \approx 0.0125$/month $\approx$ **15% annualized excess return**. At ~18% annualized portfolio vol that is **≈0.83 Sharpe points**. Under the generous end ($\sigma_\varepsilon = 3\%$, $N_{\mathrm{eff}} = 150$): $\approx 8\%$/yr $\approx$ **0.46 Sharpe**.

**So the design's detectable range starts at roughly 0.45–0.85 Sharpe and the question's range ends at 0.8.** The paper can answer "is the discount enormous?" It cannot answer the question it poses. And §2.8's monotonicity falsification requires *ordering three estimates* each carrying ±0.5 Sharpe of uncertainty — that test has no power at all.

This is not a rigor gap to be closed later. It is a go/no-go the draft defers to §2.9 ("no power analysis exists yet") and then builds five factorial cells, four prompt arms and a two-stage bootstrap on top of. **§2.9 must be executed first, before a single additional line of code.** If it comes out where I think it does, the study as designed should not be run.

There is one escape the draft already half-identifies: the **dose-response specification uses all months, not only straddling ones**. That is a genuine power multiplier and should be promoted to primary from the start — not, as §2.9 has it, contingently after the binary spec fails. But dose-response is also the specification most exposed to the size confound flagged in §2.4 and closest to Gao–Jiang–Yan's published LAP design.

### Finding 2 (major, and citable against you): TWFE with a binary indicator is the wrong estimator, by the paper's own argument

§2.2 runs two-way fixed effects with a binary treatment. §2.4's 🔴 DEFENSE then argues at length that **the effect must be heterogeneous** — decaying with distance from cutoff, larger for recent months. Heterogeneous treatment effects under staggered timing is the exact configuration where TWFE fails: Goodman-Bacon's decomposition shows the TWFE estimate is a variance-weighted average of 2×2 DiDs that includes already-treated units as controls, producing negative weights and a coefficient that need not lie in the convex hull of any real effect.

Here treatment switches $1 \to 0$ as $d$ increases (contamination turns *off* past cutoff), which is a reversed-staggered design — the literature's awkward case, not its easy one. The draft cites no modern DiD work: no Callaway–Sant'Anna, no Sun–Abraham, no Borusyak–Jaravel–Spiess, no Goodman-Bacon, no de Chaisemartin–D'Haultfœuille.

Secondary but real: **two-way clustering with 7 model clusters is not valid inference.** Cluster-robust standard errors need far more clusters; with 7, a wild cluster bootstrap is mandatory and even that is shaky. The draft says "two-way clustered and block-bootstrapped" without acknowledging the few-clusters problem.

An econometrics-literate referee — and ICAIF has them, and any finance journal will assign one — closes the PDF at this point. This is the most hostile review you will get and it is entirely fixable by reading and citing correctly, so fix it.

### Finding 3 (major): the premise is not defended, because no related work was done

There is no §related-work in a document that is otherwise meticulous about attack surfaces. The 🔴 DEFENSE for "isn't this obvious?" rehearses an answer to the wrong objection. The objection you will actually get is: *"Gao, Jiang and Yan (2025) built the recall probe and the cutoff experiment; Glasserman and Lin (2023) built the anonymization arm; KTD-Fin (2026) ran ten agents end-to-end with masking and did the knowing-vs-doing decomposition; the 18–27% Sharpe retention number is already in the literature. What is new here?"*

You have an answer — the paired-deterministic variance reduction and the date-FE design are better — but you must make it explicitly, with a table mapping each of your components to the closest prior work and stating the delta. Without that table this is desk-reject-adjacent at any venue with active reviewers in the area.

---

## 4. Desk-reject risks, specific

1. **ICAIF main track (for '27): 8 pages, no supplementary materials, no appendices.** The draft's methods section alone is ~8 pages. The factorial + prompt arms + two-stage bootstrap + event study + placebo + five robustness checks do not fit, and there is nowhere to put them. Either cut the design or pick a venue with appendices. This is a hard format constraint, not a preference.
2. **Missing related work** (§3, Finding 3). At ICAIF or ARR, an area chair who knows the LAP paper can desk-reject on premise falsity.
3. **The pilot has zero identifying variation and the draft says so.** 2018-02→2025-01 lies "almost entirely inside the training data of the model used," so $C_{m,d}=1$ throughout. §2.2 establishes that such months contribute nothing. So Appendix A is a table of numbers from a design that by the paper's own theorem cannot speak to the question. Presenting it as "what the pilot established" invites a reviewer to conclude the authors have no data at all — which is true. Appendix A should be retitled and demoted.
4. **"We release the harness" vs. §2.11's own admission** that `runs/` is gitignored, the pilot is not reproducible from the repo, and `docs/eval/*/latest.md` is overwritten in place. Reproducibility-checklist venues (NeurIPS D&B, TMLR, ICLR) take this seriously. Do not make the release claim until it is true.
5. **Repository self-contradiction (§2.11's 🔴).** README:211 calls OBV trend "Validated | Primary | only technical signal with alpha"; the committed re-judgment records `obv_trend` as NO_SIGNAL at all four horizons with negative 1M mean IC ($-0.0081$, MBB $p=0.524$). NORTHSTAR.md:17 calls OBV "the sole survivor." ERM claimed at IC 0.04–0.08, measured 0.0144–0.0263. If you release code, a reviewer who opens the README finds a headline claim disproven by your own committed JSON. Fix before any release.
6. **Three broken metrics in the live pipeline** (Sortino using sd-of-negatives instead of target semideviation; Sharpe with no risk-free subtraction over a 2018–2025 window where cash paid 4–5%; "alpha" as an arithmetic spread rather than a factor-model intercept). Any finance referee catches the missing risk-free rate immediately; it is worth roughly 0.2–0.3 of reported Sharpe at these levels. Reporting a 1.15 Sharpe that ignores a 4% risk-free rate is a first-page credibility loss.
7. **HARKing.** The draft handles this correctly and honestly — disclose the sequence, lean on prospective pre-registration. Keep that. But note that the pre-registration's protective value depends entirely on the confirmatory sample being post-cutoff months that accrue *after* registration, and Finding 1 says those months will be too few to power anything. The mitigation and the power problem are the same problem.

---

## 5. Ambition vs. evidence — is the gap bridgeable by one student?

**The money is not the constraint.** §2.11 is right: $3–4 for 84 calls; even 7 models × 5 cells × 4 arms × 30 dates × 5 repeats is low four figures, dominated by recall probes. A student can afford this.

**The identifying variation is the constraint, and money cannot buy it.** You need models whose *behaviorally effective* cutoffs are widely spread. HindsightBench measured that spread at 22 months across seven vendors, with effective cutoffs preceding reported ones by up to 8 months. That is the ceiling on your straddling window, it is set by industry release cadence, and it shrinks every time a new frontier model ships. The draft's §2.3 "forward extension" is the only lever that grows it, at one observation per month of calendar time.

**What must be built that does not exist:**
- Cutoff-diverse model panel with a documented open-weights anchor and a newer-but-weaker inversion (weeks; the provider abstraction exists)
- Knowledge probes, stratified by size tercile, with refusal coded as its own category and sensitivity under both codings (§2.4's two validity holes) — weeks, and this is the piece most duplicated by HindsightBench
- Re-identification probe validating the anonymization arm (§2.6) — days
- Holdings-overlap measurement → $N_{\mathrm{eff}}$ → real power analysis (§2.3, §2.9) — **days, and must come first**
- Run-to-run variance at $R$ repeats, establishing the noise floor that bounds every claim (§2.8) — days
- Moving-block bootstrap wired in (`mbb_pvalue` exists) — days
- Full two-stage bootstrap re-estimating $\hat\beta_c$ inside every replicate (§2.7) — weeks
- Metric fixes, risk-free rate, point-in-time survivorship correction, transaction costs and execution delay for reported levels — weeks
- Reproducibility: commit run artifacts, immutable dated result paths, remove auto-generated verdict strings — days
- Modern DiD estimator (Callaway–Sant'Anna or similar) + wild cluster bootstrap for 7 clusters — weeks, including the reading
- Related-work section that actually surveys the twelve papers above — a week

**Verdict on feasibility:** the *engineering* is a solid 6–9 months for a capable solo student and is genuinely achievable — the repo is further along than most. The *scientific* gap is not bridgeable, because the binding constraint (22 months of cutoff spread × ~7 models, against $\sigma_\varepsilon \approx 4\%$/month) is external and does not yield to effort. A student who does all of the above lands on a confidence interval that straddles the entire range of practical interest.

The honest sequencing is: **spend one week on the power analysis and the literature review. Both are cheap, both are decisive, and both are currently missing.** Do not build the factorial first.

---

## 6. What would change my verdict

**To PURSUE at TMLR** (most likely path, and a real one):
- A completed power analysis showing $\mathrm{MDE} \lesssim 0.3$ Sharpe under the dose-response specification — i.e. my estimate in Finding 1 is wrong by 3× and you can show it with measured $\sigma_\varepsilon$ and $N_{\mathrm{eff}}$ from the pilot's recorded responses. **This alone flips the verdict.**
- Reframed headline: not "here is the discount" but "here is a *bound* on the discount, and here is why this class of design cannot do better" — plus the released harness as a standing contribution. TMLR accepts modest contributions with well-supported claims; it will not accept an overclaimed one.
- Modern staggered-DiD estimator, wild cluster bootstrap, and a related-work table mapping every component to prior art with an explicit delta.

**To PURSUE at ICAIF '27** (harder):
- All of the above, *plus* a result that materially contradicts or sharpens an existing published number (e.g. you estimate the discount at 0.4 where the literature's implied retention says 0.18, and you can explain why), *plus* the whole thing compressed into 8 pages with no appendix.

**To KILL:**
- If the power analysis lands where I expect and the dose-response spec does not rescue it.
- If, on reading Gao–Jiang–Yan and KTD-Fin in full, the paired-deterministic construction turns out to be present there too. Verify this first; it is the last piece of distinctiveness standing.

**The rescope I would actually recommend**, in priority order:

1. **Publish the statistics work that is already finished.** `docs/audit/2026-08-25-hac-sharpe-validation.md` + `rejudgment.md` are a complete, measured, reproducible result: the naive $t$-statistic on monthly-sampled 12M-overlapping ICs **rejects a true null 59.3% of the time at nominal 5%**; correctly-implemented Newey–West still over-rejects at 18.7%; Monte Carlo calibration at $n=96$/overlap-12 gives a 5% critical value of **3.08, not 1.96**; and applying calibrated thresholds collapses an 11-signal × 4-horizon roster to two survivors at 1M, **zero of which survive Benjamini–Hochberg at $\alpha=0.10$ or Bonferroni across the $m=44$ family.** The small-sample HAC problem is known (Kiefer–Vogelsang, Müller), so the econometrics is not new — but the applied demonstration that a standard factor-research workflow manufactures significance at 12× the nominal rate, with a calibration table practitioners can use, is a publishable note. **Finance Research Letters or Journal of Financial Data Science, short form, submittable in weeks, not months.** This is the only finished asset in the repository and it is currently sitting in an audit directory.

2. **Reposition the contamination work as a prospective registered protocol.** Pre-register, run forward-only on post-cutoff months, report as shadow evaluation. This sidesteps the power problem by not requiring a DiD, matches §4's own conclusion that "forward shadow evaluation is the only fully valid protocol," and is a defensible ICAIF '27 or TMLR submission with a year's runway. It is also the version the pre-registration actually protects.

3. **`docs/EVALS.md` is a separate and better paper than you think.** The argument — that this system's prompts specify *arithmetic contracts*, so ground truth is derivable from inputs with no human labels and no LLM judge, and therefore trajectory metrics from agent-eval frameworks measure nothing here — is a genuine and underexplored position in agent evaluation. It needs no new data and no identifying variation. If the student wants an ML-venue paper, that is the one with an open gap.

---

**Sources:**
- [Detecting Lookahead Bias in LLM Forecasts — Gao, Jiang & Yan, arXiv:2512.23847](https://arxiv.org/abs/2512.23847)
- [Assessing Look-Ahead Bias in Stock Return Predictions Generated By GPT Sentiment Analysis — Glasserman & Lin, arXiv:2309.17322](https://arxiv.org/abs/2309.17322)
- [From Knowing to Doing: A Memory-Controlled Benchmark for LLM Trading Agents on Stock Markets (KTD-Fin), arXiv:2605.28359](https://arxiv.org/abs/2605.28359)
- [When Alpha Disappears: A One-Switch Benchmark for Decision-Time Leakage in Financial Backtests, arXiv:2605.23959](https://arxiv.org/abs/2605.23959)
- [HindsightBench: A Black-Box Behavioral Audit Protocol for Parametric Hindsight, arXiv:2607.18867](https://arxiv.org/abs/2607.18867)
- [Look-Ahead-Bench: a Standardized Benchmark of Look-ahead Bias in Point-in-Time LLMs for Finance, arXiv:2601.13770](https://arxiv.org/abs/2601.13770)
- [Summoning the Oracle to Slay It: Mitigating Look-Ahead Bias in Financial Backtesting with LLMs, arXiv:2605.24564](https://arxiv.org/abs/2605.24564)
- [MemGuard-Alpha, arXiv:2603.26797](https://arxiv.org/pdf/2603.26797)
- [All Leaks Count, Some Count More, arXiv:2602.17234](https://arxiv.org/pdf/2602.17234)
- [TEMPO: Temporal Enforcement for Trustworthy LLM Backtesting, arXiv:2605.18843](https://arxiv.org/pdf/2605.18843)
- [CLQT: Closed-Loop, Cost-Aware Benchmark for LLM Portfolio-Management Agents, arXiv:2606.29771](https://arxiv.org/html/2606.29771v1)
- [OpenPM: Auditable Point-in-Time Evaluation for LLM Portfolio-Management Agents, arXiv:2608.09988](https://arxiv.org/html/2608.09988)
- [PortBench, arXiv:2605.27887](https://arxiv.org/html/2605.27887)
- [Look-Ahead-Freedom as Temporal Non-Interference, arXiv:2607.04958](https://arxiv.org/pdf/2607.04958)
- [Evaluating LLMs in Finance Requires Explicit Bias Consideration, arXiv:2602.14233](https://arxiv.org/html/2602.14233v1)
- [AI's predictable memory in financial analysis — Economics Letters](https://www.sciencedirect.com/science/article/pii/S0165176525004392)
- [ICAIF '26 Milan — Call for Papers](https://icaif2026.org/call-for-papers.html) · [Important Dates](https://icaif2026.org/important-dates.html)
- [ICLR 2027 Call for Papers](https://iclr.cc/Conferences/2027/CallForPapers)
- [ACL Rolling Review — Dates](https://aclrollingreview.org/dates) · [CFP](https://aclrollingreview.org/cfp)
- [TMLR Editorial Policies](https://jmlr.org/tmlr/editorial-policies.html)
- [AAAI-27 Workshops Call](https://aaai.org/conference/aaai/aaai-27/workshops-call/)
- [NeurIPS 2026 Call for Papers](https://neurips.cc/Conferences/2026/CallForPapers)
- [lookaheadbench code repository](https://github.com/benstaf/lookaheadbench)
