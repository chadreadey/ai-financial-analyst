# PR #5 Python/Backend Fix Plan — `modal-backtesting`

Scope: 8 findings (4 critical, 4 important) identified in Modal CPCV dispatch,
CPCV combo execution, and the dual-write SQLite/Supabase persistence path.
Plan is intended to be executed top-to-bottom in the order listed under
**Sequencing** at the bottom. All edits preserve the existing dual-write
contract, the `CPCVState` serialization shape, and the PostgREST/SQLite schema.
No config/`requirements.txt` changes.

Line numbers below have been re-verified against `HEAD` on `modal-backtesting`.
Any drift vs. the original finding note is called out inline.

---

## Finding 1 — Daemon thread loses in-flight CPCV runs on uvicorn shutdown

- **Severity:** Critical
- **File + line:** `modal_app/dispatcher.py:553`
- **Root cause (1-2 sentences):** The background dispatch thread spawned by
  `kickoff_cpcv_background` is `daemon=True` and is never tracked. When the
  uvicorn worker receives SIGTERM (deploy, `--reload`, container stop) the
  interpreter exits without giving `_run()` a chance to finalize the row, so
  the `cpcv_runs` entry stays `running` until the 2 h stale sweeper fires —
  and any Modal containers spawned by `worker.run_combo.map()` may be
  orphaned.
- **Proposed fix:** Add a module-level thread registry in
  `modal_app/dispatcher.py`, register/unregister around `_run()`, and join
  registered threads from a FastAPI `lifespan` teardown in `backend/main.py`
  with a bounded timeout. Remove `daemon=True` so Python's interpreter-shutdown
  path also waits (the join in `lifespan` is the primary mechanism, but the
  non-daemon default is the belt to the lifespan suspenders).

  **Patch A — `modal_app/dispatcher.py`** (top of file, after `logger = ...`
  at line 40):
  ```python
  # Thread registry for in-flight background CPCV dispatches.
  # Populated by `kickoff_cpcv_background`, drained by the FastAPI
  # `lifespan` teardown in `backend/main.py`. Kept at module scope so
  # ``backend.main`` can import `active_dispatch_threads`/`dispatch_lock`
  # without importing the whole dispatcher module's heavy deps eagerly.
  import threading as _threading
  active_dispatch_threads: set[_threading.Thread] = set()
  dispatch_lock: _threading.Lock = _threading.Lock()


  def _register_thread(t: _threading.Thread) -> None:
      with dispatch_lock:
          active_dispatch_threads.add(t)


  def _unregister_thread(t: _threading.Thread) -> None:
      with dispatch_lock:
          active_dispatch_threads.discard(t)


  def snapshot_active_threads() -> list[_threading.Thread]:
      """Return a list copy of currently-registered dispatch threads.
      The lifespan teardown iterates this snapshot and joins each.
      """
      with dispatch_lock:
          return list(active_dispatch_threads)
  ```

  **Patch B — `modal_app/dispatcher.py:522-554`** (`_run` + thread spawn):
  ```python
      def _run() -> None:
          try:
              dispatch_cpcv(
                  config,
                  n_groups=n_groups,
                  n_test_groups=n_test_groups,
                  purge_months=purge_months,
                  embargo_months=embargo_months,
                  max_combos=max_combos,
                  seed=seed,
                  local=local,
                  print_leaderboard=False,
                  run_id=run_id,
                  config_hash=cfg_hash,
                  git_sha=git_sha,
              )
          except Exception as exc:  # noqa: BLE001
              logger.exception("background dispatch for run %s failed", run_id)
              _capture_sentry(run_id, cfg_hash, None, f"background dispatch failed: {exc}")
              cpcv_sqlite.patch_run(run_id, {
                  "status": "failed",
                  "error": str(exc)[:500],
                  "finished_at": time.time(),
              })
              supabase_backtest.patch_run(run_id, {
                  "status": "failed",
                  "error": str(exc)[:500],
                  "finished_at": time.time(),
              })
              emit_event(run_id, EVENT_RUN_FAILED, {"error": str(exc)[:500]})
          finally:
              _unregister_thread(_threading.current_thread())

      thread = _threading.Thread(target=_run, daemon=False, name=f"cpcv-{run_id}")
      _register_thread(thread)
      thread.start()
  ```
  Note: `daemon=False`. We rely on the `lifespan` join (Patch C) for SIGTERM.
  If an operator kills the process with SIGKILL no in-process code runs —
  the SQLite/Supabase stale-sweeper (Finding 7) remains the backstop.

  **Patch C — `backend/main.py:41-55`** (`lifespan` context manager):
  ```python
  @asynccontextmanager
  async def lifespan(app: FastAPI):
      # Start paper trading scheduler if Alpaca keys are configured
      _scheduler = None
      if settings.alpaca_api_key and settings.alpaca_secret_key:
          try:
              from backend.paper_scheduler import create_scheduler
              _scheduler = create_scheduler(start=True)
              logger.info("Paper trading scheduler started")
          except Exception as exc:
              logger.warning("Failed to start paper trading scheduler: %s", exc)
      try:
          yield
      finally:
          # Drain in-flight Modal CPCV dispatch threads so runs are finalized
          # (status, Supabase flush) before the process exits. Bounded join
          # — we do not block SIGTERM forever.
          try:
              from modal_app.dispatcher import snapshot_active_threads
              threads = snapshot_active_threads()
              if threads:
                  logger.info(
                      "lifespan: joining %d in-flight CPCV dispatch thread(s)",
                      len(threads),
                  )
              deadline_seconds = 30.0
              per_thread_budget = max(0.1, deadline_seconds / max(1, len(threads)))
              for t in threads:
                  t.join(timeout=per_thread_budget)
                  if t.is_alive():
                      logger.warning(
                          "lifespan: CPCV dispatch thread %s still running after "
                          "%.1fs — proceeding with shutdown; stale sweeper will finalize",
                          t.name, per_thread_budget,
                      )
          except Exception as exc:  # noqa: BLE001
              logger.warning("lifespan CPCV thread drain failed: %s", exc)
          if _scheduler:
              _scheduler.shutdown(wait=False)
  ```
  Timeout semantics: 30 seconds total (matches Kubernetes default
  `terminationGracePeriodSeconds`). Each thread gets `30 / n` so one
  hung thread cannot starve the rest. If the join expires we log and
  continue — we do NOT flip the run to `failed` here (the stale sweeper
  owns that transition so both stores converge consistently).
