---
name: research-merit-council
description: Use when deciding whether a research direction, hypothesis, paper, study design, experiment, or strategic pivot is worth the investment — and at what scope — rather than how to execute it. Convenes a hostile council of fresh-context subagents (referee, statistician, prior-art skeptic, practitioner, opportunity-cost advisor, and one steelmanning advocate), cross-examines every objection with a different persona, and returns a PURSUE / RESCOPE / KILL decision memo naming the strongest surviving argument on each side and what would flip it. Trigger whenever someone asks "is this worth pursuing", "should I spend the next N weeks on this", "is this publishable", "would a reviewer buy this", "should we pivot", or hands over a proposal, prospectus, research plan, or draft for a go/no-go call — especially when the person asking built the thing and is therefore a compromised judge of it. For auditing code or an implementation rather than judging whether an idea deserves the time, use adversarial-code-audit instead.
---

# Research Merit Council

## Overview

**A merit council IS "trust nothing" applied to the decision to spend weeks of your life on something.** Independent subagents attack the research direction from separate angles, then attack each other's attacks, and only objections that survive hostile refutation shape the verdict. The output is not a list of concerns — it is a **decision memo** a person can act on the same day.

**Core principle:** A conclusion is not credible because allied agents agreed on it. It is credible because a hostile agent with fresh context tried to destroy it and failed. Agreement between allies is not evidence.

This skill is the sibling of `adversarial-code-audit`, which uses the same dispatch discipline — fresh context per subagent, hostile framing, no cross-contamination — but audits **code**. That skill explicitly refuses hypothesis-worthiness questions. This one takes them.

**Verdicts are three-way, never binary: PURSUE / RESCOPE / KILL.** "Yes but smaller" is the most common correct answer to a research question and the hardest to say out loud, which is exactly why it gets a first-class seat here. A RESCOPE verdict is only valid if it names the narrower version.

## Two Rules That Make This Work

Everything else in this skill is machinery. These two are the point.

### 1. The Anti-Theater Rule

Several personas here are assigned a *stance* — the Advocate must argue for, the Referee must argue for rejection, the Priority Skeptic must argue the question is already answered. A stance is a starting posture, not a quota.

**Any persona that cannot honestly make its assigned case after genuine investigation must say so explicitly, name what it tried, and explain why the case failed.** Conceding is a valid and valuable output. It is often the single most informative line in the whole council.

The reason is not politeness — it is that manufactured arguments destroy the instrument. A decision-maker reading five objections cannot tell which two are real if three were invented to fill a template. Every fabricated concern raises the noise floor and makes the real one easier to dismiss. A council where the Referee says "I genuinely could not construct a desk-reject argument, here are the three I tried and why each collapsed" gives the reader more signal than one where every persona dutifully produced three bullet points.

The same applies in reverse: an Advocate that cannot find a real case for the work must say "I could not steelman this" rather than assembling enthusiasm. That single sentence is frequently the KILL.

Record every concession in the dossier. A concession is a finding, not a gap.

### 2. The Conflict-of-Interest Rule

If you — the orchestrator running this council — have been building, drafting, designing, or advocating for the thing under review, **you are a compromised judge and you must say so in the memo**, in a named section, in plain language.

This is not a formality. You have sunk cost in the idea, you have context that reads as evidence but is actually familiarity, and you have already rehearsed the counter-arguments to every objection the council will raise. That rehearsal feels like rigor. It is anchoring.

The entire architecture of fresh-context subagents exists to route around you. So:

- Write the charter's framing of the idea as neutrally as you can, then check it for advocacy language before dispatching.
- Do not seed subagents with your own rebuttals to objections you anticipate.
- When an objection lands that you "already know the answer to," route it through cross-examination anyway. Your answer is exactly the artifact under suspicion.
- In the memo, state your involvement, state which direction it biases you, and state whether the verdict agrees or disagrees with your prior. A verdict that agrees with the compromised judge's prior deserves an extra sentence of scrutiny, and the reader deserves to know to apply it.

If you have no stake — you were handed someone else's proposal cold — say that too. It is useful information about how much the memo can be trusted on its own.

## When to Use

**Use when:**
- Someone is deciding whether to commit weeks or months to a research direction, experiment, paper, or pivot
- A study design needs a go/no-go before data collection starts, while changing it is still cheap
- A draft or proposal needs to survive a plausible referee, funder, or reviewer before submission
- The question is "is this worth doing at all" or "is this worth doing *at this size*"
- A prior review was too friendly — everyone liked it, nobody tried to kill it
- The person asking is the person who built it, and needs a judgment their own enthusiasm cannot reach

