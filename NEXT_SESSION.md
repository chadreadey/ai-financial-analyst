# Next Session Agenda

Session completed 2026-04-06. This is the discussion + implementation roadmap for the next working session.

---

## What Just Shipped (context)

- **Alpaca price provider** — `price_provider.py` with `AlpacaClient`, factory pattern. 200 req/min replaces Tiingo's 50/hr. Backtest engine + API routes wired.
- **Finnhub news sentiment signal** — `finnhub_client.py` + `quant/sentiment.py`. VADER on headlines + insider MSPR. Disk cache. Plugs into backtest as optional overlay.
- **A/B results (liquid_10, Jun 2024-Apr 2026):** Sentiment at 10% weight → Sharpe 1.39 (vs 1.13 baseline), Sortino 1.88 (vs 1.44). On random mid-caps: roughly flat, slight drawdown improvement.

---

## 1. Adaptive Sentiment Weight by Coverage

**Problem:** Sentiment signal is strong on mega-caps (dense news) but weak/noisy on mid-caps (few articles). Currently a flat 10% weight regardless.

**Approach to discuss:**
- Scale `news_sentiment_weight` by `min(1.0, n_articles / 20)` — full weight at 20+ articles, proportionally less below
- Or: two-tier system: full weight if n_articles >= 10, zero otherwise
- Test both on the random 15-stock universe and compare Sharpe/Sortino

**Implementation:** Modify `blend_sentiment_into_signals()` in `backtest.py` to accept per-ticker article counts from `compute_sentiment_scores()`.

---

## 2. Longer Backtest Periods

Run walk-forward tests over 3-5 year periods to get statistically meaningful results:
- `liquid_20`, 2020-01-01 to 2026-04-01, walk-forward (24mo train / 6mo test)
- Random 20-stock sample, same period
- A/B with and without sentiment in each

Prefetch sentiment cache first to avoid inline rate-limit pauses:
```bash
python -c "from finnhub_client import prefetch_sentiment_cache; ..."
```

Note: Finnhub free tier has 1-year news history limit. Walk-forward windows before ~2025-04 will only have insider MSPR data (no news). This is fine — it tests whether MSPR alone adds value on older periods.

---

## 3. LSTM vs. Other Models — Stress Test the Decision

**What LSTM gives us:**
- Captures temporal dependencies in price sequences (OHLCV features over 60-day windows)
- Sharpe +0.19 OOS at 20% weight (from commit 1a77d29 cross-universe test)
- Lightweight: trains in seconds per walk-forward window on CPU
- Proven cross-universe generalization (trained on liquid_10, tested on liquid_20)

**Alternatives to evaluate in discussion:**
| Model | Pros | Cons | When to consider |
|---|---|---|---|
| **Transformer (TFT/PatchTST)** | Better long-range dependencies, attention over features | Heavier, needs more data, slower train | If LSTM plateaus and you have 50+ feature cols |
| **XGBoost/LightGBM** | Handles tabular features natively, fast, interpretable feature importance | No temporal structure — treats each row independently | If adding many non-sequential features (fundamentals, sentiment scores, macro) |
| **Ensemble: LSTM + GBM** | LSTM handles sequential price data, GBM handles tabular cross-sectional features | Complexity, two models to maintain | Best of both worlds — probably the right long-term answer |
| **N-BEATS / N-HiTS** | Purpose-built for time series forecasting, strong benchmarks | Forecasts price levels, not factors — may not translate to ranking signal | If pure price prediction matters more than signal ranking |

**Key question:** Is the LSTM the right *final* model or just the right *current* model? The answer depends on what features we're adding — if we're staying price-only, LSTM is fine. If we're adding sentiment, earnings surprise, macro indicators as input features, a tabular model (GBM) or hybrid ensemble is probably better.

---

## 4. Fully Autonomous System Design

**Vision:** A system that runs daily, scans a universe, generates trades, tracks outcomes, and improves over time — no human in the loop.

**Components to discuss:**
1. **Daily scan loop** — Cron job: load universe → compute signals → sentiment → LSTM → rank → paper trade top/bottom decile
2. **Outcome tracking** — Record every paper trade with entry signals, hold 30/60/90 days, compute realized IC per signal
3. **Signal quality monitor** — Dashboard showing rolling IC per signal. Alert if any signal's IC goes negative for 3+ months.
4. **Automatic reweighting** — Use realized IC history to update signal weights monthly (already have IC calibration in backtest.py, just need to apply it in production)
5. **Model retraining trigger** — Retrain LSTM when walk-forward performance degrades below threshold

**Key risk:** Feedback loops. If the system trades on its own signals and tracks its own outcomes, it can overfit to its own past decisions.

---

## 5. RL Without Overfitting

**The core problem:** RL optimizes a reward function over sequential decisions. In finance, the reward (returns) is noisy and non-stationary. Classic RL overfits to the training environment (historical prices) and fails on new data.