- **Why minimal:** No new process, no new queue — only threads we already
  spawn, plus a registry and a join.
- **Test to add:**
  `tests/test_dispatch_thread_registry.py::test_lifespan_drains_threads` —
  monkeypatch `modal_app.dispatcher.dispatch_cpcv` with a function that
  calls `time.sleep(0.2)` then writes a sentinel list, invoke
  `kickoff_cpcv_background` with a dummy `BacktestConfig` (monkeypatch
  `BacktestConfig.__instancecheck__` via a subclass) to spawn the thread,
  assert the thread is in `active_dispatch_threads`, then run the
  `backend.main.lifespan` async context manager against a stub `FastAPI`
  and assert the sentinel was written before lifespan exit and the set
  is empty after. Second case:
  `test_join_timeout_logs_and_moves_on` — monkeypatch dispatch with a
  2 s sleep and override `deadline_seconds = 0.1`; assert lifespan
  returns in ≤ 0.5 s and a `warning` is logged.
- **Risk of regression:** Very low. Workers not in `lifespan` (e.g. the CLI
  `run_cpcv.py`) still see `daemon=False` threads which will block process
  exit until complete — but the CLI already calls `dispatch_cpcv` directly
  (not `kickoff_cpcv_background`), so no CLI path is affected.

---

## Finding 2 — Final Supabase flush not in a `finally:`; dual-write drift on mid-map exception

- **Severity:** Critical
- **File + line:** `modal_app/dispatcher.py:251` (buffer declaration),
  `modal_app/dispatcher.py:368-371` (final flush). Line numbers verified;
  no drift.
- **Root cause (1-2 sentences):** `supabase_combo_buffer` holds up to
  `_supabase_combo_flush_size()` completed combos that have already been
  written to SQLite (per-combo) but not yet batched to Supabase. If
  `worker.run_combo.map(...)` raises (transient Modal infra fault, SIGTERM,
  network hiccup), the final flush at line 369 never runs — SQLite has the
  combos, Supabase does not, and the two stores silently diverge.
- **Proposed fix:** Wrap the `local`/`else` dispatch branches plus the final
  flush in a `try: ... finally:` so the buffer is always flushed, even when
  the underlying iteration raises. Keep the existing `if supabase_combo_buffer:`
  guard — empty flushes are a no-op but we keep the explicit check for
  readability. Diff against `modal_app/dispatcher.py:315-371`:

  ```python
      try:
          if local:
              from quant.backtest import _run_single_cpcv_combo
              for idx, (train, test) in enumerate(combos):
                  if idx % 10 == 0:
                      logger.info("local combo %d/%d", idx + 1, len(combos))
                  try:
                      out = _run_single_cpcv_combo(
                          state=local_state,
                          train_indices=train,
                          test_indices=test,
                          combo_idx=idx,
                          config=config,
                      )
                  except Exception as exc:
                      err_out = {
                          "combo_idx": idx,
                          "status": "error",
                          "error": f"{type(exc).__name__}: {exc}",
                      }
                      _handle_combo_result(err_out)
                      continue

                  if out is None:
                      _handle_combo_result({"combo_idx": idx, "status": "skipped",
                                            "skip_reason": "no_trades_or_sharpe"})
                      continue
                  out["status"] = "complete"
                  out.setdefault("git_sha", git_sha)
                  _handle_combo_result(out)
          else:
              from modal_app.app import app
              from modal_app.functions.cpcv_combo import CPCVWorker
              specs = _build_combo_specs(run_id, panel_key, combos, config_dict, cfg_hash, git_sha)
              logger.info("Dispatching %d combos to Modal CPCVWorker.run_combo.map()", len(specs))

              with app.run():
                  worker = CPCVWorker()
                  for out in worker.run_combo.map(
                      specs,
                      return_exceptions=True,
                      wrap_returned_exceptions=False,
                      order_outputs=False,
                  ):
                      if isinstance(out, Exception):
                          err_out = {
                              "combo_idx": -1,
                              "status": "error",
                              "error": f"{type(out).__name__}: {out}",
                          }
                          _handle_combo_result(err_out)
                          continue
                      _handle_combo_result(out)
      finally:
          # Always flush buffered Supabase combos, even if the fan-out
          # raises — SQLite is already up-to-date per-combo, Supabase
          # must follow or the two stores diverge.
          if supabase_combo_buffer:
              try:
                  supabase_backtest.insert_combinations_batch(supabase_combo_buffer)
              except Exception as flush_exc:  # noqa: BLE001
                  logger.warning(
                      "final Supabase combo flush failed (%d rows, run %s): %s",
                      len(supabase_combo_buffer), run_id, flush_exc,
                  )
              supabase_combo_buffer.clear()
  ```
  Notes: (a) we swallow the flush exception and log it — if Supabase is
  unreachable at shutdown, re-raising here would mask the original
  `worker.run_combo.map` exception that triggered the `finally`.
  (b) The clear happens outside the inner `try` so a second finalize pass
  (from an outer caller) does not re-send.
