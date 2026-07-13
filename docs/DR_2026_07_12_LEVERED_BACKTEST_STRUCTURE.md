---
title: Decision Record — Structuring the Levered Backtest (not a blanket approach)
date: 2026-07-12
kind: decision-record
relates_to: docs/PLAN_LEVERED_CORE_AND_INTEL_FLOW.md (§1.2, §1.3)
branch: feat/levered-core-sweep (phase 1)
status: PHASE 1 KILLED — v4-qmj-only has -161pp alpha vs SPY on clean 495-ticker universe (Sharpe 1.09). Prior "Sharpe 1.30-1.53" gold-standard numbers were cache-bias artifacts. Levered core is not a viable path on this composite. Signal-stack rebuild is prerequisite to any further leverage or sleeve work.
---

## Post-mortem addendum (2026-07-12, same-day)

Phase 1 executed as planned: gross_exposure param, financing accrual, guardrails, loader hardening, and a walk-forward sweep across L-1.0 / L-1.2 / L-1.5 / L-1.75 / L-2.0. Results at each step:

| Run | Universe | Sharpe | Alpha vs SPY | Verdict |
|---|---|---|---|---|
| L-1.0, 200 tickers alphabetical (Apr audit) | 200 | 1.30 | -140.67pp | (biased subset) |
| L-1.0, 200 tickers (Jul sweep) | 200 | 1.46 | -133.09pp | (biased subset) |
| L-1.0, "495 uncapped" but only 233 loaded silently | 233 | 1.53 | -121.53pp | (still biased subset — cache truncation) |
| **L-1.0 on backfilled clean 495** | **495** | **1.09** | **-161.42pp** | **Real number** |

**What we learned:**
1. The audit archive was contaminated in two ways: partial universe (silent drops) AND biased subset (survivorship-adjacent — the loaded 233 were mega-cap winners with long-history CSVs).
2. Every levered variant made things worse. L-1.5 already fell -246bps to financing on a strategy with negative excess return; the underlying alpha problem is structural, not a leverage calibration.
3. Universe expansion (200 → 233 → 495) moved alpha the wrong way (−133pp → −121pp → −161pp) because the added tickers were worse-performing than the survivorship-filtered starting subset. Direction is opposite of what "add more names to find alpha" intuition suggests.

**What phase 1 shipped that stays useful regardless:**
- `gross_exposure` parameter, financing accrual, guardrail checker — reusable engine primitives
- Loader hardening (`UniverseCoverageError` + coverage reports) — every future backtest will now fail loud on this class of bug
- Backfill script (`scripts/backfill_price_cache.py`) — future universe expansions have a template

**What comes next (agreed with Chad 2026-07-12):**
Re-baseline gold-standard (already done — the L-1.0 clean-universe result IS the corrected gold-standard), then signal-stack IC rebuild on the clean 495 universe. Address `project_fundamental_ic_gap.md` and `project_signal_stack_rebuild.md`. Composite weights should be derived from measured IC, not hand-tuned. Only after signal IC is validated does the leverage/sleeve conversation come back on the table.

# DR: Structuring the Levered Backtest

## Context

`PLAN_LEVERED_CORE_AND_INTEL_FLOW.md` §1.2 lists leverage variants (L-1.25, L-1.5,
beta completion, pos-15/20, combinations) and §1.3 adds a 5% convexity sleeve
(options + commodities, defined-risk only). The plan does *not* commit to how
leverage should be layered on top of that sleeve, and the engine
(`quant/backtest.py`) currently has almost no leverage plumbing — one comment at
`quant/backtest.py:1651` about a 30% short overlay is the only trace of gross > 1.0.
"We should be able to run a levered backtest now" is therefore false as of this DR;
this record fixes that gap in a principled way rather than shipping a blanket 1.5x.

## Phasing (updated in-session)

Sleeve interaction is a real question, but not the *first* question. Phase 1 tests
whether core leverage alone — no sleeve, no beta completion, no vol-target — is a
worthwhile risk to take. Only if phase 1 clears the CPCV/guardrail gate does the
sleeve become worth wiring in.

- **Phase 1 (this DR, branch `feat/levered-core-sweep`):** core-only sweep at
  L-1.0 / L-1.2 / L-1.5 with honest financing. Answers: "does levering the
  validated core survive its own CPCV gate after financing drag?"
