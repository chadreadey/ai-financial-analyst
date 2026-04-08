# Alpha Expansion Plan — From Retail Quant to Systematic Shop

**Created:** 2026-04-07
**Status:** Master plan. Supersedes PLAN_NEXT.md for prioritization. References PLAN_WRDS_INTEGRATION.md and PLAN_SIGNAL_STRESS_TEST.md (both still valid for implementation detail).
**Origin:** Literature review of Papic's Geopolitical Alpha + structured argumentation (Layers 1-4) over signal strategy + full codebase review.

---

## Strategic Context

**Current state (as of Apr 7, 2026):**
- 5 signal CATEGORIES live: technical (6 sub-signals), sentiment (FinBERT + insider MSPR), fundamental (quality + earnings revision), earnings (ERM/SUE/dispersion), ML (LSTM 7th signal)
- Walk-forward backtest engine with IC calibration, regime filter (VIX + golden/death cross), CPCV implemented
- WRDS store partially scaffolded (`wrds_store.py`, 501 lines)
- Agent veto quantification experimental (`agent_veto.py`)
- Redundancy detection built but NOT WIRED IN (`redundancy.py`)
- CPCV built but NOT DEFAULT (`cpcv.py`)

**Binding constraints (from structured argument):**
1. Signal combination and validation > signal diversity. Tools exist but aren't used.
2. No factor-neutral alpha construction. Can't distinguish alpha from factor exposure.
3. Cross-asset and institutional flow signals genuinely missing.
4. Agent layer is the unique edge — but unvalidated.
5. MacroAgent and CompetitiveAgent outputs are too shallow for real conviction.

**Goal:** Build a signal stack and agent layer competitive with sub-$100M systematic shops. Prioritize validation rigor over signal count. LLM is the LAST layer, not the first.

---

## Phase 0: Fix the Foundation (BEFORE any new signal)

**Principle:** You cannot evaluate new signals if your validation infrastructure isn't running. Everything you need is already built — just not wired in.

| Step | Action | File(s) | Effort | Gate |
|------|--------|---------|--------|------|
| 0a | Wire `redundancy.py` into default backtest flow | `quant/backtest.py` | 1 day | Signal correlation matrix runs automatically at backtest completion |
| 0b | Wire `cpcv.py` as default validation | `quant/backtest.py`, `scripts/run_backtest.py` | 1 day | PBO reported in every backtest output |
| 0c | Add Fama-French factor regression | `quant/factor_attribution.py` (create or verify exists from PLAN_SIGNAL_STRESS_TEST) | 2-3 days | Every backtest reports FF5+Mom alpha and t-stat |
| 0d | Run full diagnostic on current 5-category stack | — | 1 day | Know which signals have incremental IC, which are factor exposure |

**Decision gate:** After 0d, you know:
- How many of your current signals survive factor adjustment
- Whether LSTM adds IC or just overfits
- Whether sentiment/fundamental overlays have incremental value
- Your ACTUAL alpha (not raw Sharpe, factor-adjusted alpha with t-stat)

**See:** `PLAN_SIGNAL_STRESS_TEST.md` Phase 0 for implementation detail. Much of this may already be partially done (check `quant/redundancy.py` and `quant/factor_attribution.py` current state).

---

## Phase 1: WRDS Activation + Fundamental Signal Upgrade

**Principle:** Upgrade data quality for signals you already have, then add the highest-value fundamental signals from the WRDS research.

### 1a: WRDS Credential Setup (1 hour)
```bash
pip install wrds
python -c "import wrds; db = wrds.Connection(); print(db.list_libraries()); db.close()"
```
Confirm access to: `crsp`, `comp`, `ibes`, `tfn`, `optionm`, `trace`, `ff`. Record which are available.

### 1b: Activate `wrds_store.py` (existing plan)
Follow `PLAN_WRDS_INTEGRATION.md` Phases 1-3. The plan is well-structured. Key deliverables:
- Point-in-time SQLite store with `rdq`-based filtering
- FundamentalProvider protocol (WRDS vs FMP backends)
- Backtest engine passes `as_of_date=reb_date` to fundamental calls
- Commercial replacement tags for every WRDS dataset

