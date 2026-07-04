# Findings Ledger — Core Platform Adversarial Audit

**Frozen SHA:** `60855802c9b172985110ff482f2f12e48842a2dd`
**Schema:** `docs/superpowers/skills/adversarial-code-audit/ledger-schema.md`

This ledger is the audit trail. It is written incrementally across phases; entries grow as they pass through cross-examination (Phase 2), defense (Phase 3), and arbitration (Phase 4). It does not summarize prior phases — it appends.

## Intake summary (Phase 1)

Six persona auditors returned ~113 raw observations. The controller performed intake:

- **Rejected at intake (no file:line or no mechanism):** 0 — every submitted finding carried file:line evidence. (Several were self-marked by auditors as "areas examined, no finding" or out-of-scope-return; those are not findings.)
- **Deduplicated:** the rebalance duplicate-order bug was independently reported by Reliability, Correctness, Security, and Maintainability. Per the anti-collusion contract, **ally agreement is not confirmation** — it is merged into one finding (**F-001**) and still routed through hostile cross-examination.
- **Consolidated** to **53 distinct findings** (`F-001`…`F-053`), each with a single `originated_persona` (the persona whose axis best owns it) and `also_reported_by` where multiple personas converged.
- **Controller spot-verification:** the 5 highest-severity claims (F-001, F-002, F-024, F-025, F-041) were independently re-read against the frozen tree by the controller before intake. All confirmed at the cited lines.

### Cross-examination scoping (transparent, not silent)

The skill requires every finding be cross-examined. With 53 findings, the controller applied a **tiered** approach, recorded here so it is auditable rather than silent:

- **Tier 1 (material: CRITICAL + HIGH, 37 findings):** individually cross-examined by batched **different-persona** refuter subagents (Phase 2), then defended (Phase 3) if CONFIRMED, then arbitrated (Phase 4) if disputed. These drive the strengthening plan.
- **Tier 2 (MEDIUM + LOW, 16 findings):** triaged at controller level with a recorded verdict and rationale, not a full subagent round. They are retained in the ledger and feed the plan's lower-priority bundles, but were not put through the full three-round machinery. This is an explicit scoping decision under the "speed = less per-phase deliberation, not skipped phases" rule, adapted for finding volume.

---

## Persona legend

`SEC`=Security · `COR`=Correctness · `REL`=Reliability · `PERF`=Performance · `DATA`=Data & State · `MNT`=Maintainability

---

## Findings

### F-001 — Rebalance double-submits Alpaca orders (auto-trade + scheduler both fire)
- **origin:** REL · **also_reported_by:** COR, SEC, MNT · **assets:** A1
- **status:** PROPOSED → (Phase 2/3/4 below)
- **initial_severity:** CRITICAL · **initial_exploitability:** DEMONSTRATED (deterministic on default config)
- **evidence:**
  - `backend/paper_scheduler.py:58` calls `run_analysis_job(job, request)` → `orchestrator.run()`.
  - `orchestrator.py:955-958` (run tail) invokes `_auto_paper_trade()` when `settings.auto_paper_trade` (default `True`, `config.py:156`).
  - `orchestrator.py:288-301`: `_auto_paper_trade` submits an Alpaca market order.
  - `backend/paper_scheduler.py:78`: `run_rebalance` submits a **second** market order for the same ticker/side after the job completes.
- **mechanism:** If a rebalance opens a new watchlist name with conviction ≥ threshold and Alpaca keys are set, two same-side market orders of `paper_default_qty` each are submitted (~2× intended size), because auto-trade inside analysis and the explicit scheduler order both fire with no idempotency guard.
- **controller_verified:** yes (read paper_scheduler.py + orchestrator.py:288-301).

### F-002 — Watchlist DB failure returns empty list → rebalance liquidates entire book
- **origin:** REL · **assets:** A1
- **status:** PROPOSED
- **initial_severity:** CRITICAL · **initial_exploitability:** PLAUSIBLE (any transient SQLite fault)
- **evidence:** `backend/paper_scheduler.py:21-28` bare `except: return []`; `paper_scheduler.py:36-48`: empty `target_set` makes every held symbol "not in target" → `client.close_position(symbol)` for all.
- **mechanism:** If SQLite is locked / `watchlist` table missing / warehouse path wrong during a *scheduled* rebalance (`target_tickers=None`), `_get_watchlist_tickers()` swallows the error and returns `[]`, so the rebalance closes every open Alpaca position because it cannot distinguish "read failed" from "watchlist empty."
- **controller_verified:** yes.

