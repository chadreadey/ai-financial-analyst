# Findings Ledger Schema

The findings ledger is the **audit trail** for the adversarial code audit. It records every claim, every hostile challenge, every defense attempt, and every arbitration ruling — reproducible from a frozen git SHA. It is the deliverable a reader would use to verify that the audit process was actually adversarial and not laundered.

The ledger is written incrementally as phases complete. Each finding record grows over the phases; do not summarize prior phases when adding new ones — append, do not overwrite.

**Format:** Markdown file with one YAML block per finding, in ID order. YAML because it is diff-friendly, machine-parseable, and human-readable in a code review.

## Fields — Finding Record

```yaml
finding:
  id: F-001                                # global, assigned by controller
  title: "Missing timeout on FRED API client"
  status: HARDENED                         # see status lifecycle below

  # Provenance (Phase 1)
  originated_by: reliability-auditor        # persona name from personas.md
  originated_persona: reliability
  originated_confidence: HIGH               # LOW / MEDIUM / HIGH — auditor's initial belief
  originated_at: 2026-07-02T19:40:00Z

  # Claim
  claim: |
    The FRED HTTP client in fred_client.py has no `timeout` argument on its
    `requests.get()` call. If the FRED endpoint hangs, the calling
    orchestrator will block indefinitely, exhausting the request handler pool.
  asset_impacted: uptime                    # must map to a charter asset
  scope_check: in-scope                     # in-scope | out-of-scope-return | charter-gap

  # Evidence (Phase 1)
  evidence:
    - file: fred_client.py
      lines: 87-92
      quote: |
        response = requests.get(
            f"{self.base_url}/series/observations",
            params=params,
        )
      mechanism: |
        `requests.get` with no `timeout=` defaults to no timeout. FRED
        occasionally returns 504/hang under load; a hang here blocks the
        orchestrator's async gather because the client is sync and runs
        in a worker thread — worker starvation follows within N hung
        requests where N = pool size.

  # Initial severity (Phase 1)
  initial_severity: HIGH                    # LOW / MEDIUM / HIGH / CRITICAL
  initial_exploitability: PLAUSIBLE          # THEORETICAL / PLAUSIBLE / DEMONSTRATED

  # Cross-examination (Phase 2)
  cross_examination:
    examined_by_persona: security           # MUST differ from originated_persona
    examined_at: 2026-07-02T19:52:00Z
    angles_tried:
      - "Re-read fred_client.py:87-92 — confirms no timeout kwarg present."
      - "Searched for a wrapping decorator or retry with timeout — none found in fred_client.py, orchestrator.py, or utils.py."
      - "Checked config.py for a global session with default timeout — session is created ad-hoc per call, no defaults."
    verdict: CONFIRMED                      # CONFIRMED / DOWNGRADED / REFUTED / DUPLICATE-OF-Fnnn / NEEDS-EVIDENCE
    verdict_reasoning: |
      All three refutation angles failed. There is no upstream timeout, no
      wrapping retry, no session-default. The mechanism holds as stated.
    corrected_severity: null                # only set for DOWNGRADED
    corrected_exploitability: null          # only set for DOWNGRADED
    duplicate_of: null                      # only set for DUPLICATE-OF-Fnnn
    mitigating_file_line: null              # only set for REFUTED (must cite mitigation)
    evidence_gap: null                      # only set for NEEDS-EVIDENCE
    post_cross_examination_confidence: HIGH  # controller updates per verdict rule

  # Optional NEEDS-EVIDENCE reroute (Phase 2 side-loop)
  evidence_reroute: null                    # or { additional_evidence: [...], final_verdict: ..., or withdrawn: true }

  # Defense (Phase 3) — only present if cross-examination was CONFIRMED
  defense:
    defended_by_persona: correctness        # MUST differ from originated_persona AND examined_by_persona
    defended_at: 2026-07-02T20:03:00Z
    angles_tried:
      - "Existing mitigating control search: none found."
      - "Threat model boundary: FRED is a public endpoint, always reachable by hostile hangs. No boundary."
      - "Deployment context: no circuit breaker in front of fred_client at any deploy target."
      - "Cost-of-fix argument: adding timeout is a one-line change; not defensible to defer."
    verdict: DEFENSE-FAILED                 # DEFENSE-FAILED / DEFENSE-SUCCEEDED / SEVERITY-MITIGATED
    verdict_reasoning: |
      Four angles tried; no serious counter-argument surfaced. The finding
      stands.
    new_counter_argument: null              # only set for DEFENSE-SUCCEEDED
    mitigation_argument: null               # only set for SEVERITY-MITIGATED
    post_defense_confidence: HIGH           # this is the only confidence value that appears in audit-report.md

  # Arbitration (Phase 4) — only present if a dispute reached arbitration
  arbitration: null                         # or { ruling: ..., ruling_reasoning: ..., ... } — see arbitration schema below

  # Final state
  final_severity: HIGH
  final_exploitability: PLAUSIBLE
  hardened_at: 2026-07-02T20:03:00Z

  # Remediation link (Phase 5)
  remediation_id: R-001                     # links to a strengthening-plan.md bundle
```