### 1c: Switch SUE/ERM to IBES Backend (existing plan)
Follow `PLAN_WRDS_INTEGRATION.md` Phase 4. Your `earnings_signals.py` already has the signal logic — this upgrades the data source.

### 1d: Add Gross Profitability Signal (NEW — highest priority new signal)
```python
# In quant/fundamentals.py or new quant/compustat_signals.py
def compute_gross_profitability(ticker, provider, as_of_date=None) -> tuple[float, dict]:
    """
    Novy-Marx (2013) "The Other Side of Value"
    GP = (revt - cogs) / at
    IC: 0.03-0.06. Survives FF5. Orthogonal to value (HML).
    One of the most robust quality signals in finance.

    WRDS: comp.funda fields: revt, cogs, at
    Commercial replacement: FMP income statement + balance sheet ($29/mo)
    """
```
**Why this signal first:** Single formula, completely orthogonal to everything in your stack, 5-6% annualized alpha, decades of replication. Cheapest possible test of whether WRDS fundamental signals add IC to your pipeline.

### 1e: Add Accruals Anomaly Signal (NEW)
```python
def compute_accruals_score(ticker, provider, as_of_date=None) -> tuple[float, dict]:
    """
    Sloan (1996). Accruals = (ni - oancf) / at
    High accruals → low future returns (short signal).
    IC: 0.03-0.06. Has decayed but still significant.

    WRDS: comp.funda fields: ni, oancf, at
    """
```

### 1f: Add Asset Growth Signal (NEW)
```python
def compute_asset_growth(ticker, provider, as_of_date=None) -> tuple[float, dict]:
    """
    Cooper, Gulen & Schill (2008).
    AG = (at_t - at_{t-1}) / at_{t-1}
    Low asset growth outperforms high. 7% gross for extreme deciles.

    WRDS: comp.funda field: at (two consecutive years)
    """
```

### 1g: Validate Each New Signal
For EACH signal added in 1d-1f, before integrating into composite:
1. Compute cross-sectional rank IC on liquid_50 universe
2. Run Fama-MacBeth to get incremental IC after controlling for existing signals
3. Must have t > 2 to enter the composite
4. If t < 2, document and discard — do not force it in

**Effort:** 2-3 weeks total for Phase 1 (assumes WRDS access confirmed)

---

## Phase 2: Cross-Asset + Institutional Flow (genuinely missing categories)

**Principle:** Add signals from DIFFERENT MARKETS that are orthogonal to all equity-derived signals.

### 2a: Credit Spread Regime Signal (easy, free)
- Source: FRED (BAMLH0A0HYM2 — already pulled by MacroAgent)
- Signal: HY spread monthly change > +50bps = risk-off overlay, < -50bps = risk-on boost
- Integration: Add to existing regime filter alongside VIX + golden cross
- NOT a stock-level signal — a market regime conditioner
- **Effort:** 1-2 days

### 2b: 13F Institutional Ownership Changes (WRDS)
- Source: `tfn.s34` — quarterly institutional holdings
- Signal: Quarter-over-quarter change in institutional ownership as % of shares outstanding
- Academic: Gompers & Metrick (2001) — increasing IO predicts positive returns 1-2 quarters
- Lag: quarterly, so monthly rebalance uses most recent available quarter
- **Effort:** 3-4 days (aggregation logic + CRSP linking for shares outstanding)

### 2c: IV Skew (if OptionMetrics available on WRDS)
- Source: `optionm.vsurfd` — volatility surface daily
- Signal: `Skew = IV(OTM Put, delta=-0.25) - IV(ATM Call, delta=0.50)`, 30-day maturity
- Academic: Xing, Zhang & Zhao (2010) — ~10% gross for extreme quintiles
- This is the most alpha-dense signal in the WRDS research, but depends on data access
- **Effort:** 3-4 days

### 2d: Short Interest (free, no WRDS needed)
- Source: FINRA short interest (bi-monthly, free) or Compustat supplemental
- Signal: Short interest as % of float, changes over time
- Context-dependent: high SI + positive momentum = squeeze risk (bullish); high SI + negative momentum = informed short (bearish)
- **Effort:** 2-3 days

### Validation gate: Same as Phase 1 — every signal must prove incremental IC (t > 2) via Fama-MacBeth before entering composite.

**Effort:** 2-3 weeks total for Phase 2

