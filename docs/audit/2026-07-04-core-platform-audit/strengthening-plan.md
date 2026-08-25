# Strengthening Plan — Core Platform Adversarial Audit

**System:** AI Financial Analyst / autonomous trading system
**Frozen SHA:** `60855802c9b172985110ff482f2f12e48842a2dd`
**Inputs:** `audit-report.md` (HARDENED findings), `findings-ledger.md` (full trail)

This plan turns HARDENED findings into a sequenced, testable remediation program. It is ordered by **risk-reduction per unit of change**, not by finding number. Each bundle lists the findings it closes, the concrete change, a regression test that would have caught the bug, and rollout/verification notes.

**Prioritization model:** `priority = (asset_criticality × exploitability) / remediation_effort`, with a hard rule that anything that can autonomously mis-trade money (A1) or silently invalidate the CPCV claim (A3) jumps the queue. Effort is T-shirt sized (S/M/L) by blast radius of the edit, not calendar time.

---

## Bundle 0 — STOP-THE-BLEED: make autonomous trading safe (do first)

**Closes:** F-002 (CRITICAL), F-001 (CRITICAL), F-006 (MEDIUM), and de-risks F-016/F-020.
**Why first:** these are the only findings where a *normal, unattended* run can destroy the paper book or double every position. Until they are fixed, the safest action is to **disable the scheduler** (`settings.alpaca_api_key` unset, or don't start `create_scheduler`) — document that as the interim mitigation.

| Step | Change | Effort |
|---|---|---|
| 0.1 | **Fix the watchlist table mismatch (F-002).** Point `_get_watchlist_tickers()` at the real table (`watchlist_entries`) *or* add a compatibility view. **Critically: make it fail-CLOSED** — on any read error or empty result, `run_rebalance` must **abort with no closes**, never treat empty as "sell everything." Add an explicit `if not target_tickers: log + return {"status":"aborted-empty-universe"}` before the close loop. | S |
| 0.2 | **Remove the duplicate order path (F-001).** Choose ONE submitter. Recommended: the scheduler should NOT re-submit after `run_analysis_job` when `auto_paper_trade` already fired; pass an explicit `auto_trade=False` into the rebalance analysis call (or gate the scheduler's `submit_market_order` on "auto-trade did not already place it"). Add an idempotency key = `(ticker, side, rebalance_run_id)`. | M |
| 0.3 | **Add verdict-flip exits (F-006).** In `run_rebalance`, for held names still in the target set, re-evaluate the fresh verdict and close if it flipped to SELL/STRONG SELL (or below exit conviction). | M |
| 0.4 | **Wrap rebalance so it cannot wedge the API (F-016) and cannot hang forever (F-020).** Run `run_rebalance` and each per-ticker analysis under `asyncio.to_thread` + a wall-clock timeout; on timeout, abort that ticker, not the whole run. | M |

**Regression tests (must fail on the frozen SHA, pass after):**
- `test_rebalance_aborts_on_unreadable_watchlist` — monkeypatch the watchlist read to raise → assert **zero** `close_position` calls.
- `test_rebalance_empty_universe_does_not_liquidate` — empty watchlist → assert no closes.
- `test_rebalance_places_exactly_one_order_per_open` — spy on `submit_market_order`; assert call count == number of opened names (not 2×).
- `test_rebalance_closes_flipped_holding` — held name returns STRONG SELL → assert a close is issued.

**Rollout:** ship behind the existing `auto_paper_trade` flag; keep the scheduler disabled in production until 0.1–0.2 land and the tests are green. Verify against a paper account with 2–3 positions before re-enabling cron.

---

## Bundle 1 — Lock the front door (network trust boundary)

**Closes:** F-004 (HIGH), F-014 (HIGH), F-003 (MEDIUM), F-005 (MEDIUM), F-012 (LOW). Reduces the reachability multiplier on F-011, F-016, F-022, F-051, F-052.

| Step | Change | Effort |
|---|---|---|
| 1.1 | **Apply the existing `X-API-Key` dependency (or a session auth) app-wide**, not just to `backtest_modal`. Add it as an app-level or router-group dependency covering analysis, paper_trading, portfolio, watchlist, backtest. Keep read-only public routes explicit if truly needed. | M |
| 1.2 | **Rate-limit cost-bearing routes (F-014).** Add `slowapi` (or a simple per-IP token bucket) to `/analysis/run`, `/backtest/nl`, `/news`, `/paper-trading/rebalance`. | S |
| 1.3 | **Redact error bodies (F-012).** Return a generic message + server-side log id; never echo `str(exc)` to the client. | S |
| 1.4 | **Tighten CORS** to the exact production origin(s); drop the broad `-[a-z0-9]+` preview regex unless previews are required, and only keep `allow_credentials=True` if cookies are actually used. | S |

**Tests:** `test_protected_routes_require_key` (401/403 without key on each mutating route); `test_rate_limit_trips` (N+1 rapid calls → 429); `test_error_response_has_no_exception_text`.

**Rollout:** set `INTERNAL_API_KEY` in Railway (currently missing from `.env.example` — add it, F-045-adjacent), roll the frontend to send the header, then flip enforcement.

---

## Bundle 2 — Fix what runs by default (default-path parity)

**Closes:** F-041 (HIGH), F-044 (MEDIUM), F-040 (LOW). Related: F-039, F-042.

| Step | Change | Effort |
|---|---|---|
| 2.1 | **Attach `_signal_vector` on the default path (F-041).** Assign to a local before the `return`, or add `signal_vector` as a real field on `AnalysisData` and pass it in the constructor. Delete the dead lines 593-594. | S |
| 2.2 | **Add a regression test proving ATR stops fire on the default path** — analysis with `enable_warehouse=False`, ATR present → assert stop == 2×ATR distance, not ±8%. | S |
| 2.3 | **Decide the ranking-parity question (F-044).** Either document the OBV-only "paralysis-breaker" as an accepted product decision in NORTHSTAR/plan, or route candidate ranking through the CPCV-validated composite. This is a product call — flag for the operator. | M |
| 2.4 | **Delete or wire `settings.enable_warehouse` (F-040)** so config and runtime agree; unify on `settings`, drop the raw `os.getenv`. | S |

**Rollout:** 2.1/2.2 are safe and high-value (they change persisted stop values — validate on a few tickers). 2.3 needs a decision before code.

---

## Bundle 3 — Consolidate trade state & thresholds (make future changes safe)

**Closes:** F-039 (MEDIUM), F-042 (MEDIUM), F-009 (MEDIUM), F-008 (LOW), F-010 (LOW). Maintainability root cause behind several trade bugs.

| Step | Change | Effort |
|---|---|---|
| 3.1 | **Single source of truth for thresholds (F-039).** Move ±0.30/±0.60 verdict tiers and the 0.40 auto-trade gate into `quant/scoring.py` (or one config block); import everywhere; add a test asserting orchestrator, scoring, and the synthesis prompt agree. | M |
| 3.2 | **One position-persistence module (F-009, F-008, F-010).** Centralize `paper_positions` writes; make sync preserve metadata (don't `INSERT OR REPLACE` a subset), keep true `entry_date`, DELETE symbols closed at the broker, and record a `paper_trades` row on every close/replace. | M |
| 3.3 | **Unify stop logic (F-042)** so the API backtest engine reads the same stop model (2×ATR / stored `stop_loss_value`) as live, or clearly label the LLM-replay engine as non-validating. | M |

**Tests:** `test_thresholds_single_source`; `test_sync_preserves_verdict_and_entry_date`; `test_sync_deletes_closed_symbols`; `test_replace_records_closed_trade`.

---

## Bundle 4 — Reliability envelope on external calls

**Closes:** F-017 (MEDIUM), F-018 (MEDIUM), F-023 (MEDIUM), F-019 (LOW), F-021 (LOW), F-022 (LOW).

| Step | Change | Effort |
|---|---|---|
| 4.1 | **Timeouts everywhere (F-017, F-018).** Wrap the Alpaca trading client and FRED calls with explicit timeouts (thread-based `wait_for` or a timeout-capable HTTP layer). | M |
| 4.2 | **Bound the 429 loop (F-019)** with a max-retry + exponential backoff + break. | S |
| 4.3 | **`with`-manage SQLite connections (F-023)** at the three cited sites so they close on error. | S |
| 4.4 | **Dependency-aware `/api/health` (F-021)** — light SQLite ping + scheduler heartbeat; keep a separate cheap `/live`. | S |
| 4.5 | **Cap the news cache (F-022)** with an LRU/`maxsize` + periodic sweep. | S |

**Tests:** fault-injection tests asserting a hung provider returns/raises within the timeout; `test_sqlite_conn_closed_on_error`.

---

## Bundle 5 — Restore CPCV credibility (validation correctness)

**Closes:** F-024 (HIGH), F-027 (MEDIUM), F-028R (LOW). Directly protects the North Star claim.

| Step | Change | Effort |
|---|---|---|
| 5.1 | **Enforce temporal ordering in CPCV (F-024).** In `apply_purge_embargo` (or the IC-calibration consumer), constrain calibration data to dates strictly before `min(safe_test_dates)` for each fold — or document and gate the current interleaved-calibration behavior. Re-run a known strategy and confirm OOS Sharpe/DSR change is within expected bounds. | M |
| 5.2 | **Fix DSR `n_obs` (F-027)** to use the true return-sample size (OOS return-day count), not the combination count. | S |
| 5.3 | **Either implement rigorous logit-PBO or rename the metric (F-028R)** so the headline "PBO" is not mistaken for Bailey/López de Prado when it is `oos_negative_fraction`. | S |

**Tests:** `test_cpcv_no_future_train_dates_in_fold` (assert `max(train) < min(test)` per fold after the fix); `test_dsr_n_obs_uses_return_count`. **Verification:** re-run one canonical CPCV config and record before/after headline metrics in the plan follow-up — expect OOS numbers to move *down* slightly; that is the point.

---

## Bundle 6 — Backtest engine honesty & scale hygiene (lower urgency)

**Closes:** F-030, F-032, F-033, F-034, F-036, F-037, F-038, F-045, F-046, F-047, F-048, F-049, F-050, F-051, F-052, F-053.

Grouped because each is individually low/medium and mostly affects reporting or offline scale, not live money:
- **Backtest math (F-030, F-032, F-033, F-034):** apply the configured date window; annualize by actual holding days; feed a proper return series to Sharpe; compound the equity curve chronologically. Add unit tests for each — the `BacktestEngine` currently has none.
- **Outcome/reporting correctness (F-036, F-037, F-038):** direction-aware outcomes for SHORTs; wire `compute_outcome_metrics` into the recommendations router or remove the stub fields; fix or remove `day_change_pct`.
- **Config hygiene (F-045, F-046):** reconcile `.env.example` with `config.py`; make per-request toggles either work or be removed.
- **Scale (F-047, F-048, F-049, F-050, F-051, F-052, F-053):** add a `snapshot`/`latest` price call instead of full-history quotes; memoize `get_price_provider`; offload/ batch the N+1 price loops; cap ticker-list length and job-store size; parallelize/bound the Finnhub prefetch. Prioritize these only as the universe grows toward the R1000 target.

---

## Sequencing rationale

```
Bundle 0  ──►  (unblocks safe autonomous operation; do before re-enabling the scheduler)
Bundle 1  ──►  (closes the public attack surface; enables everything else to run exposed)
Bundle 2  ──►  (default path == validated path; stops silent wrong behavior)
Bundle 3  ──►  (structural: makes bundles 0/2 durable against future edits)
Bundle 4  ──►  (reliability envelope; needed before high-volume autonomous runs)
Bundle 5  ──►  (restores the CPCV credibility the whole thesis rests on)
Bundle 6  ──►  (reporting honesty + R1000 scale; ongoing)
```

**One-line operator asks that need a decision (not just code):**
- F-044: is OBV-only candidate ranking an accepted product decision, or a bug? (Bundle 2.3)
- F-024: what OOS-metric movement is acceptable after the temporal fix? (Bundle 5.1 verification)
- Auth model (Bundle 1.1): shared `INTERNAL_API_KEY` for the whole API, or per-user sessions?

## Definition of done

- Bundle 0 tests green and the scheduler re-enabled on a paper account with observed correct behavior.
- Bundles 1–2 merged; production backend requires auth and runs the validated default path.
- Bundle 5 merged with a recorded before/after CPCV metric delta.
- Every fixed finding has at least one regression test that fails on `60855802…` and passes after.
