# North Star: Autonomous Trading Intelligence System

> This is a living document. It defines what this system is becoming, not just what it is today.
> Update it as decisions are made and assumptions are validated or disproven.
> Last updated: 2026-04-12

---

## What This System Is

An autonomous, self-improving trading intelligence system that combines quantitative ranking with multi-agent reasoning to generate, execute, and learn from equity trades — with no human input required for normal operation.

## Core Beliefs (Tested, Not Assumed)

These are convictions earned from backtesting, not borrowed from textbooks:

- **Technical indicators have zero cross-sectional IC at monthly frequency.** SMA, RSI, Bollinger, mean reversion — all disproven. OBV is the sole survivor. We don't use signals we can't validate.
- **Earnings revision momentum (ERM) is the strongest signal available to us.** IC 0.04-0.08, survives FF5+Mom adjustment.
- **VIX 30/40 regime gating is the gold standard.** Sharpe 1.04, PBO 0% across 252 CPCV paths.
- **Weekly rebalancing destroys value.** Sharpe 0.02 vs monthly 1.04. Transaction costs and churn dominate.
- **Our edge is reasoning quality and validation rigor, not signal discovery.** We will never out-data institutions. We can out-think them per dollar of compute.
- **Every new component must pass CPCV before it touches the live pipeline.** No exceptions.

---

