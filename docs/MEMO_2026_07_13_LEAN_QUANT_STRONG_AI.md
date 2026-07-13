---
title: Strategic Memo — Lean Quant, Strong AI (Option 4 in concrete terms)
date: 2026-07-13
kind: strategic-memo
context: |
  Post-mortem of 2026-07-12 findings. The v4-qmj-only composite delivered
  Sharpe 1.09 / alpha -161pp vs SPY on the clean 495-ticker universe.
  Prior "gold standard" numbers were inflated by cache-bias. The
  underlying question this memo answers: given that the traditional
  multi-signal quant composite hasn't produced alpha, and given that
  we've built a genuinely capable AI agent stack, what should the
  strategy actually be?
---

# Strategic Memo: Lean Quant, Strong AI

## The core proposition in one sentence

Reposition quantitative signals as a **screener** that narrows the investable universe from ~500 to ~50 candidates; make the LLM agent stack the actual **decision-maker** that picks 10 positions from those 50; measure success as *AI-picks vs SPY*, not *individual signal IC*.

This treats the AI agents as the real edge — which is what they are — and treats the quant layer as infrastructure, not strategy.

---

## What changes

### 1. Composite goes from 4 hand-tuned signals to 2-3 IC-validated screener signals

**Today:** v4-qmj-only composite = 0.40·earnings + 0.30·QMJ + 0.20·OBV + 0.10·inst_flow. Weights were hand-picked. Signals were never IC-validated on clean data. Only 88 of 495 tickers have inst_flow data at all. The composite delivers -161pp alpha on the clean universe.

**Tomorrow:** After the overnight IC test on clean 495, keep only signals with statistically significant rank IC (t-stat > 2, IR > 0.5) at the 1M horizon. Realistic estimate based on literature and Chad's prior work: 2-3 signals survive (OBV likely, QMJ likely, one earnings signal likely). Weight the survivors equally or by IC-derived weights — not hand-tuned. The composite's job stops being "produce alpha"; its job becomes "rank 500 → 50 with modest predictive lift."

### 2. Ranker output feeds AI agents, not the trade blotter

**Today:** The quant composite ranks 500 → 10 picks. Agents provide analysis but don't override the composite's ordering. The composite IS the strategy.

**Tomorrow:** The quant composite ranks 500 → top-50 candidate list. The 6 specialist agents (Fundamentals, Technicals, Macro, Risk, Earnings, Pattern) analyze each of the 50. Portfolio Construction agent synthesizes the 6 views + candidate list → final 10 positions with sizing. Quant does the winnowing; AI does the selection.

### 3. Eval shifts from signal IC to strategy-level attribution

**Today:** "Does signal X have IC?" and "What's the strategy's Sharpe?" are treated as independent-but-linked questions. Signal-level rigor drives composite design; strategy-level metrics drive go/no-go.

**Tomorrow:** Three tracked series, always compared:
- **SPY:** the passive benchmark (unchanged).
- **Quant-only picks:** top-10 from the composite ranker alone (no AI). This is the control.
- **AI-augmented picks:** top-10 chosen by agents from the quant top-50. This is the strategy.

The strategy's edge is defined as `AI-augmented Sharpe − Quant-only Sharpe`. Positive → AI is adding alpha; zero → AI is expensive quant equivalent; negative → agents are noise, drop them. This is a **direct measure of whether the AI stack earns its complexity**, which is the actual question we care about.

### 4. XGBoost meta-model repurposed

**Today's plan (`project_xgb_meta_model`):** predict stock returns from signal exposures. Ambitious, requires clean signals, sensitive to data.

**Tomorrow's plan:** predict *whether an AI agent recommendation will outperform its sector over the next 21 days*. Features = signal exposures + agent confidence scores + agent-disagreement metrics. Target = binary (agent pick beat sector benchmark? yes/no). Much more tractable target, much more resistant to signal-data noise, directly answers the "should we trust this specific AI pick" question. This becomes the position-sizing input.

### 5. Data investment shifts

**Today:** WRDS + Tiingo Power + potentially FMP/Polygon down the road. Focus is expanding coverage (R1000, options).

**Tomorrow:** Same data providers, but the investment priority shifts. Instead of "extend WRDS PIT to R1000," invest in:
- **News/earnings-call transcripts** for the AI agents to reason over (probably needs Bloomberg, Refinitiv, or a scraper-grade source)
- **Insider/13D filings** to feed the Pattern agent's event detection
- **Better sector/factor return series** for excess-return eval

The AI agents are the bottleneck for edge; feeding them richer inputs matters more than adding tickers.

---

## What stays

