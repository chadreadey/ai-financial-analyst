# PR #5 General Fix Plan — `modal-backtesting`

Executor: senior engineer, Cursor, or Codex.
Do not re-read the PR. Every line number and snippet below has been verified
against the current tree on branch `modal-backtesting`.

---

## Finding 1 — Deprecated `sentry_sdk.push_scope()` in `_capture_sentry`

- **Severity:** Critical
- **File + line:** `modal_app/dispatcher.py:122-133`
- **Root cause:** `requirements.txt` pins `sentry-sdk[fastapi]>=2.0`. In
  sentry-sdk 2.x `push_scope()` was removed; the replacement is `new_scope()`.
  The current code also calls `capture_message(level="error")` which does not
  attach a stack trace. The bare `except: pass` on line 132 silently swallows
  any import or runtime failure, including the `AttributeError` that sentry-sdk
  2.x raises on `push_scope`, meaning no Sentry event ever fires for failed
  combos.
- **Proposed fix:** Replace the entire `_capture_sentry` helper (lines 122-133)
  and update call site 2 (line 540).

  Helper replacement (`modal_app/dispatcher.py:122-133`):

  ```python
  def _capture_sentry(
      run_id: str,
      config_hash: str,
      combo_idx: Optional[int],
      message: str,
      exc: Optional[BaseException] = None,
  ) -> None:
      """Best-effort Sentry capture with run/combo tags. No-op if sentry uninit."""
      try:
          import sentry_sdk
          with sentry_sdk.new_scope() as scope:
              scope.set_tag("run_id", run_id)
              scope.set_tag("config_hash", config_hash)
              if combo_idx is not None:
                  scope.set_tag("combo_idx", combo_idx)
              if exc is not None:
                  sentry_sdk.capture_exception(exc)
              else:
                  sentry_sdk.capture_message(message, level="error")
      except Exception:  # noqa: BLE001
          pass
  ```

  Call site 1 at line 279 (combo error path inside `_handle_combo_result`):
  no change needed — `exc` defaults to `None` and message-only capture is
  correct because no exception object is in scope there.

  Call site 2 at line 540 (`kickoff_cpcv_background`):

  ```python
  # was:
  _capture_sentry(run_id, cfg_hash, None, f"background dispatch failed: {exc}")

  # becomes:
  _capture_sentry(run_id, cfg_hash, None, f"background dispatch failed: {exc}", exc=exc)
  ```

- **Why minimal:** Two-line change at call site 2; helper rewrite is a
  drop-in replacement with identical signature except the new optional `exc`
  param.
- **Test to add (or manual verification):** Manual only. In a dev shell with
  `SENTRY_DSN` set, trigger a deliberate combo error (patch a worker to return
  `status="error"`), then verify the event appears in the Sentry project with
  `run_id` and `config_hash` tags. For the background dispatch path, raise
  inside `dispatch_cpcv` and confirm the Sentry event includes a stack trace.
  If automated testing is desired, mock `sentry_sdk` in
  `tests/test_dispatcher.py` and assert `capture_exception` is called with the
  exception instance.
- **Risk of regression:** Near-zero. The helper is best-effort; the
  `except: pass` fallback is preserved. The only observable change is that
  Sentry now receives correct events.

---

## Finding 2 — Walk-forward tab not the default on BacktestPage

- **Severity:** Critical
- **File + line:** `frontend/src/pages/BacktestPage.tsx:121`
- **Root cause:** `<Tabs defaultValue="modal">` makes Modal CPCV the active
  tab on page load. Project rule (memory: `feedback_backtest_default.md`)
  states walk-forward is the default view; CPCV is opt-in. The legacy
  (walk-forward) tab is mapped to value `"legacy"`.