## The Four Layers

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 4: INTERFACE                                             │
│  Dashboard, human override, trade review, system health         │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 3: EXECUTION & MEMORY                                   │
│  Live trading, position management, outcome tracking,           │
│  feedback loops, agent accuracy scoring                         │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 2: REASONING                                             │
│  Agent fleet (analysis), challenger agent, catalyst agent,      │
│  synthesis, verdict override                                    │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 1: QUANTITATIVE FOUNDATION                               │
│  Adaptive universe, signal computation, XGBoost ranking,        │
│  regime detection, sourcing agent                               │
└─────────────────────────────────────────────────────────────────┘
```

Each layer depends on the one below it. Build bottom-up, validate at each layer.

---

## Layer 1: Quantitative Foundation

### What Exists Today
- Signal pipeline: OBV (sole active), ERM, SUE, dispersion, institutional flow
- Regime detection: VIX thresholds, SPY SMA cross, Kritzman-Li turbulence, macro overlay
- CPCV validation framework (12-16 groups, purge/embargo, PBO, DSR)
- Data providers: Tiingo (prices), Finnhub (sentiment/news), FMP (fundamentals), FRED (macro), WRDS (academic point-in-time)
- Static universe: LIQUID_50/100/200, dynamic S&P 500 via FMP

### What's Next

**Adaptive Universe**
The universe should not be a static list. It should be a living filter that re-evaluates membership based on investability criteria:
- Market cap > $5B (liquidity, institutional coverage)
- Sufficient institutional holdings (ensures analyst coverage, reduces manipulation risk)
- Minimum average daily volume (ensures we can enter/exit without impact)
- Positive TTM revenue (excludes pre-revenue/speculative)
- Not in active corporate action (M&A, bankruptcy, delisting)

The universe shrinks and expands as stocks cross these thresholds. Recomputed weekly (cheap — just API lookups against FMP/Finnhub data we already have).

**Sourcing Agent**
Expands the funnel beyond the adaptive universe filter:
- Step 1: FMP screener + Finnhub recommendation trends → candidate list (~400-500)
- Step 2: Quick quant score (sector momentum, revision direction, relative strength) → top 200
- Step 3: Optional single LLM call for thematic discovery ("AI infrastructure beneficiaries", "nearshoring plays")
- Output: ~200 ranked tickers feeding into the quant ranking stage

Mostly quant, not LLM-heavy. The LLM call is for catching narratives that screens miss.

**XGBoost Meta-Model**
Replaces hand-tuned signal weights with a learned ranking model:
- Input: individual signal scores (OBV, ERM, SUE, dispersion, inst flow, ATR regime)
- Objective: `rank:pairwise` (LambdaMART)
- Training: precomputed feature matrix, ~6K rows, <1 second to train
- Validation: must pass CPCV gate before integration (PBO <= linear, median OOS Sharpe >= linear)
- Linear blend stays as fallback baseline

> Plan: `plans/PLAN_XGBOOST_META_MODEL.md`

---

## Layer 2: Reasoning

### What Exists Today
- 7 agents: DCF, Risk, Earnings, Competitive, Pattern, Macro, Sector Specialist
- BaseAgent abstraction with async LLM calls
- Orchestrator: Phase 1 parallel fan-out → Phase 2 synthesis
- Deterministic verdict override: weighted_score forces conviction from thresholds
- Enrichment pipeline: SEC filings, XBRL, market data, signal vector → agent context

### What's Next

**Catalyst Agent**
Adds temporal awareness — what's about to happen to this stock:
- Earnings calendar scan (Finnhub — defined but unused)
- FOMC/macro event proximity (Finnhub economic calendar — defined but unused)
- Recent 13D/8-K filings (activist entry, material events)
- Analyst upgrade/downgrade recency
- Output: CatalystVector per ticker + risk window flags
- Rule: never enter new positions within 3 days of earnings (binary event risk)
- Enriches agent context via `enrichment_sections["catalyst_context"]`

Uses APIs we already pay for. No new data sources needed.

**Challenger Agent**
Dedicated contrarian that receives the consensus of other agents and attacks it:
- Input: synthesis draft from other 6-7 agents (not raw data)
- Task: find the specific assumption that, if wrong, breaks the thesis
- Must name which agent's reasoning it's challenging and why
- Output: structured `{ challenge, target_agent, break_condition, probability }`
- Feeds into synthesis — high-probability break conditions lower conviction

This is the primary defense against confirmation bias. All agents see similar data and tend to agree. The challenger sees the *conclusion* and tries to break it.

**Model Interpreter Agent**
Translates XGBoost feature importance into prose for other agents:
- "XGB ranked NVDA #3 primarily because institutional flow is strongly positive (+0.8) and ERM revision momentum accelerated (+0.6). OBV is neutral."
- Other agents can now reason about *why* the quant pipeline likes a stock
- Prevents the "black box" problem where agents analyze in a vacuum

---

## Layer 3: Execution & Memory

### What Exists Today
- Paper trading with auto-entry on high-conviction signals
- Alpaca client defined but dormant
- No feedback loop — trade outcomes are not compared to pre-trade thesis
- Agent weights in synthesis are hand-tuned (Earnings 0.22, Pattern 0.18, etc.)

### What's Next

**Live Execution Bridge**
- Alpaca API for order placement (already have client code)
- Order types: market on open (MOO) for entries, limit for exits
- Position sizing: conviction-weighted within regime scalar
- Kill switch: human override halts all new entries immediately
- Failsafe: max daily loss threshold triggers automatic risk-off

**Trade Memory Store**
Every trade gets a full record:

```
Pre-Trade (captured at entry):
  - XGB rank and feature importances
  - All agent verdicts + confidence scores
  - Catalyst flags active at entry
  - Challenger agent's break condition
  - Synthesis thesis (why we entered)
  - Regime state at entry

Post-Trade (captured at exit):
  - Realized return vs XGB predicted rank
  - Max adverse excursion (worst drawdown during hold)
  - Did the catalyst play out?
  - Did the challenger's break condition materialize?
  - Which agent was most accurate about direction?
  - Which agent was most wrong?
  - Time held vs expected holding period