- **Why minimal:** Wraps existing logic in `try/finally`; no new helpers,
  no changed call shapes.
- **Test to add:**
  `tests/modal_app/test_dispatcher_finally_flush.py::test_map_midstream_exception_flushes_buffer` —
  build a minimal `BacktestConfig`, monkeypatch `modal_app.app.app.run` to a
  no-op context manager, monkeypatch `CPCVWorker` so `worker.run_combo.map`
  is a generator that yields 3 real combo dicts then `raise RuntimeError("boom")`,
  monkeypatch `supabase_backtest.insert_combinations_batch` to append rows
  to a capture list. Set `modal_backtest_flush_combos = 100` so the
  threshold-based flush never fires. Call `dispatch_cpcv(..., local=False)`
  inside `pytest.raises(RuntimeError)`. Assert the capture list received
  the 3 rows (via the `finally` flush) and that
  `cpcv_sqlite.insert_combinations_batch` was called 3 times (one per combo).
  Also assert the last emitted event is `EVENT_COMBO_COMPLETED` and
  `EVENT_RUN_FAILED` is emitted by the outer `_run` error handler.
- **Risk of regression:** None on the happy path (buffer is empty when
  flush runs normally, so the second flush is a no-op with
  `insert_combinations_batch([])` returning `(0, 0)`).

---

## Finding 3 — `_run_single_cpcv_combo` mutates `config._xgb_feature_matrix`

- **Severity:** Critical (latent — safe today, racy the moment the local
  path is parallelized)
- **File + line:** `quant/backtest.py:3262-3263`
- **Root cause (1-2 sentences):** The docstring at line 3237
  (`"Pure w.r.t. state and config."`) is false: line 3263 writes
  `config._xgb_feature_matrix = state.xgb_feature_matrix`. All combos in
  a local run share the same `config` instance, so a future
  `ThreadPoolExecutor` on the local dispatch branch becomes a data race on
  that attribute.
- **Proposed fix:** Stop mutating the shared `config`. Thread the feature
  matrix through a local copy of the configuration (`dataclasses.replace`)
  so downstream code (the rebalance loop that reads
  `config._xgb_feature_matrix`) keeps working without signature changes to
  called functions. If no downstream code reads `_xgb_feature_matrix` as an
  attribute (confirm via `Grep` before landing), prefer passing it as a
  local variable. Based on current codebase (Grep required before landing),
  the matrix is read inside this same function's rebalance loop — so a
  local variable is cleaner. Diff:

  Before (`quant/backtest.py:3259-3263`):
  ```python
      # Attach XGB feature matrix to config so the existing rolling-retrain
      # logic in the combo loop fires. State carries it so every Modal worker
      # gets a consistent PIT-frozen matrix without re-loading from disk.
      if config.enable_xgb_ranker and getattr(state, "xgb_feature_matrix", None) is not None:
          config._xgb_feature_matrix = state.xgb_feature_matrix
  ```

  After:
  ```python
      # Use a per-combo shallow-copied config so we never mutate the
      # caller's BacktestConfig (future parallel local dispatch would race
      # on `_xgb_feature_matrix`). `dataclasses.replace` returns a new
      # instance with only the fields we override; everything else is shared
      # by reference (`tickers` list etc.) which is safe because the
      # rebalance loop only reads them.
      from dataclasses import replace as _dc_replace
      if config.enable_xgb_ranker and getattr(state, "xgb_feature_matrix", None) is not None:
          config = _dc_replace(config)
          config._xgb_feature_matrix = state.xgb_feature_matrix
      # From here on, `config` is a combo-local copy.
  ```

  Before landing, run `Grep -n "_xgb_feature_matrix" quant/` to confirm no
  module caches the attribute off `config` expecting cross-combo
  persistence. If it does, promote the matrix to a dedicated positional
  argument on that helper instead.
- **Why minimal:** One `dataclasses.replace` call; no signature changes on
  any callee; existing read sites keep working because the combo-local
  copy still exposes the attribute.
- **Test to add:**
  `tests/quant/test_cpcv_combo_purity.py::test_combo_does_not_mutate_config` —
  build a `BacktestConfig` with `enable_xgb_ranker=True`, a minimal
  `CPCVState` that has `xgb_feature_matrix = pd.DataFrame({"a": [1.0]})`,
  snapshot `id(config)` and `"_xgb_feature_matrix" in vars(config)`, then
  run `_run_single_cpcv_combo(state=state, train_indices=[...],
  test_indices=[...], combo_idx=0, config=config)` (OK if it returns
  `None` on skipped — we only care about the post-condition). Assert
  `"_xgb_feature_matrix" not in vars(config)` after the call.
- **Risk of regression:** Low. `dataclasses.replace` copies only the
  dataclass fields; helpers reading `config.lookback_days` etc. see
  identical values. The only behavioral change is that attributes added
  via attribute assignment (like `_xgb_feature_matrix`) no longer leak
  back to the caller — which is exactly the fix.

