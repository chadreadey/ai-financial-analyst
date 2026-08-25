# Adversarial Code Audit — Report

**System:** AI Financial Analyst / autonomous trading intelligence system
**Scope:** release-critical core (network API, money/trading, secrets, validation correctness) — see `audit-charter.md`
**Frozen SHA:** `60855802c9b172985110ff482f2f12e48842a2dd`
**Method:** `adversarial-code-audit` skill — 6 persona auditors → hostile cross-examination → devil's-advocate defense → arbitration. Full trail in `findings-ledger.md`.

---

## How to read this report

Every finding below is **HARDENED** — it survived (1) discovery by a persona auditor, (2) a hostile cross-examiner instructed to refute it, and (3) a devil's-advocate defender arguing the code's case; disputes were settled by an independent arbitrator. Findings that were **refuted or fully downgraded to non-issues are not here** (they remain in the ledger). This is deliberately a short, high-confidence list, not the raw 113 observations.

**Adversarial process value (what the extra rounds changed):**
- **1 finding escalated** in severity by the process: **F-002** went MEDIUM→**CRITICAL** when the defender surfaced the `watchlist`/`watchlist_entries` table mismatch, making mass-liquidation deterministic rather than fault-only.
- **6 findings refuted** as false positives that a single-pass review would likely have shipped — most notably **F-028** (the "ad-hoc PBO" is *dead code*; `is_sharpes` is never populated) and **F-029/F-007** (look-ahead / substring bugs that the deterministic override and PIT-safe entrypoint neutralize on live paths).
- **8 findings downgraded** with cited justification (paper-only broker, unrendered fields, documented decoupling, bounded IC shrinkage).

---

## Severity summary

| Severity | Count | Findings |
|---|---|---|
| CRITICAL | 2 | F-001, F-002 |
| HIGH | 4 | F-004, F-014, F-024, F-041 |
| MEDIUM | 21 | F-003, F-005, F-006, F-009, F-011, F-016, F-017, F-018, F-020, F-023, F-027, F-030, F-032, F-033, F-034, F-036, F-039, F-042, F-044, F-047, F-048, F-049, F-051 |
| LOW | 14 | F-008, F-010, F-012, F-019, F-021, F-022, F-028R, F-037, F-038, F-040, F-043, F-045, F-046, F-050, F-052, F-053 |

*(MEDIUM/LOW counts include findings whose severity was reduced during defense/arbitration; the ledger holds the per-finding history.)*

---

## CRITICAL

### F-001 — Monthly rebalance submits duplicate Alpaca orders (2× position size)
**Assets:** A1 · **Exploitability:** DEMONSTRATED (default config) · **Files:** `backend/paper_scheduler.py:56-78`, `orchestrator.py:955-958`, `orchestrator.py:288-301`, `config.py:156`

On each rebalance *open*, `run_rebalance` calls `run_analysis_job` → `orchestrator.run()`, which with `auto_paper_trade=True` (default) already submits an Alpaca market order via `_auto_paper_trade`. The scheduler then submits a **second** order for the same ticker/side at `paper_scheduler.py:78`. `current_symbols` is captured once and never refreshed, and there is no idempotency key. Every qualifying rebalance entry is filled at ~2× `paper_default_qty`. Survived all three rounds with no credible mitigation.

### F-002 — Scheduled rebalance liquidates the entire book (table-name mismatch)
**Assets:** A1 · **Exploitability:** DEMONSTRATED · **Files:** `backend/paper_scheduler.py:21-28,36-48,100`, `backend/routers/watchlist.py:24-27,74-76`

`_scheduled_rebalance` calls `run_rebalance(target_tickers=None)`, which reads `SELECT ticker FROM watchlist`. The watchlist API writes to `watchlist_entries`; **no code in the tree creates a `watchlist` table.** The query raises, the bare `except` returns `[]`, and an empty target set makes every held symbol "not in target" → `client.close_position(symbol)` for all positions. The arbitrator confirmed this is deterministic on a normal deploy, not merely a transient-fault case. This is the single most dangerous defect found: an autonomous monthly job that flattens the portfolio.

---

## HIGH

### F-004 — No authentication on any router except `backtest_modal`
**Assets:** A2, A5 (A1 mitigated to paper-only) · **Files:** `backend/main.py:111-122`, `backend/routers/backtest_modal.py:24-45`

