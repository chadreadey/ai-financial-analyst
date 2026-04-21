# PR #5 Database Fix Plan — modal-backtesting

Branch: `modal-backtesting`
Reviewer: Database layer
Date: 2026-04-21

This document is self-contained. Execute findings in the **Sequencing** order at the bottom.
Do not edit `supabase/migrations/0001_backtest_tables.sql` — it is already applied. All schema
changes go in `supabase/migrations/0002_backtest_indexes_rls.sql`.

---

## Finding 1 — Events cursor returns ambiguous IDs across sources

- **Severity:** Critical
- **File + line(s):**
  - `backend/backtest_reader.py:134-145` (facade — `get_events`)
  - `backend/supabase_backtest.py:333-346` (Supabase read)
  - `backend/cpcv_sqlite.py:517-532` (SQLite read)
- **Root cause:** `backtest_events.id` is `BIGSERIAL` in Supabase and `AUTOINCREMENT` in SQLite.
  Both sequences start at 1 and are independent. The consumer passes `after_id` as a bare integer.
  When Supabase is temporarily unreachable and the facade silently falls back to SQLite (or vice
  versa on the first request after a reconnect), the `after_id` value is valid in the old store
  and meaningless — or worse, matches a different event — in the new store. Events are silently
  skipped or duplicated with no indication of the switch.
- **Proposed fix:**

  Change `get_events` in `backend/backtest_reader.py` to return a wrapper dict instead of a bare
  list. The wrapper adds a `source` field so the caller knows which backend served the response and
  can detect a source switch.

  **Before (`backend/backtest_reader.py:134-145`):**
  ```python
  def get_events(
      run_id: str,
      after_id: Optional[int] = None,
      limit: int = 200,
  ) -> list[dict]:
      if supabase_backtest.is_enabled():
          r = supabase_backtest.get_events(run_id, after_id=after_id, limit=limit)
          if r is not None:
              return r
      return _normalize_sqlite_rows(cpcv_sqlite.get_events(
          run_id, after_id=after_id, limit=limit,
      ))
  ```

  **After (`backend/backtest_reader.py:134-155`, replace the function):**
  ```python
  def get_events(
      run_id: str,
      after_id: Optional[int] = None,
      limit: int = 200,
  ) -> dict:
      """Returns {"source": "supabase"|"sqlite", "events": list[dict]}.

      Callers must reset after_id to None whenever source changes between
      consecutive polls.
      """
      if supabase_backtest.is_enabled():
          r = supabase_backtest.get_events(run_id, after_id=after_id, limit=limit)
          if r is not None:
              return {"source": "supabase", "events": r}
      rows = _normalize_sqlite_rows(
          cpcv_sqlite.get_events(run_id, after_id=after_id, limit=limit)
      )
      return {"source": "sqlite", "events": rows}
  ```

  HTTP response shape (FastAPI router, wherever `get_events` is called — update callers to read
  `result["events"]` and surface `result["source"]` in the SSE or JSON response):
  ```json
  {
    "source": "supabase",
    "events": [
      {"id": 42, "run_id": "...", "kind": "combo_completed", ...}
    ]
  }
  ```

  The frontend (TypeScript — out of scope here) must compare `source` on successive polls and reset
  `after_id` to `null` when it changes. See Cross-refs.

- **Why minimal:** Only the facade signature changes; both store implementations are untouched.
- **Test / verification:**
  File: `tests/test_backtest_reader.py`, function: `test_get_events_returns_source_tag`
  ```python
  def test_get_events_returns_source_tag(monkeypatch):
      monkeypatch.setattr("backend.supabase_backtest.is_enabled", lambda: False)
      # seed one event into sqlite
      from backend import cpcv_sqlite
      cpcv_sqlite.insert_event({"run_id": "r1", "kind": "run_started",
                                 "created_at": 1.0})
      from backend import backtest_reader
      result = backtest_reader.get_events("r1")
      assert result["source"] == "sqlite"
      assert isinstance(result["events"], list)
      assert result["events"][0]["kind"] == "run_started"

  def test_get_events_source_switches_when_supabase_enabled(monkeypatch):
      monkeypatch.setattr("backend.supabase_backtest.is_enabled", lambda: True)
      monkeypatch.setattr(
          "backend.supabase_backtest.get_events",
          lambda run_id, after_id, limit: [{"id": 1, "kind": "run_started"}],
      )
      from backend import backtest_reader
      result = backtest_reader.get_events("r1")
      assert result["source"] == "supabase"
  ```