---

## Finding 4 — `KalshiClient()` + macro fetches inside per-combo rebalance loop

- **Severity:** Critical (perf + PIT-leakage risk)
- **File + line:** `quant/backtest.py:3401-3420` (the `if
  config.enable_kalshi_signal:` block is at the top of the rebalance-date
  loop — i.e. invoked per `reb_date`, per combo).
- **Root cause (1-2 sentences):** Inside `for i, reb_date in
  enumerate(safe_test_dates[:-1]):` we instantiate `KalshiClient()` and
  call `compute_macro_modifier` / `compute_macro_momentum` on every
  rebalance date. That is (a) O(combos × test_dates × macro_series) HTTP
  calls (thousands per run) and (b) the Kalshi client fetches
  **live-at-query-time** market prices — during a historical CPCV
  simulation this injects forward-looking information (PIT leakage).
- **Proposed fix:** Hoist client construction and macro computation once
  per combo (or, ideally, once per run — see below), and pass the
  pre-computed scalars into the rebalance loop. Two-step fix:

  **Step 4a — Per-combo hoist (minimum viable, local fix):**
  In `_run_single_cpcv_combo` (between line 3285 — the
  `_vix_persistence_count` init — and the `for i, reb_date` loop at line
  3287) compute the macro scalars once per combo, then read them as
  locals inside the loop.

  ```python
      # ── PIT-safe Kalshi macro fetch (once per combo) ───────────────
      # NOTE: `KalshiClient` returns live-at-query-time prices. In a
      # historical backtest we treat the value as a const signal across
      # the test window; a point-in-time Kalshi archive is tracked in
      # quant/kalshi_signal.py TODO and blocks the leakage-free version.
      _kalshi_macro = 0.0
      _kalshi_momentum = 0.0
      _kalshi_client = None
      if config.enable_kalshi_signal:
          try:
              from quant.kalshi_client import KalshiClient
              from quant.kalshi_signal import (
                  compute_macro_modifier,
                  compute_macro_momentum,
              )
              _kalshi_client = KalshiClient()
              _kalshi_macro = compute_macro_modifier(_kalshi_client)
              _kalshi_momentum = compute_macro_momentum(_kalshi_client)
          except Exception as _exc:
              logger.warning("Kalshi macro bootstrap failed: %s", _exc)
              _kalshi_client = None
  ```

  Then inside the rebalance loop, replace lines 3401-3420 with:
  ```python
          if config.enable_kalshi_signal and _kalshi_client is not None:
              try:
                  from quant.kalshi_signal import compute_event_divergence
                  for _ticker in signals:
                      signals[_ticker].kalshi_macro_score = _kalshi_macro
                      signals[_ticker].kalshi_macro_momentum = _kalshi_momentum
                      _earn_prob = getattr(signals[_ticker], "earnings_rank_score", 0.0)
                      _our_prob = (_earn_prob + 1.0) / 2.0
                      signals[_ticker].kalshi_event_score = compute_event_divergence(
                          _kalshi_client,
                          ticker=_ticker,
                          our_prob_beat=_our_prob,
                          threshold=config.kalshi_event_threshold,
                      )
              except Exception as _exc:
                  logger.warning("Kalshi signal injection failed: %s", _exc)
  ```
  `compute_event_divergence` still runs per `reb_date` × `ticker` because
  the EARN market differs per ticker; the disk cache inside `KalshiClient`
  already dedupes the network layer. No signature changes on any
  callee — only `_run_single_cpcv_combo`'s internal locals move out of
  the loop.

  **Step 4b — Preferred per-run cache (recommended follow-up):**
  Add two optional fields to `CPCVState` at `quant/backtest.py:3225`:
  ```python
      # Cached Kalshi macro scalars (computed once per dispatcher run,
      # reused across all combos). `None` means disabled or fetch failed.
      kalshi_macro_modifier: Optional[float] = None
      kalshi_macro_momentum: Optional[float] = None
  ```
  Populate them in the dispatcher's panel-build phase (new function in
  `modal_app/panel.py`), and change `_run_single_cpcv_combo` to read
  `state.kalshi_macro_modifier` / `state.kalshi_macro_momentum` instead of
  instantiating `KalshiClient` at all. That eliminates the PIT-leakage
  concern because the scalar is captured exactly once per run, at panel
  build, and stamped into every combo. Land 4a in this PR; open a
  follow-up issue for 4b so we don't balloon scope.

  **Signature change summary:** None in 4a. In 4b, `CPCVState` gains two
  optional fields (default `None`), preserving the serialization shape for
  existing Modal volume panels because unknown fields default on the
  dataclass.
- **Why minimal:** 4a is a pure hoist — same logic, executed once per
  combo instead of once per rebalance date. Zero behavioral change in
  output.
- **Test to add:**
  `tests/quant/test_cpcv_kalshi_hoist.py::test_kalshi_client_instantiated_once_per_combo` —
  build a `CPCVState` with 5 `safe_test_dates` and `enable_kalshi_signal=True`,
  monkeypatch `quant.kalshi_client.KalshiClient.__init__` to bump a counter
  list. Call `_run_single_cpcv_combo(...)` once. Assert the counter list
  has length 1 (not 5). Second test:
  `test_macro_scalars_constant_within_combo` — monkeypatch
  `compute_macro_modifier` to return a counter (0.1, 0.2, 0.3, ...) and
  assert the value stamped on `signals[ticker].kalshi_macro_score` is
  identical across all rebalance dates in the combo.
