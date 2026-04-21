# Modal cloud backtesting — implementation plan

**Goal.** Move CPCV + parameter sweeps to Modal with per-combination fan-out, persist results to SQLite + Supabase, and expose combo + trade-level drill-down in the existing backtest frontend.

**Primary bottleneck being solved.** CPCV at `n=16, k=8` is 12,870 combinations, ~430 hours sequential. With per-combo fan-out on Modal (200-wide parallelism), same sweep finishes in ~10-15 min. XGBoost ranker training + CPCV validation becomes cheap enough to iterate on signal weights freely.

---

## Preferences locked in from interview (2026-04-20)

| Decision | Choice |
|---|---|
| Target scope | Sessions 1–3 (CLI fan-out → Supabase/SQLite persistence → frontend drill-down) |
| Primary goal | Parameter / signal-weight sweeps on CPCV |
| Trigger | CLI + FastAPI (Railway) + Modal cron (all three) |
| Parallelism unit | **Per CPCV combination** (inner), with per-config sweeps fanning those out (outer) |
| Data access | Hybrid: slow-moving data on a Modal Volume, live-ish (prices/Kalshi) via API |
| Results storage | Dual-write: SQLite on Railway + Supabase (authoritative) |
| Compute | CPU for orchestrator + backtest, GPU (T4/L4) for XGBoost training + TimesFM |
| Cost guardrails | Research mode — no hard cap, alert on single-run anomalies |
| Frontend drill-down | Two-level: combo list + trade log per combo |
| Observability | Structured events → Supabase + Sentry for errors |
| Reproducibility | Config hash + git SHA on every run; identical configs dedupe in UI |
| Existing `modal_runner.py` | Rewrite clean; keep `run_experiment` gated behind admin-only path |
| Image strategy | Both modes — dev mounts local source, deployed pins to a git SHA clone |
| Default universe | `LIQUID_50` |
| Supabase status | Needs to be set up (project + schema) — I provide SQL, user applies |
| Scope guardrails | Fix adjacent broken stuff, no new features |
| Pacing | Stacked PRs — all sessions on one feature branch, one PR at the end |
| Branch | `modal-backtesting` (off `main` after PR #4 merges) |

---

## Reproducibility policy (Config hash + git SHA)

Every backtest run persists:

- `git_sha`: `HEAD` SHA at dispatch time (captured in orchestrator, passed to Modal)
- `config_hash`: `sha256(canonical_json(config))` where canonical_json sorts keys + serializes deterministically
- `run_id`: `{config_hash[:8]}-{git_sha[:8]}-{unix_ts}` (human-scannable)
- `started_at` / `finished_at`
- `modal_call_id`: Modal's own call ID for log lookup

UI shows "this config has been run N times" when `config_hash` matches. User explicitly requests re-run if they want a fresh execution.

Not doing now: data-snapshot hash, locked `requirements.txt`. Flag as follow-up if a result ever needs to be publicly defensible.

---

## Branching + PR strategy

- Base branch: `main` (after PR #4 merges)
- Feature branch: `modal-backtesting`
- Each session is one commit (or small commit series) on that branch
- Single PR opened at end of Session 3: `modal-backtesting → main`
- Do NOT merge `main` into `modal-backtesting` mid-flight unless blocked by a change on main

---

## Session 1 — Modal foundation + CPCV fan-out

**Target duration.** 60–90 min.

**Branch start state.** `main` clean after PR #4 merge.

### Deliverables

1. **New `modal/` package** (replaces `modal_runner.py`):
   - `modal/app.py` — `modal.App("ai-financial-analyst")`, image definition supporting both modes:
     - `Image.debian_slim(...).pip_install_from_requirements("requirements.txt")`
     - Dev mode: `.add_local_python_source("agents", "quant", "backend", ...)` via flag
     - Deploy mode: `.run_commands(f"git clone ... && git -C /root/app checkout {GIT_SHA}")` pinned to env var `MODAL_GIT_SHA`
   - `modal/secrets.py` — `Secret.from_name("ai-financial-analyst-secrets")` plus a typed accessor
   - `modal/functions/cpcv_combo.py` — single Modal Function: `run_cpcv_combination(combo_spec: dict) -> dict`, CPU-only (4 CPU, 8GB, 10-min timeout)
   - `modal/functions/experiment.py` — admin-gated `run_experiment` (keeps the `exec(code)` pattern, but requires `ADMIN_TOKEN` matching an env-var secret)
   - `modal/dispatcher.py` — thin orchestrator: builds combo specs, calls `run_cpcv_combination.map(specs)`, aggregates into `CPCVResult`

2. **Config hashing utility** (`quant/config_hash.py`):
   - `config_hash(cfg: BacktestConfig) -> str` — canonical JSON → sha256 hex
   - Unit tests: same config → same hash, reordered keys → same hash, changed weight → different hash

3. **CLI entry point** (`scripts/run_modal_cpcv.py`):
   - Args: `--config <yaml>`, `--universe <liquid_50|liquid_100|sp500>`, `--n-groups 16 --n-test 8`, `--max-combos N` (default = all), `--dev` (local-mount mode)
   - Emits a leaderboard sorted by OOS Sharpe at the end with `config_hash`, `git_sha`, and a PBO/DSR summary

4. **Smoke function** (keep, rename): `run_cpcv_smoke()` — single combo on `FALLBACK_TICKERS_5`, asserts metrics shape, 60s timeout. Used by `scripts/run_modal_cpcv.py --smoke` before big runs.

### Non-deliverables for Session 1
- No Supabase writes
- No frontend changes
- No GPU functions
- No cron

### Acceptance criteria

- [ ] `modal run scripts/run_modal_cpcv.py -- --smoke` passes in < 90s end-to-end
- [ ] `modal run scripts/run_modal_cpcv.py -- --universe liquid_50 --n-groups 10 --n-test 2 --max-combos 45` completes in under 5 minutes and prints a sorted leaderboard
- [ ] `modal run scripts/run_modal_cpcv.py -- --universe liquid_50 --n-groups 16 --n-test 8 --max-combos 500` completes in under 15 min
- [ ] `config_hash` is stable across runs (unit test)
- [ ] Dev mode: editing a signal file locally + rerunning reflects change without Docker rebuild
- [ ] Deploy mode: pinning `MODAL_GIT_SHA=<sha>` and rerunning produces identical results

### Risks / open questions
- Container cold-start cost at 500+ concurrent containers — mitigate with `min_containers=50` + `max_inputs=...` on the Function decorator
- Data provider rate limits (FMP / Tiingo) when 500 containers hit simultaneously — Session 1 eats the cost; Session 2's Volume hybrid mitigates

---

## Session 2 — Supabase schema + dual-write persistence + structured events

**Target duration.** 60–90 min.

### Deliverables

1. **Supabase SQL migration** (`supabase/migrations/0001_backtest_tables.sql`):
   ```sql
   -- Conceptual; actual SQL in the migration file
   backtest_runs (
     run_id text primary key,
     config_hash text not null,
     git_sha text not null,
     status text not null,           -- queued|running|completed|failed
     started_at timestamptz,
     finished_at timestamptz,
     config_json jsonb not null,
     universe text,
     n_groups int, n_test_groups int, n_combinations int,
     median_oos_sharpe numeric, pbo numeric, dsr numeric,
     metrics_json jsonb,
     error text,
     modal_call_id text
   )

   backtest_combinations (
     run_id text references backtest_runs,
     combo_idx int,
     train_indices int[], test_indices int[],
     is_sharpe numeric, oos_sharpe numeric,
     n_train_dates int, n_test_dates int,
     gates_json jsonb,
     primary key (run_id, combo_idx)
   )

   backtest_trades (
     run_id text references backtest_runs,
     combo_idx int,
     trade_id text,
     ticker text,
     entry_date date, exit_date date,
     entry_price numeric, exit_price numeric,
     side text,                       -- long|short
     pnl numeric, pnl_pct numeric,
     signals_at_entry_json jsonb,     -- snapshot of SignalVector
     regime text,
     weight numeric,
     primary key (run_id, combo_idx, trade_id)
   )
   ```
   Indexes on `(config_hash)`, `(run_id)`, `(ticker, entry_date)`.

2. **Supabase client wrapper** (`backend/supabase_backtest.py`):
   - Uses existing `settings.supabase_url` / `settings.supabase_service_key` pattern
   - Functions: `upsert_run`, `insert_combinations_batch`, `insert_trades_batch`, `get_run_history`, `get_run_detail`, `get_combo_detail`, `get_trades_for_combo`, `find_runs_by_config_hash`
   - Graceful no-op if Supabase disabled (existing pattern from `sec/supabase_history.py`)

3. **SQLite mirroring** (extends existing `backtest_runs` table in `sec/cache.py`):
   - Add missing columns via migration: `config_hash`, `git_sha`, `universe`, `pbo`, `dsr`, `modal_call_id`
   - New tables: `backtest_combinations`, `backtest_trades` (matching Supabase schema)

4. **Structured event stream**:
   - New module `modal/events.py` — `emit_event(run_id, kind, payload)` writes a row to a lightweight `backtest_events` table (Supabase + SQLite)
   - Each CPCV combo container emits: `combo_started`, `combo_completed`, `combo_failed`
   - Orchestrator emits: `run_started`, `run_completed`, `run_failed`

5. **Sentry hooks**:
   - Wrap each Modal Function with `sentry_sdk.capture_exception` on uncaught errors
   - Include `run_id`, `config_hash`, `combo_idx` as tags

6. **FastAPI endpoints** (extends existing `backend/routers/backtest.py`):
   - `POST /backtest/modal` — dispatch a sweep/CPCV run on Modal; returns `run_id`
   - `GET /backtest/runs` — list with pagination, filters by `config_hash` / `status`
   - `GET /backtest/runs/{run_id}` — full run detail
   - `GET /backtest/runs/{run_id}/combinations` — paginated combo list
   - `GET /backtest/runs/{run_id}/combinations/{combo_idx}/trades` — trade log
   - `GET /backtest/runs/{run_id}/events` — event stream (for polling)

### Supabase setup user needs to do before Session 2 starts
1. Create a Supabase project (free tier is fine for dev)
2. Copy URL and `service_role` key into Railway env vars: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ENABLE_SUPABASE_HISTORY=true`
3. Apply the migration (`supabase db push` from CLI, or paste SQL in the Supabase SQL editor)

I'll provide the exact SQL and the `supabase/` directory — user handles credentials + apply.

### Acceptance criteria

- [ ] Supabase migration applies cleanly from a fresh project (verified by user)
- [ ] A completed Modal run produces rows in `backtest_runs`, `backtest_combinations`, `backtest_trades` in both SQLite and Supabase
- [ ] `find_runs_by_config_hash(hash)` returns all prior runs with the same config
- [ ] Killing a Modal run mid-flight marks the run `failed` in DB with a Sentry event
- [ ] `GET /backtest/runs/{run_id}/events` returns rows in order as combos complete

### Non-deliverables for Session 2
- No frontend changes
- No GPU / XGBoost training

---

## Session 3 — Frontend drill-down (combo list + trade log)

**Target duration.** 2–3 hours.

### Deliverables

1. **"Run on Modal" flow on `/backtest`**:
   - New dialog variant in `NewBacktestDialog.tsx` with a "Run on Modal" toggle (default on)
   - Submit hits `POST /backtest/modal`, routes user to the new run's detail page

2. **Run list (updates `BacktestPage.tsx` `RunSelector`)**:
   - Columns: date, universe, config hash (short), status badge, median OOS Sharpe, PBO, DSR, # combos
   - Sort: newest first; filter by status + config_hash
   - When a `config_hash` has multiple runs, show a "×3" pill beside it

3. **Run detail page** (new route `/backtest/runs/:runId`):
   - Header: status, config hash, git SHA, times, Sharpe/PBO/DSR summary
   - Tab 1: **Combinations** — sortable table of the (up to) 12,870 combos with IS Sharpe, OOS Sharpe, pass/fail gates, click-to-drill
   - Tab 2: **Events** — streaming timeline of combo_started / completed / failed events (polls `/events` every 2s while `status=running`)
   - Tab 3: **Config** — pretty-printed JSON, diff vs previous run of same `config_hash` stem
   - Tab 4: **Trades aggregate** — all trades across all combos, grouped by ticker, with attribution placeholder (full attribution is Session 5 scope)

4. **Combo detail page** (new route `/backtest/runs/:runId/combos/:comboIdx`):
   - Train / test date ranges
   - Gates panel (pass/fail checklist)
   - **Trade log table** — every trade: ticker, side, entry/exit dates, entry/exit price, P&L, weight, regime at entry
   - Click a trade → inline expand: full `SignalVector` at entry (every signal's score) + annotation box for user-written notes (notes store local only in Session 3; DB-backed in a follow-up)

5. **Design system fit**:
   - Use existing shadcn components (`Card`, `Table`, `Tabs`, `Badge`, `Sheet`)
   - Zinc + cyan palette, no new colors
   - All new pages accessible from the sidebar under Research → Backtest

### Acceptance criteria

- [ ] Click "Run on Modal" from `/backtest` → 15 min later a completed run with 500 combos is fully browsable
- [ ] Can sort combinations by OOS Sharpe and click the worst one to see which trades lost money
- [ ] Click a losing trade → see its full SignalVector and identify which signals were high (i.e. which signal was "wrong")
- [ ] Config-hash dedup pill appears when you've run the same config twice
- [ ] Live event stream ticks as combos complete during a running sweep

### Non-deliverables for Session 3
- XGBoost GPU training (Session 4)
- Modal cron (Session 4)
- Signal attribution panel (Session 5)
- User-written annotations persist to DB (follow-up)
- Cost tracking UI (follow-up)

---

## Sessions 4 and 5 (not in this PR, captured for continuity)

### Session 4 — XGBoost GPU training + nightly cron (~60–90 min)
- Second Modal Function on T4/L4: `run_xgb_training(config)` — builds feature matrix, trains ranker, saves artifact to Modal Volume, references in Supabase
- `modal.Cron` for a nightly sweep using a fixed config; results auto-appear in the UI

### Session 5 — Signal attribution (~open-ended)
- Per-trade: contribution breakdown of every signal to the portfolio decision (score-level + realized-P&L-level attribution)
- Per-run regime × signal IC matrix — "which signals work in which regimes"
- The "route bad decisions back to signals" insight loop

---

## Task breakdown (flat checklist)

### Session 1
- [ ] Create branch `modal-backtesting` off `main` (after PR #4 merges)
- [ ] Scaffold `modal/` package (app.py, secrets.py, functions/, dispatcher.py)
- [ ] Write `quant/config_hash.py` + tests
- [ ] Write `modal/functions/cpcv_combo.py` — per-combo function
- [ ] Write `modal/dispatcher.py` — orchestrator with `.map()`
- [ ] Port `run_experiment` behind admin token
- [ ] `scripts/run_modal_cpcv.py` CLI
- [ ] Delete old `modal_runner.py`
- [ ] Smoke test passes
- [ ] 500-combo CPCV < 15 min — document actual wall-clock in the PR

### Session 2
- [ ] Write Supabase migration SQL under `supabase/migrations/0001_backtest_tables.sql`
- [ ] `backend/supabase_backtest.py` client wrapper
- [ ] Extend SQLite schema in `sec/cache.py` with migration logic (additive columns + new tables)
- [ ] `modal/events.py` event emitter (dual-write)
- [ ] Wire Sentry tags
- [ ] FastAPI endpoints: `POST /backtest/modal`, `GET /backtest/runs`, `/runs/{id}`, `/combinations`, `/trades`, `/events`
- [ ] Provide user the SQL to apply and the env-var checklist

### Session 3
- [ ] `NewBacktestDialog.tsx` Modal toggle
- [ ] Update `RunSelector` columns + config-hash dedup pill
- [ ] New route `/backtest/runs/:runId` + page
- [ ] New route `/backtest/runs/:runId/combos/:comboIdx` + page
- [ ] Live event polling hook `useBacktestEvents(runId)`
- [ ] Trade log component with expandable SignalVector row
- [ ] End-to-end click-through test plan in the PR

### PR
- [ ] Open `modal-backtesting → main` with summary grouping all three sessions + acceptance-criteria checklist

---

## Tracking notes (updated as we go)

- 2026-04-20: Plan created. Waiting for PR #4 to merge before creating `modal-backtesting` branch.
- 2026-04-20: Dirty tree cleaned: DCF multiples calibration committed to `frontend-overhaul` (2 commits), `.gitignore` tightened, `claude/elated-haslett` worktree + branch removed (fully superseded by main).
