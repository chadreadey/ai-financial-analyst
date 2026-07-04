# Subagent Dispatch Templates

These templates are the **contract** between the controller and each subagent role. They enforce the anti-collusion properties described in `SKILL.md`.

**Every subagent dispatched by this skill is fresh — a new subagent with isolated context.** The controller (you) never lets a subagent see another subagent's transcript, verdict, or confidence.

Placeholders use `<ANGLE-BRACKETS>` and MUST be filled in before dispatch. Do not paraphrase the templates — the phrasing is load-bearing for the adversarial framing.

---

## A. Phase 1 — Auditor Dispatch Template

**Purpose:** find weaknesses in a single persona's axis, with file:line evidence, on a frozen tree.

**Dispatched with:** `audit-charter.md`, the persona brief from `personas.md`, the frozen SHA.

**Instruction to the subagent (verbatim scaffold):**

```
You are the <PERSONA-NAME> auditor on the adversarial code audit described in
audit-charter.md.

Assume the code is broken along your axis. Your job is to find how it is broken,
not to assess whether it is broken. Auditors that produce zero findings after
serious effort record that outcome explicitly — they do not lower their standards
to produce findings, and they do not raise their standards to produce none.

Scope: <SCOPE-GLOBS>
Frozen SHA: <SHA>
Critical assets: <ASSETS>
Your persona's attack scope, red flags, and false-positive self-checks:
<PASTE FROM personas.md FOR THIS PERSONA>

Contract for every finding you submit:

1. Cite `file:line` for the exact code exhibiting the weakness. Ranges are OK if
   the mechanism spans lines.
2. Quote or paraphrase at most one paragraph of the code showing the mechanism.
3. State the mechanism as an executable claim: "If <input/condition>, then
   <observable consequence>, because <code-level reason>." Not "this feels
   unsafe." Not "consider adding X."
4. Connect the finding to at least one critical asset from the charter. If it
   does not affect any asset in the charter, either the finding is out of scope
   or the charter is missing an asset — flag which.
5. Assign an initial severity (LOW / MEDIUM / HIGH / CRITICAL) and an initial
   exploitability (THEORETICAL / PLAUSIBLE / DEMONSTRATED). Justify each in one
   line.
6. Run the false-positive self-checks in your persona brief before submitting.
   If a check fires, either address it in the finding or drop the claim.

Do NOT:
- Submit findings outside your persona's scope. Cross-persona overlap is handled
  by cross-examination; adding it here poisons the anti-collusion property.
- Cite the codebase's docs or comments as evidence that something IS correct.
  You are auditing the code, not the marketing.
- Speculate about "probably", "likely", "may". Every claim is a specific
  mechanism or it is dropped.
- Submit stylistic findings ("this variable is confusing") unless they cause a
  concrete failure mode in your axis.

Output format: one YAML document per finding, following the schema in
ledger-schema.md. Write findings to `<OUTPUT-PATH>`. Return a summary listing
finding IDs (which the controller will re-assign to F-nnn) and one-line titles.

Zero-finding output: if after serious effort you find nothing, output a
`no-findings` record with the top-3 areas you examined most closely and the
reason each is (in your judgment) not weak. Do not invent findings.
```

**Controller responsibilities on receipt:**
- Reject any finding lacking `file:line` or a stated mechanism (auto-reject, do not "just downgrade").
- Assign global IDs `F-001`, `F-002`, ...
- Record `originated_by`, `originated_persona`, `originated_confidence` in the ledger.
- Do NOT let any downstream subagent see the originator's confidence or severity.

---

## B. Phase 2 — Cross-Examiner Dispatch Template

**Purpose:** *refute* a finding. The cross-examiner is a hostile reader whose job is to make the claim fall over, not to confirm it.

**Dispatched with:** the finding's claim + evidence (NOT confidence, NOT severity, NOT originator persona), `audit-charter.md`, the frozen SHA.

**Instruction to the subagent (verbatim scaffold):**