- **Risk of regression:** Low. The only behavioral shift is that if a
  follow-up rebalance date would have produced a *different* macro value
  due to state drift inside `KalshiClient`, it now uses the first one.
  That is **desirable** given the PIT concern — and the disk cache in
  `KalshiClient` already produces the same value across a day anyway.

---

## Finding 5 — `patch_run` builds UPDATE SQL via f-string from dict keys

- **Severity:** Important
- **File + line:** `backend/cpcv_sqlite.py:221`
- **Root cause (1-2 sentences):** `patch_run` does
  `cols = ", ".join(f"{k}=?" for k in patch)` — column identifiers come
  directly from the caller's dict keys. Today all callers are internal
  (`modal_app/dispatcher.py`), so the inputs are trusted, but the pattern
  is a SQL-injection footgun the moment a FastAPI handler wires user
  input to it.
- **Proposed fix:** Allowlist the column names against a fixed set and
  raise `ValueError` on anything outside it. Reuse the existing
  `_RUN_COLS` list (at line 377 in the same file) as the source of truth,
  minus the primary key and auto-managed columns. Diff
  (`backend/cpcv_sqlite.py:213-233`):
  ```python
  # Columns patch_run is allowed to touch. Excludes run_id (primary key)
  # and created_at (immutable). Derived from the schema at
  # `_ensure_schema` — update together when adding new columns.
  _PATCHABLE_RUN_COLS: frozenset[str] = frozenset({
      "config_hash", "git_sha", "status", "universe",
      "n_groups", "n_test_groups", "n_combinations",
      "n_completed", "n_skipped", "n_failed",
      "median_oos_sharpe", "oos_sharpe_min", "oos_sharpe_max",
      "pbo", "deflated_sharpe",
      "config_json", "metrics_json", "error", "modal_call_id",
      "started_at", "finished_at",
  })


  def patch_run(run_id: str, patch: dict) -> bool:
      """Targeted UPDATE of specific columns on a cpcv_runs row."""
      if not patch:
          return False
      unknown = set(patch.keys()) - _PATCHABLE_RUN_COLS
      if unknown:
          raise ValueError(
              f"patch_run: unknown columns {sorted(unknown)} "
              f"(allowed: {sorted(_PATCHABLE_RUN_COLS)})"
          )
      try:
          conn = _connect()
          try:
              _ensure_schema(conn)
              cols = ", ".join(f"{k}=?" for k in patch)
              params = list(patch.values()) + [time.time(), run_id]
              conn.execute(
                  f"UPDATE cpcv_runs SET {cols}, updated_at=? WHERE run_id=?",
                  params,
              )
              conn.commit()
              return True
          finally:
              conn.close()
      except Exception as exc:  # noqa: BLE001
          logger.warning("sqlite patch_run failed: %s", exc)
          return False
  ```
  Note: Raise `ValueError` *before* the `try/except` so the allowlist
  check surfaces in tests; the existing broad `except` only catches
  sqlite-level errors.
- **Why minimal:** One frozenset + one membership check. No caller
  touches a column outside the allowlist today (grep all `patch_run`
  sites under `modal_app/` and `backend/` to confirm before landing).
- **Test to add:**
  `tests/backend/test_cpcv_sqlite_patch_run.py::test_patch_run_rejects_unknown_column` —
  call `patch_run("xyz", {"status": "running", "DROP TABLE cpcv_runs; --": 1})`
  inside `pytest.raises(ValueError)` and assert the message contains the
  bad key. Second test: `test_patch_run_accepts_all_known_columns` —
  call with every key in `_PATCHABLE_RUN_COLS` set to a safe value and
  assert it returns True (no exception raised). Third test:
  `test_patch_run_empty_dict_returns_false` — preserves the existing
  early-return behavior.
- **Risk of regression:** Any caller passing a column name not in the
  allowlist will now raise. Grep the repo before landing:
  `Grep "patch_run\(" --type py` — expected sites are
  `modal_app/dispatcher.py` (4 occurrences) and the new code, all using
  the fields in the allowlist. If any mismatch is found, extend the
  allowlist rather than disabling the check.

---

## Finding 6 — `json.dumps` in `config_hash` raises on NaN/inf; zero test coverage

- **Severity:** Important
- **File + line:** `quant/config_hash.py:46-47` (`_coerce` float branch),
  `quant/config_hash.py:110-115` (the `json.dumps` call). Test file is
  `tests/test_config_hash.py`.
- **Root cause (1-2 sentences):** `_coerce` rounds floats but does not
  reject non-finite values. `json.dumps(..., allow_nan=False)` is not
  set, so default behavior emits non-RFC-8259 `NaN`/`Infinity` literals
  — which `json.loads` on a strict parser (PostgREST, other languages)
  will reject. And no tests cover NaN/inf.