### F-003 — Unauthenticated `POST /api/paper-trading/rebalance` triggers live orders
- **origin:** SEC · **assets:** A1
- **status:** PROPOSED
- **initial_severity:** CRITICAL · **initial_exploitability:** PLAUSIBLE (single HTTP POST)
- **evidence:** `backend/routers/paper_trading.py:415-424` (`trigger_rebalance` calls `run_rebalance(target_tickers=...)`), router mounted with no auth dependency at `backend/main.py:122`.
- **mechanism:** If the Railway backend is internet-reachable and Alpaca keys are configured, any unauthenticated client can force position closes and market orders because the rebalance endpoint has no auth gate.

### F-004 — No authentication on any router except `backtest_modal` (systemic)
- **origin:** SEC · **assets:** A1, A2, A5
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** PLAUSIBLE
- **evidence:** `backend/main.py:111-122` mounts analysis/reports/portfolio/watchlist/backtest/paper_trading with no dependency; only `backend/routers/backtest_modal.py:24-45` enforces `X-API-Key`.
- **mechanism:** If the backend is public, any client can invoke analysis, backtests, portfolio/watchlist mutations, and trade triggers, because auth exists on exactly one router.

### F-005 — Unauthenticated `POST /api/analysis/run` reaches the auto-paper-trade path
- **origin:** SEC · **assets:** A1
- **status:** PROPOSED
- **initial_severity:** CRITICAL · **initial_exploitability:** PLAUSIBLE
- **evidence:** `backend/routers/analysis.py:16-25` (no auth) → `backend/jobs.py:124` runs orchestrator → `orchestrator.py:955-958` auto-trades with `config.py:156` default `True`.
- **mechanism:** If an attacker POSTs `{"ticker":"AAPL"}`, an autonomous Alpaca order can follow analysis completion, because the public analysis endpoint drives the orchestrator and auto-trade defaults on.

### F-006 — Rebalance never exits a held name whose verdict flipped to SELL
- **origin:** COR · **assets:** A1
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** PLAUSIBLE
- **evidence:** `backend/paper_scheduler.py:52-54`: `if ticker in current_symbols: continue` — held names are skipped entirely; positions only close when *removed* from the watchlist.
- **mechanism:** If a ticker stays on the watchlist but its analysis flips BUY→STRONG SELL, the long stays open because the scheduler only closes symbols dropped from the target set.

### F-007 — Substring verdict matching: `"BUY" in "DO NOT BUY"` → LONG
- **origin:** COR · **also_reported_by:** — · **assets:** A4, A1
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** PLAUSIBLE (when `weighted_score` override absent / historical verdicts)
- **evidence:** `backend/paper_scheduler.py:71` `if "BUY" in verdict`; `backend/backtest_engine.py:154-158` `is_buy = "BUY" in verdict`; `orchestrator.py:232-236`.
- **mechanism:** If a verdict string contains `BUY` inside a bearish phrase, backtest simulates a long, and the scheduler submits a buy, because matching ignores negation.

### F-008 — Auto-trade overwrites an open position with no realized-PnL record
- **origin:** COR · **assets:** A4, A1
- **status:** PROPOSED
- **initial_severity:** MEDIUM · **initial_exploitability:** PLAUSIBLE
- **evidence:** `orchestrator.py:266-278` `INSERT OR REPLACE INTO paper_positions` (PK ticker); no `paper_trades` row written.
- **mechanism:** If analysis re-runs on a ticker already held, the old position is silently replaced with no closed-trade record, breaking position state and history totals.

### F-009 — Alpaca `sync_positions_to_db` wipes metadata & resets `entry_date` to today
- **origin:** COR · **also_reported_by:** MNT · **assets:** A4
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** DEMONSTRATED (every sync)
- **evidence:** `backend/alpaca_paper_client.py:113-123`: `INSERT OR REPLACE` lists only `(ticker,entry_price,entry_date,current_price,direction)` → `verdict=''`, `conviction_score=NULL`; `entry_date = time.strftime("%Y-%m-%d")`.
- **mechanism:** After every rebalance sync, stored `entry_date`/`verdict`/`conviction_score` for open positions are corrupted, breaking `days_held`, verdict joins, and conviction display.