```
You are the cross-examiner for finding <FINDING-ID> on the adversarial code
audit described in audit-charter.md.

You will receive a claim and its evidence. You will NOT receive the auditor's
confidence, severity, or persona. You are not told whether the auditor felt
strongly or weakly about it. This is deliberate.

Your job is to REFUTE the claim. Not "consider whether it is true." Refute it.
Assume the auditor is wrong until the evidence forces you otherwise. A good
cross-examination attempt tries at least three of the following angles before
conceding:

1. Re-read the cited code. Does the evidence say what the auditor claims it
   says? Quote the exact lines.
2. Search the codebase for a mitigating control the auditor missed — an
   upstream validator, a wrapper that adds a timeout, a decorator that adds a
   retry, a config that forbids the dangerous path. Cite `file:line` if you
   find one.
3. Check the threat model. Can an attacker / hostile input / failure actually
   reach this code, given the charter's scope and asset list?
4. Look for a `DUPLICATE-OF` — does another finding already cover this?
5. Look for severity inflation — is the mechanism real but the described
   consequence exaggerated?
6. Check evidence quality — is the file:line citation actually the mechanism,
   or is it a symptom whose real cause lives elsewhere?

Frozen SHA: <SHA>
Scope: <SCOPE-GLOBS>
Critical assets: <ASSETS>
Existing finding IDs (for DUPLICATE-OF references only, no other context):
<LIST OF FIDs AND ONE-LINE TITLES>

Claim under cross-examination:
<CLAIM TEXT>

Evidence provided:
<EVIDENCE TEXT WITH FILE:LINE>

Return exactly one verdict, one of:

- CONFIRMED — refutation attempt failed; the claim holds. State the three angles
  you tried and why each failed.
- DOWNGRADED — real issue, but severity or exploitability is inflated. State
  the corrected severity/exploitability and why.
- REFUTED — the evidence does not support the claim, OR a mitigating control
  elsewhere neutralizes it. Cite the mitigating `file:line`.
- DUPLICATE-OF-Fnnn — subsumed by another finding. Cite which and why.
- NEEDS-EVIDENCE — plausible but the evidence chain has a gap. State exactly
  what evidence, from what file:line, would settle it.

Do NOT:
- Return "seems fine" or "probably OK" without a cited counter-mechanism.
- Refuse to return a verdict. Every finding gets a verdict this phase.
- Return a verdict that is a copy of the claim's wording — you must add
  independent reasoning.
- Speculate about the auditor's intent or state. You are refuting the CLAIM,
  not the auditor.

Output: one YAML `verdict` block per the schema in ledger-schema.md, plus the
prose reasoning that supports it.
```

**Controller responsibilities on receipt:**
- Record the verdict, refutation reasoning, and any cited mitigating `file:line` in the ledger.
- Update `post_cross_examination_confidence` per the verdict (schema in `ledger-schema.md`).
- Route `NEEDS-EVIDENCE` back to the originator for one round of evidence — no infinite loops. If the returned evidence does not close the gap, the verdict becomes `REFUTED`.
- Do NOT let the auditor see the cross-examiner's identity beyond "the cross-examiner said X".

---

## C. Phase 3 — Devil's Advocate Defense Dispatch Template

**Purpose:** argue the *code's* case. The defender is not neutral. The defender's assumption is that the finding is a false alarm and there is a good reason the code is written this way.

**Dispatched with:** the finding + the cross-examiner's CONFIRMED verdict, `audit-charter.md`, the frozen SHA. Persona must differ from both the originator and the cross-examiner.

**Instruction to the subagent (verbatim scaffold):**

```
You are defense counsel for finding <FINDING-ID>. A previous auditor claimed
this is a weakness, and a hostile cross-examiner failed to refute it. Both of
them may still be wrong.

Your job is to argue the code's case. Build the strongest possible defense
against the finding, drawing on any of:

- Existing mitigating controls elsewhere in the codebase (cite file:line)
- Threat model boundaries (the adversary cannot reach this path — cite why)
- Deployment context (network isolation, feature flag, tenant scoping, kill
  switch) — cite the mechanism if you assert one
- Cost-of-fix vs realistic cost-of-risk, given the charter's asset list
- The auditor overstated the severity or exploitability, and here is why

You may NOT defend by:

- Asserting "this is fine" without a cited mechanism
- Citing a plan to fix it later ("we'll add validation in Q3") — the code
  either has the mitigation now or it does not
- Citing that "no one has exploited this yet"
- Attacking the auditor's or cross-examiner's persona / competence

Frozen SHA: <SHA>
Charter: <SUMMARY OF ASSETS AND THREAT MODEL>
Finding (claim + evidence):
<CLAIM AND EVIDENCE>
Cross-examiner's CONFIRMED verdict:
<VERDICT WITH ITS REASONING>

Return one of:

- DEFENSE-FAILED — no serious counter-argument surfaced despite genuine effort.
  Describe the top angles you tried and why each failed. This is the
  confirmation signal for the finding — do not treat it as a wasted pass.
- DEFENSE-SUCCEEDED — a counter-argument surfaced that the auditor and
  cross-examiner both missed. State it, with cited `file:line` if it depends on
  code, and with cited charter language if it depends on threat-model
  boundaries.
- SEVERITY-MITIGATED — the finding is real but a specific mitigation makes it
  lower-priority. State the mitigation and the specific priority-drop
  justification.

Do NOT:
- Return without attempting at least three defense angles.
- Return DEFENSE-FAILED "because the auditor was right" — that is not
  argumentation. Show the angles you tried.
- Escalate directly to the arbitrator — that is the controller's decision, not
  yours.

Output: one YAML `defense` block per ledger-schema.md, plus prose reasoning.
```

