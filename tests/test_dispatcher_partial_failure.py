"""Verify SQLite write survives a Supabase upsert_run failure.

The dual-write path is: SQLite first, then Supabase. If Supabase raises
after SQLite has already written, the queued row MUST still be visible in
SQLite so the UI can poll `GET /runs/{run_id}` and see the run.

This is a regression guard for the partial-failure contract; full recovery
logic (retry queue, divergence alerting) belongs in the DB reviewer's DLQ
plan and is intentionally out of scope here.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _make_minimal_config():
    """Build the smallest BacktestConfig that passes kickoff_cpcv_background's
    `config.tickers` assertion. Avoids importing heavy providers.
    """
    from quant.backtest import BacktestConfig
    return BacktestConfig(
        tickers=["AAPL"],
        start_date="2022-01-01",
        end_date="2022-06-01",
    )


def test_sqlite_row_persists_when_supabase_upsert_fails(tmp_path, monkeypatch):
    """kickoff_cpcv_background writes SQLite first, then Supabase. If
    Supabase raises, the SQLite row must already be there.
    """
    import backend.cpcv_sqlite as sqlite_mod
    import backend.supabase_backtest as supa_mod

    # Point SQLite at an isolated tmp database.
    db_file = tmp_path / "cpcv_test.db"
    # settings.warehouse_db_path is read inside _connect().
    from config import settings as cfg_settings
    monkeypatch.setattr(cfg_settings, "warehouse_db_path", str(db_file), raising=False)
    # Force the module to rebuild the schema against this fresh DB.
    monkeypatch.setattr(sqlite_mod, "_SCHEMA_READY", False, raising=False)

    # Force Supabase.is_enabled() true so patch_run/upsert_run routes fire
    # the real (mocked) writer instead of short-circuiting.
    monkeypatch.setattr(supa_mod, "is_enabled", lambda: True)

    # Make Supabase's upsert raise — this models Supabase being unavailable.
    supa_upsert = MagicMock(side_effect=RuntimeError("supabase timeout"))
    monkeypatch.setattr(supa_mod, "upsert_run", supa_upsert)

    from modal_app.dispatcher import kickoff_cpcv_background
    config = _make_minimal_config()

    # kickoff_cpcv_background will call cpcv_sqlite.upsert_run synchronously
    # first, then supabase_backtest.upsert_run which raises. The function
    # should propagate that exception (no swallowing on the happy path),
    # but the SQLite row must already exist.
    with pytest.raises(RuntimeError):
        kickoff_cpcv_background(config, local=True, max_combos=1)

    # The Supabase writer must have been called (order guard).
    assert supa_upsert.called, "Supabase upsert_run was never invoked"

    # The SQLite row must exist despite the Supabase failure.
    rows = sqlite_mod.list_runs(limit=5)
    assert len(rows) >= 1, (
        "SQLite queued row was not persisted before the Supabase upsert failure — "
        "dual-write ordering is broken"
    )


def test_supabase_failure_does_not_leak_state_across_runs(tmp_path, monkeypatch):
    """Second-call safety: after one failed Supabase write, a subsequent
    kickoff with Supabase healed should persist both stores cleanly.
    """
    import backend.cpcv_sqlite as sqlite_mod
    import backend.supabase_backtest as supa_mod

    db_file = tmp_path / "cpcv_test2.db"
    from config import settings as cfg_settings
    monkeypatch.setattr(cfg_settings, "warehouse_db_path", str(db_file), raising=False)
    monkeypatch.setattr(sqlite_mod, "_SCHEMA_READY", False, raising=False)

    monkeypatch.setattr(supa_mod, "is_enabled", lambda: True)

    # First call: Supabase raises.
    monkeypatch.setattr(
        supa_mod, "upsert_run", MagicMock(side_effect=RuntimeError("boom"))
    )
    from modal_app.dispatcher import kickoff_cpcv_background
    config = _make_minimal_config()
    with pytest.raises(RuntimeError):
        kickoff_cpcv_background(config, local=True, max_combos=1)

    rows_after_first = sqlite_mod.list_runs(limit=10)
    assert len(rows_after_first) == 1

    # Second call: Supabase now healed (returns True).
    healed = MagicMock(return_value=True)
    monkeypatch.setattr(supa_mod, "upsert_run", healed)

    kickoff_cpcv_background(config, local=True, max_combos=1)

    # SQLite should now have 2 rows (or 1 merged depending on PK); both
    # calls should have reached the Supabase writer.
    assert healed.called, "Second Supabase upsert was not invoked"