### F-010 — Alpaca sync leaves ghost SQLite positions after broker close (no DELETE)
- **origin:** COR · **assets:** A4, A1
- **status:** PROPOSED
- **initial_severity:** MEDIUM · **initial_exploitability:** PLAUSIBLE
- **evidence:** `backend/alpaca_paper_client.py:100-127`: sync upserts only symbols currently held at Alpaca; never deletes rows for closed symbols.
- **mechanism:** If a position is closed at the broker, SQLite may still list it open, causing stale `/positions` and blocking re-entry via candidate exclusion.

### F-011 — User-supplied API keys written to process-global `os.environ` (cross-request bleed)
- **origin:** SEC · **assets:** A2
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** PLAUSIBLE (race with concurrent requests)
- **evidence:** `backend/schemas.py:10` (`api_key` field); `backend/jobs.py:91-106` copies it into `os.environ["ANTHROPIC_API_KEY"]`/`["OPENAI_API_KEY"]`; jobs run in daemon threads sharing one process env.
- **mechanism:** If two analysis jobs run concurrently and one supplies a BYOK key, another job's LLM call can run under the wrong key, because env mutation is process-global across threads.

### F-012 — Raw exception strings returned to unauthenticated clients (secret-leak surface)
- **origin:** SEC · **assets:** A2
- **status:** PROPOSED
- **initial_severity:** MEDIUM · **initial_exploitability:** PLAUSIBLE
- **evidence:** `backend/jobs.py:149-153` sets `job.error = str(exc)`; `backend/routers/analysis.py:44-47,69-70` returns it via SSE/REST.
- **mechanism:** If a provider error embeds key fragments/metadata, any holder of `job_id` receives it, because errors propagate verbatim without redaction.

### F-013 — Backend Sentry init lacks `send_default_pii=False` (app.py sets it, backend/main.py does not)
- **origin:** SEC · **assets:** A2
- **status:** PROPOSED
- **initial_severity:** MEDIUM · **initial_exploitability:** THEORETICAL→PLAUSIBLE (Sentry on + failing request)
- **evidence:** `backend/main.py:31-36` (no `send_default_pii=False`); contrast `app.py:101`; request bodies carry `api_key` (`schemas.py:10`).
- **mechanism:** If Sentry is enabled and a request with `api_key` is captured in an event, the secret is shipped to Sentry, because PII capture is not disabled in the backend init.

### F-014 — No rate limiting on compute/cost-bearing endpoints (denial-of-wallet)
- **origin:** SEC · **assets:** A2, A5
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** PLAUSIBLE
- **evidence:** No throttling middleware anywhere under `backend/`; expensive public routes: `analysis.py:16`, `backtest.py:117-162` (LLM), `news.py:13-45` (Tavily), `paper_trading.py:415`.
- **mechanism:** If an attacker floods these routes, LLM/data-provider quotas are exhausted and CPU pinned, because there is no per-IP/key rate limit.

### F-015 — CORS `allow_credentials=True` with attacker-registerable Vercel subdomain regex
- **origin:** SEC · **assets:** A5, A2
- **status:** PROPOSED
- **initial_severity:** MEDIUM · **initial_exploitability:** PLAUSIBLE
- **evidence:** `backend/main.py:95-104`: `allow_credentials=True`, `allow_origin_regex=r"https://ai-financial-analyst(-[a-z0-9]+)?\.vercel\.app"`.
- **mechanism:** If an attacker deploys a matching Vercel project (e.g. `ai-financial-analyst-evil123.vercel.app`) and the real frontend uses credentialed cross-origin calls, the attacker origin gets credentialed CORS access, because the regex whitelists attacker-controllable subdomains.

### F-016 — Rebalance runs synchronously inside `async def` → wedges the event loop
- **origin:** REL · **assets:** A5
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** PLAUSIBLE
- **evidence:** `backend/routers/paper_trading.py:415-420`: `async def trigger_rebalance` calls `run_rebalance()` directly (no `to_thread`); `run_rebalance` does Alpaca I/O + per-ticker LLM analysis.
- **mechanism:** If a rebalance starts, all other requests on that worker stall because the event loop is blocked in synchronous I/O + analysis.