- **Risk of regression:** None to the database layer. The only regression surface is any existing
  caller that treated the return value as a bare list — those callers will `TypeError` at runtime
  instead of silently misbehaving, which is the desired failure mode.
- **Migration ordering:** No schema change. Deploy code change only. Zero-downtime.

---

## Finding 2 — `select=*` on trade rows causes OOM / timeout on large runs

- **Severity:** Critical
- **File + line(s):**
  - `backend/supabase_backtest.py:229` (`list_runs`)
  - `backend/supabase_backtest.py:242` (`get_run`)
  - `backend/supabase_backtest.py:264` (`get_combinations`)
  - `backend/supabase_backtest.py:283` (`get_trades`)
  - `backend/supabase_backtest.py:340` (`get_events`)
- **Root cause:** Every PostgREST GET uses `select=*`. `backtest_trades` includes
  `signals_at_entry_json` (JSONB, potentially several KB per row). A run with 252 combinations
  and 200 trades each = 50 400 trade rows. With `select=*` the full `signals_at_entry_json`
  column is pulled on every trade list call, putting several hundred MB of JSON through the
  Python process and over the wire.
- **Proposed fix:**

  Define explicit column lists at the top of `backend/supabase_backtest.py` and substitute them
  for every `select=*`. Add a `get_trade_detail` function for single-trade drill-down that
  includes `signals_at_entry_json`.

  **Add near line 35 in `backend/supabase_backtest.py` (after `_HTTP_TIMEOUT`):**
  ```python
  # Explicit column projections — never use select=* in bulk reads.
  _RUNS_COLS = (
      "run_id,config_hash,git_sha,status,universe,"
      "n_groups,n_test_groups,n_combinations,"
      "n_completed,n_skipped,n_failed,"
      "median_oos_sharpe,oos_sharpe_min,oos_sharpe_max,"
      "pbo,deflated_sharpe,config_json,metrics_json,"
      "error,modal_call_id,started_at,finished_at,updated_at"
  )
  _COMBO_COLS = (
      "run_id,combo_idx,status,train_indices,test_indices,"
      "oos_sharpe,return_pct,n_trades,n_test_dates,"
      "elapsed_seconds,git_sha,error,gates_json,created_at"
  )
  # signals_at_entry_json intentionally excluded — use get_trade_detail for drill-down.
  _TRADE_COLS_LIST = (
      "run_id,combo_idx,trade_idx,ticker,direction,"
      "entry_date,exit_date,entry_price,exit_price,"
      "pnl_dollar,pnl_pct,holding_days,exit_reason,"
      "composite_score,regime_at_entry,flags_json,created_at"
  )
  _TRADE_COLS_DETAIL = _TRADE_COLS_LIST + ",signals_at_entry_json"
  _EVENT_COLS = "id,run_id,kind,combo_idx,payload,created_at"
  ```

  **Patch each read function to replace `"select": "*"` with the appropriate constant:**

  `list_runs` (line 229): `"select": _RUNS_COLS`
  `get_run` (line 242): `"select": _RUNS_COLS`
  `get_combinations` (line 264): `"select": _COMBO_COLS`
  `get_trades` (line 283): `"select": _TRADE_COLS_LIST`
  `get_events` (line 340): `"select": _EVENT_COLS`

  **Add a new `get_trade_detail` function after `get_trades`:**
  ```python
  def get_trade_detail(
      run_id: str,
      combo_idx: int,
      trade_idx: int,
  ) -> Optional[dict]:
      """Single-trade fetch including signals_at_entry_json for drill-down UI."""
      rows = _get(
          "backtest_trades",
          {
              "run_id": f"eq.{run_id}",
              "combo_idx": f"eq.{combo_idx}",
              "trade_idx": f"eq.{trade_idx}",
              "select": _TRADE_COLS_DETAIL,
              "limit": 1,
          },
      )
      if rows is None:
          return None
      return rows[0] if rows else None
  ```

  Export `get_trade_detail` in `__all__`.

- **Why minimal:** Column constants are defined once; each call site is a one-word substitution.
- **Test / verification:**
  File: `tests/test_supabase_backtest.py`, function: `test_get_trades_excludes_signals_column`
  ```python
  def test_get_trades_excludes_signals_column(monkeypatch):
      captured = {}
      def fake_get(path, params=None):
          captured["select"] = (params or {}).get("select", "")
          return []
      monkeypatch.setattr("backend.supabase_backtest._get", fake_get)
      from backend import supabase_backtest
      supabase_backtest.get_trades("r1")
      assert "signals_at_entry_json" not in captured["select"]

  def test_get_trade_detail_includes_signals_column(monkeypatch):
      captured = {}
      def fake_get(path, params=None):
          captured["select"] = (params or {}).get("select", "")
          return []
      monkeypatch.setattr("backend.supabase_backtest._get", fake_get)
      from backend import supabase_backtest
      supabase_backtest.get_trade_detail("r1", 0, 0)
      assert "signals_at_entry_json" in captured["select"]
  ```
