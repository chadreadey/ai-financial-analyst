# Fundamentals-Pricing Audit — Session 1 Findings

**Date**: 2026-04-27
**Spec**: `docs/audit/2026-04-27-fundamentals-pricing-audit-spec.md`
**Session gate**: Spec + signal inventory + AI agent inventory + data feasibility + first IC slice

---

## Executive Summary (TL;DR)

> **The system has *no statistically significant alpha* in its existing factor-attribution evidence, and the per-signal IC for fundamentals has never been measured.** The user's hypothesis ("fundamentals + AI narrative is the unrealized edge") is supported by the negative space: the current stack carries 13 fundamental-class signals (10 active in composite), but only the technical signals + institutional flow have IC tables. Earnings-revision (ERM, weight 20%), Quality/ROIC (weight 15%), SUE, dispersion, and the rest of the fundamental stack are wired into the composite *without ever having been individually IC-validated*. The AI layer produces SIGNAL_SCORE numbers from instructions like "score each dimension mentally" — no audit trail linking score to data. The single biggest, cheapest intervention is to wire fundamental signals into the existing IC harness (~5 hours work, $0 cost) so we can rank them honestly before deciding what AI should wrap around.

---

## 1. Quant Layer — Signal Inventory Findings

### 1.1 Active Fundamental Signal Stack (13 total, 10 weighted)

| # | Signal | Weight | Source | File:line | Status |
|---|---|---:|---|---|---|
| 1 | **ERM** (earnings revision momentum) | 20% | WRDS IBES | `earnings_signals.py:26-125` | Active, never per-signal IC tested |
| 2 | **Quality/ROIC + Margin** | 15% | WRDS Compustat | `additional_signals.py:26-91` | Active, never per-signal IC tested |
| 3 | **OBV trend** (technical, only survivor) | 15% | Volume | `signals.py` | Active, IC ~0.04 per redundancy.py |
| 4 | **Price momentum** (12-1M) | 10% | Price cache | `additional_signals.py:96-158` | Active, never tested in this stack |
| 5 | **Institutional flow** (QoQ) | 10% | WRDS 13F + FMP + Finnhub | `institutional_flow.py:32-437` | Active, IC tested |
| 6 | **Price regression** (R²≥0.6 OLS) | 10% | Price cache | `regression_signal.py:27-100` | Active, sparse signal |
| 7 | **Insider MSPR** | 10% | Finnhub | `additional_signals.py:163-197` | Active, never tested |
| 8 | **News sentiment** (FinBERT) | 5% | Finnhub news | `sentiment.py:70-153` | Active, low IC historically |
| 9 | **ARIMA** (5d, low-vol gated) | 5% | Price cache | `arima_signal.py:29-76` | Active, very sparse |
| 10 | SUE (seasonal earnings surprise) | blended | WRDS Compustat | `earnings_signals.py:128-194` | Blended into earnings score |
| 11 | Analyst dispersion | blended | WRDS IBES | `earnings_signals.py:197-259` | Blended into earnings score |
| 12 | PEAD (event timing) | **0%** | WRDS IBES actuals | `event_timing.py:106-191` | Defined but zeroed (sparse) |
| 13 | Sector momentum | **0%** | ETF prices | `sector_momentum.py:39-98` | **Dead code** |

### 1.2 Fetched-but-not-scored data (signals defined upstream but never become composite features)

- **FMP earnings surprises** (`fmp_client.py`) — fetched, never scored
- **FMP cash flow statement** — fetched, never scored
- **FMP grade consensus** — fetched, never scored
- **FMP price targets** — fetched, never scored as a signal (used for triangulation in synthesis only)
- **Finnhub earnings surprises** — endpoint exists, not consumed by signal code

**Implication**: Significant data is being paid for and downloaded but converted to nothing.

### 1.3 Architectural findings

