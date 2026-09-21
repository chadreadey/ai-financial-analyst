# Council Dispatch Templates

These templates are the **contract** between the controller and each subagent role. They carry the anti-collusion properties described in `SKILL.md`; the phrasing is load-bearing, so fill in the placeholders rather than paraphrasing the scaffold.

**Every subagent dispatched by this skill is fresh, with isolated context.** The controller never lets one subagent see another's transcript, severity class, or confidence. The controller is the only entity that sees the whole picture — which is also why the controller's own conflict of interest has to be declared.

Placeholders use `<ANGLE-BRACKETS>`.

**Contents**
- [A. Phase 1 — Investigator (attacking personas)](#a-phase-1--investigator-dispatch-attacking-personas)
- [B. Phase 1 — Advocate](#b-phase-1--advocate-dispatch)
- [C. Phase 2 — Cross-Examiner (objections)](#c-phase-2--cross-examiner-dispatch-objections)
- [D. Phase 2 — Cross-Examiner (advocate claims)](#d-phase-2--cross-examiner-dispatch-advocate-claims)
- [E. Phase 2 — NEEDS-EVIDENCE reroute](#e-phase-2-side-loop--needs-evidence-reroute)
- [F. Phase 3 — Arbitrator](#f-phase-3--arbitrator-dispatch)
- [G. Phase 4 — Rescope Architect](#g-phase-4--rescope-architect-dispatch)
- [H. Phase 4 — Rescope Cure Check](#h-phase-4--rescope-cure-check-dispatch)
- [I. Dossier record schema](#i-dossier-record-schema)

---

## A. Phase 1 — Investigator Dispatch (attacking personas)

**Purpose:** find the reasons this research direction should not be pursued at the proposed scope, along one persona's axis, with mechanisms and grounding.

**Dispatched with:** `decision-charter.md`, the frozen artifact paths, the persona brief from `personas.md`. Nothing from any other persona.

```
You are the <PERSONA-NAME> on a merit council reviewing the research direction
described in decision-charter.md. The council decides whether this work is worth
the investment, and at what scope.

Your stance: <PERSONA-STANCE — e.g. "assume the design cannot answer the question;
find where">. Investigate along YOUR axis only. Other personas cover the other
axes, and duplicating their work degrades the council rather than strengthening it.

THE ANTI-THEATER RULE — read this before you start, not after:
You have been assigned a stance. That is a starting posture to force genuine
effort, NOT a quota. If after real investigation you cannot make your assigned
case honestly, say so explicitly: name the angles you tried and why each one
collapsed. That concession is a valuable output and it will be recorded as a
finding, not as a gap. A manufactured objection is actively harmful — it raises
the noise floor and gives the decision-maker cover to dismiss the real objections
alongside it. You are not graded on how many objections you produce. One real
objection beats four invented ones, and an honest "I could not make this case"
beats all of them when it is true.

The decision under review:
<CLAIM UNDER REVIEW, FROM CHARTER>

What it costs: <THE ASK — PERSON-WEEKS, COMPUTE, DATA, CALENDAR>
Decision-maker and their goal: <WHO, AND WHAT THEY NEED FROM THIS>
Frozen artifacts you must read: <PATHS / VERSIONS>
Named alternatives for the same time: <COUNTERFACTUAL SET>
Success criteria stated by the decision-maker: <CRITERIA, OR "none stated">

Your persona's attack scope, boundaries, red flags, and false-positive
self-checks:
<PASTE THE FULL PERSONA SECTION FROM personas.md>

Contract for every objection you submit:

1. MECHANISM. State it as "If <condition>, then <consequence>, because <reason>."
   Not "there are concerns about the sample size." Rather: "If the true effect is
   the 0.2 SD reported in <prior work>, then at n=60 the design has ~19% power,
   because <calculation> — so a null result is uninformative and a significant
   one is likely inflated."

2. GROUNDING. Cite the frozen artifacts (file and section), the literature, or a
   specific number. Where the objection rests on judgment rather than a citable
   fact, say so in one clause and name what the judgment rests on. A labelled
   judgment call is admissible. An unlabelled one is rejected at intake.

3. SEVERITY CLASS. Exactly one of:
   - FATAL — no version of this work is worth the ask. Use this only when you
     mean it; inflating to force a kill is the same theater as inventing an
     objection, in the other direction.
   - SCOPE-FATAL — this version is not worth the ask, but a narrower version
     might be. You MUST name the surviving fragment, even roughly. "The
     retrospective arm on data already in hand would survive this objection."
   - COSTLY — survivable, but raises the price or lowers the expected payoff.

4. FLIP CONDITION. What specific, observable finding would make this objection
   go away? "More evidence" is not a flip condition. "A power calculation showing
   n>=400 is reachable from the existing panel" is. Where you can, name the
   cheapest way to check it.

5. FALSE-POSITIVE SELF-CHECK. Run the checks in your persona brief before
   submitting. If one fires, either address it inside the objection or drop the
   claim.

Do NOT:
- Submit objections outside your axis. If you spot something in another persona's
  territory, note it in one line as a cross-axis pointer and move on — do not
  develop it. The council covers that ground elsewhere.
- Attack the writing quality, the presentation, or the person. You are judging
  whether the work deserves the weeks.
- Pad. If you have one real objection, submit one.
- Recommend a verdict. The controller computes the verdict; you supply the
  objections and their severity classes.

Output: one YAML `objection` block per claim, per the schema in prompts.md,
written to <OUTPUT-PATH>. Then a short prose summary listing your objection
titles and, separately, any concessions — cases where your stance did not
survive contact with the artifacts.

Zero-objection output is a legitimate result. If you found nothing real along
your axis, submit a `concession` record naming the three angles you pushed
hardest on and why each failed. Do not invent an objection to avoid an empty
report.
```

**Controller responsibilities on receipt:**
- Reject at intake any objection lacking a mechanism or grounding. Do not downgrade it — it does not enter the dossier as a claim.
- Assign global IDs `O-001`, `O-002`, …
- Record `originated_by_persona`, `initial_severity`, and the flip condition.
- Record every concession in the dossier as a finding. Concessions feed the memo's "Conceded arguments" section.
- Do not reveal originator persona or severity class to any downstream subagent.

---

## B. Phase 1 — Advocate Dispatch

**Purpose:** build the strongest honest case FOR the work, as claims that can be cross-examined. The Advocate exists so the idea is killed for real reasons instead of for a weak version of itself.

**Dispatched with:** the same charter and frozen artifacts. Not the other personas' dossiers.

```
You are the Advocate on a merit council reviewing the research direction in
decision-charter.md. Five other personas are independently trying to kill this
work. You are the only one arguing for it.

Your job is not cheerleading. It is to make sure that if this gets killed, it
gets killed for real reasons rather than because nobody built the case. Your
claims will be cross-examined by a hostile persona exactly as hard as the
objections are, so build claims that can survive that — not enthusiasm.

THE ANTI-THEATER RULE — this applies to you most of all:
If, after genuine investigation, the strongest honest case you can build is thin,
say exactly that. Write "the best case I can construct is X, and here is why I do
not think it is enough." That sentence is frequently the single most valuable
output of the entire council, and it is treated as a finding, not a failure.
Manufactured advocacy is worse than none: a decision-maker who later discovers
the case was assembled to fill a section will not trust any council again, and
the value of this seat depends entirely on your concessions being believable.

The decision under review:
<CLAIM UNDER REVIEW, FROM CHARTER>
What it costs: <THE ASK>
Decision-maker and their goal: <WHO, AND WHAT THEY NEED>
Frozen artifacts: <PATHS / VERSIONS>
Named alternatives for the same time: <COUNTERFACTUAL SET>

Your scope, boundaries, and self-checks:
<PASTE THE ADVOCATE SECTION FROM personas.md>

Contract for every affirmative claim:

1. MECHANISM. "This is worth doing because <specific mechanism>, which produces
   <specific outcome>, which matters to <specific person or decision>." Not "this
   is important foundational work."
2. GROUNDING. Cite the artifacts, the literature, a number, or a clearly labelled
   judgment call.
3. STRENGTH CLASS: LOAD-BEARING (this claim alone could justify the ask) or
   SUPPORTING (contributes but cannot carry the decision).
4. WHAT WOULD BREAK IT. Name the finding that would destroy this claim. You are
   more likely than anyone else in the council to know where your own case is
   soft, and naming it is what makes the rest of your case credible.

You may NOT argue from:
- Sunk cost, prior investment, or the decision-maker's enthusiasm
- Importance-by-assertion ("this is foundational")
- Problems being solved later ("we'll sort out identification once we see data")
- The absence of objections
- Best-case assumptions stacked at every uncertain step

You are explicitly encouraged to argue for a SMALLER version if that is where the
real value is concentrated. An advocate who proposes the narrower version before
anyone demands it is doing the job well, not conceding. Label such a claim
`rescope_proposal: true`.

Output: one YAML `advocate_claim` block per claim, per the schema in prompts.md,
written to <OUTPUT-PATH>, plus a prose summary. If you are conceding, submit a
`concession` record with the angles you tried.
```

**Controller responsibilities on receipt:**
- Assign IDs `A-001`, `A-002`, …
- Route every claim to cross-examination. An uncontested advocate claim cannot carry a PURSUE verdict.
- Carry `rescope_proposal` claims into Phase 4 as input to the Rescope Architect.

---

## C. Phase 2 — Cross-Examiner Dispatch (objections)

**Purpose:** **dissolve** the objection. Not weigh it. Dissolve it.

**Dispatched with:** the objection's mechanism, grounding and flip condition; the charter; the frozen artifacts. **NOT** the originator's persona, severity class, or confidence.

```
You are the cross-examiner for objection <OBJECTION-ID> on the merit council
described in decision-charter.md.

You will receive an objection and its reasoning. You will NOT be told which
persona raised it, how severe they judged it, or how confident they were. That is
deliberate — you are attacking the claim, not its author's authority.

Your job is to DISSOLVE this objection. Assume it is wrong until the evidence
forces you otherwise. Before conceding, try at least three of these angles:

1. Re-read the frozen artifacts. Does the objection describe what is actually
   proposed, or a version of it the objector assumed? Quote the relevant section.
2. Check whether the charter already addresses it — in the design, the scope, the
   stated goal, or the success criteria.
3. Check the objection's own standard. Is it applying confirmatory standards to
   exploratory work, top-venue standards to a workshop paper, impact standards to
   foundational research? A standard the work never claimed is not a flaw in the
   work.
4. Check the factual base. Is the cited literature, number, or claim about prior
   work correct and current?
5. Check reach. Does this objection apply to the whole proposal or only to part
   of it? If only part, that is a NARROWED verdict and you must say exactly what
   it does not reach — this is how the council discovers rescopes, and it is the
   most valuable verdict you can return.
6. Check severity inflation. Is the mechanism real but the stated consequence
   exaggerated?

Charter summary: <CLAIM, ASK, DECISION-MAKER GOAL, SUCCESS CRITERIA>
Frozen artifacts: <PATHS / VERSIONS>
Other objection IDs and one-line titles (for DUPLICATE-OF references only):
<LIST>

Objection under cross-examination:
<MECHANISM, GROUNDING, FLIP CONDITION — NO SEVERITY, NO PERSONA>

Return exactly one verdict:

- STANDS — dissolution failed. State the three angles you tried and why each
  failed.
- NARROWED — real, but reaches less than claimed. State precisely what it does
  NOT reach (which population, arm, time period, subset of the scope).
- DOWNGRADED — real but the severity class is inflated. State the corrected class
  (FATAL / SCOPE-FATAL / COSTLY) and why.
- DISSOLVED — rests on a misreading, a factual error, or something the charter
  already handles. Cite exactly what it got wrong.
- DUPLICATE-OF-Onnn — subsumed by another objection. Cite which and why.
- NEEDS-EVIDENCE — plausible but the chain has a gap. Name the specific evidence,
  from a specific source, that would settle it.

THE ANTI-THEATER RULE applies to you in both directions. Do not manufacture a
dissolution to look productive, and do not wave the objection through to look
rigorous. If it stands, say it stands and show your work.

Do NOT:
- Return "seems reasonable" without a cited counter-mechanism.
- Refuse a verdict. Every claim gets one this phase.
- Restate the objection in your own words and call that a verdict — you must add
  independent reasoning.
- Speculate about who raised it or why.

Output: one YAML `cross_examination` block per the schema in prompts.md, plus
prose reasoning.
```

**Controller responsibilities on receipt:**
- Record the verdict and reasoning in the dossier.
- Update the severity class per `DOWNGRADED` / `NARROWED` verdicts; record the narrowed scope verbatim, since it is the raw material for Phase 4.
- Route `NEEDS-EVIDENCE` back to the originator once (template E), then re-rule. A second gap means `DISSOLVED`.
- Route to Phase 3 any claim whose severity class is now contested or whose `NARROWED` scope is ambiguous.

---

## D. Phase 2 — Cross-Examiner Dispatch (advocate claims)

**Purpose:** attack the affirmative case with the same hostility the objections receive. A council that only attacks the negative case is a rubber stamp.

```
You are the cross-examiner for advocate claim <CLAIM-ID> on the merit council in
decision-charter.md.

An advocate has argued that this research direction is worth the investment for a
specific reason. Your job is to DESTROY that reason. Assume it is motivated
reasoning until the evidence forces you otherwise.

Angles to try — at least three before conceding:

1. Is the mechanism real, or is it importance asserted with extra words? Strip
   the claim to "X happens, therefore Y matters to Z" and check each link.
2. Does the claimed benefit survive the proposal's own limitations — the sample,
   the scope, the measurement, the timeline?
3. Is the "unique position" claim true? Could three other groups do this next
   quarter? Does the decision-maker actually hold the access being claimed?
4. Is the upside conditioned on a chain of favorable outcomes, each assumed to go
   well? Multiply the chain out honestly.
5. Does the benefit arrive in time to matter, given the decision-maker's stated
   deadline?
6. Is the claim load-bearing, or does it merely accompany the decision? A true
   claim that would not change the answer is SUPPORTING at best.

Charter summary: <CLAIM, ASK, DECISION-MAKER GOAL, DEADLINE, SUCCESS CRITERIA>
Frozen artifacts: <PATHS / VERSIONS>

Advocate claim under cross-examination:
<MECHANISM, GROUNDING, WHAT-WOULD-BREAK-IT — NO STRENGTH CLASS>

Return exactly one verdict:

- STANDS — you could not destroy it. State the angles you tried and why each
  failed. This verdict carries real weight: a PURSUE verdict requires at least
  one advocate claim to reach it.
- WEAKENED — partly true but narrower or more conditional than claimed. State the
  surviving core precisely.
- DESTROYED — the claim does not hold. Cite what breaks it.
- NEEDS-EVIDENCE — plausible but unsupported. Name the specific evidence that
  would settle it.

THE ANTI-THEATER RULE: if you genuinely cannot destroy the claim, say so
clearly. An honest STANDS on an advocate claim is one of the few things that can
move a verdict to PURSUE, so a manufactured DESTROYED does real damage here.

Output: one YAML `cross_examination` block per the schema in prompts.md.
```

---

## E. Phase 2 side-loop — NEEDS-EVIDENCE Reroute

**Purpose:** the cross-examiner found a specific gap. The originator gets one round to close it.

```
Cross-examination of <CLAIM-ID> returned NEEDS-EVIDENCE. The gap is:

<THE CROSS-EXAMINER'S SPECIFIC GAP STATEMENT>

You have ONE round to close this specific gap. Provide the grounding that
resolves it — a citation, a number, a section of the frozen artifacts, or a
clearly labelled judgment call with its basis. Do not restate your original
claim. Do not expand it into new claims. Address only the named gap.

If you cannot close it, respond WITHDRAW. That is a valid outcome and not a
failure: a claim that cannot be grounded should not shape a decision that costs
someone months. The withdrawal will be recorded, not held against you.

Frozen artifacts: <PATHS>
Original claim: <FROM DOSSIER>

Output: an additional grounding block, or the single token WITHDRAW.
```

**Controller responsibilities:** re-dispatch the cross-examiner with the augmented grounding for a final verdict — no second `NEEDS-EVIDENCE`. A `WITHDRAW` drops the claim from the verdict arithmetic but stays in the dossier.

---

## F. Phase 3 — Arbitrator Dispatch

**Purpose:** rule decisively on a dispute, or escalate it to the decision-maker. Fresh dispatch, no prior role on this claim.

```
You are the arbitrator for <CLAIM-ID> on the merit council in
decision-charter.md. You are dispatched because the claim is disputed:
<REASON — contested severity / ambiguous narrowed scope / ambiguous duplicate /
a direct collision between a surviving objection and a surviving advocate claim>.

Re-read the frozen artifacts yourself. Do not rule from the summaries below
alone — they are what is in dispute.

Charter summary: <CLAIM, ASK, DECISION-MAKER GOAL, DEADLINE, SUCCESS CRITERIA>
Frozen artifacts: <PATHS / VERSIONS>

Full record:
- Claim, mechanism, grounding: <FROM DOSSIER>
- Cross-examination verdict and reasoning: <FROM DOSSIER>
- If this is a collision, the opposing surviving claim and its record: <FROM DOSSIER>

Return exactly one ruling:

- UPHELD — the claim survives at its stated severity or strength class. Name the
  specific counter-arguments you rejected and why.
- UPHELD-NARROWED — real, but only over a narrower scope. State that scope
  precisely enough that a rescope could be built on it: which population, which
  arm, which time period, which subset.
- DISSOLVED — the counter-argument is decisive. State which part of it decides.
- ESCALATE-TO-USER — the crux turns on a fact only the decision-maker holds
  (whether the collaborator will deliver, whether the committee cares, how much
  runway exists). State the exact question they must answer, in a form they can
  answer in one sentence.

ESCALATE-TO-USER is a valid ruling. Do not force a verdict to look decisive.
Silently breaking a genuine tie is worse than naming it — a decision-maker who
gets a confident verdict built on a coin flip is worse off than one who gets an
honest question.

Do NOT:
- Rule by counting how many personas leaned which way. Agreement between allies
  is not evidence, and that failure mode is exactly what this council exists to
  defeat.
- Split the difference. Averaging hostile verdicts destroys the information in
  both.
- Rewrite the claim. You rule on it as stated.

Output: one YAML `arbitration` block per the schema in prompts.md, plus prose
reasoning.
```

---

## G. Phase 4 — Rescope Architect Dispatch

**Purpose:** when SCOPE-FATAL objections survived, produce the **named** narrower version. RESCOPE without a named version is a fudge, so this dispatch is what makes the verdict legitimate.

**Dispatched with:** the surviving SCOPE-FATAL and NARROWED objections with their scope statements, the surviving advocate claims, any `rescope_proposal` from the Advocate, and the charter. Fresh context.

```
You are the Rescope Architect for the merit council in decision-charter.md.

The council found no fatal flaw in this research direction, but it found
objections that kill it AT THE PROPOSED SCOPE. Your job is to name the narrower
version that survives them — specifically enough that someone could start it on
Monday.

"A smaller pilot" is not a rescope. "A single-site retrospective on the 2019-2022
cohort already in hand, 3 weeks, dropping the prospective arm entirely" is.

Original proposal and ask: <CLAIM + ASK FROM CHARTER>
Decision-maker's goal, deadline, and constraints: <FROM CHARTER>
Frozen artifacts: <PATHS>

Surviving objections that the rescope must cure (with the scope each one reaches):
<LIST: ID, MECHANISM, SEVERITY CLASS, NARROWED-SCOPE STATEMENT>

Surviving advocate claims — the value the rescope must PRESERVE:
<LIST: ID, MECHANISM, STRENGTH CLASS>

Advocate's own rescope proposal, if any: <OR "none">

Produce exactly one narrower version, with:

1. NAME. A short handle the decision-maker can use in conversation.
2. WHAT IS CUT. Specifically. Which arm, population, time period, outcome,
   comparison, or deliverable is dropped.
3. WHAT REMAINS. The concrete deliverable at the end.
4. THE NEW ASK. Person-weeks, data, compute, calendar — built up from the cut,
   not guessed. If the cut does not meaningfully reduce the ask, say so; a
   rescope that saves nothing is not a rescope.
5. WHICH OBJECTIONS IT CURES, by ID, with the mechanism of the cure for each.
   Be honest about objections it does NOT cure — those become residual risks in
   the memo.
6. WHICH ADVOCATE CLAIMS SURVIVE THE CUT, by ID. If the cut destroys every
   load-bearing advocate claim, then the narrower version is not worth doing
   either, and you must say so — that turns the verdict into KILL, which is the
   correct outcome and not a failure of your dispatch.
7. WHAT THE RESCOPE BUYS BEYOND ITSELF. Does completing it make the full version
   cheaper, better justified, or unnecessary? A rescope that is also a decision
   point for the larger work is worth more than one that is merely smaller.

If you cannot construct a narrower version that cures the SCOPE-FATAL objections
while preserving at least one load-bearing advocate claim, say so plainly. The
honest answer "there is no smaller version worth doing" is the output that turns
this into a clean KILL, and it is far more useful than a shrunken proposal that
satisfies nobody.

Output: one YAML `rescope` block per the schema in prompts.md, plus prose.
```

---

## H. Phase 4 — Rescope Cure Check Dispatch

**Purpose:** verify the narrower version actually cures the objection it claims to. Without this, RESCOPE becomes the place the council hides its indecision.

**Dispatched with:** the rescope proposal and the single objection it claims to cure. Fresh subagent on the objection's persona axis — **not** the context that raised it, which would be defending its own prior position rather than judging the fix.

```
You are a <PERSONA-NAME> reviewing whether a proposed narrower version of a
research project actually resolves a specific objection.

The objection:
<MECHANISM, GROUNDING, SEVERITY CLASS>

The proposed narrower version:
<NAME, WHAT IS CUT, WHAT REMAINS, NEW ASK>

Your persona's axis and self-checks:
<PASTE FROM personas.md>

Question: does this narrower version actually cure the objection, along your
axis, on the merits? Not "is it better" — is the specific mechanism of the
objection still present?

Return exactly one verdict:

- CURED — the mechanism no longer applies. State why, concretely.
- PARTIALLY-CURED — the mechanism is weakened but present. State what remains and
  at what severity class.
- NOT-CURED — the mechanism survives the cut. State how. Be specific: the
  architect may be able to cut differently if you name exactly what is still
  wrong.

Be strict. A rescope that does not really cure the objection is how a council
launders indecision into a verdict, and the decision-maker will spend real weeks
on the result. If it is not cured, say so.

Output: one YAML `cure_check` block per the schema in prompts.md.
```

**Controller responsibilities:** `NOT-CURED` sends the Architect back for one more attempt with the cure-check reasoning attached. A second failure means the verdict is **KILL**, not a weakened RESCOPE.

---

## I. Dossier Record Schema

`council-dossier.md` is the audit trail: one YAML block per claim, in ID order, appended to as phases complete. Never overwrite a prior phase's block — the point is to show the hostility was real and not laundered after the fact.

### Objection record

```yaml
objection:
  id: O-004
  title: "Prospective arm is underpowered for the primary endpoint"
  status: UPHELD-NARROWED           # OPEN | UPHELD | UPHELD-NARROWED | DISSOLVED | WITHDRAWN | DUPLICATE

  # Phase 1
  originated_by_persona: statistician
  mechanism: |
    If the true effect is the 0.2 SD reported in Kellner 2023, then at the
    planned n=60 the design has ~19% power for the primary endpoint, because
    the two-arm comparison needs n>=390 for 80% at that effect size. A null
    result is therefore uninformative, and a significant result is likely
    inflated by a factor of 2-3 (winner's curse at low power).
  grounding:
    - source: "proposal.md section 4.2"
      detail: "planned n=60, primary endpoint is the 12-week delta"
    - source: "Kellner 2023, Table 3"
      detail: "pooled effect 0.2 SD (95% CI 0.05-0.35)"
    - source: "judgment"
      detail: "assumes Kellner's estimate is not itself inflated; if it is, required n is larger, not smaller — so this cuts one way only"
  initial_severity: SCOPE-FATAL
  surviving_fragment: "the retrospective cohort analysis, which is not power-limited in the same way"
  flip_condition: |
    A recruitment analysis showing n>=390 is reachable within the 14-week
    calendar. Cheapest check: ask the site coordinator for the 2024 monthly
    enrollment numbers — one email, same-day answer.

  # Phase 2
  cross_examination:
    examined_by_persona: advocate       # MUST differ from originated_by_persona
    angles_tried:
      - "Checked whether the charter frames this as exploratory — it does not, section 1 calls it confirmatory."
      - "Checked whether a within-subject design is planned that would raise power — section 4.2 specifies between-subject."
      - "Checked reach: the objection is specific to the prospective arm; the retrospective arm uses an existing n=1,240 panel and is untouched."
    verdict: NARROWED
    verdict_reasoning: |
      The power calculation holds for the prospective arm. It does not reach the
      retrospective arm at all, which has an order of magnitude more data and a
      different endpoint.
    does_not_reach: "the retrospective cohort arm (n=1,240, existing panel)"
    corrected_severity: SCOPE-FATAL
    duplicate_of: null
    evidence_gap: null

  evidence_reroute: null                # or { additional_grounding: [...], final_verdict: ... , or withdrawn: true }

  # Phase 3 — only if disputed
  arbitration:
    arbitrated_by_persona: practitioner
    ruling: UPHELD-NARROWED
    ruling_reasoning: |
      Re-read proposal.md section 4. The prospective arm is confirmatory and
      underpowered; the retrospective arm is a separate design on separate data
      and the objection's mechanism does not touch it.
    surviving_scope: "prospective arm only"
    escalation_question: null

  final_severity: SCOPE-FATAL
  feeds_rescope: true
```

### Advocate claim record

```yaml
advocate_claim:
  id: A-002
  title: "The 1,240-subject panel is not available to competing groups"
  status: UPHELD                    # OPEN | UPHELD | WEAKENED | DESTROYED | WITHDRAWN
  mechanism: |
    The panel was assembled under a data-sharing agreement that expires in 2027
    and has not been replicated elsewhere, so a retrospective analysis on it
    cannot be run by the two groups working on the same question. That makes
    the result non-duplicable rather than merely first.
  grounding:
    - source: "dsa-2021.pdf section 3"
      detail: "exclusive access through 2027"
    - source: "judgment"
      detail: "assumes the two competing groups have not assembled an equivalent panel; searched their 2024-2025 publications and found none"
  strength_class: LOAD-BEARING      # LOAD-BEARING | SUPPORTING
  what_would_break_it: "evidence that either group has comparable panel access, or that the endpoint can be approximated from a public dataset"
  rescope_proposal: false

  cross_examination:
    examined_by_persona: priority-skeptic
    angles_tried:
      - "Searched for equivalent public panels — the closest is <X>, which lacks the 12-week follow-up."
      - "Checked whether the agreement's exclusivity is real — section 3 confirms it."
      - "Checked whether uniqueness matters if the question is uninteresting — separate axis, not my verdict to make."
    verdict: STANDS
    verdict_reasoning: |
      Could not find an equivalent data source. The uniqueness claim survives.
    surviving_core: null              # set for WEAKENED

  final_strength: LOAD-BEARING
```

### Concession record

A concession is a finding. Record it with the same weight as a claim.

```yaml
concession:
  by_persona: referee
  assigned_stance: "argue that this would be rejected at a plausible venue"
  angles_tried:
    - "Novelty: checked the last three years of <venue>; nothing close has appeared."
    - "Baselines: the proposal's comparison set matches what <venue> accepted in 2024-2025."
    - "Contribution framing: the abstract's claim is narrower than the results section supports, which is the safe direction."
  why_the_case_failed: |
    I could not construct a desk-reject argument I would actually make as a
    reviewer. My strongest version was "incremental relative to <paper>," and
    re-reading that paper shows it studies a different population under a
    different intervention. I am conceding rather than submitting a weak
    objection.
  residual_doubt: "I am less confident about <venue>'s appetite for negative results; if the study nulls, acceptance is a real question."
```

### Rescope record

```yaml
rescope:
  name: "Retrospective-only, 3 weeks"
  cut: "the entire prospective arm, including recruitment, the 12-week follow-up, and the site agreement"
  remains: "a retrospective cohort analysis on the existing 1,240-subject panel, reporting the association with the primary endpoint and a preregistered sensitivity analysis"
  new_ask:
    person_weeks: 3
    compute: "negligible"
    data: "already in hand"
    calendar: "3 weeks, no external dependency"
  cures:
    - objection_id: O-004
      mechanism_of_cure: "the power objection is specific to n=60 in the prospective arm; the retrospective panel is n=1,240 for the same endpoint"
      cure_check: CURED
      checked_by_persona: statistician
    - objection_id: O-007
      mechanism_of_cure: "removes the dependency on the site coordinator's enrollment timeline"
      cure_check: CURED
      checked_by_persona: opportunity-cost-advisor
  does_not_cure:
    - objection_id: O-002
      residual: "the endpoint remains a proxy; this becomes a stated limitation rather than a blocker"
  advocate_claims_surviving: [A-002]
  buys_beyond_itself: |
    A null on the retrospective panel would make the prospective arm hard to
    justify at any n, so this version is also the decision point for the full
    study — it converts a 14-week bet into a 3-week test of the bet.
```

### Verdict record

```yaml
verdict:
  decision: RESCOPE                 # PURSUE | RESCOPE | KILL
  reason: |
    No fatal objection survived. One SCOPE-FATAL objection (O-004, power)
    survived cross-examination and arbitration, and the named narrower version
    cures it while preserving the load-bearing advocate claim A-002.
  surviving_fatal: []
  surviving_scope_fatal: [O-004]
  surviving_costly: [O-002, O-009]
  surviving_advocate_claims: [A-002]
  rescope_name: "Retrospective-only, 3 weeks"
  concessions: [referee, practitioner]
  escalations:
    - claim_id: O-011
      question: "Will the site coordinator commit to 2024-level enrollment rates in writing before week 2?"
  orchestrator_conflict: |
    I drafted the original proposal and argued for the prospective arm in two
    prior sessions. That biases me toward PURSUE. This verdict disagrees with
    my prior, which is weak evidence that the council was not merely echoing me.
```

---

## Dispatch Discipline Reminders

- **Parallelism.** Phase 1 investigators run in parallel. Phase 2 cross-examiners run in parallel across claims. Phase 3 arbitrators run in parallel across disputes. Phase 4 cure checks run in parallel across cured objections. This is what makes a six-persona council tractable in wall time — and the isolation it enforces is the point, not a side effect.
- **Context isolation.** Each dispatch is a fresh subagent receiving only what its template names. Not the full dossier, not the other subagents' outputs, not the controller's opinion.
- **No self-review.** No subagent is dispatched twice on the same claim, except the single `NEEDS-EVIDENCE` reroute.
- **Halt on drift.** If the proposal changes mid-council — the user revises the design, new results arrive — halt, re-freeze the artifact set, and re-run the affected phases. Personas arguing about different versions of the idea produce a memo about nothing.
- **The controller does not vote.** You aggregate, you apply the verdict arithmetic, you declare your conflict. You do not add a seventh opinion to the council you are running.