- **The 6-agent architecture** (`agents/`) — Fundamentals, Technicals, Macro, Risk, Earnings, Pattern, Portfolio Construction. Zero change.
- **The WRDS PIT data layer** (`.wrds_pit.db`) — still needed for the screener signals AND agent context.
- **The backtest engine** (`quant/backtest.py`) — same infra, different composite config.
- **The loader hardening + coverage reports** just shipped — fail-loud stays on, more valuable in the new setup because signal quality has direct downstream impact on agents.
- **The GraphRAG direction** (per `project_graphrag_direction`) — even more important as the agents become the primary decision layer.
- **The position sizing / risk management** — unchanged in mechanics; only the input (which 10 tickers) changes.
- **The multi-provider data layer** — unchanged.

---

## What stops mattering

- **Composite weight tuning.** The composite is now a screener with light weights, not a decision engine. Fiddling with `earnings_weight = 0.35 vs 0.40` becomes noise.
- **Signal IC of marginal signals.** If a signal doesn't clear a clear IC bar, it's out. No more "keep it because it improves Sharpe by 2bps."
- **The conviction_sizing parameter.** If the composite score is no longer trusted enough to size positions, conviction sizing based on it doesn't make sense. Equal-weight or vol-weighted becomes the default.
- **The rank-vs-blend earnings mode debate.** Downstream artifact of the composite-as-decision-engine framing.
- **Chasing more signals for the composite.** The composite is 2-3 signals, well-understood, IC-validated. Additional predictive power comes from the AI layer, not more quant signals.
- **The levered-core thesis.** Definitively dead on this composite.

---

## Migration path (concrete phases)

### Phase 0 (tonight, running): IC test on clean 495
Determines how many signals survive. Sets the size of the "screener" (2 signals? 3? 4?). No code changes yet.

### Phase 1 (~1 week): Rebuild the composite as a screener
- Rebuild the composite with only IC-validated signals, IC-derived weights.
- Widen the top-N output from 10 → 50 (candidate list, not trade list).
- Add a `screener_only` mode to the backtest engine that emits candidate lists instead of trades.
- Deliverable: candidate lists for every historical rebalance date, saved for phase 2 replay.

### Phase 2 (~1 week): Wire AI agents to the screener output
- Modify the orchestrator so agents receive the top-50 (not top-10) as their working universe.
- Agents produce ranked picks. Portfolio Construction agent synthesizes.
- Add historical replay: for each historical rebalance, run agents on that date's top-50, generate the agent's top-10. Backtest those.
- Deliverable: `AI-augmented picks` return series alongside the `Quant-only` series.

### Phase 3 (~1 week): New eval + reporting
- Build the three-series comparison (SPY / Quant-only / AI-augmented).
- Update the dashboard to show AI-vs-quant attribution.
- Update the daily/weekly summary to highlight where AI diverged from quant and whether that call outperformed.
- Deliverable: an honest scoreboard of AI's contribution.

### Phase 4 (~2 weeks): XGBoost meta-model on AI recommendations
- Train meta-model on "will this AI pick beat sector over 21d?"
- Add as a filter (only take AI picks the meta-model says are >X% likely to outperform) or as a position-sizing input.
- Deliverable: risk-adjusted returns improvement measurable in phase 3's eval.

### Phase 5 (later, as capital + confidence grow): Sleeve reconsideration
- If the AI-augmented series shows real alpha, revisit the 5% convexity sleeve (originally phase 2 of the levered-core plan). The sleeve's idea-provenance requirement (`IdeaCard` per plan §2) becomes tractable because the agents already do this reasoning.
- Options-provider bake-off (Polygon.io vs ORATS) at that point.

---

## What this means for the plan doc

`docs/PLAN_LEVERED_CORE_AND_INTEL_FLOW.md` becomes largely obsolete. Its §1 (levered core) is dead. Its §2 (intelligence flow) is essentially what this memo describes as the AI layer — that part still stands and gets emphasis. Its §3 (CI/CD remainder) still holds.

Recommended: instead of editing the plan doc, retire it and write a fresh `PLAN_LEAN_QUANT_STRONG_AI.md` that this memo becomes the front-matter for. Cleaner than trying to graft a fundamentally different strategic direction onto a doc built around a dead thesis.

---

## What would tell us this framing is wrong

To keep this honest, three ways this memo could turn out to be misdirected:

1. **IC test tomorrow shows 4-5 signals with strong IC.** If the composite can actually pick stocks well on clean data, the case for "AI as primary decision-maker" weakens. Quant-only may already be enough. Revisit whether AI is doing anything the composite isn't.

2. **AI-augmented picks fail to beat quant-only in phase 2 replay.** If agents don't add measurable alpha over the composite screener, they're expensive quant equivalents. Cut the agent complexity dramatically.

3. **Composite screener's top-50 is dominated by mega-caps and misses opportunities.** If the screener is too "safe" and never surfaces the actionable ideas, the agents have nothing interesting to work with. Fix the screener before blaming the agents.

Each of these has a specific test built into the phased plan. None require abandoning the direction; they refine what "lean quant" and "strong AI" actually mean in practice.

---

## The one-sentence recap

**Stop trying to build a great quant strategy with an AI layer on top; start treating the AI stack as the strategy and the quant as the infrastructure that makes it tractable.**