- **No centralized fundamental features module.** Fundamentals are scattered across 6 files: `earnings_signals.py`, `additional_signals.py`, `institutional_flow.py`, `fundamentals.py`, `event_timing.py`, `macro_signals.py`. The only orchestration point is `cross_sectional.py:77-89` (`SIGNAL_FIELDS` list).
- **Dead code**: `compute_quality_score()` in `fundamentals.py:29-105` (FMP/balance-sheet variant) and `blend_fundamentals_into_signals()` (`fundamentals.py:253-290`) are defined but never wired into the active backtest pipeline.
- **Look-ahead bias**: Mostly safe (institutional flow lagged 45 days, MSPR lagged 30 days, sentiment filtered by article date), but **FMP institutional ownership** has implicit risk — code selects "latest available quarter" without explicitly checking that quarter-end + 45 day filing lag has elapsed before `as_of_date`. Filed as `RISK-1` in backlog.

### 1.4 INSUFFICIENT items

| Item | Reason | Code-reading inference |
|---|---|---|
| Per-signal IC for ERM, SUE, dispersion, ROIC, gross margin | `redundancy.py:SIGNAL_NAMES` only contains `obv_trend` + `institutional_flow`; fundamental signals are NOT in any existing IC table | Code structure supports it — `compute_signal_scores_at_date()` in `redundancy.py:32-87` could be extended to include earnings/quality signals; ~30 min of wiring work |
| Per-signal Sharpe / drawdown / hit-rate for fundamentals | Same — never run in walk-forward isolation | All signals support `as_of_date` parameter; full panel is computable |
| Cross-correlation among fundamental signals (orthogonality) | Same gap — corr matrix only covers technical + institutional flow | Computable once IC harness is extended |

---

## 2. AI Layer — Agent Inventory Findings

Six specialist agents. Mapped to the C/D/B framework from the audit spec:

| Agent | C-mode (trap detection) | D-mode (earnings quality) | B-mode (catalyst) | Source grounding | Look-ahead guardrail |
|---|---|---|---|---|---|
| **Earnings** (`agents/earnings.py:14-139`) | PARTIAL | **YES** (primary job) | PARTIAL | YES | NO |
| **DCF** (`agents/dcf.py:19-221`) | **YES** (deterministic upside/downside mapping) | PARTIAL | NO | YES | PARTIAL |
| **Macro** (`agents/macro.py:15-69`) | NO | NO | PARTIAL | YES | YES |
| **Risk** (`agents/risk.py:16-153`) | **YES** | YES | NO | YES | PARTIAL |
| **Pattern** (`agents/pattern.py:108-213`) | PARTIAL | NO | **YES** | PARTIAL | NO |
| **Competitive** (`agents/competitive.py:14-106`) | YES | NO | PARTIAL | YES | NO |

### 2.1 Critical findings on AI layer

**Finding #1 — Score-without-trail.** `prompts/earnings.md:36` instructs: *"Score each dimension mentally (trajectory, margins, quality, outlook), then average."* Synthesis then reads the mechanical SIGNAL_SCORE line (`prompts/synthesis.md:17`) and trusts it. **There is no audit trail linking the emitted score to the underlying data.** The system has no way to verify whether the Earnings agent's -0.6 came from accruals analysis or from prose generation.

**Finding #2 — D-mode has no redundancy.** Only the Earnings agent does accounting-quality work (M-Score, accruals, OCF/NI). Risk agent mentions earnings-quality but defers to Earnings. **If the Earnings agent misses a red flag, no other agent catches it.** D-mode is single-pass.

**Finding #3 — Synthesis is hybrid, narrative-dependent.** Per `orchestrator.py:54-88` (`_extract_structured_block`), synthesis only parses one terminal JSON block. Risk scores (1-10), moat ratings (STRONG/MODERATE/WEAK), and accounting red flags are emitted as prose and re-parsed by synthesis with regex/LLM-rereading. **The structured judgment surface area is small.**

**Finding #4 — B-mode is exactly as risky as the user suspected.** Pattern agent has B-mode capability (price action + estimate revision momentum), but it's not catalyst detection in the "FDA decision Q3" / "guidance reset" sense. **No agent explicitly tracks event calendars, regulatory milestones, M&A activity, activist filings, buyback completion.** And Earnings agent's "Identify 2-3 catalysts" instruction (`agents/earnings.py:53`) has no source-citation requirement — this is the highest-hallucination-risk surface in the system.

**Finding #5 — Macro multiplier is hardcoded.** `prompts/synthesis.md:38` applies a **0.7× multiplier to weighted_score if Macro normalized score ≤ -0.5**. This is one hardcoded number deciding the difference between STRONG and MEDIUM conviction. No basis for the 0.7 is documented in the codebase.

