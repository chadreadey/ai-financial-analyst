# Fundamentals-Pricing Audit — Spec

**Date**: 2026-04-27
**Owner**: chadreadey
**Status**: Active, multi-session

---

## 0. Hypothesis Under Test

> The system's biggest unrealized edge is **finding the best fundamental stocks then investing based on the AI's narrative around them.** This audit produces a defensible yes/no on (a) whether the quant fundamental layer is competitive vs academic baselines, (b) whether the AI adds real signal beyond prose, (c) the all-in cost to operate this stack at Russell 1000 scale.

---

## 0.5 Audit Continuity Principle

1. **Each audit item is independent unless explicitly dependent.** The audit does not stop because one upstream item fails.
2. **Insufficient ≠ blocked.** When an item cannot be empirically audited (data missing, code not present, infra not built), it is marked `INSUFFICIENT — [reason]` and the audit proceeds to the next non-dependent item.
3. **Code-reading still counts.** For `INSUFFICIENT` items, the audit will still document what the code can and cannot do, what data structures support, and what the design implies. Empirical scoring waits for data.
4. **Hard floor only stops the audit.** Only environment-level failures (broken Python env, repo non-functional) halt forward progress.
5. **Every `INSUFFICIENT` item becomes a backlog spec.** The final session deliverable includes a ranked, scoped list of follow-up specs to remediate insufficiencies.

---

## 1. Universe & Window

| Parameter | Value |
|---|---|
| Universe | Russell 1000 |
| Market cap floor | ~$3.5–5B (annual reconstitution boundary) |
| Market cap range | ~$4B – $3T |
| Window | 2015-01-01 to 2024-12-31 (10 years) |
| Regime coverage | 2018 vol, 2020 COVID, 2022 rates, 2023 AI boom |
| Survivorship handling | R1000 historical membership (point-in-time index constituency required) |

**PIT decision (line item):**
- **Recommended**: Sharadar SF1 ($150–300/mo personal). Required for honest ERM-class signal audit. Optional for valuation/quality signals (bias is optimistic but informative).
- **Without PIT**: All earnings-revision signals carry look-ahead bias and cannot be honestly backtested. Mark such signals `BIASED — no-PIT` if run anyway.

---

## 2. Quant Audit Layer

### 2.1 Signal Inventory (precondition)
Enumerate every fundamental signal the codebase computes today, regardless of prod-status. For each, capture:
- File:line reference
- Signal name and definition
- Source data (provider, field)
- Computation method
- Current state: `wired-prod` / `wired-dev` / `disabled` / `dormant-code`

### 2.2 Per-Signal Tests
For each inventoried signal, compute on R1000 2015–2024:
- **Information Coefficient** (rank correlation with forward returns) at 1M / 3M / 6M / 12M
- **Top-vs-bottom decile spread**, annualized
- **Yearly hit rate** (% of years with positive long-short return)
- **Long-short drawdown**
- **Turnover** at monthly rebalance

### 2.3 Benchmarks
Same universe, same window, same horizons:
- **Piotroski F-score** (free, well-known quality screen — sets the floor)
- **QMJ proxy** (Asness Quality-Minus-Junk, computable from common fundamental fields)
- **HML proxy** (Fama-French value, P/B-based)
- **Buy-and-hold R1000**

**Decision artifact**: ranked signal table. If our system's best fundamental signal cannot beat Piotroski, we do not have a fundamental edge — we have a fundamental wrapper.

---

## 3. AI Audit Layer

### 3.1 Method: Historical Case-Study Replay
30 historical situations replayed with agents seeing **only data available at the trade date**. Each case study includes: ticker, trade date, ground-truth outcome, expected agent behavior.

### 3.2 Case-Study Composition
| Slice | N | Purpose |
|---|---|---|
| Value traps that crashed | 10 | Test C-mode (trap detection): Yellow, BBBY-2022, Peloton-2022, Wirecard, Luckin, Lemonade, SVB-2023, Hertz pre-BK, Carvana-2022, Plug Power |
| Cheap-and-rallied winners | 10 | Test C-mode false-positive rate: Meta-2022, NVDA-2023, energy 2021, COF-2023, Disney-2024, etc. (final list TBD) |
| Earnings-quality probes | 10 | Test D-mode (accounting / one-time gains / WC games) |
| Catalyst-hallucination temptations | 10 | Test B-mode grounding: recent narrative names where every catalyst claim must trace to a verifiable cited source |