## Fields — Arbitration Sub-Block

Only present when a finding reached Phase 4.

```yaml
arbitration:
  arbitrated_by_persona: performance        # any persona that had no prior role on this finding
  arbitrated_at: 2026-07-02T20:12:00Z
  ruling: HARDENED                          # HARDENED / HARDENED-DOWNGRADED / REFUTED / ESCALATE-TO-USER
  ruling_reasoning: |
    The defense argued that a wrapping decorator provides an implicit timeout,
    but re-reading orchestrator.py:230-260 shows the decorator is applied
    only in the `enrich_market_data` path, not in `enrich_macro_data` which
    calls fred_client. The defense's argument does not reach this call site.
  corrected_severity: null                  # only for HARDENED-DOWNGRADED
  corrected_exploitability: null            # only for HARDENED-DOWNGRADED
  refute_reason: null                       # only for REFUTED
  escalation_question: null                 # only for ESCALATE-TO-USER
```

## Fields — Remediation Record

Written by Phase 5 planners, one per finding, then bundled by the controller.

```yaml
remediation:
  finding_id: F-001
  planned_at: 2026-07-02T20:20:00Z
  planned_by_persona: reliability

  minimal_viable_fix:
    file: fred_client.py
    lines: 87-92
    patch_sketch: |
      response = requests.get(
          f"{self.base_url}/series/observations",
          params=params,
          timeout=(3.0, 10.0),  # (connect, read) — matches FRED SLA
      )

  defense_in_depth_fix:
    additional_sites:
      - file: finnhub_client.py
        lines: [124, 156, 201]
        note: "Same missing-timeout pattern on all outbound GETs."
      - file: fmp_client.py
        lines: [88, 141]
        note: "Same pattern."
    also_add: |
      Move to a shared session helper in utils.py with `timeout=(3.0, 10.0)`
      default; ban ad-hoc `requests.get(...)` at module top with a lint rule.

  regression_test:
    file: tests/test_fred_client.py
    test_name: test_fred_get_series_times_out_when_endpoint_hangs
    assertion: |
      With a stub that sleeps 30s, the client raises requests.Timeout within
      15s (upper bound = connect + read = 13s + slack).
    fixture_needed: "responses.Mock or requests_mock server that hangs."

  blast_radius:
    in_scope_files: [fred_client.py, finnhub_client.py, fmp_client.py, utils.py]
    out_of_scope_files: []                  # if non-empty, flag as follow-up spec
    behavioral_change: |
      Requests that previously hung forever now raise Timeout. Callers must
      handle Timeout (they currently catch bare Exception in orchestrator.py,
      so behavior degrades to logged failure — acceptable per charter).

  rollout_risk:
    sequencing: |
      1. Add utils.session_with_defaults()
      2. Migrate one client (fred_client) + test
      3. Migrate remaining clients
      4. Add lint rule banning bare requests.get in api-client modules
    flag_needed: false
    migration_needed: false
    rollback: "Revert the specific client if unexpected Timeout surge; low-risk."

  priority:
    severity: HIGH                          # LOW=1, MEDIUM=2, HIGH=3, CRITICAL=4
    exploitability: PLAUSIBLE                # THEORETICAL=1, PLAUSIBLE=2, DEMONSTRATED=3
    asset_value: HIGH                       # LOW=1, MEDIUM=2, HIGH=3, CRITICAL=4 — from charter
    effort: SMALL                           # SMALL=1, MEDIUM=2, LARGE=4, X-LARGE=8
    score: 27                               # (3 * 2 * 3) / 1 = 18; using integer scaling
    score_formula: "severity * exploitability * asset_value / effort"
```

## Scales (used in `priority.score`)

The scales are integer so the score is stable and comparable.

- **severity**: LOW=1, MEDIUM=2, HIGH=3, CRITICAL=4
- **exploitability**: THEORETICAL=1, PLAUSIBLE=2, DEMONSTRATED=3
- **asset_value**: LOW=1, MEDIUM=2, HIGH=3, CRITICAL=4 (from the charter)
- **effort**: SMALL=1, MEDIUM=2, LARGE=4, X-LARGE=8

`score = severity * exploitability * asset_value / effort` (rounded to nearest integer).

Bundles use the **max** of member `score` values by default. If a bundle's aggregation uses another rule, it must annotate why.

## Status Lifecycle