- **Risk of regression:** Any caller that reads `signals_at_entry_json` from the `get_trades`
  response will now get `None` / missing key. Audit callers of `backtest_reader.get_trades` and
  `supabase_backtest.get_trades` before deploying. The trade-off is intentional: read amplification
  (a second request for drill-down) is better than OOM on list queries.
- **Migration ordering:** No schema change. Code deploy only. Zero-downtime.

---

## Finding 3 — `backtest_events` cursor index missing on both stores

- **Severity:** Critical
- **File + line(s):**
  - `supabase/migrations/0001_backtest_tables.sql:144-145` (Supabase index)
  - `backend/cpcv_sqlite.py:133-134` (SQLite index)
- **Root cause:** The existing index on `backtest_events` / `cpcv_events` is
  `(run_id, created_at)`. The cursor query for the event stream is:
  ```sql
  WHERE run_id = ? AND id > ? ORDER BY id ASC
  ```
  The `id` column is not covered by the index. Every poll tick with `after_id` set triggers
  an index scan on `(run_id, created_at)` followed by a filesort on `id`. As a run accumulates
  thousands of events this becomes the dominant latency in the live-progress UI.
- **Proposed fix:**

  **Supabase — add to `supabase/migrations/0002_backtest_indexes_rls.sql`:**
  ```sql
  -- Fix event cursor index: replace (run_id, created_at) with (run_id, id).
  -- The old index on created_at is unused by the polling query.
  DROP INDEX IF EXISTS idx_backtest_events_run_time;
  CREATE INDEX IF NOT EXISTS idx_backtest_events_run_id
      ON backtest_events (run_id, id);
  ```

  **SQLite — in `backend/cpcv_sqlite.py` inside `_ensure_schema`, replace lines 133-134:**

  Before:
  ```python
  CREATE INDEX IF NOT EXISTS idx_cpcv_events_run_time
      ON cpcv_events (run_id, created_at);
  ```

  After:
  ```python
  CREATE INDEX IF NOT EXISTS idx_cpcv_events_run_id
      ON cpcv_events (run_id, id);
  ```

  Note: existing SQLite databases with the old index will keep `idx_cpcv_events_run_time`
  alongside the new one until the table is dropped and recreated. The old index is harmless (small
  table during dev) but wastes a small amount of write overhead. A one-time migration script is not
  warranted — the dev database can be wiped; production uses Supabase.

- **Why minimal:** One DDL statement per store; the query shape does not change.
- **Test / verification:**
  Run against a seeded SQLite file:
  ```sql
  EXPLAIN QUERY PLAN
  SELECT id, run_id, kind, combo_idx, payload, created_at
    FROM cpcv_events
   WHERE run_id = 'r1' AND id > 5
   ORDER BY id ASC
   LIMIT 200;
  ```
  Expected: `SEARCH cpcv_events USING INDEX idx_cpcv_events_run_id (run_id=? AND id>?)`.
  Before the fix it shows `SCAN` or `USE TEMP B-TREE FOR ORDER BY`.

  For Supabase:
  ```sql
  EXPLAIN (ANALYZE, BUFFERS)
  SELECT id, run_id, kind, combo_idx, payload, created_at
    FROM backtest_events
   WHERE run_id = 'some_run_id' AND id > 100
   ORDER BY id ASC
   LIMIT 200;
  ```
  Expected: `Index Scan using idx_backtest_events_run_id`.

- **Risk of regression:** Write amplification increases by one index entry per insert into
  `backtest_events`. Events are low-frequency (one per combo completion), so this is negligible.
  The old `(run_id, created_at)` index is dropped on Supabase; if any unreported query filters by
  `created_at` range it will fall back to seq scan. Confirm no such query exists before deploying.
- **Migration ordering:** Schema change. Apply `0002_*.sql` to Supabase before deploying the
  SQLite `_ensure_schema` change (the SQLite change only affects new databases). Zero-downtime —
  `CREATE INDEX` on Supabase can be done with `CONCURRENTLY` if the table is large enough to
  matter; at current data volumes a plain `CREATE INDEX` during off-hours is acceptable.

---

## Finding 4 — Dual-write partial failures silently swallowed