### 3.3 Scoring Rubric
- **Trap-catch true-positive rate** (C-mode): % of value traps correctly flagged
- **Cheap-winner false-positive rate** (C-mode): % of real winners wrongly rejected as traps
- **Accounting-flag precision** (D-mode): % of agent-flagged accounting issues that match ground-truth issues
- **Catalyst grounding rate** (B-mode): % of catalyst claims with verifiable cited sources
- **Prose-vs-substance ratio**: tokens of falsifiable claims / total synthesis tokens

### 3.4 AI Mode Priorities (per user direction)
- **Primary**: D (earnings-quality judgment), C (value-trap filtering)
- **Stress-test under suspicion**: B (catalyst detection) — assumed prone to aggrandizing/hallucination until proven otherwise; grounding rate is the key metric
- **Implicit**: A (triage/ranking) — covered by the existing two-stage pipeline; not separately measured here

---

## 4. Cost Analysis Layer

### 4.1 Provider Cost Matrix
At R1000 scale, monthly cost for fundamentals coverage:
- Sharadar SF1 (Nasdaq Data Link)
- Finnhub + FMP combo (current stack)
- Tiingo
- WRDS Compustat commercial (academic-only currently)
- FactSet / Refinitiv (reference upper bound)

For each: coverage %, PIT support, historical depth, latency, monthly cost.

### 4.2 LLM Cost Curve
Per-name analysis cost at R1000 scale, with cadence sensitivity:
- Claude Sonnet 4.6
- Claude Opus 4.7
- DeepSeek hybrid (per `reference_llm_costs` memory)
- Cadences: monthly rebalance, weekly, event-driven

### 4.3 TCO Output
Total monthly cost table, broken into "minimum defensible" and "full quality" tiers, with break-even cost-per-name.

---

## 5. Phasing

| Session | End-state gate |
|---|---|
| **1 (today)** | Spec committed. Signal inventory complete. AI-agent fundamentals usage inventory complete. Data feasibility report. First IC slice run on whatever subset is feasible (or marked `INSUFFICIENT` per signal). |
| **2** | Case-study replay infrastructure built. First 10 case studies run and scored. |
| **3** | Remaining 20 case studies run. Cost analysis complete. |
| **4** | Synthesis: full audit report + ranked backlog of follow-up specs. |

---

## 6. Scope Discipline

### 6.1 Deferred to backlog (final-session deliverable)
- ML retraining (XGB rebuild, LSTM revisit, signal-stack rebuild)
- Pipeline/two-stage redesign
- Trading execution / portfolio construction logic
- Any `INSUFFICIENT`-flagged audit item

### 6.2 Out of scope entirely (not queued)
- International expansion beyond R1000
- Sub-$4B universe (micro-cap, OTC)
- Frontend / UX changes to surface findings
- Real-time data infra

---

## 7. End-State Gate (this session)

✅ Spec committed at `docs/audit/2026-04-27-fundamentals-pricing-audit-spec.md`
✅ **Signal inventory**: every fundamental signal in the codebase, with file:line references and prod-status
✅ **AI-agent inventory**: per-agent fundamental data usage and synthesis role
✅ **Data feasibility report**: which IC tests can run today vs blocked on data acquisition
✅ **First IC slice**: per-signal IC on feasible subset, vs Piotroski baseline if computable
✅ **Insufficiency log**: every item marked `INSUFFICIENT` with reason and code-reading findings
✅ **Next-session plan**: scope for Session 2 (case-study replay infra)

---

## 8. Open Decisions (to answer before Session 2)

1. **Sharadar SF1 subscription** ($150–300/mo)? Required for honest ERM audit. Affects whether earnings-revision signals enter Session 2's case studies.
2. **Final case-study list** (especially the 10 cheap-winners and 10 catalyst-hallucination temptations) — to be drafted in Session 1's last 30 minutes for review.