- **Proposed fix:**

  Line 121:

  ```tsx
  // was:
  <Tabs defaultValue="modal">

  // becomes:
  <Tabs defaultValue="legacy">
  ```

  Swap tab order in `TabsList` (lines 123-125) so the active tab appears first:

  ```tsx
  // was:
  <TabsTrigger value="modal">Modal CPCV</TabsTrigger>
  <TabsTrigger value="legacy">Legacy (in-process)</TabsTrigger>

  // becomes:
  <TabsTrigger value="legacy">Walk-Forward</TabsTrigger>
  <TabsTrigger value="modal">Modal CPCV</TabsTrigger>
  ```

  The label rename to "Walk-Forward" matches project terminology. If the
  rename is out of scope, at minimum flip `defaultValue` and swap tab order.

- **Why minimal:** Single attribute change. Tab order swap is three lines. No
  state or hook changes required.
- **Test to add (or manual verification):** Load `/backtest` in a browser and
  confirm the walk-forward panel is visible without any clicks. Automated: add
  a Vitest/RTL test in `frontend/src/pages/__tests__/BacktestPage.test.tsx`
  that renders the page and asserts the active tabpanel contains legacy
  content, not `ModalRunsPanel`.
- **Risk of regression:** None. The Modal CPCV tab still exists and functions
  unchanged.

---

## Finding 3 — Router endpoints have no TestClient coverage

- **Severity:** Important
- **File + line:** `backend/routers/backtest_modal.py` — no corresponding test
  file exists anywhere in the tree
- **Root cause:** The PR description claims "every FastAPI GET exercised via
  TestClient." No test file for `backtest_modal` exists. The router exposes
  7 GETs and 1 POST. Missing coverage means regressions in path parameters,
  query validation, and 404 handling are invisible.
- **Proposed fix:** Create `tests/routers/test_backtest_modal.py`:

  ```python
  # tests/routers/test_backtest_modal.py
  """TestClient coverage for backend/routers/backtest_modal.py."""
  from __future__ import annotations

  import pytest
  from fastapi.testclient import TestClient
  from unittest.mock import MagicMock

  FAKE_RUN = {
      "run_id": "abc123", "config_hash": "hash1", "git_sha": "deadbeef",
      "status": "complete", "n_combinations": 10, "n_completed": 10,
      "n_failed": 0, "n_skipped": 0,
  }
  FAKE_COMBO = {"run_id": "abc123", "combo_idx": 0, "oos_sharpe": 1.2, "status": "complete"}
  FAKE_TRADE = {"run_id": "abc123", "combo_idx": 0, "ticker": "AAPL", "pnl_pct": 0.05}
  FAKE_EVENT = {"id": 1, "run_id": "abc123", "event_type": "run_started"}


  @pytest.fixture()
  def client():
      from backend.main import app  # adjust if entrypoint differs
      return TestClient(app)


  @pytest.fixture(autouse=True)
  def mock_reader(monkeypatch):
      import backend.backtest_reader as reader
      monkeypatch.setattr(reader, "source", lambda: "sqlite")
      monkeypatch.setattr(reader, "list_runs", lambda **kw: [FAKE_RUN])
      monkeypatch.setattr(reader, "get_run",
                          lambda run_id: FAKE_RUN if run_id == "abc123" else None)
      monkeypatch.setattr(reader, "find_runs_by_config_hash", lambda h, **kw: [FAKE_RUN])
      monkeypatch.setattr(reader, "get_combinations", lambda run_id, **kw: [FAKE_COMBO])
      monkeypatch.setattr(reader, "get_trades", lambda run_id, **kw: [FAKE_TRADE])
      monkeypatch.setattr(reader, "get_events", lambda run_id, **kw: [FAKE_EVENT])


  def test_source(client):
      r = client.get("/backtest/modal/source")
      assert r.status_code == 200
      assert r.json()["source"] == "sqlite"

  def test_list_runs_default(client):
      r = client.get("/backtest/modal/runs")
      assert r.status_code == 200
      assert r.json()["count"] == 1

  def test_list_runs_status_filter(client):
      r = client.get("/backtest/modal/runs?status=complete")
      assert r.status_code == 200

  def test_list_runs_invalid_status(client):
      r = client.get("/backtest/modal/runs?status=bogus")
      assert r.status_code == 422

  def test_get_run_found(client):
      r = client.get("/backtest/modal/runs/abc123")
      assert r.status_code == 200
      assert r.json()["run_id"] == "abc123"

  def test_get_run_not_found(client):
      r = client.get("/backtest/modal/runs/doesnotexist")
      assert r.status_code == 404

  def test_runs_by_config_hash(client):
      r = client.get("/backtest/modal/runs/by-config-hash/hash1")
      assert r.status_code == 200
      assert r.json()["count"] == 1

  def test_get_combinations(client):
      r = client.get("/backtest/modal/runs/abc123/combinations")
      assert r.status_code == 200
      assert r.json()["count"] == 1

  def test_get_combinations_invalid_order_by(client):
      r = client.get("/backtest/modal/runs/abc123/combinations?order_by=evil")
      assert r.status_code == 422

  def test_get_combo_trades(client):
      r = client.get("/backtest/modal/runs/abc123/combinations/0/trades")
      assert r.status_code == 200

  def test_get_run_trades(client):
      r = client.get("/backtest/modal/runs/abc123/trades")
      assert r.status_code == 200

  def test_get_events(client):
      r = client.get("/backtest/modal/runs/abc123/events")
      assert r.status_code == 200
      assert r.json()["count"] == 1

  def test_dispatch_modal_missing_tickers_and_universe(client):
      r = client.post("/backtest/modal", json={})
      assert r.status_code == 400

  def test_dispatch_modal_success(client, monkeypatch):
      import modal_app.dispatcher as disp
      monkeypatch.setattr(
          disp, "kickoff_cpcv_background",
          lambda config, **kw: {
              "run_id": "newrun1", "config_hash": "h2",
              "git_sha": "sha1", "status": "queued",
          },
      )
      r = client.post("/backtest/modal", json={"universe": "liquid_10"})
      assert r.status_code == 200
      assert r.json()["run_id"] == "newrun1"
  ```