### F-017 — Alpaca SDK client configured with no HTTP timeout
- **origin:** REL · **assets:** A1, A5
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** PLAUSIBLE
- **evidence:** `backend/alpaca_paper_client.py:33-37` constructs `TradingClient` with only keys + `paper=True`; order/close methods (64,69,87,92) set no timeout.
- **mechanism:** If Alpaca hangs after TCP accept, `submit_order`/`close_position` block the calling thread indefinitely, because no timeout bounds the wait.

### F-018 — FRED client has no HTTP timeout
- **origin:** REL · **assets:** A5
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** PLAUSIBLE
- **evidence:** `fred_client.py:89-114` constructs `Fred(api_key=...)` and calls `get_series` with no timeout; only throttle is `time.sleep(0.5)`.
- **mechanism:** If FRED stalls, `get_series` blocks unbounded on the analysis critical path, because no timeout is configured.

### F-019 — Alpaca EOD pagination `while True` spins forever on persistent 429
- **origin:** REL · **assets:** A5
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** PLAUSIBLE
- **evidence:** `price_provider.py:135-156`: on `429`, `time.sleep(1); continue` without incrementing page token, retry cap, or break.
- **mechanism:** If Alpaca rate-limits every request, the loop retries the same page forever, because 429 handling has no bounded backoff/abort.

### F-020 — Analysis invoked by rebalance has no end-to-end timeout / cancellation
- **origin:** REL · **assets:** A1, A5
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** PLAUSIBLE
- **evidence:** `backend/jobs.py:70-135` runs `asyncio.run(orchestrator.run(...))` with no wall-clock bound; called synchronously per ticker by `paper_scheduler.py:56-58`.
- **mechanism:** If any upstream in `prepare_data` hangs, `run_rebalance` blocks on that ticker forever, because nothing bounds total job duration.

### F-021 — `/api/health` always returns OK (no dependency / event-loop probe)
- **origin:** REL · **assets:** A5
- **status:** PROPOSED
- **initial_severity:** MEDIUM · **initial_exploitability:** PLAUSIBLE
- **evidence:** `backend/main.py:125-127` returns `{"status":"ok"}` unconditionally.
- **mechanism:** If the event loop is wedged (F-016/F-049) or rebalance is hung, load balancers still route to a dead worker because health reports success.

### F-022 — Unbounded in-process news cache (memory growth)
- **origin:** REL · **assets:** A5
- **status:** PROPOSED
- **initial_severity:** MEDIUM · **initial_exploitability:** PLAUSIBLE
- **evidence:** `backend/routers/news.py:9-10,58`: module dict keyed by `f"{ticker}:{sector}"`, never evicted except TTL-on-hit, no max size.
- **mechanism:** If clients spam unique keys, the cache grows unbounded until OOM, because there is no cap/eviction.

### F-023 — SQLite connections leaked on error paths (no try/finally close)
- **origin:** REL · **assets:** A5, A1
- **status:** PROPOSED
- **initial_severity:** MEDIUM · **initial_exploitability:** PLAUSIBLE
- **evidence:** `backend/paper_scheduler.py:23-28` closes only on success; `backend/jobs.py:114-147` `cache.close()` not in finally; `backend/routers/portfolio.py:257-276` no try/finally.
- **mechanism:** If repeated `OperationalError`s occur under load, connections accumulate because error paths skip close, worsening SQLite contention (feeds F-002).

### F-024 — CPCV `apply_purge_embargo` has no global temporal ordering guard (future-train → past-test leak)
- **origin:** DATA · **assets:** A3
- **status:** PROPOSED
- **initial_severity:** CRITICAL · **initial_exploitability:** PLAUSIBLE (depends on IC-calibration consumer)
- **evidence:** `quant/cpcv.py:144-193`: purge only removes dates near *adjacent* train/test group boundaries (`for i in range(len(groups)-1)`); `safe_train`/`safe_test` are never constrained so that all train dates precede all test dates. Consumer IC calibration lives in `quant/backtest.py` (out of scope, default `enable_ic_calibration=True` per DATA auditor).
- **mechanism:** If a CPCV combination places a test group earlier in time than a train group, `safe_train` retains chronologically-later dates; if the consumer calibrates signal weights on train and applies them to earlier test rebalances, OOS metrics are inflated by future information.
- **controller_verified:** in-scope portion (no temporal guard) confirmed by reading cpcv.py:144-193. Consumer behavior is out-of-scope → cross-examination must establish impact.