---

## Phase 3: Agent Layer as Alpha Source (the unique edge)

**Principle:** The six LLM agents are the only component of your stack that no other retail quant has. If agent verdicts have positive incremental IC over quant signals, this is a genuine and defensible edge. If they don't, they're expensive window dressing.

### 3a: Agent Veto Backtest (CRITICAL — prove or disprove the edge)
- `agent_veto.py` already converts agent prose → quantified veto signals
- Run walk-forward backtest: quant-only vs quant + agent veto overlay
- Measure incremental IC of agent verdicts after controlling for all quant signals
- **This is the single highest-leverage test in the entire plan.** If agent verdicts add IC, the entire AI Financial Analyst platform is validated as more than a UI wrapper. If they don't, the agents are a research tool for you personally but not a trading signal source.
- **Effort:** 1 week

### 3b: MacroAgent Upgrade — Depth over Breadth
**Problem:** "Taiwanese and Chinese tensions could affect TSMC" is useless. Generic geopolitical takes provide zero IC.

**Solution:** Restructure MacroAgent prompt and enrichment to produce constraint-based analysis (Papic framework):
- For each geopolitical risk identified, require: (1) which constraint category (political/economic/financial/geopolitical/legal), (2) what the binding constraint IS (specific — e.g., "TSMC's CoWoS advanced packaging capacity is the bottleneck, not fab capacity"), (3) what the latest movement is (via Tavily real-time search), (4) quantified risk level (probability-weighted impact on revenue/earnings)
- Add credit spread data to MacroAgent enrichment (already in FRED pipeline, just not prominently featured)
- Add Papic-style regime classification: is the current environment Hydrogen/Goldilocks/Stagflation/Secular Stagnation?

**Files:** `prompts/macro.md`, `agents/macro.py`, `market_enrichment.py`
**Effort:** 1 week

### 3c: CompetitiveAgent Upgrade — Full Industry Landscape
**Problem:** Shows top-3 competitors with margin comparison. Doesn't show sub-industry dynamics, brand-level analysis, or cultural/trend signals.

**Solution:**
- Expand peer discovery beyond FMP `stock_peers` — add SIC/NAICS code matching for full sub-industry coverage
- Add Tavily web search specifically for brand-level competitive intelligence (e.g., "Jordan brand market share 2026", "Nike NIL deals competitive landscape")
- Restructure prompt to require: (1) full competitive positioning within sub-industry, (2) brand-level breakdown where applicable, (3) trend analysis (consumer sentiment, cultural relevance), (4) specific competitive threats with quantified revenue risk

**Files:** `prompts/competitive.md` (new prompt structure), `agents/competitive.py`, `peer_enrichment.py`
**Effort:** 1 week