- **Why minimal:** Purely in-process via TestClient with monkeypatched reader;
  no Modal or Supabase credentials required in CI.
- **Test to add:** `tests/routers/test_backtest_modal.py` — this finding IS
  the test file.
- **Risk of regression:** None — additive.

---

## Finding 4 — Dual-write partial-failure path is untested

- **Severity:** Important
- **File + line:** `modal_app/dispatcher.py:200-201` and `246-247`
- **Root cause:** If `supabase_backtest.upsert_run` raises after
  `cpcv_sqlite.upsert_run` succeeds, the run row exists in SQLite but not
  Supabase. Reads from the Supabase-preferred path return 404 while the run
  is executing. No test covers this and there is no recovery logic.
- **Proposed fix:** Create `tests/test_dispatcher_partial_failure.py`:

  ```python
  # tests/test_dispatcher_partial_failure.py
  """Verify SQLite write survives a Supabase upsert_run failure."""
  from unittest.mock import MagicMock
  import pytest


  def test_queued_row_persists_when_supabase_upsert_fails(tmp_path, monkeypatch):
      import backend.cpcv_sqlite as sqlite_mod
      import backend.supabase_backtest as supa_mod

      monkeypatch.setattr(sqlite_mod, "_DB_PATH", str(tmp_path / "test.db"))
      sqlite_mod._init_db()

      monkeypatch.setattr(
          supa_mod, "upsert_run", MagicMock(side_effect=RuntimeError("timeout"))
      )
      monkeypatch.setattr(supa_mod, "is_enabled", lambda: True)

      from quant.backtest import BacktestConfig
      from modal_app.dispatcher import dispatch_cpcv

      config = BacktestConfig(
          tickers=["AAPL"], start_date="2022-01-01", end_date="2022-06-01"
      )

      with pytest.raises(Exception):
          dispatch_cpcv(config, local=True, max_combos=1)

      rows = sqlite_mod.list_runs(limit=1)
      assert len(rows) >= 1, "SQLite queued row was not written before Supabase error"
  ```

  This test is a minimum-viable regression guard. Full recovery logic (retry
  queue, divergence alerting) belongs in the DB reviewer's DLQ plan.