```

**Agent Accuracy Tracker**
- Rolling per-agent directional accuracy (was the agent's signal correct?)
- Per-agent contribution to profitable vs unprofitable trades
- Output: earned agent weights for synthesis (replaces hand-tuned 0.22/0.18/0.17/...)
- Same logic as XGBoost over hand-tuned signal weights — let the data decide which agents matter
- Guardrail: shrinkage toward equal weights (no agent drops below 5% or exceeds 40%)

**XGBoost Retrain Loop**
- Monthly retrain using expanding window of realized outcomes
- Feature matrix updated with new months of signal scores + forward returns
- Model comparison: new model must beat prior model on holdout before swapping
- Logged: feature importance drift, performance delta

---

## Layer 4: Interface

### What Exists Today
- React + Vite + Tailwind frontend with 7 pages
- Analysis page: enter ticker, run agents, see synthesis report
- Watchlist: add tickers, see cards with price + recommendation
- Paper trading: manual position entry, open/closed tables, equity curve
- Backtest: natural language config, equity curve, trade log, metrics
- Deep dive: per-stock performance history and charts
- News and Industry pages (basic)
- No auth, no persistent user state, no real-time updates

### What's Missing (The Dashboard Vision)

The current frontend is built for *manual analysis* — you type a ticker and wait. The autonomous system needs a dashboard built for *monitoring and intervention*.

**The dashboard should answer these questions at a glance:**

1. **What did the system do today?** (Trade log, entries/exits, P&L)
2. **What is it about to do?** (Pending signals, upcoming rebalance, catalyst flags)
3. **Is it healthy?** (Agent accuracy trends, model drift, API status, error rates)
4. **Where should I intervene?** (Challenger alerts, low-confidence positions, regime warnings)
5. **Is it getting better?** (Rolling Sharpe, agent accuracy curves, prediction error trends)

> NOTE: Dashboard design is still being honed. The sections below are a starting
> framework — expect this to evolve through discussion and iteration.

**Proposed Pages:**

```
┌─ Dashboard (home) ──────────────────────────────────────────────┐
│                                                                  │
│  ┌─ System Status Bar ────────────────────────────────────────┐ │
│  │  Pipeline: ● Running    Last run: 6:00 AM EST              │ │
│  │  Regime: BULLISH (VIX 18.3)   Positions: 8 long, 2 short  │ │
│  │  Today P&L: +$1,240 (+0.31%)  Kill switch: [OFF]          │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌─ Today's Actions ──────────┐  ┌─ Alerts ─────────────────┐ │
│  │  BUY  NVDA  @ $142.30     │  │  ⚠ AAPL earnings in 2d   │ │
│  │  BUY  LLY   @ $891.20     │  │  ⚠ Challenger: TSLA      │ │
│  │  SELL PARA  @ $11.82      │  │    thesis fragile (p=0.4) │ │
│  │  HOLD 7 positions         │  │  ● XGB retrained (drift   │ │
│  └────────────────────────────┘  │    <5%, no swap needed)   │ │
│                                  └───────────────────────────┘ │
│                                                                  │
│  ┌─ Portfolio ────────────────────────────────────────────────┐ │
│  │  Equity curve (30d)           Sector exposure pie          │ │
│  │  ████████████████▓▓▓▓▓▓       Tech: 28% | HC: 18%        │ │
│  │                                Fin: 15% | Ind: 12%        │ │
│  │  Sharpe (rolling 90d): 1.12   Max position: NVDA (4.8%)   │ │
│  │  Max drawdown: -3.2%          Correlation: 0.34 avg pair  │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌─ System Health ────────────────────────────────────────────┐ │
│  │  Agent accuracy (30d rolling):                             │ │
│  │    Earnings: 68% ██████▓░░░                                │ │
│  │    DCF:      61% ██████░░░░                                │ │
│  │    Risk:     72% ███████▓░░  ← best performer              │ │
│  │    Pattern:  54% █████░░░░░                                │ │
│  │    Macro:    58% █████▓░░░░                                │ │
│  │                                                            │ │
│  │  XGB feature importance (current model):                   │ │
│  │    ERM: 31% | InstFlow: 24% | OBV: 18% | ...              │ │
│  │  Prediction IC (last 3 months): 0.042                     │ │
│  └────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘

┌─ Trade Review (feedback loop) ──────────────────────────────────┐
│                                                                  │
│  Recent closed trades with thesis comparison:                    │
│                                                                  │
│  MSFT  +4.2%  Held 28d  Thesis: "ERM +0.7, strong revision"    │
│    ✅ Earnings agent correct (predicted beat, beat by 8%)        │
│    ❌ DCF agent wrong (said overvalued, rallied 6%)              │
│    Challenger said: "cloud growth deceleration" — didn't happen  │
│    [Mark as: learned / noise / unlucky]                          │
│                                                                  │
│  PARA  -8.1%  Held 14d  Thesis: "Activist entry, value unlock"  │
│    ❌ Competitive agent wrong (moat weaker than assessed)         │
│    ✅ Challenger correct (said "streaming losses accelerating")   │
│    ✅ Risk agent correct (flagged high vol, stop triggered)       │
│    [Mark as: learned / noise / unlucky]                          │
│                                                                  │
│  Human labels feed back into agent accuracy tracker              │
└──────────────────────────────────────────────────────────────────┘

┌─ Opportunity Radar ─────────────────────────────────────────────┐
│                                                                  │
│  Top 20 ranked stocks (XGB) with catalyst overlay:               │
│                                                                  │
│  #1  NVDA   XGB: 0.92  Catalyst: post-earnings drift (+12%)     │
│  #2  LLY    XGB: 0.87  Catalyst: FDA decision in 18d            │
│  #3  AVGO   XGB: 0.84  Catalyst: none                           │
│  #4  AAPL   XGB: 0.81  Catalyst: ⚠ earnings in 2d — BLOCKED    │
│  ...                                                             │
│                                                                  │
│  Click any row → full agent analysis + challenger output         │
└──────────────────────────────────────────────────────────────────┘

┌─ Deep Dive (existing, enhanced) ────────────────────────────────┐
│  /stock/:ticker — add:                                           │
│  - Agent verdict history (how each agent scored over time)        │
│  - Catalyst timeline (upcoming + past events)                    │
│  - Trade history for this ticker (entries, exits, P&L)           │
│  - Challenger history (what was challenged, was it right?)        │
└──────────────────────────────────────────────────────────────────┘