**Do NOT use when:**
- **The decision is cheap and reversible.** If the thing costs an afternoon and can be abandoned without consequence, run it and find out. A six-persona council to decide a two-hour experiment is a way of avoiding the experiment.
- **The user has already decided and wants execution help.** Adversarial review of a settled decision is demoralizing and useless. If they want help running the study, help them run the study. If you suspect the decision is bad, say so in one paragraph and ask whether they want it challenged — do not ambush them with a council.
- **It is a code or implementation question** — "is this pipeline correct", "will this scale", "is this signal implemented right". Use `adversarial-code-audit`.
- **The cost is unknown.** The charter cannot be written without a time and resource estimate, and the Opportunity Cost Advisor has nothing to weigh. Get the estimate first; it is often the whole decision.
- **The real objective is the doing, not the result.** If someone wants to pursue a direction because they want to learn the method or because the problem delights them, a merit council will return a technically correct KILL to a question nobody asked. Surface the real objective first.
- **The commitment is already irreversible** — funded, announced, staffed. Then the useful question is "how do we de-risk it", not "should we".

## Workflow at a Glance

```
Phase 0  Charter & COI Declaration  → decision-charter.md (the claim, the ask, the alternatives, your stake)
Phase 1  Independent Investigation  → N personas in parallel, isolated contexts, one dossier each
Phase 2  Cross-Examination          → every objection AND every advocate claim refuted by a DIFFERENT persona
Phase 3  Arbitration                → surviving disputes ruled on, or escalated to the user
Phase 4  Rescope Design + Memo      → named narrower version (if any), then decision-memo.md
```

Persona attack surfaces, boundaries, and false-positive self-checks live in [personas.md](personas.md).
Dispatch templates for every role, plus the dossier record schema, live in [prompts.md](prompts.md).

Save all artifacts under one directory, e.g. `docs/merit/<date>-<topic>/`. Do not scatter them.

## Phase 0 — Charter & Conflict Declaration

Before dispatching anyone, write `decision-charter.md`. It is the frozen frame every persona argues inside. It captures:

- **The claim under review** — stated in one or two sentences, as a falsifiable proposition where possible, in neutral language. "Retail order-flow imbalance predicts next-day returns in small caps" is a claim. "Exploring the exciting intersection of order flow and returns" is not.
- **The ask** — what committing actually costs: person-weeks, compute, data licences, access to subjects, calendar time. If this is unknown, stop and get it.
- **The decision-maker and their constraints** — who lives with this, what they need (a paper? a product? a grant?), what their deadline and career/organizational constraints are. An objection that ignores the decision-maker's actual goal is noise.
- **The frozen artifact set** — the exact drafts, notebooks, prior results, preregistration, or design docs every persona reads. Pin file paths and versions. If the proposal changes mid-council, halt and re-freeze; personas arguing about different versions of the idea produce a useless memo.
- **Success criteria** — what "this worked" would concretely look like in 6 months. If nobody can state this, that is itself a finding, and the Practitioner should be told about it.
- **The counterfactual set** — the 2-5 other things this person could do with the same weeks, named specifically. Without this the Opportunity Cost Advisor invents alternatives, and invented alternatives are unbeatable.
- **Persona set** — which personas from [personas.md](personas.md) apply. Dropping one is allowed but must be justified in one sentence. The Advocate is never dropped.
- **Conflict-of-interest declaration** — your stake in the outcome, per the rule above. Written here, carried into the memo.

Do not put your own assessment in the charter. The charter frames; it does not judge.

## Phase 1 — Independent Investigation

Dispatch one **fresh** subagent per selected persona, **in parallel**, using the investigator template in [prompts.md](prompts.md). Each gets the charter, the frozen artifacts, and its own persona brief — and nothing from any other persona.

Parallelism is not just speed here. It is the isolation mechanism. A persona that has read another persona's dossier is no longer an independent draw, and the council collapses into the agreement-between-allies failure it exists to prevent.

Each persona returns **objections** (the Advocate returns **affirmative claims**) in the dossier schema. Every objection must carry:

- A **mechanism**: "If X, then Y, because Z" — not "there may be concerns about X."
- **Grounding**: a citation to the frozen artifacts, to prior literature, to a specific number, or to an explicit statement that this is a judgment call and what it rests on. A well-labelled judgment call is admissible; an unlabelled one is not.
- A **severity class**, which is the load-bearing field for the verdict:
  - `FATAL` — no version of this work is worth the ask. If true, this is a KILL on its own.
  - `SCOPE-FATAL` — this version is not worth the ask, but some identifiable narrower version might be. Must name the surviving fragment, even roughly.
  - `COSTLY` — survivable, but raises the price or lowers the expected payoff. Accumulates; does not kill alone.