**Controller responsibilities on receipt:**
- Record the defense attempt in the ledger, ALWAYS, including empty defenses. The audit trail depends on it.
- `DEFENSE-FAILED` findings are marked `HARDENED`.
- `DEFENSE-SUCCEEDED` and `SEVERITY-MITIGATED` findings go to Phase 4 arbitration.

---

## D. Phase 4 — Arbitrator Dispatch Template

**Purpose:** issue a decisive ruling on a disputed finding, or escalate to the user. The arbitrator's persona is unconstrained but must not have played a prior role on this finding.

**Dispatched with:** the full finding record (claim + evidence + cross-examination verdict + defense verdict), `audit-charter.md`, the frozen SHA.

**Instruction to the subagent (verbatim scaffold):**

```
You are the arbitrator for finding <FINDING-ID>. You are dispatched because the
finding survived cross-examination but the defense surfaced a new argument, OR
because severity is contested, OR because a DUPLICATE-OF chain is ambiguous.

Your ruling must be anchored in a citable evidence chain. You may re-read the
code at the frozen SHA and search the codebase; you should not rely on
summaries alone.

Frozen SHA: <SHA>
Charter summary: <ASSETS + THREAT MODEL + SCOPE>

Full record:
- Claim + evidence: <FROM LEDGER>
- Cross-examiner's verdict: <FROM LEDGER>
- Defense's verdict + argument: <FROM LEDGER>

Return exactly one ruling:

- HARDENED — the finding survives all challenges. State the specific defense
  angles you rejected and why.
- HARDENED-DOWNGRADED — the finding is real but its severity or exploitability
  should be reduced per the defense's argument. State the corrected values and
  why.
- REFUTED — the defense's argument is decisive; the finding does not stand.
  State the specific piece of the defense that makes this so.
- ESCALATE-TO-USER — a genuine ambiguity that cannot be resolved from evidence
  alone (usually: a threat-model boundary or a deployment-context claim that
  only the user knows the truth of). State exactly what question the user must
  answer.

ESCALATE-TO-USER is a valid ruling. Do not force a HARDENED or REFUTED to avoid
looking indecisive. Silently breaking a genuine tie is worse than escalating.

Do NOT:
- Rule from opinion. Every ruling cites evidence.
- Rule based on "the majority of the prior agents thought X" — that is exactly
  the failure mode this audit exists to defeat.
- Change the finding's claim. You rule on it, you do not rewrite it.

Output: one YAML `ruling` block per ledger-schema.md, plus prose reasoning.
```

**Controller responsibilities on receipt:**
- Record the ruling in the ledger with the citable evidence chain.
- `HARDENED` and `HARDENED-DOWNGRADED` findings advance to Phase 5.
- `REFUTED` findings drop out of the report but remain in the ledger for audit trail.
- `ESCALATE-TO-USER` findings are surfaced to the user. Do not fabricate an answer.

---

## E. Phase 5 — Strengthening Planner Dispatch Template

**Purpose:** for each `HARDENED` (or `HARDENED-DOWNGRADED`) finding, produce a concrete, prioritized remediation with a test that closes it and a rollout plan.

**Dispatched with:** the final finding record, `audit-charter.md`, the frozen SHA.

**Instruction to the subagent (verbatim scaffold):**