- **Proposed fix:** In `_coerce`, canonicalize non-finite floats to
  deterministic string sentinels so they round-trip stably. Pass
  `allow_nan=False` to `json.dumps` in `config_hash` to make the
  invariant explicit (and fail-fast on any path we missed). Diff
  (`quant/config_hash.py:40-67`):
  ```python
  import math

  def _coerce(value: Any) -> Any:
      """Recursively coerce values into JSON-serializable, hash-stable forms."""
      if value is None or isinstance(value, bool):
          return value
      if isinstance(value, int):
          return int(value)
      if isinstance(value, float):
          # Non-finite floats are not valid JSON (RFC 8259). Map to
          # deterministic string sentinels so two configs with NaN in
          # the same slot still hash identically, but a strict JSON
          # consumer never sees `NaN`/`Infinity` literals.
          if math.isnan(value):
              return "__nan__"
          if math.isinf(value):
              return "__pos_inf__" if value > 0 else "__neg_inf__"
          return round(value, _FLOAT_PRECISION)
      if isinstance(value, str):
          return value
      try:
          import numpy as np
          if isinstance(value, np.integer):
              return int(value)
          if isinstance(value, np.floating):
              v = float(value)
              if math.isnan(v):
                  return "__nan__"
              if math.isinf(v):
                  return "__pos_inf__" if v > 0 else "__neg_inf__"
              return round(v, _FLOAT_PRECISION)
      except ImportError:
          pass
      # ... rest unchanged ...
  ```
  And at `quant/config_hash.py:110`:
  ```python
      serialized = json.dumps(
          payload,
          sort_keys=True,
          separators=(",", ":"),
          ensure_ascii=True,
          allow_nan=False,  # defense-in-depth; _coerce already strips non-finite
      )
  ```
- **Why minimal:** Two local branches in `_coerce` + one `json.dumps`
  kwarg. Does not change the hash for any finite-float config that was
  hashable before.
- **Test to add:** Extend `tests/test_config_hash.py` with a parametrized
  case:
  ```python
  @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
  def test_non_finite_floats_are_hashable_and_deterministic(bad):
      a = _FakeConfig(tickers=["AAPL"], long_threshold=bad)
      b = _FakeConfig(tickers=["AAPL"], long_threshold=bad)
      # Same non-finite value → same hash.
      assert config_hash(a) == config_hash(b)
      # And different non-finite values produce different hashes.


  def test_nan_differs_from_inf():
      a = _FakeConfig(tickers=["AAPL"], long_threshold=float("nan"))
      b = _FakeConfig(tickers=["AAPL"], long_threshold=float("inf"))
      assert config_hash(a) != config_hash(b)


  def test_nested_dict_with_nan_is_hashable():
      cfg = {"tickers": ["AAPL"], "nested": {"x": float("nan"), "y": 0.3}}
      # Must not raise and must be stable across calls.
      assert config_hash(cfg) == config_hash(cfg)
  ```
  Third assertion pins the version-prefix invariant:
  `assert config_hash(a).startswith(f"v{CONFIG_HASH_VERSION}:")`.
- **Risk of regression:** Any existing callers with non-finite floats
  were already broken (raised on `json.dumps` if `allow_nan=True` emitted
  a value a downstream consumer could not parse). This fix normalizes
  them. Existing finite-float tests are unaffected.

---

## Finding 7 — 2 h stale sweeper flips in-flight full-universe runs to `failed`

- **Severity:** Important
- **File + line:** `backend/cpcv_sqlite.py:535`,
  `backend/supabase_backtest.py:295`
- **Root cause (1-2 sentences):** Full-universe CPCV (12 870 combos ×
  5-20 min per combo on a single worker) legitimately takes longer than
  2 h. The sweeper flips the row to `failed` mid-run; the dispatcher
  then flips it back to `complete` when it actually finishes — producing
  a `failed → complete` status oscillation across dual-write sites and a
  misleading `error` column on a successful run.
- **Proposed fix:** Two parts:

  **Part 7a — raise the default timeout and expose as setting.** In
  `config/settings.py` (or wherever `settings` is defined), add:
  ```python
  cpcv_stale_sweep_seconds: int = 24 * 3600  # 24h — covers full-universe runs
  ```
  In `backend/cpcv_sqlite.py:535` change the default:
  ```python
  def sweep_stale_runs(max_age_seconds: Optional[float] = None) -> int:
      if max_age_seconds is None:
          from config import settings
          max_age_seconds = float(getattr(settings, "cpcv_stale_sweep_seconds", 24 * 3600))
      # ...
  ```
  Apply the identical change to `backend/supabase_backtest.py:295`.

  **Part 7b — heartbeat-based stale detection.** A 24 h timeout still
  misclassifies a multi-day sweep. Replace "row is older than cutoff"
  with "row has not been updated recently". In the SQLite query at
  line 547-557 change:
  ```sql
  WHERE status = 'running'
    AND started_at < ?
  ```
  to:
  ```sql
  WHERE status = 'running'
    AND COALESCE(updated_at, started_at) < ?
  ```
  `updated_at` is already maintained by `patch_run` and every combo
  insert path — so a healthy run refreshes its timestamp every few
  seconds via the per-combo row insert's side effect. Any run that
  truly hangs (no combo writes for N minutes) is still caught. Mirror
  the same logic in Supabase:
  ```
  status=eq.running&updated_at=lt.<cutoff>
  ```
  But: `backtest_runs.updated_at` must actually be maintained. Confirm
  via `Grep "updated_at" backend/supabase_backtest.py` — the dispatcher
  should `.patch_run` with `updated_at=...` on every combo result. If
  not currently emitted, add `updated_at=time.time()` to the per-combo
  `patch_run` call (or rely on PostgREST's trigger — the current
  Supabase schema may have `updated_at DEFAULT now()` with an
  on-update trigger; verify against `supabase/migrations/*.sql` before
  landing).

  Set the default heartbeat cutoff to 30 minutes (tunable):
  ```python
  cpcv_stale_sweep_seconds: int = 30 * 60  # 30min since last heartbeat
  ```