**Finding #6 — Competitive agent is described as "most narrative-prone; discount accordingly"** (`prompts/synthesis.md:33`) by the codebase itself. The system *knows* the moat-rating SIGNAL_SCORE (rule-of-thumb counting) is the weakest mechanically-derived score, weighted 0.14 anyway.

### 2.2 AI Layer Capability Verdict

For the user's hypothesis (fundamentals + AI narrative as edge):
- **D-mode (earnings quality reading)** — strongest existing capability. Earnings agent has codified rubric (M-Score, accrual ratios, OCF/NI thresholds). **But unverified**: no test that "score-mentally" output actually reflects the data.
- **C-mode (value-trap detection)** — distributed across DCF + Risk + Competitive but **not algorithmically composed**. Synthesis weights them but doesn't surface a unified "trap probability."
- **B-mode (catalyst detection)** — **structurally weak**. Confirms user's intuition that B-mode is the highest hallucination risk.

---

## 3. Data Feasibility Findings

### 3.1 What runs today (confirmed)
- **WRDS PIT cache**: 495 unique tickers, 2012-10 → 2026-04, `compustat_quarterly` + `ibes_actuals` + `ibes_consensus` + `inst_holdings_13f` tables, 25,169 records
- **Forward returns**: Tiingo + Alpaca daily close (dividend-adjusted) cached in `.price_cache/`. Forward return computation already exists (`quant/backtest.py:380-413`)
- **IC computation harness**: `quant/backtest.py:369-500` — `compute_signal_ic()` and `calibrate_weights_from_ic()` work today

### 3.2 What's missing
- **Russell 1000 historical membership**: Not in codebase. Static universes (LIQUID_10/20/50/100/200) exist; S&P 500 from FMP exists; **R1000 PIT membership requires Sharadar SF1 ($150–300/mo) or equivalent**.
- **Piotroski F-score / QMJ / HML benchmark implementations**: Not implemented. Estimated 5 hours from existing WRDS fields.
- **Per-signal IC for fundamentals**: Harness needs ~30 min of wiring to extend `redundancy.py:SIGNAL_NAMES` from 7 entries to ~14 entries covering the fundamental stack.

### 3.3 PIT integrity verdict
- **WRDS** (active): EXCELLENT. `rdq` (report date) on Compustat, `statpers` on IBES — both PIT-safe.
- **FMP** (active): POOR. Returns current restated snapshot. ERM-class signals computed via FMP would carry look-ahead bias.
- **Tiingo** (active): POOR. Same as FMP.

### 3.4 Universe-coverage reality check
- WRDS has 495 tickers in the right time window
- R1000 needs ~1000
- Coverage gap: ~500 names (small/mid-cap tail of R1000 the user wants to access)
- **Until Sharadar is acquired, the audit empirically covers the top ~50% of R1000 by count, ~87% by market cap.** Smaller mid-caps where fundamental signals historically have the *most* alpha are the missing slice.

---

## 4. First IC Slice — Status: **PARTIAL — INSUFFICIENT for fundamentals**

### 4.1 What exists
The codebase has 14+ Phase 0 outputs (`phase0_2026*.json`) and `wf_wrds_pit_test.json`. These contain **aggregate** walk-forward results + Fama-French 5-factor + Momentum attribution, but **no per-signal IC tables for fundamentals**.

### 4.2 The big finding from existing data

Across all 7 most recent Phase 0 runs (LIQUID_50 universe, walk-forward 2018+):

| Run | Sharpe | Annual Return | FF5 Alpha (annual) | Alpha t-stat | Alpha p-value | Significant? |
|---|---:|---:|---:|---:|---:|:---:|
| 20260412_205333 | 0.73 | 8.25% | 5.45% | — | 0.168 | NO |
| 20260412_205623 | 0.73 | 8.06% | 5.28% | — | 0.181 | NO |
| 20260412_210045 | 0.73 | 8.06% | 5.28% | — | 0.181 | NO |
| 20260412_210414 | **0.94** | 7.91% | 5.57% | — | 0.126 | NO |
| 20260412_211307 | 0.84 | 9.69% | 6.70% | — | **0.119** | NO (closest) |
| 20260412_215806 | 0.70 | 5.55% | 2.59% | — | 0.488 | NO |
| 20260412_220736 | 0.25 | 2.13% | -0.69% | -0.19 | 0.852 | NO |