- **Severity:** Important
- **File + line(s):**
  - `backend/supabase_backtest.py:76-78` (`_post` exception handler)
  - `backend/cpcv_sqlite.py:208-210` (`upsert_run` exception handler)
  - `modal_app/dispatcher.py:294-295` (trade dual-write, no failure check)
  - `modal_app/dispatcher.py:306-307` (combo flush, no failure check)
- **Root cause:** Both `_post` and the SQLite write functions catch all exceptions and return
  `False` / log a warning. The dispatcher discards the return value from
  `supabase_backtest.insert_trades_batch` and `insert_combinations_batch` at the flush site.
  A transient network error or Supabase 503 silently drops entire combo or trade batches with no
  recovery path.
- **Proposed fix:**

  Add an append-only JSONL dead-letter file for failed Supabase batches. This is a backend-side
  durability shim, not a full outbox pattern.

  **Add to `backend/supabase_backtest.py` after `_HTTP_TIMEOUT`:**
  ```python
  import os
  import pathlib

  _FAILED_BATCH_LOG = pathlib.Path(
      os.environ.get("SUPABASE_FAILED_BATCH_LOG", "/tmp/supabase_failed_batches.jsonl")
  )

  def _append_failed_batch(table: str, rows: list[dict]) -> None:
      """Append a failed batch to a local JSONL for manual replay."""
      try:
          with _FAILED_BATCH_LOG.open("a") as fh:
              fh.write(json.dumps({"table": table, "rows": rows,
                                   "ts": datetime.now(timezone.utc).isoformat()},
                                  default=_json_default) + "\n")
      except Exception as exc:
          logger.error("Could not write failed batch to %s: %s", _FAILED_BATCH_LOG, exc)
  ```

  **Patch `_post` to call `_append_failed_batch` on failure (lines 76-78):**

  Before:
  ```python
  except Exception as exc:  # noqa: BLE001
      logger.warning("supabase POST %s failed (%d rows): %s", table, len(rows), exc)
      return False
  ```

  After:
  ```python
  except Exception as exc:  # noqa: BLE001
      logger.warning("supabase POST %s failed (%d rows): %s", table, len(rows), exc)
      _append_failed_batch(table, rows)
      return False
  ```

  **Patch dispatcher call sites to log non-zero failure counts:**

  In `modal_app/dispatcher.py` around line 295, change:
  ```python
  cpcv_sqlite.insert_trades_batch(trade_rows)
  supabase_backtest.insert_trades_batch(trade_rows)
  ```
  to:
  ```python
  cpcv_sqlite.insert_trades_batch(trade_rows)
  _sb_inserted, _sb_failed = supabase_backtest.insert_trades_batch(trade_rows)
  if _sb_failed:
      logger.warning(
          "supabase trade write partial failure: run=%s combo=%s failed=%d",
          run_id, combo_idx, _sb_failed,
      )
  ```

  Apply the same pattern to the combo flush at line 306.

- **Why minimal:** The JSONL file requires no new infrastructure and is readable by any replay
  script. The dispatcher change adds two lines per write site.
- **Test / verification:**
  File: `tests/test_supabase_backtest.py`, function: `test_failed_post_appends_to_jsonl`
  ```python
  import json, pathlib, tempfile
  def test_failed_post_appends_to_jsonl(monkeypatch, tmp_path):
      log_file = tmp_path / "failed.jsonl"
      monkeypatch.setenv("SUPABASE_FAILED_BATCH_LOG", str(log_file))
      # Force reload so the module picks up the new env var.
      import importlib, backend.supabase_backtest as sb
      importlib.reload(sb)
      monkeypatch.setattr("backend.supabase_backtest.is_enabled", lambda: True)
      # Make urlopen raise to simulate network failure.
      import urllib.request
      monkeypatch.setattr(urllib.request, "urlopen",
                          lambda *a, **kw: (_ for _ in ()).throw(OSError("timeout")))
      sb._post("backtest_trades", [{"run_id": "r1", "trade_idx": 0}])
      lines = log_file.read_text().strip().splitlines()
      assert len(lines) == 1
      entry = json.loads(lines[0])
      assert entry["table"] == "backtest_trades"
      assert entry["rows"][0]["run_id"] == "r1"
  ```
- **Risk of regression:** `_append_failed_batch` runs on every Supabase write failure. If the
  filesystem is full or `/tmp` is read-only in the Modal container, it logs an error and continues —
  the original failure path is unchanged. No write-amplification to the database.
- **Migration ordering:** No schema change. Code deploy only. Zero-downtime.

---