- A **flip condition**: what specific, observable finding would make this objection go away. This field is what makes the memo actionable, so do not accept "more evidence" — accept "a power calculation showing n≥400 is reachable from the existing panel."

Objections lacking a mechanism or grounding are **rejected at intake by the controller**. Do not merge them into the dossier and do not "downgrade" them — they never enter.

Then assign global IDs (`O-001`, `O-002`, … for objections; `A-001`, … for advocate claims) and record the originating persona and its initial severity class. Downstream personas never see the originator's identity or severity.

## Phase 2 — Cross-Examination

Every objection is routed to a **different-persona** subagent whose job is to **dissolve** it. Every advocate claim is routed the same way. The affirmative case gets attacked exactly as hard as the negative case — otherwise the council is just a firing squad with extra steps.

The cross-examiner receives the claim, its mechanism and grounding, and the charter. It does **not** receive the originator's persona, severity class, or confidence.

Verdicts:

- `STANDS` — refutation failed. The objection holds at its stated severity.
- `NARROWED` — the objection is real but applies to less than claimed: a subset of the scope, a specific population, one arm of the design. **This is the main engine of RESCOPE verdicts**, so the cross-examiner must state exactly what the objection does *not* reach.
- `DOWNGRADED` — real but the severity class is inflated (typically FATAL → SCOPE-FATAL, or SCOPE-FATAL → COSTLY). State the corrected class and why.
- `DISSOLVED` — the objection rests on a misreading of the artifacts, a factual error, or a concern the charter already addresses. Must cite what it got wrong.
- `DUPLICATE-OF-Onnn` — subsumed by another objection. Cite which.
- `NEEDS-EVIDENCE` — plausible but the chain has a gap. Name the specific evidence that would settle it. Routed back to the originator for **one** round, then re-ruled. A second gap means `DISSOLVED`. No infinite loops.

A cross-examiner that cannot dissolve an objection says so and names the angles it tried. Per the anti-theater rule, it does not manufacture a dissolution to look productive.

## Phase 3 — Arbitration

Any claim still in dispute goes to a single **arbitrator** subagent per dispute — fresh, with no prior role on that claim. Disputes are: contested severity class, a `NARROWED` verdict whose remaining scope is unclear, a `DUPLICATE-OF` chain that is ambiguous, or a direct collision between an advocate claim and an objection that each survived the other.

That last case matters most. When `A-002` ("the dataset is unique and nobody else can run this") and `O-004` ("three groups have comparable data and one has published on it") both survived cross-examination, the council has found the crux of the decision. Arbitrate it explicitly; do not average it.

The arbitrator re-reads the frozen artifacts and rules: `UPHELD`, `UPHELD-NARROWED` (with the surviving scope named), `DISSOLVED`, or `ESCALATE-TO-USER`.

**Escalation is a valid ruling.** Some cruxes turn on facts only the decision-maker holds — whether the collaborator will actually deliver the data, whether the committee cares about this subfield, how much runway there is. State the exact question and move on. Do not guess on the user's behalf and do not let a coin-flip harden into a verdict.

## Phase 4 — Rescope Design and the Decision Memo

### 4a. Verdict arithmetic

Determine the verdict from the surviving claims. **Do not count votes.** One surviving FATAL objection outweighs five personas who liked it; that asymmetry is the entire design.

- Any surviving `FATAL` objection → **KILL**.
- No FATAL, but one or more surviving `SCOPE-FATAL` objections → **RESCOPE**, if and only if a narrower version survives 4b. If no narrower version survives, the verdict is KILL, not a reluctant PURSUE.
- No FATAL, no SCOPE-FATAL, and at least one advocate claim survived cross-examination → **PURSUE**. Surviving COSTLY objections do not block it; they become the conditions and risks section of the memo.
- No FATAL, no SCOPE-FATAL, and **no** surviving advocate claim → this is a KILL, and a quiet one. The work has no fatal flaw and no reason to exist. Say that plainly; it is the most commonly missed verdict.

### 4b. Rescope design (only when heading toward RESCOPE)

Dispatch a fresh **Rescope Architect** using the template in [prompts.md](prompts.md). It receives the surviving SCOPE-FATAL objections and the surviving advocate claims, and must produce a **named, specific** narrower version: what is cut, what remains, the new ask in weeks, and which specific objections the cut is supposed to cure.

