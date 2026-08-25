# Adversarial Code Audit — Charter

**Audit:** Core platform of the AI Financial Analyst / autonomous trading system
**Date:** 2026-07-04
**Skill:** `docs/superpowers/skills/adversarial-code-audit`
**Controller:** cloud agent (coordinator; never audits, only dispatches and validates)

---

## Frozen SHA

```
60855802c9b172985110ff482f2f12e48842a2dd
```

Every subagent audits this exact tree. If code changes mid-audit, the audit halts and re-syncs. (The audit-run branch `cursor/adversarial-audit-run-3dae` is cut from this SHA; audit artifacts are additive and do not change the audited tree.)

---

## Hypothesis / Expressed Direction (from documentation)

Per `NORTHSTAR.md`, this system is becoming an **autonomous, self-improving trading intelligence system** that trades equities **with no human input required for normal operation**. Its stated core belief:

> *"Our edge is reasoning quality and validation rigor, not signal discovery."*
> *"Every new component must pass CPCV before it touches the live pipeline. No exceptions."*

This makes two things simultaneously true and shapes the whole audit:

1. **The system is designed to move money autonomously** (`auto_paper_trade: bool = True`, `auto_paper_trade_min_conviction: 0.40`, a paper-trading scheduler that runs on a cron and places orders through Alpaca). Any weakness that lets it trade wrongly, trade on a stale/incorrect signal, or lets an outsider trigger a trade is high-severity.
2. **The system's entire claimed value is validation correctness** (CPCV, purge/embargo, point-in-time data, no look-ahead). A look-ahead-bias or CPCV-integrity defect is therefore not a "quant nitpick" — it directly falsifies the North Star's core belief and would make every downstream "validated" verdict untrustworthy.

The audit is scoped to hold the code accountable to *its own stated standard*.

---

## Critical Assets

| ID | Asset | Why it matters |
|---|---|---|
| A1 | **Trade execution integrity** | The system autonomously places (paper) orders via Alpaca. Wrong, duplicated, unbounded, or attacker-triggered orders are the top risk. `auto_paper_trade=True` by default. |
| A2 | **Secrets / API keys** | Anthropic, OpenAI, Alpaca (trading), Tiingo, Finnhub, FMP, FRED, Tavily, Pinecone, Supabase service key. Leakage = financial + data-provider abuse. |
| A3 | **Validation correctness (no look-ahead / CPCV integrity)** | The North Star's *entire* claimed edge. A leak here silently invalidates every "passed CPCV" claim. Includes point-in-time data handling. |
| A4 | **Output correctness (verdicts, rankings, PnL)** | Wrong conviction scores, wrong PnL math, wrong signal aggregation → wrong trades and false confidence. |
| A5 | **API availability / backend uptime** | FastAPI backend serves the dashboard and dispatches jobs; hangs/exhaustion take the system down. |
| A6 | **Data integrity at rest** | SQLite warehouse + Supabase mirror hold positions, trades, backtest results. Corruption or unsafe migration loses trade history. |

---

## Threat Model

Adversaries and failure sources considered in scope:

- **External network attacker** — the FastAPI backend is internet-deployed (Railway) with a browser frontend (Vercel). CORS is credentialed. Endpoints that mutate state or trigger trades are reachable.
- **Hostile / malformed input** — ticker strings, request bodies, and user-supplied API keys flow into subprocess/env/DB/LLM paths.
- **Misbehaving upstream** — data providers (FRED/Finnhub/FMP/Tiingo/Alpaca) hang, rate-limit, return partial/garbage data, or change schema.
- **Silent data corruption / look-ahead** — historical calculations that accidentally use future or current-reference data; CPCV purge/embargo defects; cache staleness.
- **Operator / deployment error** — missing env var causes fail-open rather than fail-closed; unsafe migration; secret in logs.
- **Model / signal regression** — a signal or verdict path that degrades silently without telemetry.