### 3d: Sector Specialist Agent Activation
- `agents/sector.py` is skeletal. Sector-specific prompts exist (`prompts/sector_*.md`) but aren't wired into the orchestrator.
- For tech/AI sector specifically (Chad's deepest domain knowledge), the sector specialist should provide: supply chain mapping, CapEx cycle positioning, technology transition risk, TAM bottleneck analysis.
- **Effort:** 3-4 days to wire in and write a real tech sector prompt

---

## Phase 4: Signal Combination Upgrade (after Phases 0-3)

**Principle:** Once you have 8-12 validated signals across 5+ categories, the combination method becomes the primary alpha source. This is where shops like AQR spend most of their research budget.

### 4a: Composite Quality Factor (AQR QMJ-style)
Combine Gross Profitability + Accruals + ROE + Earnings Stability into a single quality composite. AQR's QMJ is publicly documented — replicate it.

### 4b: Factor-Neutral Portfolio Construction
Before trading any signal, project out exposure to FF5 factors. Trade the RESIDUAL alpha only. This is the single biggest gap between retail and institutional.

### 4c: Regime-Conditional Signal Weighting
Different signals work in different macro regimes (from Papic's framework):
- Hydrogen (high growth, high inflation): momentum + commodities exposure signals
- Stagflation: quality + low-vol signals
- Goldilocks: growth + momentum
- Secular stagnation: value + yield signals

Use the regime classification from MacroAgent (Phase 3b) to condition signal weights.

### 4d: Non-Linear Signal Combination
Once you have enough signals and data, test tree-based models (XGBoost) for signal combination. Your LSTM is already doing this for 11 features — expand it to all validated signals.

---

## Phase 5: Research Feed Pipeline (DEFERRED)

See `memory/project_research_feed_pipeline.md`. Do not start until Phases 0-3 are complete and validated. The agent layer must be proven before adding external research ingestion.

---

## Execution Timeline

```
Phase 0 (foundation)          ← START HERE. 1 week.
    │
    ├── 0a-0b: Wire redundancy.py + cpcv.py
    ├── 0c: Fama-French factor regression
    └── 0d: Full diagnostic on current stack
         │
         ▼ DECISION GATE: Know your actual alpha
         │
Phase 1 (WRDS + fundamentals)     2-3 weeks
    │
    ├── 1a: WRDS credentials
    ├── 1b: wrds_store.py activation (see PLAN_WRDS_INTEGRATION.md)
    ├── 1c: SUE/ERM → IBES backend
    ├── 1d-1f: Gross Profitability + Accruals + Asset Growth
    └── 1g: Validate each (incremental IC, t > 2)
         │
Phase 2 (cross-asset + flow)      2-3 weeks (can overlap Phase 1)
    │
    ├── 2a: Credit spread regime
    ├── 2b: 13F institutional changes
    ├── 2c: IV skew (if OptionMetrics available)
    └── 2d: Short interest
         │
Phase 3 (agent layer)             3-4 weeks (can overlap Phase 2)
    │
    ├── 3a: Agent veto backtest ← HIGHEST LEVERAGE TEST
    ├── 3b: MacroAgent upgrade (Papic constraints + Tavily real-time)
    ├── 3c: CompetitiveAgent upgrade (full landscape + brands)
    └── 3d: Sector specialist activation
         │
         ▼ DECISION GATE: Do agents add IC?
         │
Phase 4 (combination upgrade)     2-3 weeks
    │
    ├── 4a: QMJ composite
    ├── 4b: Factor-neutral construction
    ├── 4c: Regime-conditional weights
    └── 4d: Non-linear combination (XGBoost)
         │
Phase 5 (research feed)           DEFERRED
```

**Total estimated time:** 10-14 weeks for Phases 0-4, working part-time alongside other commitments.

---

## Success Criteria

| Metric | Current | Phase 0 Target | Phase 1-2 Target | Phase 3-4 Target |
|--------|---------|---------------|-----------------|-----------------|
| Factor-adjusted alpha t-stat | ~1.08 (unverified) | Measured | > 2.0 | > 2.5 |
| Independent signal categories | 5 (some redundant) | Validated count | 7-8 | 8-10 + agent overlay |
| PBO (Probability of Backtest Overfitting) | Unknown (CPCV not default) | Measured | < 20% | < 15% |
| Fama-MacBeth signals with t > 2 | Unknown | Measured | ≥ 5 | ≥ 7 |
| Agent veto incremental IC | Untested | — | — | Positive, t > 2 |
| MacroAgent depth | Generic | — | — | Constraint-based, quantified |
| CompetitiveAgent depth | Top-3 peers | — | — | Full sub-industry + brands |

---

## What This Plan Kills

- VC funding → public market signal (not tradeable, killed in argumentation)
- Social policy → macro as an "edge" (reclassified as hypothesis until formalized and backtested)
- Adding signals before fixing validation infrastructure (Phase 0 is non-negotiable)
- Research feed pipeline (deferred to Phase 5, after agent layer proven)
- n8n workflow for SA/Substack ingestion (idea saved in memory, not actionable yet)

---

## Key References

- `PLAN_WRDS_INTEGRATION.md` — Detailed WRDS architecture, schema, commercial tags. Still valid.
- `PLAN_SIGNAL_STRESS_TEST.md` — Phase 0 diagnostic methodology. Still valid.
- `PLAN_WRDS_DATA_EXPANSION.md` — Check for overlap with Phase 2 signals.
- `literature-reviews/geopolitical-alpha-papic-2020.md` — Papic constraints framework for MacroAgent upgrade.
- `literature-reviews/thought-nodes/geopolitical-constraints-framework.md` — Graph node with regime framework data.
- `memory/project_research_feed_pipeline.md` — Deferred Phase 5 idea.