"A smaller pilot version" is not a rescope. "A single-site retrospective on the 2019–2022 cohort already in hand, 3 weeks, dropping the prospective arm entirely" is.

Then **verify the cure**: send the named narrower version back to the persona whose objection it claims to resolve, and ask whether it actually does. A rescope that does not survive this check is a fudge wearing a verdict's clothing — either the Architect tries once more, or the verdict is KILL.

### 4c. The decision memo

`decision-memo.md` is the deliverable. Not a findings list. Its structure:

```markdown
# Decision Memo: <claim under review>

## Verdict
PURSUE | RESCOPE | KILL — in the first line, with the one-sentence reason.
If RESCOPE: the named narrower version, in one sentence, right here.

## The ask
What was proposed, and what it costs. One short paragraph.

## Strongest surviving argument FOR
The single best case that survived hostile cross-examination. One paragraph.
If none survived, say so explicitly — that is a finding, not an omission.

## Strongest surviving argument AGAINST
The single best objection that survived. One paragraph, with its severity class.
If none survived, say so — an idea that no hostile persona could dent is rare and worth flagging as such.

## What would flip this verdict
2-4 specific, observable findings, each with the cheapest way to check it.
"If a power calculation shows n≥400 is reachable from the existing panel, this goes from RESCOPE to PURSUE."
Where a single uncertainty dominates, name the cheapest test that resolves it and
say what it costs — often a day of work replaces the whole debate.

## If RESCOPE: the narrower version
What is cut, what remains, the new ask, which objections the cut cures,
and confirmation that the cure was verified against the objecting persona.

## Conditions and residual risks
Surviving COSTLY objections, as things to manage rather than reasons to stop.

## Conceded arguments
Where a persona could not honestly make its assigned case, and why.
This section is signal. Do not omit it because it looks like empty space.

## Compromised judge declaration
The orchestrator's stake in the outcome, the direction it biases, and whether
this verdict agrees with that prior.

## Open questions for the decision-maker
Anything the arbitrator escalated, stated as answerable questions.
```

Keep it to roughly two pages. A decision memo that takes an hour to read has failed at being a decision memo.

Also write `council-dossier.md` — the full trail of every claim, verdict, and ruling, per the schema in [prompts.md](prompts.md). The memo is the deliverable; the dossier is the proof the council was adversarial and not laundered.

## Anti-Collusion Contracts

1. **Independence.** No persona in Phase 1 sees another's dossier, and no cross-examiner knows which persona raised the claim it is attacking. Once personas read each other, they stop being independent draws.
2. **Persona hygiene.** Cross-examiner persona ≠ originator persona. Arbitrator has played no prior role on that claim. The Rescope Architect is a fresh dispatch.
3. **Symmetric hostility.** Advocate claims are cross-examined as hard as objections. A council that only attacks the negative case is a rubber stamp; one that only attacks the positive case is a guillotine.
4. **No consensus laundering.** An objection does not become decisive because three personas raised something similar. It becomes decisive because a hostile cross-examiner tried to dissolve it and failed.
5. **Grounding discipline.** Every claim cites the frozen artifacts, the literature, a number, or an explicitly labelled judgment call. Unlabelled intuition is rejected at intake.
6. **Severity honesty.** `FATAL` means "no version of this is worth it." Inflating a COSTLY objection to FATAL to force a KILL is theater in the other direction, and cross-examination exists partly to catch it.
7. **The charter is frozen.** If the proposal changes mid-council, halt and re-freeze. Personas arguing about different versions of the idea produce a memo about nothing.

## Rationalization Table

Every row is a shortcut the controller will reach for under pressure. All of them mean **stop and follow the protocol**.