```
                                     ┌─────────────────┐
Phase 1: auditor submits       →     │ PROPOSED        │
                                     └─────────────────┘
                                              │
Phase 2: cross-examination            ┌───────┴────────────────────────────────┐
                                      ▼                                        ▼
                             ┌────────────────┐                    ┌────────────────────┐
                             │ CROSS-EXAMINED │                    │ REFUTED / DUPLICATE│
                             └────────────────┘                    └────────────────────┘
                                      │                                        │
Phase 3: defense                      ▼                                        │
                             ┌────────────────┐                                │
                             │ DEFENDED       │                                │
                             └────────────────┘                                │
                                      │                                        │
                    ┌─────────────────┼───────────────────┐                    │
                    ▼                 ▼                   ▼                    │
Phase 4: arbitrate (if disputed)                                               │
              ┌──────────┐   ┌───────────────┐   ┌─────────────────┐          │
              │ HARDENED │   │  HARDENED-DG  │   │  ESCALATED      │          │
              └──────────┘   └───────────────┘   └─────────────────┘          │
                    │                 │                   │                    │
Phase 5: plan       ▼                 ▼                   ▼                    ▼
              ┌────────────────────────────────────────────────────────────────────┐
              │ REMEDIATED (linked to strengthening-plan.md bundle) or DROPPED     │
              └────────────────────────────────────────────────────────────────────┘
```

Status field values, in the order a finding progresses through them:

- `PROPOSED` — auditor submitted; ledger intake pending
- `CROSS-EXAMINED` — verdict recorded (see `cross_examination.verdict` for direction)
- `REFUTED` — dropped from report at cross-examination or defense or arbitration
- `DUPLICATE-OF-Fnnn` — merged into another finding
- `DEFENDED` — defense recorded (see `defense.verdict` for direction)
- `ARBITRATED` — arbitration ruling recorded
- `HARDENED` — final rested state, ready for Phase 5
- `HARDENED-DOWNGRADED` — like HARDENED but with corrected severity
- `ESCALATED` — awaits user answer; not in report until resolved
- `REMEDIATED` — Phase 5 linked to a strengthening-plan bundle

## Confidence Update Rules (Cross-Examination)

The controller updates `post_cross_examination_confidence` based on the verdict — the cross-examiner does NOT set this directly. The reason: cross-examiners must not become negotiators over confidence.

| Verdict | `post_cross_examination_confidence` |
|---|---|
| CONFIRMED | max(HIGH, originated_confidence) |
| DOWNGRADED | one step below originated (HIGH→MEDIUM, MEDIUM→LOW) |
| REFUTED | n/a (finding drops out) |
| DUPLICATE-OF | n/a (finding drops out; other finding inherits nothing) |
| NEEDS-EVIDENCE | unchanged pending reroute |

## `post_defense_confidence` (the only one that appears in the report)

| Defense verdict | `post_defense_confidence` |
|---|---|
| DEFENSE-FAILED | HIGH (this is the confirmation signal) |
| SEVERITY-MITIGATED | MEDIUM |
| DEFENSE-SUCCEEDED | unchanged from post_cross_examination pending arbitration |

## Worked Example — Minimal Ledger Entry

Reproducing the F-001 fields above in a compact form suitable for the ledger file:

```yaml
finding:
  id: F-001
  title: "Missing timeout on FRED API client"
  status: HARDENED
  originated_by: reliability-auditor
  originated_persona: reliability
  originated_confidence: HIGH
  originated_at: 2026-07-02T19:40:00Z
  claim: >
    fred_client.py's requests.get has no timeout; a FRED hang blocks the
    orchestrator's request handler pool.
  asset_impacted: uptime
  scope_check: in-scope
  evidence:
    - {file: fred_client.py, lines: 87-92, mechanism: "no timeout kwarg → worker starvation on FRED hang"}
  initial_severity: HIGH
  initial_exploitability: PLAUSIBLE
  cross_examination:
    examined_by_persona: security
    verdict: CONFIRMED
    angles_tried: [re-read, mitigation search, session-default search]
    post_cross_examination_confidence: HIGH
  defense:
    defended_by_persona: correctness
    verdict: DEFENSE-FAILED
    angles_tried: [existing mitigation, threat boundary, deployment context, cost-of-fix]
    post_defense_confidence: HIGH
  arbitration: null
  final_severity: HIGH
  final_exploitability: PLAUSIBLE
  remediation_id: R-001
```

## What the Ledger Guarantees

If the ledger is well-formed, a reader can verify — from evidence alone — that:

1. Every reported finding survived a cross-examination attempt AND a defense attempt (no consensus laundering).
2. No cross-examiner shared a persona with the originator (no allied review).
3. No defender shared a persona with either (no self-review).
4. Every claim cites `file:line` at the frozen SHA (no fabrication).
5. Every ruling in dispute-arbitration cites an evidence chain (no vibes).
6. Every reported finding maps to a remediation bundle in the plan (no orphaned severities).
7. Every escalation is explicit (no silent tie-breaking).

Missing any of these guarantees invalidates the audit. The controller MUST verify each of them in the closeout checklist before publishing.