- **Why minimal:** Patches two module-level functions; no network or Modal
  calls.
- **Test to add:** `tests/test_dispatcher_partial_failure.py`.
- **Risk of regression:** None — additive.

---

## Finding 5 — `modal_runner.py` deletion status

- **Severity:** Important (resolved)
- **File + line:** `.cursor/plans/modal-backtesting.md:281`
- **Root cause:** The plan specified `git rm modal_runner.py`. A glob search
  of the current tree confirms the file does not exist. Finding closed — no
  action required. Retained to prevent re-raising in future reviews.
- **Proposed fix:** None.
- **Risk of regression:** None.

---

## Finding 6 — `modal_trade_snapshot_top_n` declared but never read

- **Severity:** Important
- **File + line:** `config.py:153`
- **Root cause:** The setting was added alongside `modal_backtest_flush_combos`
  but is never imported or referenced anywhere in the codebase (grep over all
  `.py` files confirms zero read sites). Dead config misleads future engineers.
- **Proposed fix (option A — delete, preferred):**

  Remove lines 149-153 from `config.py`:

  ```python
  # DELETE these 5 lines:
  #
  #    # Only persist full SignalVector snapshots for trades in this many top/
  #    # bottom combos by OOS Sharpe (None = every combo). Lets big sweeps keep
  #    # detailed attribution for the interesting combos without ballooning
  #    # the trade table to 100k+ rows of JSONB.
  #    modal_trade_snapshot_top_n: int = 0  # 0 = snapshot all
  ```

  The current value (0 = snapshot all) is identical to not having the filter,
  so deletion has zero runtime impact.

  **Option B (stub with TODO, if deletion is rejected):**

  ```python
  # TODO(#<issue>): wire into _handle_combo_result — filter trade JSONB
  # snapshots to top/bottom N combos by OOS Sharpe before Supabase insert.
  modal_trade_snapshot_top_n: int = 0  # 0 = snapshot all
  ```

  Option A is strongly preferred.

- **Why minimal:** One field deletion in one config class; no callers to
  update.
- **Test to add:** None.
- **Risk of regression:** None.

---

## Finding 7 — Restatement comments that should be deleted

- **Severity:** Important
- **File + line:** `modal_app/dispatcher.py:245`, `304`, `368`
- **Root cause:** These comments restate what the adjacent code already says
  rather than explaining why.
- **Proposed fix:** Delete only these three comment lines:

  - Line 245: `# Flip status to running now that combos are resolved. Update n_combinations.`
    The two `patch_run` calls with `"status": "running"` are self-documenting.
  - Line 304: `# Flush buffered combo rows to Supabase when threshold reached.`
    The `if len(...) >= flush_size` guard is self-evident.
  - Line 368: `# Final flush of buffered combos to Supabase.`
    Same as 304.

  Line 187 (`# Persist 'queued' row before panel build so crashes are
  observable.`) explains a non-obvious ordering invariant — keep it.

  For `quant/backtest.py:3260-3263`: apply the same criterion. Those lines
  were not re-read in this pass; verify before touching.

- **Why minimal:** Comment-only deletions; no logic change.
- **Test to add:** None.
- **Risk of regression:** None.

---

## Finding 8 — `backtest_reader.py` has no error handling; raw tracebacks surface as 500

- **Severity:** Important
- **File + line:** `backend/backtest_reader.py:71-156` — all six public
  functions
- **Root cause:** Each function calls `supabase_backtest.*` or `cpcv_sqlite.*`
  without a try/except. A Supabase network timeout or SQLite locked-file error
  propagates as an unhandled exception, returning a raw 500 with a Python
  traceback. There is also no fallback from Supabase to SQLite on error — only
  on a `None` return.
