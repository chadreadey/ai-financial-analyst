---
name: adversarial-code-audit
description: Use when a codebase, subsystem, or pending change requires high-confidence weakness discovery beyond a single reviewer — before major releases, after security or reliability incidents, prior to external audit or compliance review, when reviewing safety-critical or high-blast-radius changes, when a prior review felt too agreeable, when stakeholders demand independent risk validation, or when the deliverable must be a prioritized remediation plan rather than a finding list.
---

# Adversarial Code Audit

## Overview

**Adversarial code auditing IS "trust nothing" applied to code review.** Multiple subagents attack the code independently, then attack each other's findings, and only claims that survive hostile refutation reach the report. The output is not a list of opinions — it is a **filtered, evidence-anchored, prioritized strengthening plan**.

**Core principle:** A finding is not "confirmed" because two agents agreed. It is confirmed because at least one *hostile* agent tried to disprove it and failed. Agreement between allies is not evidence.

**REQUIRED BACKGROUND:** You SHOULD understand superpowers:subagent-driven-development. This skill uses the same subagent dispatch discipline (fresh context per subagent, precisely crafted prompts, no bleeding of prior conclusions) but organizes the subagents into *adversaries* rather than *collaborators*.

## When to Use

**Use when:**
- Reviewing a subsystem for release readiness, incident postmortem, external audit, or compliance handoff
- The blast radius of a bug is large (customer funds, PII, availability, correctness of a critical output)
- A prior single-reviewer pass felt too agreeable — few findings, high certainty, no pushback
- Stakeholders need **independent** validation of risk, not one reviewer's opinion
- The required deliverable is **a plan**, not a list

**Do NOT use when:**
- The code under review is < ~300 lines and one careful reading suffices — this skill's overhead does not pay off
- The goal is style/formatting review (use a linter)
- The goal is *domain-signal quality* audit (e.g. "is this trading signal predictive?") — use a domain audit spec instead, this skill audits **code** not **hypotheses**
- You have no way to freeze a git SHA — the audit will drift and its findings will become unreproducible

## Workflow at a Glance

```
Phase 0  Scope & Charter          → audit-charter.md (frozen SHA, personas, assets)
Phase 1  Red-Team Discovery       → N auditor subagents in parallel, one per persona
Phase 2  Cross-Examination        → each finding refuted by a *different-persona* subagent
Phase 3  Devil's Advocate Defense → confirmed findings must survive a third hostile pass
Phase 4  Arbitration              → surviving disputes ruled on (or escalated to user)
Phase 5  Strengthening Plan       → per-finding remediation, then aggregated & prioritized
```

Detailed dispatch templates for each subagent role live in [prompts.md](prompts.md).
Persona attack surfaces and scoping live in [personas.md](personas.md).
The findings-ledger schema and adversarial-history fields live in [ledger-schema.md](ledger-schema.md).

## Phase 0 — Scope & Charter

Before dispatching any auditor, the controller (you) MUST commit `audit-charter.md` capturing:

- **Frozen git SHA** — the exact tree every subagent audits. If code changes mid-audit, halt and re-sync.
- **Scope boundary** — file globs / directory list / entry points included. Anything outside is out of scope, and no auditor may claim findings outside it.
- **Critical assets** — what the audit protects (customer funds, PII, uptime, correctness of output X, secrets, etc.). Findings must connect back to at least one critical asset to justify severity.
- **Threat model** — who or what is the adversary (external attacker, hostile input, misbehaving upstream, operator error, silent data corruption, model regression). Personas that have no matching threat may be dropped.
- **Persona set** — which of the six personas in [personas.md](personas.md) apply. Dropping personas is allowed and encouraged when there is genuinely no attack surface, but the drop must be explicit and justified.
- **Deliverable set** — `findings-ledger.md`, `audit-report.md`, `strengthening-plan.md`. Do not deviate.

Save all audit artifacts under a single directory (e.g. `docs/audit/<date>-<subsystem>/`). Do NOT scatter them.

## Phase 1 — Red-Team Discovery

For each persona in the charter, dispatch a **fresh** subagent using the auditor template in [prompts.md](prompts.md). Run these **in parallel** — each auditor's context must be isolated from every other auditor's.

Each auditor must return findings in the ledger schema. Findings without file:line evidence and a reproducible mechanism (attack step, invariant violation, failure scenario, or exploit sketch) are **rejected at intake by the controller** — do not merge them into the ledger.

