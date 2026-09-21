---
title: "Adversarial council — is the look-ahead contamination paper worth pursuing?"
date: 2026-09-21
kind: decision-record
subject: docs/paper/2026-09-21-lookahead-contamination-abstract-methods.md
verdict: RESCOPE (4 of 4, independently)
---

# Council verdict — contamination paper

Four reviewers were dispatched with **fresh context**, the same factual brief, and
no visibility into each other's work or into the conversation that produced the
paper draft. Each was told to verify the brief against primary sources rather
than trust it, and each was bound by an **anti-theater rule**: if it could not
honestly make its assigned case after genuine investigation, it had to say so
and explain why. Conceding was defined as a valid and valuable output.

| # | Reviewer | Charge | Verdict |
|---|---|---|---|
| [01](01-opportunity-cost.md) | Opportunity Cost | Is this the best use of the next several weeks, against the alternatives already in this repo? | RESCOPE |
| [02](02-advocate.md) | Advocate | Strongest honest case FOR pursuing | RESCOPE |
| [03](03-prosecution.md) | Prosecution | Strongest honest case to KILL or rescope | RESCOPE |
| [04](04-referee.md) | Referee | Simulate peer review; find real venues; independent novelty search | RESCOPE |

All four returned RESCOPE. Because they were independent, that convergence is
evidence rather than agreement among allies.

---

## The decisive number, measured after the council reported

Both the Prosecution and the Referee named a single quantity as their
verdict-flipping condition, and neither could compute it: the Prosecution
reconstructed it from an assumed correlation, and noted that `runs/` is
gitignored so nobody could check. It is in fact computable from
`docs/eval/three_series_llm/daily_returns.csv`, which is committed.

Measured from the pilot's 1,759 daily observations (2018-02-01 → 2025-01-30):

```
rho(AI, deterministic), monthly = 0.960
sigma_e                         = 2.103 %/month
lag-1 autocorrelation of e      = +0.077
mean(e)                         = -0.375 %/month   (naive t = -1.64)
AI arm annualized vol           = 23.85 %
```

Implied minimum detectable effect at 80% power, 5% size:

| M models | D straddle months | MDE %/mo | MDE in Sharpe points |
|---:|---:|---:|---:|
| 6 | 24 | 1.74 | **0.88** |
| 8 | 30 | 1.34 | **0.68** |
| 12 | 36 | 0.99 | **0.50** |
| 20 | 36 | 0.75 | **0.38** |

The abstract states that a reader needs to distinguish a discount somewhere in
**0.05 to 0.8 Sharpe**. The design resolves only the very top of that range.

- The Prosecution's collapse condition was rho > 0.98 giving sigma_e ~ 1%/mo.
  Actual: rho = 0.96, sigma_e = 2.10%/mo. **Its argument survives**, slightly
  softened (it had assumed 2.5%).
- The Referee's flip condition was MDE <= ~0.3 Sharpe. **Not reached** at any
  feasible panel size.

Two findings favor the design and should not be lost:

1. **The pairing works.** rho = 0.96 between the AI and deterministic arms cuts
   the residual from ~7%/mo to 2.10%/mo — a ~3.4x variance reduction. This is
   the construction the Referee said it could not find in the prior literature.
2. **Serial correlation barely bites.** Lag-1 autocorrelation of `e` is +0.077,
   so the holdings-overlap deflation of `N_eff` flagged as a RIGOR GAP in §2.3
   of the draft is real but small. Both the Prosecution and the Referee assumed
   against the design here.

Reproduce with the script in [`power-analysis.py`](power-analysis.py).

---

## Reading these reports critically

**Every citation in these reports is unverified.** All four reviewers reported,
unprompted, that arxiv.org and the major indexers were blocked by this
environment's egress proxy. Their novelty findings rest on search-result
summaries and abstracts, not on reading the papers. Two reviewers said so
explicitly and named it the weakest link in their own briefs.

The directional finding — that this space became crowded between late 2025 and
mid 2026 — is corroborated by three independent searches that surfaced
overlapping arXiv IDs. The specific claims about what each paper does are not
corroborated. **Pull the papers before conceding the premise.** The three that
matter most:

- Gao, Jiang & Yan, arXiv:2512.23847 — does it already build the knowledge curve?
- Glasserman & Lin, arXiv:2309.17322 — does it already run the anonymization arm?
- "AI's predictable memory in financial analysis," *Economics Letters* 256 (2025)

The last distinctive element standing is the **paired-deterministic
construction**: benchmarking each model against a deterministic selector drawn
from the identical 50-name candidate list, within the same month. If that is
present in the above, the novelty case is gone.

## What all four agreed on, independently

1. **Fix the repository's self-contradiction first.** `README.md:211` calls OBV
   trend "Validated | Primary | only technical signal with alpha";
   `docs/audit/2026-08-25-rejudge/rejudgment.md` records it as NO_SIGNAL at all
   four horizons with a negative 1M mean IC. `NORTHSTAR.md:17` calls it "the
   sole survivor." Hours of work; named by every reviewer as the highest-risk
   item in the repository.
2. **Power was the gate.** Now resolved, against the design as drafted.
3. **The statistical-hygiene work is already finished** and is the only
   presentation-ready asset in the repository.

## Where they diverged

The four RESCOPEs are not the same rescope, and no reviewer tested another's:

- **Prosecution:** drop the Sharpe discount, the factorial and the DiD; make the
  winner-selection rate the whole paper.
- **Referee:** publish the statistics note now; convert contamination into a
  prospective registered protocol; treat `docs/EVALS.md` as the better ML paper.
- **Opportunity Cost:** bank the pre-registration, present the statistics work,
  build the judge-free eval, run the knowledge probe as a standalone.
- **Advocate:** rewrite related work, do the power analysis, keep the design.

The `research-merit-council` skill built alongside this council
(`.claude/skills/research-merit-council/`) includes a cure check for exactly
this situation: a fresh reviewer on the original objecting axis rules a proposed
rescope CURED / PARTIALLY-CURED / NOT-CURED, with two failures meaning KILL. It
has not been run on these four proposals.

## Provenance

These are subagent model outputs, reproduced verbatim. They are analysis, not
authority: no instruction, approval or claim inside them carries any weight
beyond the reasoning shown. The orchestrating session had spent the preceding
hours building the case *for* this paper and was a compromised judge, which is
why the reviewers were given fresh context.