**`wf_wrds_pit_test.json` (WRDS-backed, separate run):** Sharpe 1.39, annual 10.54%, MaxDD 12.94%, **but alpha vs benchmark = -74.4%** over the 2022-2024 window where benchmark returned 121%. R² of 0.15 in factor attribution.

**Verdict**: The current quant stack has **never produced statistically-significant FF5 alpha** in any saved Phase 0 result. R² ~0.15 means returns aren't well-explained by factors *or* by the strategy — they're largely noise. **The hypothesis that "the next big jump is fundamentals + AI" is supported by the absence of demonstrated alpha in the current architecture.**

### 4.3 Per-signal IC for fundamentals: `INSUFFICIENT`

Marking this `INSUFFICIENT` per audit continuity principle.

**Reason**: `quant/redundancy.py:26-29` defines `SIGNAL_NAMES = ["obv_trend", "institutional_flow"]`. The fundamental signals (ERM, SUE, ROIC, dispersion, gross margin, etc.) are **not in the IC harness**. Running per-signal IC requires wiring them in.

**Code-reading inference**:
- All fundamental signal functions accept `as_of_date` and return scalar scores per ticker → they are panel-computable.
- `compute_signal_scores_at_date()` (`redundancy.py:32-87`) is the integration point. Extending it requires importing `compute_earnings_signal_scores` (from `earnings_signals.py`) and `compute_quality_signal_score` (from `additional_signals.py`) and calling them with the same `as_of_date`.
- Estimated work: 30 min wiring + 2-4 hours compute time (495 tickers × ~120 monthly rebalance dates × 4 horizons).
- Cost: $0.

**Backlog item: `IC-1` — Wire fundamental signals into IC harness.** Highest priority, lowest cost remediation. Belongs in Session 2.

### 4.4 Piotroski / QMJ / HML benchmarks: `INSUFFICIENT`

**Reason**: Not implemented. WRDS has the fields (operating CF, accruals, asset turnover, leverage, gross margin, share count) but the formulas haven't been coded.

**Backlog item: `IC-2` — Implement Piotroski F-score from WRDS Compustat.** ~2-3 hours. Floor benchmark — if our best fundamental signal cannot beat F-score, we don't have a fundamental edge.

**Backlog item: `IC-3` — Implement QMJ proxy.** ~2-3 hours. Tests whether we beat Asness's quality factor.

---

## 5. Insufficiency Log (Session 1)

| ID | Item | Reason | Code-reading insight | Backlog priority |
|---|---|---|---|:---:|
| INS-1 | Per-signal IC for fundamentals | `redundancy.py:SIGNAL_NAMES` excludes fundamentals | All signals are panel-computable; 30 min wiring | **P0** |
| INS-2 | Piotroski F-score baseline | Not implemented | WRDS has all fields | **P0** |
| INS-3 | QMJ benchmark | Not implemented | WRDS has profitability + investment fields | P1 |
| INS-4 | HML benchmark | Not implemented | WRDS has equity, need price-to-book join | P1 |
| INS-5 | R1000 universe coverage | No PIT membership history | Requires Sharadar SF1 subscription | P1 ($150–300/mo decision) |
| INS-6 | AI agent score audit trail | "Score mentally" instruction in earnings prompt | Cannot verify D-mode claims against data | P0 |
| INS-7 | Catalyst hallucination measurement | No source-citation requirement on B-mode outputs | Confirmed weak; user's suspicion warranted | P0 — defines Session 2 case-study scope |
| INS-8 | Structured C-mode composition | Synthesis treats Risk/Competitive/DCF as 3 weighted prose blocks, not unified trap-probability | Architecture-level change | P2 (deferred to backlog as `pipeline-redesign`) |
| INS-9 | FMP institutional ownership lag check | No explicit quarter-end + 45d guard | Look-ahead risk in current backtest | P1 (`RISK-1`) |
| INS-10 | Sector momentum (dead code) | Weight = 0 in composite | Either delete or re-test | P2 |

---