**Approaches to discuss:**
1. **Reward shaping** — Don't use raw returns as reward. Use risk-adjusted metrics (Sharpe of recent window) or rank-based reward (did the model pick better than random?). Penalize turnover.
2. **Conservative policy optimization** — Use offline RL (e.g., CQL, IQL) that constrains the policy to stay close to the historical data distribution. Prevents the agent from learning strategies that only work in simulation.
3. **Ensemble of policies** — Train N policies on different time windows, take majority vote. Reduces variance from any single overfit.
4. **Walk-forward RL** — Same as walk-forward backtest: train on 24 months, evaluate on next 6 months, never look ahead. If reward degrades OOS, don't deploy that policy.
5. **Meta-learning** — Instead of learning *what to trade*, learn *how to weight signals*. The action space is signal weights, not trades. Much smaller action space → less overfitting surface.
6. **Simplest viable approach:** Use the IC calibration framework already built (trailing IC → adaptive weights) and call that "lightweight RL." It's essentially a bandit that upweights signals with positive recent IC and downweights negative ones. No neural network needed.

**Recommendation to discuss:** Start with the bandit approach (adaptive IC weights, already built). Only graduate to full RL if there's evidence that the signal-weighting problem is non-stationary enough to benefit from a learned policy.

---

## 6. Geopolitical Graph RAG

**Existing plan:** `PLAN_GRAPHRAG.md` covers a SQLite property graph for peer/supplier/macro relationships. Phases 1-3 are designed and ready to build (~6 hours).

**Extension for geopolitics:**
- Add `GEOPOLITICAL_RISK` edge type: country → sector sensitivity (e.g., "China" → "Semiconductors" weight=0.9)
- Data source: FRED's trade policy uncertainty index, or a curated rules table like the existing `MACRO_TRANSMISSION` dict
- Integration: macro agent gets geopolitical context automatically
- This connects naturally to supply chain extraction (Phase 2 of GraphRAG plan) — if AAPL has SUPPLIER edge to TSMC, and TSMC has COUNTRY edge to Taiwan, the graph traversal surfaces the geopolitical risk automatically

**New indicators to test:**
- Trade policy uncertainty index (FRED: USEPUINDXD)
- Geopolitical risk index (Caldara & Iacoviello)
- Sanctions/tariff event detection from Finnhub news

---

## 7. Pre-Earnings Signals

**Your existing work:** Standardized predictions of market moves around MP announcements and earnings calls.

**Integration path:**
- Add as a **standalone signal** (not blended into composite) — a time-limited signal that activates N days before earnings
- Use Finnhub's `/calendar/earnings` endpoint (free, already available via `FinnhubClient`) to know *when* earnings are coming
- Combine with historical earnings surprise data (`get_earnings_surprises()`) for the base rate
- The signal would be: "AAPL reports in 5 days, has beaten estimates 8 of last 10 quarters, pre-earnings drift is historically +2.3%"
- Gate: only activate within a configurable window (e.g., 7 days before earnings)

**For the backtest:** This is naturally point-in-time safe — you know the earnings date in advance (it's announced). The signal activates on a schedule, not on data.

---

## 8. From the Existing Plans (PLAN_NEXT.md + EXPANSION_PLAN.md)

Topics to potentially add to the session:

- **P1: Accumulate 50+ Paper Trades** — The daily scan loop (item 4 above) directly addresses this. Needed for funding criteria (PLAN_NEXT.md line 78-82).
- **P1: API Authentication** — Simple API key middleware. Quick win before any external demo (PLAN_NEXT.md line 72-76).
- **GraphRAG Phase 1** — The minimal viable graph (peer + sector + macro extractors) is ~3 hours of work and directly enables the geopolitical extension (item 6). Should discuss whether to build this before or after the RL/model discussions.
- **Insider Transactions Agent** — EXPANSION_PLAN Phase 3A. Relevant because Finnhub already provides insider data via the endpoint we just built. Could be a quick new agent.
- **Earnings Call Transcript Agent** — EXPANSION_PLAN Phase 3B. Connects to the pre-earnings signals work (item 7).
- **edgartools migration** — EXPANSION_PLAN Phase 1A. Unlocks Form 4 and 8-K transcript access needed for the above two agents.
- **Success criteria checkpoint:** PLAN_NEXT.md says Sharpe > 0.7 across 5+ years, 50+ paper trades, win rate > 55% in high conviction band. Current liquid_10 result (Sharpe 1.39 with sentiment) already exceeds this on a short window. Need the longer walk-forward test (item 2) to validate over 5+ years.

---

## Suggested Session Order

1. **Quick wins first:** Adaptive sentiment weight + kick off long walk-forward backtest (runs in background)
2. **Architecture discussion:** LSTM vs alternatives, autonomous system design, RL approach
3. **Design decisions:** Geopolitical GraphRAG extensions, pre-earnings signal spec
4. **Build:** Whatever we align on from the discussion — likely GraphRAG Phase 1 or the daily scan loop