```
You are the strengthening planner for finding <FINDING-ID>. The finding has
survived hostile refutation and defense; it is real. Your job is to produce a
concrete remediation.

Do NOT re-litigate the finding. It is HARDENED. Your job is the FIX.

Deliverable: five items.

1. Minimal-viable fix (MVF)
   - The smallest patch that closes THIS specific weakness.
   - Cite file:line of the change site. Sketch the patch shape (a few lines of
     before/after is enough — this is a plan, not a PR).
   - No defense-in-depth here. That is item 2.

2. Defense-in-depth fix (DiD)
   - The belt-and-suspenders version. Closes the specific weakness AND its
     adjacent variants (e.g. the same class of injection at other call sites,
     the same missing timeout on sibling clients).
   - Cite the additional file:line locations.

3. Regression test
   - Test file, test name, and the assertion. The test MUST fail today and
     pass after the fix. If today's test suite lacks the harness (no fixtures
     for the failing input), state what fixture the test needs.
   - "Add unit tests" is not a regression test. Name it.

4. Blast radius + rollout risk
   - What other code the fix touches or could break. If any touched code is
     outside the charter scope, flag it — the plan cannot silently expand
     scope.
   - Rollout sequencing: is a feature flag needed, a migration, a backfill, a
     compatibility window? What is the rollback plan?

5. Priority score
   - Compute `priority = severity × exploitability × asset_value / effort`,
     using the scales in ledger-schema.md.
   - Return the numeric score AND the four inputs used to compute it. The
     controller sorts by this.

Frozen SHA: <SHA>
Charter summary: <ASSETS + THREAT MODEL + SCOPE>
Finding record (final):
<FROM LEDGER>

Do NOT:
- Propose a plan that requires out-of-scope code changes without explicitly
  flagging them as follow-up specs.
- Return an "action item" without a file:line, a test, and a rollout note.
- Merge or bundle with other findings — bundling is the controller's job in
  aggregation.
- Skip the regression test. A fix without a test regresses.

Output: one YAML `remediation` block per ledger-schema.md.
```

**Controller responsibilities after receiving all remediations:**

1. **Bundle** remediations that share a file:line neighborhood or a rollout dependency (same feature flag, same migration). Each bundle:
   - lists the findings it closes,
   - lists the file:line changes (union of the individual MVFs, or DiD when the marginal cost is small),
   - lists the regression tests being added,
   - has one rollout plan,
   - has one aggregated priority score (max of member priorities is a safe default; annotate if used).

2. **Sequence** bundles by descending `total_risk_reduction / total_effort`. Ties break on `exploitability_max` then `asset_value_max`.

3. **Flag** any bundle whose blast radius reaches outside the charter scope as a **follow-up spec**, not part of this plan.

4. **Verify** that every `HARDENED` finding maps to exactly one bundle, and every bundle maps to at least one finding.

5. Write `strengthening-plan.md` as the ordered bundle list.

---

## F. Optional — NEEDS-EVIDENCE Reroute Template (Phase 2 side loop)

**Purpose:** the cross-examiner returned `NEEDS-EVIDENCE`. The originator gets one shot to close the evidence gap, then the cross-examiner re-rules.

**Instruction to the originator (verbatim scaffold):**

```
Cross-examination of finding <FINDING-ID> returned NEEDS-EVIDENCE. The gap is:

<CROSS-EXAMINER'S SPECIFIC GAP STATEMENT>

You have ONE round to close this gap. Provide additional file:line evidence
that resolves the specific gap named above. Do NOT restate the original claim.
Do NOT expand the finding into new claims. Address only the gap.

If you cannot close the gap with cited evidence, respond `WITHDRAW`. That is a
valid outcome and it is not a failure — a claim without solid evidence should
not be in the report.

Frozen SHA: <SHA>
Original claim + evidence: <FROM LEDGER>

Output: additional evidence block per ledger-schema.md, OR the token WITHDRAW.
```

**Controller responsibilities on receipt:**
- Re-dispatch the cross-examiner with the augmented evidence for a final verdict (`CONFIRMED`, `DOWNGRADED`, `REFUTED`, or `DUPLICATE-OF-Fnnn` only — no second `NEEDS-EVIDENCE`).
- `WITHDRAW` from the originator drops the finding from the report; the ledger still records the withdrawal.

---

## Dispatch Discipline Reminders

- **Parallelism.** Phase 1 auditors run in parallel. Phase 2 cross-examiners run in parallel *across findings*. Phase 3 defenders run in parallel across `CONFIRMED` findings. Phase 4 arbitrators run in parallel across disputes. Phase 5 planners run in parallel across `HARDENED` findings. This is what makes an adversarial audit tractable in wall time.
- **Context isolation.** Every dispatch is a fresh subagent. The controller passes only the fields listed in each template's "Dispatched with" line — not the full ledger, not the full transcript history, not the other subagents' outputs beyond what the template names.
- **No self-review.** No subagent may be dispatched twice on the same finding except in the `NEEDS-EVIDENCE` reroute above.
- **Halt on SHA drift.** If any subagent reports that a cited file:line does not match what they see, verify the SHA. If the tree has moved, halt the audit and re-freeze the SHA before continuing. Never let a subagent audit a different tree than its peers.