### F-025 — CPCV purge/embargo of 0 months silently disables leakage protection
- **origin:** DATA · **assets:** A3
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** PLAUSIBLE (modal router allows `ge=0`)
- **evidence:** `quant/cpcv.py:108-109` defaults 1/1 but accept 0; `:151-154` purge zone becomes `date == bd` only; `:166-172` embargo `g_end < date <= g_end` is unsatisfiable → no-op. `backend/routers/backtest_modal.py:71-72` allows `ge=0` (out of scope).
- **mechanism:** If `purge_months=0` / `embargo_months=0` are passed, forward-return labels (~21 trading days) still overlap train/test boundaries because only the exact boundary timestamp is removed and embargo is disabled.
- **controller_verified:** yes (read cpcv.py purge/embargo).

### F-026 — Contiguous CPCV groups share a boundary date → dual train/test assignment
- **origin:** DATA · **assets:** A3
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** PLAUSIBLE (only when purge=0)
- **evidence:** `quant/cpcv.py:66-69` groups are `(snapped[i], snapped[i+1])` inclusive both ends → shared day; `:177-187` a boundary date is appended to both raw train and test lists; purge is the only deduplicator.
- **mechanism:** If a rebalance date equals a shared train/test group boundary, it enters both sets and (with purge=0, F-025) participates in both IC estimation and OOS trading for that fold.

### F-027 — Deflated Sharpe uses combination count as `n_obs`, not return sample size
- **origin:** DATA · **assets:** A3
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** DEMONSTRATED (every CPCV run)
- **evidence:** `quant/cpcv.py:362-372`: `n_obs = max(len(self.oos_sharpes), 10)` feeds `compute_deflated_sharpe` where `se_sr ∝ 1/sqrt(n_obs-1)` (`:290-295`).
- **mechanism:** If a run completes N combos each yielding one OOS Sharpe, DSR is computed as if there were N return observations, overstating significance because `n_obs` counts Sharpe draws, not underlying return days.

### F-028 — PBO is an ad-hoc top-half fraction but labeled `is_optimal`
- **origin:** DATA · **assets:** A3
- **status:** PROPOSED
- **initial_severity:** MEDIUM · **initial_exploitability:** DEMONSTRATED
- **evidence:** `quant/cpcv.py:216-229`: sorts `(IS,OOS)` by IS, counts top-half `OOS<=0` / `(n//2)`; labeled method `"is_optimal"` though not Bailey/López de Prado logit-PBO.
- **mechanism:** If IS Sharpes are supplied, reported PBO is a simplified statistic mislabeled as the rigorous overfitting probability, corrupting the headline anti-overfitting gate.

### F-029 — `compute_signal_vector_from_provider` anchors to the latest bar (look-ahead if reused for a historical date)
- **origin:** DATA · **assets:** A3
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** PLAUSIBLE
- **evidence:** `quant/signals.py:473-490`: `start = now - 730d`, fetches through latest close, signals use `.iloc[-1]`/`.tail(n)`; no `as_of_date`. CPCV path uses a different truncated entrypoint (`compute_signals_at_date`) per DATA auditor.
- **mechanism:** If this helper is used to score any date before "today," signals incorporate post-decision data, because the last row is always the most recent market bar.

### F-030 — API `BacktestEngine` ignores its own `start_date` / `end_date`
- **origin:** COR · **also_reported_by:** DATA · **assets:** A4, A3
- **status:** PROPOSED
- **initial_severity:** CRITICAL · **initial_exploitability:** DEMONSTRATED (every custom-date run)
- **evidence:** `backend/backtest_engine.py:15-18` stores dates; `run()` (`:106-221`) never filters recs (`ORDER BY run_at` only) or prices (rolling 5y from `now`) by them.
- **mechanism:** If a user runs a 2024 backtest, trades from 2021 recs and post-2024 prices are still included, because the configured window is never applied. The advertised window is cosmetic.
- **controller_verified:** partial (dates stored; not referenced in run()).

### F-031 — Backtest price cache never refreshes once warm (>100 rows, no TTL)
- **origin:** DATA · **assets:** A6, A3
- **status:** PROPOSED
- **initial_severity:** MEDIUM · **initial_exploitability:** PLAUSIBLE
- **evidence:** `backend/backtest_engine.py:77-80`: returns cached rows when `len(cached) > 100` with no TTL or max-date check.
- **mechanism:** If the cache was populated earlier, later backtests reuse stale terminal prices and omit new history, because the warm-cache branch short-circuits fetch.