The internet-deployed FastAPI backend (Vercel→Railway rewrite, `--host 0.0.0.0`) mounts every router with no auth dependency except the Modal CPCV dispatch route. Unauthenticated clients can drive analysis (operator LLM spend), backtests, portfolio/watchlist mutations, and trade triggers (F-003/F-005). Defense correctly noted the broker is paper-only, lowering *capital* impact, but denial-of-wallet against operator API keys and state mutation remain HIGH. This is the parent of F-003 and F-005.

### F-014 — No rate limiting on cost-bearing endpoints (denial-of-wallet)
**Assets:** A2, A5 · **Files:** `backend/routers/analysis.py:16`, `backtest.py:117-162`, `news.py:13-45`, `paper_trading.py:415`

No throttling middleware exists. Unauthenticated floods of `/analysis/run`, NL backtests, and Tavily news exhaust operator LLM/data quotas and pin CPU. The 300s news cache is only a partial mitigation. Compounds with F-004.

### F-024 — CPCV IC calibration leaks future information into OOS metrics
**Assets:** A3 (the North Star's core claim) · **Files:** `quant/cpcv.py:144-193`, `quant/backtest.py:3410-3453,51,53`

`apply_purge_embargo` purges only *adjacent* train/test group boundaries; it never enforces that all train dates precede all test dates. With `enable_ic_calibration=True` (default), signal weights calibrated on chronologically-later train dates are applied to earlier test rebalances, inflating OOS Sharpe/DSR. Per-date signals are PIT-safe; the leak is confined to weight calibration. Arbitrated down to HIGH (not CRITICAL) because `ic_shrinkage=0.90` and negative-IC-zeroing bound the effect to ≤10% of OOS weighting — but it still corrupts the headline metric the whole system stakes its credibility on.

### F-041 — ATR stop-loss logic is dead on the default deploy → always fixed ±8% stops
**Assets:** A4, A1 · **Exploitability:** DEMONSTRATED · **Files:** `orchestrator.py:567-594,817-834`, `market_enrichment.py:1276-1310`

`AnalysisData._signal_vector` is only attached inside the warehouse branch (`orchestrator.py:394`). On the default (non-warehouse) path, the assignment lives at lines 593-594 — **after** the `return` at 567, so it is unreachable. ATR *is* computed during enrichment but never wired in, so the stop logic always misses ATR and falls back to fixed ±8%. The intended 2×ATR stops never run in the default configuration. Defense's "8% matches the documented fallback" was rejected: the fallback is for when ATR is *unavailable*, but here ATR is available and silently discarded.

---

## MEDIUM (condensed)

| ID | Title | Assets | Files |
|---|---|---|---|
| F-003 | Unauthenticated `POST /rebalance` triggers paper orders | A1 | `paper_trading.py:415-424` |
| F-005 | Unauthenticated `/analysis/run` reaches auto-paper-trade | A1 | `analysis.py:16-25` → orchestrator |
| F-006 | Rebalance never exits a held name whose verdict flips to SELL | A1 | `paper_scheduler.py:52-54` |
| F-009 | Alpaca sync wipes verdict/conviction, resets `entry_date` to today | A4 | `alpaca_paper_client.py:113-123` |
| F-011 | User API keys written to process-global `os.environ` (concurrent race) | A2 | `jobs.py:91-106` |
| F-016 | `async` rebalance handler blocks the event loop | A5 | `paper_trading.py:415-420` |
| F-017 | Alpaca trading client has no HTTP timeout | A1, A5 | `alpaca_paper_client.py:33-37` |
| F-018 | FRED client has no timeout on the analysis path | A5 | `fred_client.py:89-114` |
| F-020 | No wall-clock timeout on analysis jobs | A1, A5 | `jobs.py:70-135` |
| F-023 | SQLite connections leaked on error paths | A5 | `paper_scheduler.py:23-28`, `jobs.py:114-147`, `portfolio.py:257-276` |
| F-027 | Deflated Sharpe uses combo count as `n_obs` (overstated significance) | A3 | `quant/cpcv.py:362-372` |
| F-030 | API `BacktestEngine` ignores its `start_date`/`end_date` | A4 | `backend/backtest_engine.py:15-18,106-221` |
| F-032 | Backtest Calmar assumes fixed 90-day holds | A4 | `backend/backtest_engine.py:259` |
| F-033 | Backtest/paper Sharpe treats per-trade returns as daily | A4 | `backtest_engine.py:239-258`, `paper_trading.py:356-367` |
| F-034 | Paper equity-curve series compounded reverse-chronologically | A4 | `paper_trading.py:189-207` |
| F-036 | `history_outcomes` assumes LONG; SHORT outcomes inverted | A4 | `history_outcomes.py:49-73` |
| F-039 | Verdict/conviction thresholds duplicated across 3 places | A4 | `orchestrator.py:879-915`, `quant/scoring.py:16-18` |
| F-042 | Live 2×ATR vs API-backtest fixed-15% stop divergence | A4 | `orchestrator.py:809-861`, `backtest_engine.py:126-127` |
| F-044 | Candidate ranking uses OBV-only stack vs CPCV blend (documented) | A4 | `portfolio.py:223`, `signals.py:59-66` |
| F-047 | Tiingo `get_quote` downloads full EOD history for one price | A5 | `tiingo_client.py:29-41` |
| F-048 | `get_price_provider()` builds a fresh client+cache each call | A3, A5 | `price_provider.py:244-280` |
| F-049 | Paper endpoints do N+1 blocking HTTP in async handlers | A5 | `paper_trading.py:63-76,249-253` |
| F-051 | Backtest API accepts unbounded ticker lists + threads | A3, A5 | `backtest.py:225-235` |

## LOW (condensed)

| ID | Title | Files |
|---|---|---|
| F-008 | Auto-trade `INSERT OR REPLACE` overwrites position, no PnL record | `orchestrator.py:266-278` |
| F-010 | Alpaca sync never DELETEs closed symbols → ghost positions | `alpaca_paper_client.py:100-127` |
| F-012 | Raw exception strings returned to clients | `jobs.py:149-153`, `analysis.py:44-47` |
| F-019 | Alpaca EOD pagination infinite loop on persistent 429 (opt-in provider) | `price_provider.py:135-156` |
| F-021 | `/api/health` has no dependency probe (silent degradation) | `backend/main.py:125-127` |
| F-022 | Unbounded in-process news cache | `news.py:9-10,58` |
| F-028R | Live PBO is `oos_negative_fraction`, not rigorous logit-PBO | `quant/cpcv.py:232-235` |
| F-037 | Recommendations history outcomes hardcoded `None` | `recommendations.py:38-40` |
| F-038 | Portfolio `day_change_pct` mislabeled (field unrendered) | `portfolio.py:87-104` |
| F-040 | `settings.enable_warehouse` is a dead config mirror | `config.py:130`, `orchestrator.py:354` |
| F-043 | `agent_veto` wired into backtest but not live/candidate (opt-in) | `agent_veto.py`, `portfolio.py:210-231` |
| F-045 | Per-request env toggles ignored (settings singleton frozen at import) | `jobs.py:77-106`, `config.py:194` |
| F-046 | `.env.example` disagrees with `config.py` defaults | `.env.example` vs `config.py` |
| F-050 | Full `analysis_history` scan per poll | `paper_trading.py:231-239` |
| F-052 | Unbounded in-memory backtest job stores | `backtest.py:24,194` |
| F-053 | Finnhub prefetch serial O(N×M) with 1.1s sleep (offline) | `finnhub_client.py:377-401` |

---

## Themes (root causes behind the findings)

1. **Trade execution has no single owner or safety envelope.** Orders are submitted from two places (orchestrator auto-trade *and* the scheduler), position state lives in 3–4 writers, and there is no idempotency, no atomic broker+DB boundary, and no "fail-closed on empty universe" guard. F-001, F-002, F-006, F-008, F-009, F-010 all stem from this.
2. **The default deploy path is under-exercised vs the warehouse path.** The most-run configuration (`enable_warehouse=False`) silently drops the signal vector (F-041) and diverges from the validated pipeline (F-044). What is tested/validated is not what runs.
3. **The API surface assumes a trusted network it does not have.** No auth (F-004), no rate limiting (F-014), credentialed CORS (downgraded), and blocking work on the event loop (F-016) — all fine for localhost, dangerous on Railway.
4. **Two backtest engines with different math and no tests.** The user-facing `BacktestEngine` ignores dates (F-030), mis-annualizes (F-032, F-033), and uses different stops than live (F-042) — while the validated `quant/backtest.py` is the "real" one. Engineers can get false confidence from the wrong engine.
5. **CPCV — the crown jewel — has bounded but real methodology leaks** (F-024, F-027, F-028R). None fully invalidate the framework, but each nudges the headline numbers in the optimistic direction, which is exactly the direction that erodes the North Star's credibility.
6. **Missing timeouts on the analysis critical path** (F-017, F-018, F-020) make any slow upstream a full-pipeline hang.

Remediation is sequenced in `strengthening-plan.md`.