The controller then:
1. Assigns unique IDs (`F-001`, `F-002`, ...) across all auditors' outputs.
2. Records `originated_by` (persona) and `originated_confidence` on each finding.
3. Deduplicates only *identical claims on identical lines* — near-duplicates go through cross-examination and are merged there via the `DUPLICATE-OF-Fnnn` verdict, not here.

## Phase 2 — Adversarial Cross-Examination

Every finding gets routed to a **different-persona** subagent whose job is to *refute* it — not to confirm, not to strengthen, to **refute**.

The cross-examiner is dispatched with:
- The claim + evidence + reproducible mechanism.
- The audit charter.
- **NOT** the originator's confidence, severity, or persona.
- **NOT** any other findings.
- Explicit instruction: "Assume the auditor is wrong. Build the strongest possible case for why."

The cross-examiner returns one verdict per finding:
- `CONFIRMED` — refutation attempt failed; the claim holds
- `DOWNGRADED` — real issue but severity or exploitability inflated
- `REFUTED` — the evidence does not support the claim, or a mitigating control elsewhere neutralizes it (must cite the mitigating file:line)
- `DUPLICATE-OF-Fnnn` — subsumed by another finding (must cite which)
- `NEEDS-EVIDENCE` — the claim is plausible but the evidence chain is incomplete; routed back to originator for one round of evidence, then re-cross-examined

`NEEDS-EVIDENCE` findings that come back without stronger evidence become `REFUTED`. No infinite loops.

## Phase 3 — Devil's Advocate Defense

Every `CONFIRMED` finding then faces a **defense counsel** subagent (a *third* persona, different from both the originator and the cross-examiner). The defender's job is to argue the code's case: "This is not really a problem, because…"

The defender may cite:
- Existing mitigating controls elsewhere in the codebase
- Threat model boundaries (the attacker cannot reach this path)
- Deployment context (network isolation, feature flag, tenant scoping)
- Cost-of-fix vs realistic cost-of-risk

The defender returns:
- `DEFENSE-FAILED` — no serious counter-argument surfaced → finding is now `HARDENED`
- `DEFENSE-SUCCEEDED` — a new counter-argument surfaced that the auditor and cross-examiner both missed → finding goes to Phase 4 arbitration
- `SEVERITY-MITIGATED` — the finding is real but the defender surfaced a mitigation that lowers priority; note it, then Phase 4 arbitrates severity

**Critical:** "The defender could not find anything" is *itself* the confirmation signal. Record the defense attempt in the ledger even when it produces nothing — the audit trail must show the defense was attempted.

## Phase 4 — Arbitration

Any finding in dispute after Phase 3 (defense surfaced a new argument, severity is contested, or a `DUPLICATE-OF` chain is ambiguous) goes to a single **arbitrator** subagent per dispute. The arbitrator:

- Receives: the claim, the evidence, the cross-examination verdict, the defense argument, the audit charter.
- Re-reads the actual code at the frozen SHA.
- Writes a decisive ruling **anchored in a citable evidence chain**.
- May rule `HARDENED`, `HARDENED-DOWNGRADED`, `REFUTED`, or `ESCALATE-TO-USER`.

**Escalation is a valid ruling.** If two hostile agents disagree on whether a finding is real and the arbitrator cannot break the tie from evidence, mark `ESCALATE-TO-USER` and move on. Do **not** default-accept or default-reject to break ties silently.

## Phase 5 — Strengthening Plan

For every `HARDENED` or `HARDENED-DOWNGRADED` finding, dispatch a **Strengthening Planner** subagent. Each planner produces, for its finding:

- **Minimal-viable fix** — smallest code change that closes the specific weakness (file:line, patch sketch).
- **Defense-in-depth fix** — the belt-and-suspenders version that also closes adjacent variants.
- **Regression test** — the test that would fail today and pass after the fix (name, file, assertion).
- **Blast radius** — what other code the fix touches or could break.
- **Rollout risk** — sequencing (behind flag? migration? backfill?), rollback plan.
- **Priority score** — `severity × exploitability × asset_value / effort`. Numeric, so the aggregate is sortable.

The controller then aggregates all planner outputs and:
1. Merges remediations that share code paths into a single change bundle.
2. Sequences bundles by descending `risk-reduction / effort`.
3. Flags any remediation whose blast radius reaches out-of-scope code — those become follow-up specs, not part of this plan.