### F-032 — Backtest Calmar annualization assumes every trade lasts 90 days
- **origin:** COR · **assets:** A4
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** DEMONSTRATED
- **evidence:** `backend/backtest_engine.py:259`: exponent `252 / (len(returns) * TIME_DECAY_DAYS)` with 90-day constant, ignoring actual holding periods (early stop-loss exits).
- **mechanism:** If trades exit in 5–30 days, annual return and Calmar are systematically wrong, because the annualization assumes fixed 90-day holds.

### F-033 — Backtest & paper Sharpe/Sortino treat per-trade returns as daily
- **origin:** COR · **assets:** A4
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** DEMONSTRATED
- **evidence:** `backend/backtest_engine.py:239-258` and `backend/routers/paper_trading.py:356-367` feed per-trade returns to `compute_sharpe(..., annual_factor=252)` (`quant/metrics.py:17-32`) which assumes a daily series.
- **mechanism:** If a backtest yields N trades, Sharpe is scaled as if N daily observations annualized by √252, producing economically meaningless risk-adjusted metrics.

### F-034 — Paper history equity curve compounds in reverse-chronological order
- **origin:** COR · **assets:** A4
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** DEMONSTRATED
- **evidence:** `backend/routers/paper_trading.py:189-207`: trades fetched `ORDER BY exit_date DESC`, then `equity *= (1 + pnl_pct/100)` compounded in that order.
- **mechanism:** If ≥2 closed trades exist, the equity curve and ending equity are wrong, because compounding is order-dependent and applied newest-first.

### F-035 — Paper metrics compound PnL in undefined DB order (no ORDER BY)
- **origin:** COR · **assets:** A4
- **status:** PROPOSED
- **initial_severity:** MEDIUM · **initial_exploitability:** PLAUSIBLE
- **evidence:** `backend/routers/paper_trading.py:350-361`: `SELECT pnl_pct FROM paper_trades` with no `ORDER BY`, compounded sequentially.
- **mechanism:** If trades are inserted out of exit-date order, `total_pnl_pct` differs from true chronological compounding.

### F-036 — `history_outcomes` assumes LONG (return sign + target/stop) — SHORT inverted
- **origin:** COR · **assets:** A4
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** PLAUSIBLE
- **evidence:** `backend/history_outcomes.py:49-73`: `return_since_analysis_pct = (current-entry)/entry`, `target hit = current >= target`, stop = `entry*(1-stop/100)`; no direction branch.
- **mechanism:** If a stored analysis is a SHORT (SELL/STRONG SELL), outcome sign, target-hit, and stop-hit are inverted, misreporting recommendation performance.

### F-037 — Recommendations history hardcodes outcome fields to `None`
- **origin:** COR · **assets:** A4
- **status:** PROPOSED
- **initial_severity:** MEDIUM · **initial_exploitability:** DEMONSTRATED
- **evidence:** `backend/routers/recommendations.py:38-40`: `outcome/outcome_price/outcome_date = None`, never calls `compute_outcome_metrics` (which exists).
- **mechanism:** If the frontend calls `/recommendations/history/{ticker}`, outcomes are always empty even when computable, producing an empty track record.

### F-038 — Portfolio `day_change_pct` is total return since cost basis, not daily
- **origin:** COR · **assets:** A4
- **status:** PROPOSED
- **initial_severity:** MEDIUM · **initial_exploitability:** DEMONSTRATED
- **evidence:** `backend/routers/portfolio.py:87-104`: `day_change_pct = (total_value/total_cost - 1)*100`; no prior-day price.
- **mechanism:** If holdings moved since purchase, the field reports cumulative PnL, not same-day change, mislabeling portfolio performance.

### F-039 — Verdict/conviction thresholds duplicated across 3 uncoupled places
- **origin:** MNT · **assets:** A4
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** PLAUSIBLE (routine threshold edits)
- **evidence:** `orchestrator.py:879-915` hard-codes ±0.30/±0.60; `quant/scoring.py:16-18` defines `BUY_THRESHOLD=0.30`,`ACTIONABLE_THRESHOLD=0.40`; `prompts/synthesis.md` documents 0.30/0.60; orchestrator never imports `quant.scoring`.
- **mechanism:** A change to "when do we BUY / auto-trade?" requires editing prompt + orchestrator literals + quant scoring with no shared function or test asserting alignment; updating one silently diverges trades vs ranking vs backtest.