## Finding 5 — Schema drift: `train_indices_json` / `test_indices_json` not normalised in all callers

- **Severity:** Important
- **File + line(s):**
  - `backend/backtest_reader.py:44-52` (`_normalize_sqlite_run`)
  - `backend/cpcv_sqlite.py:385-389` (`_COMBO_COLS`, column list used by `get_combinations`)
- **Root cause:** SQLite `cpcv_combinations` stores `train_indices_json TEXT` and
  `test_indices_json TEXT`. Supabase stores `train_indices INTEGER[]` and `test_indices INTEGER[]`.
  `_normalize_sqlite_run` in `backtest_reader.py` renames these keys when it processes rows that
  came through `get_combinations`. However, direct callers of `cpcv_sqlite.get_combinations` (e.g.
  a future CLI tool or test helper) receive the `_json`-suffixed names and the frontend will see
  `null` for `train_indices` / `test_indices` on any code path that bypasses the reader facade.
- **Proposed fix:**

  Normalise column names inside `cpcv_sqlite._row_to_dict` rather than in the facade layer.
  The facade normalisation in `_normalize_sqlite_run` should then become a no-op for these columns
  (keep it for safety, but the primary fix lives at the source).

  **Patch `_row_to_dict` in `backend/cpcv_sqlite.py` (after line 416, inside the function):**

  Before:
  ```python
  def _row_to_dict(row: sqlite3.Row, json_cols: set[str]) -> dict:
      out = dict(row)
      for col in json_cols & out.keys():
          v = out[col]
          if isinstance(v, str) and v:
              try:
                  out[col] = json.loads(v)
              except Exception:
                  pass
      return out
  ```

  After:
  ```python
  # Map SQLite _json suffix column names to their Supabase equivalents so
  # all callers (not just the reader facade) get consistent key names.
  _SQLITE_COL_ALIASES = {
      "train_indices_json": "train_indices",
      "test_indices_json": "test_indices",
  }

  def _row_to_dict(row: sqlite3.Row, json_cols: set[str]) -> dict:
      out = dict(row)
      for col in json_cols & out.keys():
          v = out[col]
          if isinstance(v, str) and v:
              try:
                  out[col] = json.loads(v)
              except Exception:
                  pass
      # Rename _json-suffixed cols to match Supabase column names.
      for old, new in _SQLITE_COL_ALIASES.items():
          if old in out:
              out[new] = out.pop(old)
      return out
  ```

  Also update `_JSON_COMBO_COLS` in `cpcv_sqlite.py` so that `json.loads` is still applied
  before the rename:
  ```python
  # Before:
  _JSON_COMBO_COLS = {"train_indices_json", "test_indices_json", "gates_json"}
  # After (unchanged — renaming happens after parsing):
  _JSON_COMBO_COLS = {"train_indices_json", "test_indices_json", "gates_json"}
  ```
  No change needed to `_JSON_COMBO_COLS`; the rename step happens after JSON parsing.

- **Why minimal:** One dict and one loop added to `_row_to_dict`; no schema change required.
- **Test / verification:**
  File: `tests/test_cpcv_sqlite.py`, function: `test_get_combinations_normalises_index_columns`
  ```python
  def test_get_combinations_normalises_index_columns(tmp_path, monkeypatch):
      monkeypatch.setenv("WAREHOUSE_DB_PATH", str(tmp_path / "test.db"))
      from backend import cpcv_sqlite
      cpcv_sqlite._SCHEMA_READY = False  # force re-init
      cpcv_sqlite.upsert_run({"run_id": "r1", "config_hash": "h", "git_sha": "g",
                               "started_at": 1.0, "updated_at": 1.0})
      cpcv_sqlite.insert_combinations_batch([{
          "run_id": "r1", "combo_idx": 0,
          "train_indices": [0, 1, 2], "test_indices": [3, 4],
          "oos_sharpe": 1.1, "created_at": 1.0,
      }])
      combos = cpcv_sqlite.get_combinations("r1")
      assert "train_indices" in combos[0], "expected normalised key name"
      assert "train_indices_json" not in combos[0], "raw _json key must not leak"
      assert combos[0]["train_indices"] == [0, 1, 2]
  ```
- **Risk of regression:** Any caller that currently reads `train_indices_json` from the SQLite
  result dict will get `KeyError`. Search for `train_indices_json` as a dict key access in all
  non-migration Python files and update to `train_indices`.
- **Migration ordering:** No schema change. Code deploy only. Zero-downtime.

---

## Finding 6 — `patch_run` builds SET clause from unsanitised dict keys