**Explicitly out of adversary scope:** a fully-trusted local operator running offline research scripts by hand (those paths are lower priority and largely out of file scope below).

---

## Scope

This is a **release-critical core** audit, not a whole-repo audit. The repo is ~44k lines of Python; auditing all of it in one adversarial pass would dilute signal. Scope is the network-facing, money-touching, secret-handling, and validation-correctness core.

### In scope

**Network / API surface**
- `main.py`, `app.py`
- `backend/main.py`
- `backend/routers/*.py` (analysis, reports, config, portfolio, news, industry, watchlist, market_data, recommendations, backtest, backtest_modal, paper_trading)
- `backend/jobs.py`, `backend/schemas.py`

**Money / trading**
- `backend/alpaca_paper_client.py`
- `backend/paper_scheduler.py`
- `quant/agent_veto.py` (veto gate that can block/allow trades)

**Secrets / config**
- `config.py`, `.env.example`

**Data-provider clients (secrets + reliability + schema drift)**
- `finnhub_client.py`, `fmp_client.py`, `fred_client.py`, `tiingo_client.py`, `price_provider.py`
- `backend/supabase_backtest.py`

**Validation-correctness core (look-ahead / CPCV / signals / synthesis)**
- `quant/cpcv.py`
- `quant/signals.py`
- `quant/factor_attribution.py`
- `orchestrator.py` (agent fan-out + synthesis + verdict override)

### Out of scope (this pass → candidate follow-up specs)

- ML training / research scripts (`scripts/*`, `quant/*_backtest*.py`, LSTM/XGBoost/TimesFM training)
- `quant/backtest.py` (3,929 lines — too large for a single adversarial pass; **flagged as its own follow-up audit**, especially the regime-detection and ETF-ladder logic)
- `warehouse/*`, `modal_app/*`, `sec/*`, `infra/*` internals
- Frontend (no Python present in `frontend/`)
- Test suite quality (`tests/*`) — the audit *uses* tests as evidence but does not audit them as a target

Any auditor finding a weakness outside this file list records it as `scope_check: out-of-scope-return` and it becomes a follow-up spec, not a Phase-2 finding.

---

## Persona Set

All six personas from `personas.md` are selected. Justification per the "comprehensive" mandate and the asset map:

| Persona | Selected? | Primary assets | Focus within scope |
|---|---|---|---|
| Security | ✅ | A1, A2, A5 | Router auth, CORS, secret handling, user-supplied key flow, injection, SSRF |
| Correctness | ✅ | A4, A1 | PnL math, conviction/verdict override, signal aggregation, edge cases |
| Reliability | ✅ | A5, A1 | Provider timeouts, retries, scheduler concurrency, thread drain, SQLite access |
| Performance | ✅ | A5, A3 | N+1 price fetches, hot-path allocations, unbounded results at R1000 scale |
| Data & State | ✅ | A3, A6 | **Look-ahead bias, CPCV purge/embargo integrity, PIT data, cache coherence, migrations** |
| Maintainability | ✅ | A4 | Coupling that makes trade-logic edits dangerous; config sprawl; dead flags |

No persona dropped. Data & State is the highest-priority persona given the North Star's validation-rigor thesis.

---

## Deliverables

Written under `docs/audit/2026-07-04-core-platform-audit/`:

1. `audit-charter.md` — this file (frozen after Phase 1 starts).
2. `findings-ledger.md` — full adversarial audit trail per `ledger-schema.md`.
3. `audit-report.md` — HARDENED findings only, with final severity + evidence.
4. `strengthening-plan.md` — sequenced remediation bundles with tests, rollout, priority.

---

## Anti-Collusion Reminders (binding on the controller)

- Every finding needs `file:line` evidence or it is rejected at intake.
- Cross-examiner persona ≠ originator persona; defender ≠ both; arbitrator has no prior role on the finding.
- No subagent sees another subagent's confidence/verdict/transcript.
- A finding is HARDENED only after surviving a hostile refutation AND a defense attempt.
- SHA drift halts the audit.