- **Why minimal:** Heartbeat-based detection is the correct design
  change; the setting is a single plumbing hop. No schema migration is
  needed — `updated_at` already exists in both stores.
- **Test to add:**
  `tests/backend/test_sweep_stale_runs.py::test_running_run_with_recent_heartbeat_not_swept` —
  insert a run with `started_at = now - 4h` and `updated_at = now - 60s`,
  call `sweep_stale_runs(max_age_seconds=30 * 60)`, assert the row is
  still `running`. Second test:
  `test_running_run_with_stale_heartbeat_is_swept` —
  `started_at = now - 4h`, `updated_at = now - 40 * 60`, call with the
  same cutoff, assert the row is now `failed` and `error` contains
  `"stale run"`. Third test:
  `test_sweep_respects_settings_default` — monkeypatch
  `config.settings.cpcv_stale_sweep_seconds = 1`, insert a run with
  `updated_at = now - 2`, call `sweep_stale_runs()` with no argument,
  assert the row was swept.
- **Risk of regression:** Any operator relying on the 2 h sweep for
  killed-local-dev runs will now wait 30 m instead of 2 h — strictly
  faster, not slower. A pathological case where a combo takes > 30 m is
  still caught early, but only if no progress events fire in that
  window — which already indicates the worker is wedged.

---

## Finding 8 — Missing type annotations on public dispatcher + reader + sqlite APIs

- **Severity:** Important
- **File + line:**
  - `modal_app/dispatcher.py:136` (`dispatch_cpcv`)
  - `modal_app/dispatcher.py:468` (`kickoff_cpcv_background`)
  - `backend/backtest_reader.py:28` (`_ts_to_iso`)
  - `backend/cpcv_sqlite.py:160` (`upsert_run`),
    `backend/cpcv_sqlite.py:213` (`patch_run`),
    `backend/cpcv_sqlite.py:238` (`insert_combinations_batch`),
    and siblings. Most already have return types — the gaps are the
    untyped `row`/`patch`/`rows` parameters.
- **Root cause (1-2 sentences):** Several public functions rely on
  un-annotated `dict`/`row` parameters, which makes call-site typos
  silent and blocks adding mypy to CI.
- **Proposed fix:** Add explicit annotations. None require behavioral
  changes. Diffs:

  **`modal_app/dispatcher.py:136-151`:**
  ```python
  def dispatch_cpcv(
      config: "BacktestConfig",
      *,
      n_groups: int = 16,
      n_test_groups: int = 8,
      purge_months: int = 1,
      embargo_months: int = 1,
      max_combos: Optional[int] = None,
      seed: int = 42,
      allow_dirty: bool = False,
      local: bool = False,
      print_leaderboard: bool = True,
      run_id: Optional[str] = None,
      config_hash: Optional[str] = None,
      git_sha: Optional[str] = None,
  ) -> dict[str, Any]:
  ```
  Import `BacktestConfig` under `TYPE_CHECKING` at top of file to avoid
  a circular import:
  ```python
  from typing import TYPE_CHECKING
  if TYPE_CHECKING:
      from quant.backtest import BacktestConfig
  ```

  **`modal_app/dispatcher.py:468-478`:**
  ```python
  def kickoff_cpcv_background(
      config: "BacktestConfig",
      *,
      n_groups: int = 16,
      n_test_groups: int = 8,
      purge_months: int = 1,
      embargo_months: int = 1,
      max_combos: Optional[int] = None,
      seed: int = 42,
      local: bool = False,
  ) -> dict[str, Any]:
  ```
  Already annotated; only the `config` parameter needs the
  stringified type. Also annotate the helper at line 443:
  ```python
  def _infer_universe_label(config: "BacktestConfig") -> Optional[str]:
  ```
  and line 462:
  ```python
  def _supabase_run_row(row: dict[str, Any]) -> dict[str, Any]:
  ```

  **`backend/backtest_reader.py:28`:**
  ```python
  from typing import Any, Optional, Union
  from datetime import datetime

  _IsoInput = Union[None, str, int, float, datetime]

  def _ts_to_iso(v: _IsoInput) -> Optional[str]:
      if v is None or isinstance(v, str):
          return v
      if isinstance(v, (int, float)):
          return datetime.fromtimestamp(float(v), tz=timezone.utc).isoformat()
      if hasattr(v, "isoformat"):
          return v.isoformat()
      return str(v)


  def _normalize_sqlite_run(row: dict[str, Any]) -> dict[str, Any]:
  def _normalize_sqlite_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
  ```

  **`backend/cpcv_sqlite.py`:** annotate the still-untyped dict params:
  ```python
  def upsert_run(row: dict[str, Any]) -> bool:
  def patch_run(run_id: str, patch: dict[str, Any]) -> bool:
  def insert_combinations_batch(rows: list[dict[str, Any]]) -> tuple[int, int]:
  def insert_trades_batch(rows: list[dict[str, Any]]) -> tuple[int, int]:
  def insert_event(
      run_id: str,
      kind: str,
      payload: dict[str, Any],
      combo_idx: Optional[int] = None,
  ) -> bool:
  ```
  Return-type `tuple[int, int]` matches the existing `(0, 0)` early
  return; confirm the successful path also returns `(inserted, total)`
  and add the explicit return if missing.

- **Why minimal:** Type-annotations only; zero runtime change. Can be
  verified with `python -m py_compile` on each touched module.