- **Severity:** Important
- **File + line(s):**
  - `backend/cpcv_sqlite.py:221` (`patch_run`, f-string `SET` construction)
  - `backend/supabase_backtest.py:144-146` (`patch_run`, passes dict directly to `_patch` which encodes it as JSON — lower risk, but same root cause pattern)
- **Root cause:** `cpcv_sqlite.patch_run` builds
  `SET col1=?, col2=?` by iterating `patch.keys()` without validating the keys against a whitelist.
  If `patch` ever contains a key derived from user input or an upstream API response, it is a
  second-order SQL injection. Current callers pass controlled dicts, but the function's contract
  does not enforce this.
- **Proposed fix:**

  Add an allowlist constant and raise `ValueError` for unknown keys. The Supabase side is lower
  risk (PostgREST ignores unknown columns) but should mirror the pattern for consistency.

  **Add to `backend/cpcv_sqlite.py` before `patch_run`:**
  ```python
  _PATCH_RUN_ALLOWED_COLS = frozenset({
      "status", "error", "finished_at", "updated_at",
      "n_completed", "n_skipped", "n_failed",
      "median_oos_sharpe", "oos_sharpe_min", "oos_sharpe_max",
      "pbo", "deflated_sharpe", "metrics_json", "modal_call_id",
  })
  ```

  **Patch `patch_run` in `backend/cpcv_sqlite.py` (lines 213-233), add validation at the top:**
  ```python
  def patch_run(run_id: str, patch: dict) -> bool:
      if not patch:
          return False
      unknown = set(patch) - _PATCH_RUN_ALLOWED_COLS
      if unknown:
          raise ValueError(f"patch_run: disallowed column(s): {unknown}")
      # ... rest unchanged
  ```

  **Add to `backend/supabase_backtest.py` before `patch_run`:**
  ```python
  _PATCH_RUN_ALLOWED_COLS = frozenset({
      "status", "error", "finished_at",
      "n_completed", "n_skipped", "n_failed",
      "median_oos_sharpe", "oos_sharpe_min", "oos_sharpe_max",
      "pbo", "deflated_sharpe", "metrics_json", "modal_call_id",
  })
  ```

  **Patch `supabase_backtest.patch_run` (line 144-146):**
  ```python
  def patch_run(run_id: str, patch: dict) -> bool:
      unknown = set(patch) - _PATCH_RUN_ALLOWED_COLS
      if unknown:
          raise ValueError(f"patch_run: disallowed column(s): {unknown}")
      return _patch("backtest_runs", {"run_id": f"eq.{run_id}"}, patch)
  ```

- **Why minimal:** Two frozensets and two guard clauses; no schema change.
- **Test / verification:**
  File: `tests/test_cpcv_sqlite.py`, function: `test_patch_run_rejects_unknown_column`
  ```python
  import pytest
  def test_patch_run_rejects_unknown_column(tmp_path, monkeypatch):
      monkeypatch.setenv("WAREHOUSE_DB_PATH", str(tmp_path / "test.db"))
      from backend import cpcv_sqlite
      cpcv_sqlite._SCHEMA_READY = False
      with pytest.raises(ValueError, match="disallowed"):
          cpcv_sqlite.patch_run("r1", {"__proto__": "injected"})
  ```
- **Risk of regression:** Any caller that passes a column outside `_PATCH_RUN_ALLOWED_COLS` will
  now raise instead of silently writing. Audit all `patch_run` call sites (dispatcher.py has two;
  verify both pass only allowed keys). The Python reviewer has a parallel finding on input
  sanitisation — coordinate allowlist contents. See Cross-refs.
- **Migration ordering:** No schema change. Code deploy only. Zero-downtime.

---

## Finding 7 — RLS policies grant full access to anon role

- **Severity:** Important
- **File + line(s):**
  - `supabase/migrations/0001_backtest_tables.sql:68` (`backtest_runs`)
  - `supabase/migrations/0001_backtest_tables.sql:95` (`backtest_combinations`)
  - `supabase/migrations/0001_backtest_tables.sql:129` (`backtest_trades`)
  - `supabase/migrations/0001_backtest_tables.sql:148` (`backtest_events`)
- **Root cause:** All four tables have `USING (true) WITH CHECK (true)` policies with no role
  restriction. The service-role key bypasses RLS by design, so current server-side writes are safe.
  However, if the anon key is ever used client-side (e.g. a browser calling the Supabase REST API
  directly, or a misconfigured environment variable), these policies allow full read and write
  access to backtest data including trade PnL and strategy configurations.