- **Proposed fix:** Add `import logging` and `logger = logging.getLogger(__name__)`
  at the top of `backend/backtest_reader.py` (currently absent). Wrap the
  Supabase call in each of the six read functions. Pattern for `list_runs`:

  ```python
  # Add near top of backend/backtest_reader.py:
  import logging
  logger = logging.getLogger(__name__)

  # list_runs body replacement:
  def list_runs(status=None, config_hash=None, limit=50, offset=0) -> list[dict]:
      if supabase_backtest.is_enabled():
          try:
              r = supabase_backtest.list_runs(
                  status=status, config_hash=config_hash, limit=limit, offset=offset
              )
              if r is not None:
                  return r
          except Exception:
              logger.warning(
                  "supabase list_runs failed, falling back to SQLite", exc_info=True
              )
      return _normalize_sqlite_rows(
          cpcv_sqlite.list_runs(
              status=status, config_hash=config_hash, limit=limit, offset=offset
          )
      )
  ```

  Apply the same two-line `try/except` wrapper to: `get_run`,
  `find_runs_by_config_hash`, `get_combinations`, `get_trades`, `get_events`.
  The SQLite call itself is allowed to raise (correct when the local DB is
  corrupted).

- **Why minimal:** The `try/except` is a narrow wrapper; the fallback logic
  already exists. Six functions, same two-line wrapper each.
- **Test to add:** Add to `tests/routers/test_backtest_modal.py`:

  ```python
  def test_list_runs_supabase_error_falls_back(monkeypatch):
      import backend.backtest_reader as reader
      import backend.supabase_backtest as supa
      import backend.cpcv_sqlite as sqlite_mod
      from unittest.mock import MagicMock

      monkeypatch.setattr(supa, "is_enabled", lambda: True)
      monkeypatch.setattr(supa, "list_runs", MagicMock(side_effect=RuntimeError("timeout")))
      monkeypatch.setattr(sqlite_mod, "list_runs", lambda **kw: [FAKE_RUN])

      result = reader.list_runs()
      assert result == [FAKE_RUN], "Should return SQLite rows on Supabase failure"
  ```

- **Risk of regression:** Low. The `try/except` fires only on Supabase error;
  the happy path is unchanged.

---

## Sequencing

Execute in this order to minimise conflicts:

1. Finding 1 — `_capture_sentry` rewrite. Isolated; do first so Sentry is
   reliable before any test runs.
2. Finding 2 — `defaultValue="legacy"` flip. Standalone UI change.
3. Finding 8 — `backtest_reader.py` error handling. Do before router tests.
4. Finding 3 — Router TestClient tests. Depends on Finding 8.
5. Finding 4 — Dual-write partial failure test. Additive; do after Finding 3.
6. Findings 6 and 7 — Config deletion and comment cleanup. Batch together.
7. Finding 5 — Already resolved; skip.

---

## Cross-refs

- Finding 4 overlaps with the DB reviewer's DLQ plan. The test here is a
  regression guard only. Recovery logic belongs in that plan and must not be
  implemented here.
- Finding 1 (`new_scope`) may interact with any `finally:` buffer-flush
  changes from the Python reviewer. The `except Exception: pass` wrapper
  ensures no exception suppression regardless.
- Finding 2 is a standalone UI flip with no backend interaction.

---

## Deferred / Out-of-Scope

Considered but excluded at less than 80% confidence or determined out of scope:

- `quant/backtest.py:3260-3263` comment cleanup — those lines were not
  re-read in this pass. Apply the Finding 7 criterion in a separate pass.
- `_run_single_cpcv_combo` numerical parity test — requires a non-trivial
  fixture. Deferred to a dedicated testing sprint.
- `backtest_reader.py` unbounded queries — the router enforces `le=500` via
  `Query`, so the exposure is bounded. Not critical for this PR.
- `TradeDetailRow` index key (`BacktestPage.tsx:230`, `key={i}`) — the trade
  list is read-only and never reordered, making this a pattern violation
  rather than a bug. Deferred.