### F-040 — `enable_warehouse` config field is dead; gating uses raw `os.getenv`
- **origin:** MNT · **assets:** A4
- **status:** PROPOSED
- **initial_severity:** MEDIUM · **initial_exploitability:** PLAUSIBLE
- **evidence:** `config.py:130` `enable_warehouse=False` never read; `orchestrator.py:354` gates on `os.getenv("ENABLE_WAREHOUSE","").lower()=="true"`; config docstring says use `settings`.
- **mechanism:** Flipping `enable_warehouse` in config does nothing unless the separate `ENABLE_WAREHOUSE` env string is set — two toggles, one effective, and they select different enrichment paths (see F-041).

### F-041 — `_signal_vector` never attached on default path (dead code after `return`) → always ±8% stops
- **origin:** COR · **also_reported_by:** MNT · **assets:** A4
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** DEMONSTRATED (default deploy)
- **evidence:** `orchestrator.py:567-592` `return AnalysisData(...)`; lines `593-594` `data._signal_vector = ...` are unreachable; warehouse path sets it at `:394`; stop logic reads `getattr(data,"_signal_vector",None)` at `:817-821` and falls back to ±8% at `:830-834`.
- **mechanism:** With `enable_warehouse` off (default), analyses never attach `_signal_vector`, so ATR-based stops are skipped and fixed ±8% stops are persisted, contradicting the intended ATR logic.
- **controller_verified:** yes (read orchestrator.py:566-594).

### F-042 — Stop-loss logic diverges: live 2×ATR vs API BacktestEngine fixed 15%
- **origin:** MNT · **assets:** A4
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** PLAUSIBLE
- **evidence:** `orchestrator.py:809-861` (2×ATR / 8% fallback) vs `backend/backtest_engine.py:126-127` `STOP_LOSS_PCT = 0.15` + 90-day decay, ignoring stored `stop_loss_value`.
- **mechanism:** A change to live stop logic won't change `/backtest` results, so engineers validating rule changes via the API backtest ship divergent live behavior.

### F-043 — `agent_veto` wired into backtests but not live/candidate paths
- **origin:** MNT · **assets:** A4
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** MEDIUM
- **evidence:** `quant/agent_veto.py:227-276` used by `quant/backtest.py` (out of scope); `backend/routers/portfolio.py:210-231` candidate ranking and `orchestrator`/`paper_scheduler` never import it.
- **mechanism:** A change to veto thresholds affects research/backtest results but not live paper entries or `/portfolio/candidates`, so research-approved rules never reach the money paths.

### F-044 — Candidate ranking uses a stripped OBV-only signal stack vs production backtest blend
- **origin:** MNT · **also_reported_by:** COR · **assets:** A4
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** MEDIUM
- **evidence:** `backend/routers/portfolio.py:223` calls `compute_signal_vector_from_provider()` only; `quant/signals.py:59-66` `WEIGHTS` set `obv_trend=1.0`, all other technicals `0.0`; production CPCV applies cross-sectional norm + earnings/flow/QMJ blends + vetoes.
- **mechanism:** A change to composite construction in the backtest pipeline won't change dashboard candidates, giving false feedback and letting live recs diverge from validated ranking.

### F-045 — `jobs.py` mutates `os.environ` but orchestrator reads cached `settings` singleton
- **origin:** MNT · **assets:** A4
- **status:** PROPOSED
- **initial_severity:** MEDIUM · **initial_exploitability:** PLAUSIBLE
- **evidence:** `backend/jobs.py:77-106` sets env vars per request; `orchestrator.py:28`/enrichment read `from config import settings` (instantiated once at `config.py:194`).
- **mechanism:** Per-request feature toggles silently fail because Pydantic settings were read at import time and env mutation does not refresh them.

### F-046 — `.env.example` disagrees with `config.py` defaults (budgets differ ~2×)
- **origin:** MNT · **assets:** A4
- **status:** PROPOSED
- **initial_severity:** MEDIUM · **initial_exploitability:** PLAUSIBLE
- **evidence:** `MAX_AGENT_CONTEXT_CHARS` 7000 (`.env.example:64`) vs 12000 (`config.py:54`); `SYNTHESIS_INPUT_MAX_CHARS` 14000 vs 22000 (`config.py:65`); `ENRICHMENT_MAX_CHARS` 3500 vs 10000 (`config.py:78`); `TAVILY_SNIPPET_CHARS` 220 vs 600 (`config.py:79`).
- **mechanism:** Verdict inputs (synthesis budgets, enrichment truncation) differ depending on whether an operator copies the example file or relies on code defaults.