- **Proposed fix:**

  Replace the permissive `(true)` policies with service-role-only policies in
  `supabase/migrations/0002_backtest_indexes_rls.sql`. Use `DROP POLICY ... IF EXISTS` to replace
  them without an intermediate gap.

  **Add to `supabase/migrations/0002_backtest_indexes_rls.sql`:**
  ```sql
  -- Replace permissive anon-accessible policies with service-role-only policies.
  -- Service role bypasses RLS, so these policies exist to block anon/authenticated
  -- roles from accessing backtest data via the public PostgREST endpoint.

  -- backtest_runs
  DROP POLICY IF EXISTS "allow all backtest_runs" ON backtest_runs;
  CREATE POLICY "service_role_only_backtest_runs"
      ON backtest_runs
      FOR ALL
      USING (auth.role() = 'service_role')
      WITH CHECK (auth.role() = 'service_role');

  -- backtest_combinations
  DROP POLICY IF EXISTS "allow all backtest_combinations" ON backtest_combinations;
  CREATE POLICY "service_role_only_backtest_combinations"
      ON backtest_combinations
      FOR ALL
      USING (auth.role() = 'service_role')
      WITH CHECK (auth.role() = 'service_role');

  -- backtest_trades
  DROP POLICY IF EXISTS "allow all backtest_trades" ON backtest_trades;
  CREATE POLICY "service_role_only_backtest_trades"
      ON backtest_trades
      FOR ALL
      USING (auth.role() = 'service_role')
      WITH CHECK (auth.role() = 'service_role');

  -- backtest_events
  DROP POLICY IF EXISTS "allow all backtest_events" ON backtest_events;
  CREATE POLICY "service_role_only_backtest_events"
      ON backtest_events
      FOR ALL
      USING (auth.role() = 'service_role')
      WITH CHECK (auth.role() = 'service_role');
  ```

  Note: the application already uses `settings.supabase_service_key` for all requests
  (`backend/supabase_backtest.py:54-57`), so this change will not break any current write or read
  path. The `Authorization: Bearer <service_key>` header sets `auth.role()` to `'service_role'`
  in the PostgREST JWT context.

- **Why minimal:** Four `DROP POLICY` + `CREATE POLICY` pairs; no table or column changes.
- **Test / verification:**
  Manual SQL check against the Supabase project (cannot be automated without a live anon key):
  ```sql
  -- Run as the anon role (use the anon key in a psql connection or REST call):
  -- Expected: zero rows returned and/or permission denied.
  SET ROLE anon;
  SELECT count(*) FROM backtest_runs;
  -- Expected result: ERROR: permission denied for table backtest_runs
  -- (or 0 rows if RLS blocks without error, depending on Postgres version)
  ```
  For CI, verify the policy definitions:
  ```sql
  SELECT policyname, cmd, qual, with_check
    FROM pg_policies
   WHERE tablename IN (
       'backtest_runs','backtest_combinations',
       'backtest_trades','backtest_events'
   );
  -- All rows should show qual = "(auth.role() = 'service_role')"
  ```
- **Risk of regression:** Any client that calls the PostgREST endpoint with the anon key will
  receive 0 rows (RLS blocks) instead of data. This is the desired outcome. If a legitimate
  authenticated-user flow needs read access to these tables in the future, add a separate SELECT
  policy gated on `auth.uid()` at that time.
- **Migration ordering:** Schema change. Apply `0002_*.sql`. Zero-downtime — `DROP POLICY` /
  `CREATE POLICY` do not lock the table. Apply during off-peak to avoid a brief window between
  drop and create (the window is sub-millisecond in practice).

---

## New migration file

All schema changes above belong in a single new file:

**`supabase/migrations/0002_backtest_indexes_rls.sql`**

```sql
-- =============================================================================
-- Migration 0002: backtest table index corrections and RLS hardening
--
-- Applies to: backtest_events, backtest_runs, backtest_combinations,
--             backtest_trades, backtest_events (RLS only for the last three)
--
-- Prerequisites: 0001_backtest_tables.sql must be applied.
-- Downtime: none (index CREATE/DROP and policy changes do not lock tables).
-- =============================================================================

-- ── Finding 3: Replace (run_id, created_at) index with (run_id, id) ──────────

DROP INDEX IF EXISTS idx_backtest_events_run_time;

CREATE INDEX IF NOT EXISTS idx_backtest_events_run_id
    ON backtest_events (run_id, id);

-- ── Finding 7: Restrict RLS to service_role only ──────────────────────────────

DROP POLICY IF EXISTS "allow all backtest_runs" ON backtest_runs;
CREATE POLICY "service_role_only_backtest_runs"
    ON backtest_runs FOR ALL
    USING  (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

DROP POLICY IF EXISTS "allow all backtest_combinations" ON backtest_combinations;
CREATE POLICY "service_role_only_backtest_combinations"
    ON backtest_combinations FOR ALL
    USING  (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

DROP POLICY IF EXISTS "allow all backtest_trades" ON backtest_trades;
CREATE POLICY "service_role_only_backtest_trades"
    ON backtest_trades FOR ALL
    USING  (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

DROP POLICY IF EXISTS "allow all backtest_events" ON backtest_events;
CREATE POLICY "service_role_only_backtest_events"
    ON backtest_events FOR ALL
    USING  (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');
```