| Excuse | Reality |
|---|---|
| "Four personas flagged the sample size — it's obviously fatal." | Agreement between allies is not evidence. Route it through a hostile cross-examiner like everything else. |
| "The Advocate's case is weak, so I'll skip cross-examining it." | Symmetric hostility is the whole design. An uncontested advocate claim cannot carry a PURSUE verdict. |
| "The Referee found nothing, so that dispatch was wasted." | A persona that genuinely could not make its case is the most informative output in the council. Record it. |
| "I need three objections per persona to make the memo look thorough." | Manufactured objections raise the noise floor and hide the real one. Quotas are the anti-theater rule's exact target. |
| "This is really a RESCOPE but I can't articulate the smaller version — I'll say RESCOPE anyway." | A RESCOPE without a named narrower version is a fudge. Either the Architect names it or the verdict is KILL. |
| "I built this, but I'm being objective about it." | Everyone believes that. That belief is the bias. Declare the conflict and let the fresh-context personas do their job. |
| "I already know the answer to that objection." | Your pre-rehearsed answer is the artifact under suspicion. Cross-examine it. |
| "Two personas disagree; I'll split the difference." | Averaging hostile verdicts destroys the information. Arbitrate the crux or escalate it. |
| "The memo should list all findings so the reader can decide." | The reader asked for a decision. A findings list delegates the judgment back to them and is the failure mode this skill exists to prevent. |
| "Nobody found anything fatal, so PURSUE." | Absence of fatal flaws is not a reason to do something. If no advocate claim survived, it is a KILL. |
| "The opportunity cost persona needs alternatives and the charter has none — I'll invent some." | Invented alternatives are unbeatable straw men. Get real ones from the decision-maker or drop the persona. |
| "Merging two personas into one subagent saves dispatches." | Persona fusion destroys independence. The separation is the mechanism, not the packaging. |

## Red Flags — STOP and Restart the Affected Phase

- A claim advanced past intake **without a mechanism or grounding** → reject the claim, do not downgrade it.
- A cross-examiner **shares a persona** with the originator → re-dispatch with a different persona.
- **Every persona produced exactly the same number of objections** → strong signal of quota-filling. Re-read the dossiers for manufactured concerns and re-dispatch the suspect personas with the anti-theater rule emphasized.
- **No concessions anywhere in the council** → suspicious. Genuine hostile investigation of a real idea almost always produces at least one persona that could not make its case.
- A `RESCOPE` verdict **with no named narrower version**, or one that never went through the 4b cure check → protocol violation; the verdict is not valid.
- The memo **has no "what would flip this" section**, or fills it with "more data" → the memo is not actionable; re-derive it from the flip conditions on surviving claims.
- The orchestrator built the thing and **the memo has no conflict declaration** → non-negotiable; add it.
- The verdict **agrees with the orchestrator's stated prior and no objection survived** → not automatically wrong, but re-read the charter for advocacy language and check that the Referee and Priority Skeptic were dispatched with full hostility.
- Two phases ran **against different versions of the proposal** → invalidate, re-freeze, re-run the affected phases.

## Skill Execution Checklist

Create a todo per item.

**Phase 0 — Charter:**
- [ ] State the claim as a falsifiable proposition, in neutral language
- [ ] Quantify the ask (person-weeks, compute, data, calendar)
- [ ] Identify the decision-maker, their goal and their constraints
- [ ] Freeze and pin the artifact set
- [ ] Name 2-5 real counterfactual uses of the same time
- [ ] Select personas (Advocate is mandatory); justify any drop
- [ ] Write the conflict-of-interest declaration

**Phase 1 — Investigation:**
- [ ] Dispatch one fresh subagent per persona, in parallel, isolated
- [ ] Reject at intake any claim without mechanism or grounding
- [ ] Confirm every claim carries a severity class and a flip condition
- [ ] Record concessions as findings

**Phase 2 — Cross-Examination:**
- [ ] Cross-examine every objection with a different persona
- [ ] Cross-examine every advocate claim just as hard
- [ ] Withhold originator persona and severity from the cross-examiner
- [ ] Run NEEDS-EVIDENCE reroutes once, then rule

**Phase 3 — Arbitration:**
- [ ] Dispatch a fresh arbitrator per surviving dispute
- [ ] Arbitrate advocate-vs-objection collisions explicitly — that is the crux
- [ ] Allow ESCALATE-TO-USER

**Phase 4 — Verdict and Memo:**
- [ ] Apply the verdict arithmetic; do not count votes
- [ ] If heading to RESCOPE, dispatch the Rescope Architect and verify the cure
- [ ] Write `decision-memo.md` in the required structure
- [ ] Write `council-dossier.md` with the full trail
- [ ] Verify the memo names flip conditions with cheapest checks
- [ ] Verify the conflict declaration is present and honest

## The Bottom Line

**Attack it before you fund it.** An idea that survives six hostile personas with fresh context is worth weeks of someone's life. An idea that survives only its author's enthusiasm is not, and no amount of agreement among friendly reviewers converts one into the other. The verdict is the deliverable; the surviving arguments are its justification; the dossier is the proof the hostility was real. And when the honest answer is "this is good, but a third of the size" — say that, name the third, and hand over a memo someone can act on this afternoon.