### F-047 — Tiingo `get_quote` downloads full EOD history for a single current price
- **origin:** PERF · **assets:** A5
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** DEMONSTRATED (all position/portfolio polls)
- **evidence:** `tiingo_client.py:29-41,111-127`: `tiingo/daily/{symbol}/prices` with no `startDate`, materializes full JSON, returns `data[0]`.
- **mechanism:** If N positions poll price, each does a full-history download because "quote" is implemented as an unbounded EOD fetch.

### F-048 — `get_price_provider()` builds a fresh client+cache on every call (no singleton)
- **origin:** PERF · **assets:** A3, A5
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** DEMONSTRATED
- **evidence:** `price_provider.py:244-280`: always constructs new `TiingoClient`/`AlpacaClient` + new cache; callers (`quant/signals.py:471-474`, `market_data.py:23-26`, `portfolio.py:237-238` ×8 threads) never share.
- **mechanism:** If N tickers are scored, you pay N cold sessions and N redundant history fetches because caches never warm across calls.

### F-049 — Paper/portfolio endpoints do N+1 synchronous HTTP inside async handlers
- **origin:** PERF · **also_reported_by:** REL · **assets:** A5
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** DEMONSTRATED
- **evidence:** `backend/routers/paper_trading.py:63-76,88-89,249-253` loop `_fetch_current_price(ticker)` (new client + blocking `get_quote`) inside `async def`.
- **mechanism:** As positions grow, each poll becomes O(N) sequential blocking HTTP on the event loop, exhausting workers and Tiingo limits.

### F-050 — Full-table scan of `analysis_history` (no LIMIT) on every positions-with-verdicts poll
- **origin:** PERF · **assets:** A5
- **status:** PROPOSED
- **initial_severity:** MEDIUM · **initial_exploitability:** PLAUSIBLE
- **evidence:** `backend/routers/paper_trading.py:231-239`: `SELECT ... FROM analysis_history ORDER BY run_at DESC` no LIMIT, dedup in Python.
- **mechanism:** As history grows to thousands of rows, each poll reads and sorts the whole table because the latest-per-ticker join is not pushed into SQL.

### F-051 — Quant backtest API accepts unbounded ticker lists and spawns unbounded threads
- **origin:** PERF · **assets:** A3, A5
- **status:** PROPOSED
- **initial_severity:** HIGH · **initial_exploitability:** PLAUSIBLE
- **evidence:** `backend/routers/backtest.py:225-235`: `payload.get("tickers", [])` no cap; `threading.Thread` per job, no pool.
- **mechanism:** A single POST with 1000 tickers launches an unbounded CPU thread with superlinear inner cost; concurrent submissions multiply threads without limit.

### F-052 — In-memory backtest job stores grow without eviction
- **origin:** PERF · **assets:** A3, A5
- **status:** PROPOSED
- **initial_severity:** MEDIUM · **initial_exploitability:** PLAUSIBLE
- **evidence:** `backend/routers/backtest.py:24,194`: module globals `_jobs`/`_quant_jobs` store full `result.to_dict()` with no TTL/LRU/cap.
- **mechanism:** Large results accumulate in process memory until OOM because completed jobs are never evicted.

### F-053 — Finnhub sentiment prefetch is serial O(N×M) with fixed 1.1s sleep
- **origin:** PERF · **assets:** A3
- **status:** PROPOSED
- **initial_severity:** MEDIUM · **initial_exploitability:** PLAUSIBLE
- **evidence:** `finnhub_client.py:377-401,363`: builds `{(ticker,from,to)}` over `tickers × rebalance_dates`, iterates serially with `time.sleep(rate_limit_sleep)` default 1.1s; docstring notes ~110 min at 50×120.
- **mechanism:** At N=1000 × ~120 dates the prefetch alone is multi-day wall time before the backtest starts, because the loop is strictly serial with a mandatory sleep.

---

*(Phase 2/3/4 verdicts appended below as they complete.)*