---

## Sequencing

Execute in this order. Each step is independently zero-downtime unless noted.

1. **Apply `0002_backtest_indexes_rls.sql` to Supabase** (Findings 3 + 7).
   This is schema-only and has no code dependency. Apply via the Supabase dashboard SQL editor or
   `supabase db push`. Verify with the `pg_policies` query in Finding 7 and the `EXPLAIN ANALYZE`
   in Finding 3.

2. **Deploy Finding 5 (column alias normalisation in `cpcv_sqlite._row_to_dict`)**.
   No external dependency. Ship alone so that if it breaks a caller the blast radius is minimal.

3. **Deploy Finding 6 (allowlist in `patch_run`, both stores)**.
   Coordinate with Python reviewer on allowed column list. Deploy after Finding 5 so schema is
   stable.

4. **Deploy Finding 2 (explicit column projections in `supabase_backtest.py`)**.
   Audit all callers of `get_trades` and `backtest_reader.get_trades` for `signals_at_entry_json`
   reads before deploying. Update those callers to use the new `get_trade_detail` function.

5. **Deploy Finding 4 (JSONL dead-letter for failed Supabase batches)**.
   Confirm `SUPABASE_FAILED_BATCH_LOG` is writable in the Modal container environment. If `/tmp`
   is ephemeral in Modal (it is), the log is per-invocation — acceptable for a durability shim;
   note this in ops runbook.

6. **Deploy Finding 1 (events cursor source tag) + TS frontend cursor reset** (joint deploy with
   TypeScript reviewer). Both sides must ship together or the frontend will `TypeError` on
   `result["events"]`. Coordinate release.

---

## Cross-refs

- **Finding 1 (backend side)** depends on the TypeScript reviewer's frontend cursor-reset change.
  The backend signature change (`get_events` returns `dict` instead of `list`) must ship in the
  same deploy as the frontend fix, or the frontend will break.

- **Finding 6 (patch_run allowlist)** overlaps with the Python reviewer's input-sanitisation
  finding. Agree on the canonical `_PATCH_RUN_ALLOWED_COLS` frozenset contents before either side
  ships, to avoid one reviewer's allowlist rejecting the other reviewer's callers.

- **Finding 3 (SQLite index)** also requires updating `_ensure_schema` in `cpcv_sqlite.py` (code
  change, not just the Supabase migration). That code change is listed in Finding 3's proposed fix
  and is independent of the migration sequencing.

---

## Deferred / out-of-scope

- **Frontend `after_id` cursor reset on source switch** — TypeScript reviewer's scope. This plan
  only covers the backend source tag emission.

- **OFFSET pagination on `list_runs` / `get_combinations`** — `list_runs` uses `LIMIT/OFFSET`
  (lines 69, 232). At current run volumes (dozens to low hundreds) this is not a problem. Convert
  to keyset pagination (`WHERE started_at < $cursor`) if the table grows beyond ~10 000 rows.

- **`signals_at_entry_json` in SQLite `get_trades`** — The SQLite path already omits nothing
  (it returns all columns in `_TRADE_COLS`). Applying a column-exclusion pattern to SQLite reads
  is lower priority because SQLite is local and the data volume is bounded by available disk, not
  network bandwidth. Defer until the SQLite path is used in production.

- **Supabase free-tier 1 MB POST cap** — Noted in `supabase_backtest.py:31-33`. The `_TRADE_CHUNK`
  constant of 2000 rows is fine for current signal vector sizes but should be revisited if
  `signals_at_entry_json` bloat increases row size. Out of scope for this PR.

- **Full outbox / transactional dual-write** — Finding 4's JSONL shim is intentionally minimal.
  A proper outbox pattern (write to SQLite first, background process syncs to Supabase) is the
  correct long-term solution but is a larger architectural change deferred to a follow-up.