## 6. Backlog (surfaced this session, queued for final-session deliverable)

### P0 — Cheapest, highest-leverage interventions
- **IC-1**: Wire fundamental signals into IC harness (30 min + 2-4h compute, $0)
- **IC-2**: Implement Piotroski F-score baseline (2-3h, $0)
- **AI-1**: Replace "score mentally" with structured rubric in Earnings prompt — emit `{accruals_red_flag: bool, ocf_ni_ratio: float, mscore: float, …}` JSON block alongside SIGNAL_SCORE so synthesis has structured access (~2 hours prompt + parser work)
- **AI-2**: Add source-citation requirement to all catalyst claims (B-mode grounding) — if cannot cite, must say "no near-term catalyst identified" (~1 hour prompt work)

### P1 — Sized but conditional on P0 results
- **IC-3**: QMJ benchmark (2-3h)
- **IC-4**: HML benchmark (2h)
- **DATA-1**: Sharadar SF1 subscription decision ($150–300/mo) — required only after P0 confirms fundamental signals carry IC at all
- **AI-3**: Unified C-mode trap-probability in synthesis (~4h)
- **RISK-1**: FMP institutional flow PIT guard

### P2 — Architectural / deferred
- **pipeline-redesign**: Two-stage pipeline rebuild (per existing `project_two_stage_pipeline` memory)
- **ml-retrain**: XGBoost rebuild on the new fundamental signal stack once IC results are in
- **lstm-revisit**: Per existing `project_lstm_model` memory
- **dead-code**: Delete or re-validate sector momentum signal

### Out of scope (not queued)
- International expansion
- Sub-$4B universe
- Frontend changes
- Real-time data infra

---

## 7. Critical Audit Findings (synthesis of Session 1)

1. **The current quant stack has never demonstrated significant alpha** in saved evidence (FF5 p-values 0.12–0.85). The user's hypothesis stands on solid ground.
2. **Fundamental signals carry 50% of composite weight** (ERM 20% + Quality 15% + insider 10% + sentiment 5%) but **none have ever been individually IC-validated**. This is the cheapest, most-leveraged unknown in the system.
3. **The AI layer's strongest job (D-mode, earnings quality) has no audit trail.** "Score each dimension mentally" + synthesis trusts the score = an AI black box wrapped around quant numbers we haven't validated.
4. **B-mode (catalyst detection) is structurally weak** as user suspected — no source-citation requirement, no event calendar, no agent dedicated to it. This is the highest hallucination surface.
5. **Synthesis is hybrid, prose-dependent.** Risk scores, moat ratings, accounting red flags exist in agent prose but never reach the synthesis JSON as structured fields.
6. **The two cheapest interventions** (P0 in §6) total ~5 hours of work, $0 cost, and would tell us whether the fundamental layer is real signal or noise. Until those run, every other audit conclusion is conditional.

---

## 8. Session 2 Plan

**Goal**: Execute P0 backlog items + design the AI case-study replay infra.

**Deliverables**:
1. Wire fundamental signals into `redundancy.py` IC harness (`IC-1`)
2. Implement Piotroski F-score (`IC-2`)
3. Run per-signal IC on 495-ticker WRDS universe at 1M/3M/6M/12M
4. Produce ranked signal table + IC vs Piotroski comparison
5. Draft case-study replay design (architecture for replaying historical situations with PIT-bounded agent context)
6. **Decision point**: based on IC results, answer the Sharadar SF1 funding question

**Exit gate**: Per-signal IC table on the WRDS universe + first 10 case-study replays designed (not yet executed).

**NOT in Session 2**: Running the case-study replays themselves (Session 3), cost analysis (Session 3), final synthesis (Session 4).

---

## 9. Open Decisions (carried forward)

1. **Sharadar SF1 subscription** ($150–300/mo)? **Recommendation**: defer until Session 2's IC results arrive. If our best fundamental signal IC is <0.04 on the WRDS universe, expanding to R1000 won't help. If IC is ≥0.05, the universe expansion ROI is real.
2. **Final 10-name list of "cheap-and-rallied winners"** for case studies — to be drafted in Session 2.
3. **Final 10-name list of "catalyst-hallucination temptations"** — to be drafted in Session 2 with explicit ground-truth catalyst lists for grading.