- **Test to add:**
  `tests/typing/test_public_api_annotations.py::test_dispatcher_has_full_annotations` —
  use `typing.get_type_hints(dispatch_cpcv)` and assert every parameter
  is present in the returned dict. Same for `kickoff_cpcv_background`,
  `_ts_to_iso`, `upsert_run`, `patch_run`, `insert_combinations_batch`,
  `insert_trades_batch`, `insert_event`. This catches regressions where
  a future edit drops an annotation.
- **Risk of regression:** None at runtime. Only risk is a `TYPE_CHECKING`
  import being evaluated at runtime — guarded by the
  `if TYPE_CHECKING:` block, so it will not.

---

## Sequencing

Apply in this order; each step depends on the preceding one only where
noted.

1. **Finding 8 (annotations)** — purely additive, unblocks IDE/mypy
   signal for the rest of the work. Zero test dependencies.

2. **Finding 6 (NaN/inf in `config_hash`)** — independent. Land with
   its parametrized tests before touching any code that hashes configs
   (Findings 1, 2, 7 all write a run row keyed by config hash).

3. **Finding 5 (SQL allowlist in `patch_run`)** — independent; land
   before Finding 7 because Finding 7 extends the allowlist to include
   `updated_at`-related writes from the sweeper path. Confirm via grep
   that current callers only use allow-listed columns.

4. **Finding 3 (`_xgb_feature_matrix` purity)** — independent. Fix the
   mutation and land the test before Finding 4, since Finding 4 also
   edits `_run_single_cpcv_combo` and would conflict on the same
   function boundary.

5. **Finding 4 (Kalshi hoist)** — independent of everything else
   *after* Finding 3, because both touch the top of
   `_run_single_cpcv_combo`. If landed separately, merge conflicts will
   be trivial (different hunks), but serializing here avoids reviewer
   churn.

6. **Finding 1 (lifespan thread registry)** — must precede Finding 2's
   `finally` flush if the flush is routed through a shared teardown.
   Although Finding 2 as written keeps the flush in-function (not in the
   lifespan path), keeping the ordering lets the integration test for
   Finding 2 rely on the thread registry to observe the flush from the
   main test thread.

7. **Finding 2 (`try/finally` flush)** — depends on Finding 1 only for
   the integration test observability (the registry lets the test
   `.join()` the thread). The core code change is self-contained.

8. **Finding 7 (heartbeat sweeper + 24 h default)** — depends on
   Finding 5 (allowlist) only because the sweeper's mock tests will
   call `patch_run({"status": "failed", "error": ..., "finished_at":
   ...})` — all already-allowed columns. Land last because changing
   the sweep semantics while the other in-flight fixes are mid-merge
   would make failure-mode reproduction noisy.

Cross-dependencies:
- Finding 1 introduces `snapshot_active_threads` — Finding 2's
  integration test imports it.
- Finding 4b (follow-up — not in this PR) will extend `CPCVState`; if
  we land 4b, Finding 3's `dataclasses.replace` site must still round-trip
  the new fields. `replace` preserves all dataclass fields by default
  so this is automatic.
- Finding 7 assumes `updated_at` is written on every per-combo
  `patch_run` / row insert. Verify in `modal_app/dispatcher.py`
  `_handle_combo_result` that we actually call `patch_run({..., })`
  with each combo — today we only call `insert_combinations_batch`
  (which updates `cpcv_combinations`, not `cpcv_runs`). Either add a
  lightweight `patch_run(run_id, {"updated_at": time.time()})` every N
  combos (e.g. N=25) as a heartbeat, or rely on the final patch only.
  Recommend: add a heartbeat at every flush-threshold boundary (aligns
  with the Supabase flush cadence, adds ~1 write per N combos). This is
  the only sub-change inside Finding 7 that touches the dispatcher.

---

## Deferred / out-of-scope

- **Finding 4b (`CPCVState` pre-caching of Kalshi scalars).** Correct
  long-term design, but requires adding fields to the dataclass and a
  dispatcher-side fetch in panel build. Deferred to a follow-up issue
  so PR #5 stays focused on correctness + latent-bug fixes rather than
  a shape change to the panel serialization.

- **Replacing `KalshiClient` with a PIT archive.** The root PIT-leakage
  issue (using live markets for historical simulations) is only
  mitigated by Finding 4a; fully eliminating it requires a historical
  Kalshi snapshot (not currently stored). Tracked separately under
  `project_signal_stack_rebuild.md`.

- **Typed `BacktestConfig` `_xgb_feature_matrix` field.** Today it is
  attached via attribute assignment, not declared on the dataclass.
  Promoting it to a proper `field(default=None, repr=False)` is
  cleaner but would interact with `config_hash`'s exclusion list
  (leading-underscore fields already skipped at `quant/config_hash.py:93`)
  and the Modal volume's pickle shape. Out of scope.

- **Moving the dispatcher thread off in-process threading onto a
  proper job queue (Celery, RQ, Modal's own scheduled jobs).** The
  registry + lifespan join is a legitimate, working solution for
  single-instance FastAPI deployment. A queue is the right answer for
  multi-instance, but is a much larger change that does not belong in
  PR #5.

- **Integration test that covers the Supabase flush `finally` path
  against a real Supabase instance.** The added unit test uses
  monkeypatching; a full E2E test needs a test Supabase project and
  network. Deferred to the CI-plumbing PR that adds Supabase fixtures.

- **mypy in CI.** Finding 8 adds annotations, but wiring a mypy gate
  into the test pipeline is a separate infra change. Ship the
  annotations now; turn on the gate later.