- **Phase 2 (deferred, separate branch):** sleeve book with delta-notional
  accounting, beta completion, vol-targeted + regime-conditional policies,
  futures-overlay financing model. Everything below in §"three testable policies"
  belongs to phase 2 planning and is preserved here only so the reasoning isn't
  lost.

## Framing: leverage is a 5-axis decision, not a single dial

| Axis | Blanket answer | Explicit answer used here |
|---|---|---|
| What do you lever? | Everything | Core-only; sleeve is separately capped |
| How is sleeve exposure counted? | Premium | **Delta-notional** — consumes core gross budget |
| Mechanism | "Margin" | Two curves modeled: spot margin (SOFR+150bp) and futures overlay ((fut−spot)/spot ann.); pick per policy |
| When | Static | Varies by policy (see below) |
| Guardrail | Max gross | Max gross **+** stressed single-day loss cap **+** margin cushion **+** financing-cost cap as fraction of expected excess return, all **pre-declared** |

## The three testable policies (sequenced A → B → C)

Not a linear leverage sweep. Three policies, each falsifiable, each answering a
distinct question.

### Policy A — Beta completion first (weakest form, most informative first test)
- Gross = 1.0x, un-invested residual → SPY overlay. No borrowed capital, no financing.
- **Question it answers:** how much of the SPY gap is cash-drag vs selection?
- **Decision rule:** if this closes ≥40% of the SPY gap, the argument for real
  leverage weakens materially and B/C need to clear a higher bar.

### Policy B — Static 1.5x core + sleeve counted at delta
- Core gross = 1.5x, financing = FRED 3M SOFR + 150bp accrued daily.
- Sleeve = 5% *premium*, but its **delta-notional** consumes the core's gross budget
  so `(core_gross + sleeve_delta_notional) ≤ 1.5` at all times.
- **Question it answers:** with honest accounting, does the plan's L-1.5 variant
  still clear CPCV, and does the sleeve pay its notional cost?
- **Decision rule:** must pass the same CPCV/PBO/DSR gate as the current gold
  standard *after* financing drag and *with* joint gross accounting.

### Policy C — Vol-targeted core + regime overlay, sleeve independent
- Core sized daily to target realized-vol (~12% ann.), gross floats 0.8x–1.6x with
  hard caps at both ends. Regime overlay: gross halved when VIX regime = risk-off.
- Sleeve accounted separately (still 5% premium cap, defined-risk-only per plan §1.3).
- **Question it answers:** does dynamic gearing beat static? Vol-target is the
  policy CPCV can most cleanly validate because gross is endogenous to state, not
  a knob tuned to the sample.
- **Decision rule:** must beat Policy B on risk-adjusted terms *after* financing —
  otherwise the extra complexity isn't earning its keep.

## Non-negotiable rules (all three policies)

1. **Pre-declared guardrails.** Max-DD tolerance, stressed single-day loss cap
   (e.g., "−8% market day at policy gross must not breach −15% NAV"), and a
   financing-cost cap as a fraction of expected excess return are written down
   *before* the policy runs. In-sample breach fails the CPCV path structurally —
   the engine, not the operator, enforces this. No re-tuning against the guardrail.
2. **Financing sensitivity.** ±200bp sweep on the SOFR spread, per plan §1.2 gate.
   Any policy that only clears at the low end is out.
3. **Same CPCV gate as gold standard.** 252 paths, PBO < 25%, DSR significance.
4. **Sleeve accounting rule is delta-notional across all policies** so results are
   comparable and the sleeve never appears "free."

## Engine work required before any policy can run honestly

These are the four pieces tracked in the task list; ~1.5–2 days total:

1. `gross_exposure` parameter with a per-day scaling hook.
2. Daily financing accrual — two selectable models (spot margin SOFR+150bp,
   futures overlay).
3. Sleeve book with own P&L ledger + `delta_notional` field per position.
4. Pre-declared guardrail checker that fails the CPCV path on breach.

Nothing exotic; sequencing matters more than sophistication.

## What this DR does not commit to

- No decision yet on which policy becomes production if all three pass CPCV — that
  is a separate promotion decision after results, not a design-time bet.
- No decision on futures vs spot-margin *mechanism* per policy — that's a run-time
  parameter once both financing models exist.
- No sleeve implementation, sizing rule, or execution path — plan §1.3 governs
  that; this DR only sets how the sleeve *interacts with* the core's leverage math.
- No change to the deprecated `regime_modifier()` weights path — that stays dead
  per plan §0 / §2.1.