┌─ Backtest Lab (existing, enhanced) ─────────────────────────────┐
│  Add:                                                            │
│  - XGBoost vs linear blend comparison mode                       │
│  - CPCV results visualization (OOS Sharpe distribution)          │
│  - Feature importance over time chart                            │
│  - Agent accuracy backtesting (if we'd used earned weights)      │
└──────────────────────────────────────────────────────────────────┘
```

---

## Trigger Engine (Batch → Event-Driven)

### Current State: Pure Batch
- Backtest runs on demand or scheduled
- Analysis runs when user types a ticker
- Paper trades entered manually or auto-triggered at rebalance

### Target State: Event-Driven with Batch Seed

```
┌─ Scheduled Triggers ────────────────────┐
│  Daily 6:00 AM:  Full pipeline run      │
│  Weekly Monday:  Universe recomputation  │
│  Monthly 1st:    XGB retrain cycle      │
│  Monthly 1st:    Agent accuracy update  │
└─────────────────────────────────────────┘

┌─ Event Triggers ────────────────────────┐
│  Price:    >3% intraday move            │
│  Volume:   >2x 20-day average           │
│  News:     Finnhub webhook (if avail)   │
│  Earnings: release detected             │
│  Filing:   13D, 8-K detected            │
│  Model:    XGB rank change >20 pctile   │
│  Regime:   VIX crosses threshold        │
│                                         │
│  Each trigger → re-run pipeline for     │
│  affected ticker(s) only                │
└─────────────────────────────────────────┘
```

Event triggers don't require a fundamentally different pipeline. They run the same code as the daily batch — just for one ticker, triggered by an event instead of a schedule. The infrastructure need is a lightweight event listener (poll-based initially, webhook-based later) and a job queue.

---

## What We Don't Build

Discipline is knowing what to skip:

- **Custom data infrastructure.** CSV files + SQLite + JSON disk cache is our feature store. We don't need Kafka, Redis, or a data warehouse at our scale.
- **LangGraph / LangChain.** Our async orchestrator does everything we need. These frameworks add abstraction without capability at our architecture's complexity level.
- **Real-time tick data.** We rebalance monthly. Intraday data doesn't improve our signals. Event triggers work on daily bars.
- **Multiple XGBoost models.** One ranking model. ~6K rows can't support four specialized models without overfitting.
- **GPU compute.** XGBoost trains in <1 second on CPU. CPCV with precomputed features runs in minutes. The bottleneck is API calls, not compute.

---

## Implementation Roadmap

### Phase A: Reasoning Quality (Current Focus)
*Your stated edge. Make the agents better before making the system faster.*

- [ ] Challenger Agent — contrarian analysis on synthesis consensus
- [ ] Catalyst Agent — temporal awareness using existing Finnhub/FMP APIs
- [ ] XGBoost meta-model — learned signal combination (Phases 1-3 of plan)
- [ ] Adaptive universe — dynamic filter replacing static LIQUID_* lists

### Phase B: Feedback Loop
*Self-improving requires memory. Close the loop between decisions and outcomes.*

- [ ] Trade Memory Store — pre-trade thesis + post-trade outcomes
- [ ] Agent Accuracy Tracker — per-agent rolling directional accuracy
- [ ] Earned synthesis weights — agent weights from track record, not hand-tuning
- [ ] Model Interpreter Agent — XGB reasoning → prose for agents
- [ ] XGB retrain loop — monthly expanding window with holdout comparison

### Phase C: Autonomy
*Event-driven execution. The system runs without you.*

- [ ] Live Execution Bridge — Alpaca API orders, fill tracking
- [ ] Trigger Engine — event listener for price/volume/news/filing events
- [ ] Sourcing Agent — dynamic universe expansion + thematic discovery
- [ ] Kill switch + failsafes — max daily loss, position limits, circuit breakers
- [ ] Alerting — notifications for trades, regime changes, system errors

### Phase D: Dashboard
*The interface for monitoring, not operating.*

- [ ] Dashboard home — system status, today's actions, portfolio, health
- [ ] Trade Review page — thesis vs outcome comparison, human labeling
- [ ] Opportunity Radar — ranked candidates with catalyst overlay
- [ ] Enhanced Deep Dive — agent history, catalyst timeline, trade log per ticker
- [ ] Enhanced Backtest Lab — XGB vs linear, CPCV visualization, feature importance

---

## Open Questions

Things still being figured out. Update this section as answers emerge.

- **Dashboard tech stack:** Keep React + Vite or move to Next.js for SSR + API routes? Current FastAPI backend works, but real-time updates (WebSocket for trade alerts, live P&L) may benefit from a unified framework.
- **Event trigger implementation:** Start with polling (cron checks Finnhub every N minutes) or invest in webhooks/streaming upfront?
- **Agent accuracy minimum sample size:** How many trades before earned weights are statistically meaningful? (Probably 30+ per agent, which means ~6 months of live trading before the feedback loop has teeth.)
- **Challenger agent scope:** Should it challenge every trade, or only high-conviction ones? Challenging every trade may dilute conviction systematically.
- **Multi-account support:** Is this ever multi-user, or always single-operator? Affects auth, state management, and dashboard design.
- **Bloomberg data integration:** What downloaded data gets permanent slots in the feature pipeline vs one-time enrichment?

---

## Principles for Updating This Document

1. **When a belief is disproven** (like weekly rebalance was), update Core Beliefs.
2. **When a phase completes**, check the box and note the date.
3. **When an open question gets answered**, move it to the relevant section.
4. **When scope changes**, update What We Don't Build — it's as important as what we do build.
5. **When the dashboard vision crystallizes**, replace the ASCII mockups with real designs.