The final `strengthening-plan.md` is a sequenced list of change bundles, each with the findings it closes, the test it adds, the rollout plan, and the residual risk after the fix.

## Anti-Collusion Contracts

These are non-negotiable. Violating any of them invalidates the audit.

1. **Evidence discipline.** Every claim cites `file:line` and one paragraph of quoted or paraphrased code showing the mechanism. Claims without evidence are auto-rejected before entering the ledger — they do not "just get downgraded".
2. **Persona hygiene.** Cross-examiner persona ≠ originator persona. Defender persona ≠ both. Arbitrator is a fresh dispatch with no prior role on this finding. If you catch yourself reusing a persona for a role it already played, re-dispatch.
3. **Context isolation.** No subagent sees another subagent's confidence, verdict, or session history. They receive only: the frozen SHA, the audit charter, the claim + evidence (for downstream phases), and their role-specific template. The controller — not the subagents — is the only entity that sees the whole picture.
4. **No consensus laundering.** A finding is not `HARDENED` because multiple agents agreed. It is `HARDENED` because at least one *hostile* agent tried to disprove it and failed. Agreement between allies (same persona, or agents that saw each other's conclusions) does not count.
5. **Confidence is earned, not asserted.** The ledger tracks `originated_confidence`, `post_cross_examination_confidence`, `post_defense_confidence`. Only the final post-defense value appears in `audit-report.md`. The other two are audit-trail only.
6. **No fabrication of code state.** If code changes between phases, the audit halts. Re-sync at a new frozen SHA and re-run affected phases. Never allow "the code probably still says X" reasoning.

## Rationalization Table

Every entry below is a shortcut the controller (or a subagent) will attempt under time or context pressure. All of them mean **stop and follow the protocol**.

| Excuse | Reality |
|---|---|
| "Two auditors flagged the same thing — call it confirmed and skip cross-examination." | Agreement between allies is not consensus. Route it through a hostile refuter. Every finding, no exception. |
| "This finding is obviously real — evidence is redundant." | If obvious, the file:line citation takes one sentence. Provide it or drop the finding. |
| "Cross-examining every finding is expensive; let me batch-approve the small ones." | Skipping refutation ships inflated severities and false positives. Small findings are how audits lose credibility. |
| "The defender came up with nothing, so the defense pass was a waste." | The defender finding nothing IS the confirmation. Record the empty defense — the audit trail requires it. |
| "I'll merge two personas into one subagent to save context." | Persona fusion destroys the anti-collusion property. Fresh, single-persona subagents are the mechanism. |
| "This finding is small; skip the defense pass." | Same protocol for all findings. Small unmitigated findings are how cumulative attack surface grows. |
| "The user wants speed, not thoroughness." | 'Speed' means all phases executed with less per-phase deliberation. It does not mean skipping phases. |
| "The plan is obvious — just list the fixes in severity order." | A flat list is not a plan. Prioritization is `risk-reduction / effort`. Bundles matter. Rollout matters. |
| "I already have a strong opinion about this finding — let me short-circuit arbitration." | Your opinion is the exact bias the adversarial process exists to defeat. Dispatch the arbitrator anyway. |
| "The cross-examiner refuted it, but I still think it's real. I'll keep it." | If you can build the counter-evidence, feed it back as `NEEDS-EVIDENCE` and re-cross-examine. Do not silently override verdicts. |
| "It's fine to have the same subagent both find and defend the finding — it saves a dispatch." | Same-subagent audit-and-defense is not adversarial. It is monologue with extra steps. |
| "Escalating to the user looks indecisive; I'll just pick one." | Silently breaking a genuine tie is worse than escalating. Escalation is a valid ruling. |

## Red Flags — STOP and Restart the Affected Phase

- Any finding advances to a later phase **without a cited `file:line`** → refuse and reject the finding.
- Cross-examiner and originator **share a persona** → protocol violation; re-dispatch cross-examiner with a different persona.
- `defense-succeeded` finding **skips arbitration** → protocol violation; dispatch the arbitrator.
- "It's probably fine" or "seems safe" appears in any subagent output **without evidence** → treat as a `REFUTED` output; re-dispatch that subagent with a stricter template.
- One persona produces **more than ~30% of the total findings** → the audit is skewed toward that persona's blind spots (or its overreach). Sanity-check the charter, persona set, and that persona's dispatch template before trusting Phase 5.
- The final plan **lists fixes without a `risk-reduction / effort` rationale** → planner failed; re-dispatch.
- Two consecutive phases were run **at different git SHAs** → invalidate results, re-freeze SHA, re-run.

All of these mean: **restart the affected phase.** They do not mean "note it and continue".

## Outputs

Three artifacts, in this order, under a single audit directory (e.g. `docs/audit/<date>-<subsystem>/`):

1. **`audit-charter.md`** — scope, SHA, personas, critical assets, threat model. Written in Phase 0. Never edited after Phase 1 starts.
2. **`findings-ledger.md`** — the full audit trail: every claim, every verdict, every defense attempt, every arbitration ruling. This is the *auditable* deliverable; it must be reproducible from the frozen SHA. See [ledger-schema.md](ledger-schema.md).
3. **`audit-report.md`** — only `HARDENED` and `HARDENED-DOWNGRADED` findings, with final severity, evidence, and one-line remediation pointer to the plan.
4. **`strengthening-plan.md`** — sequenced change bundles with risk-reduction rationale, test additions, rollout plan, and residual-risk notes.

Do not produce a "summary of opinions". Every claim in `audit-report.md` must be traceable to an entry in `findings-ledger.md` and a bundle in `strengthening-plan.md`.

## Quick Reference

| Phase | Subagent role | Dispatched by | Persona rule | Verdict shape |
|---|---|---|---|---|
| 1 | Auditor | Controller, in parallel | one per persona | file:line-cited finding |
| 2 | Cross-examiner | Controller, per finding | ≠ originator persona | CONFIRMED / DOWNGRADED / REFUTED / DUPLICATE / NEEDS-EVIDENCE |
| 3 | Defense counsel | Controller, per CONFIRMED finding | ≠ originator and ≠ cross-examiner | DEFENSE-FAILED / DEFENSE-SUCCEEDED / SEVERITY-MITIGATED |
| 4 | Arbitrator | Controller, per disputed finding | fresh dispatch | HARDENED / HARDENED-DOWNGRADED / REFUTED / ESCALATE-TO-USER |
| 5 | Strengthening planner | Controller, per HARDENED finding | any persona with domain fit | fix + test + rollout + priority score |

## Skill Execution Checklist

Create a todo per item. Do not skip.

**Phase 0 — Charter:**
- [ ] Freeze audit SHA and record it
- [ ] Enumerate scope (globs, entry points)
- [ ] Enumerate critical assets and threat model
- [ ] Select personas (drop with justification)
- [ ] Commit `audit-charter.md`

**Phase 1 — Discovery:**
- [ ] Dispatch fresh auditor per selected persona, in parallel
- [ ] Reject at intake any finding lacking file:line evidence
- [ ] Assign F-IDs; record originator + originated_confidence

**Phase 2 — Cross-Examination:**
- [ ] For every finding, dispatch a different-persona cross-examiner
- [ ] Withhold originator confidence/severity from cross-examiner
- [ ] Record verdict + refutation reasoning in ledger

**Phase 3 — Defense:**
- [ ] For every CONFIRMED finding, dispatch a third-persona defender
- [ ] Record defense attempt even when empty
- [ ] Route DEFENSE-SUCCEEDED and SEVERITY-MITIGATED to Phase 4

**Phase 4 — Arbitration:**
- [ ] Dispatch arbitrator per disputed finding
- [ ] Allow ESCALATE-TO-USER as a valid ruling
- [ ] Record ruling with citable evidence chain

**Phase 5 — Plan:**
- [ ] Dispatch planner per HARDENED finding
- [ ] Aggregate + de-dup shared-path remediations into bundles
- [ ] Sequence bundles by risk-reduction / effort
- [ ] Flag out-of-scope blast radius as follow-up specs

**Closeout:**
- [ ] Commit `findings-ledger.md`, `audit-report.md`, `strengthening-plan.md`
- [ ] Verify every claim in report traces to a ledger entry and a plan bundle
- [ ] Verify no phase ran at a different SHA
- [ ] Verify no persona produced >30% of findings without an explanation

## The Bottom Line

**Trust nothing, cite everything, refute first.** Findings that survive hostile refutation are worth reporting. Findings that don't are noise. The plan is the deliverable; the report is its justification; the ledger is its audit trail. Skipping any adversarial round trades the audit's credibility for a few minutes of wall time — do not make that trade.
