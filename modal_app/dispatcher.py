"""CPCV orchestrator.

Runs on the operator's box (dev) or inside a FastAPI endpoint (future Session 3).
Responsibilities:

  1. Resolve universe + build a `BacktestConfig`.
  2. Stamp the run: UUID, `config_hash`, `git_sha`.
  3. Persist a `queued` → `running` row to SQLite (and Supabase if enabled).
  4. Build the CPCV panel LOCALLY (using cached price CSVs → fast).
  5. Upload panel to the Modal Volume.
  6. Generate all CPCV combinations; optionally sample `max_combos`.
  7. Dispatch via `CPCVWorker.run_combo.map(...)`.
  8. Stream results into a `CPCVResult`, dual-writing combos + trades +
     events as each completes.
  9. Finalize the run row (status/metrics) and print a leaderboard.

Returns a Python dict suitable for pickling to `runs/{run_id}.pkl`.
"""

from __future__ import annotations

import logging
import random
import time
import uuid
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Optional

from backend import cpcv_sqlite, supabase_backtest
from modal_app.events import (
    emit_event,
    EVENT_COMBO_COMPLETED,
    EVENT_COMBO_FAILED,
    EVENT_COMBO_SKIPPED,
    EVENT_RUN_COMPLETED,
    EVENT_RUN_DEGRADED,
    EVENT_RUN_FAILED,
    EVENT_RUN_STARTED,
)

if TYPE_CHECKING:
    from quant.backtest import BacktestConfig

logger = logging.getLogger(__name__)


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


# Buffer combos before flushing to Supabase (SQLite flushes per-combo since
# writes are local + WAL). Default is 50 combos per HTTP round-trip — well
# under PostgREST's ~1 MB cap. Tunable via `settings.modal_backtest_flush_combos`.
def _supabase_combo_flush_size() -> int:
    try:
        from config import settings as _s

        return max(1, int(_s.modal_backtest_flush_combos))
    except Exception:
        return 50


def _build_combo_specs(
    run_id: str,
    panel_key: str,
    combos: list,
    config_dict: dict,
    config_hash: str,
    git_sha: str,
) -> list[dict]:
    """Shape the per-combo inputs Modal will fan out."""
    return [
        {
            "run_id": run_id,
            "panel_key": panel_key,
            "combo_idx": idx,
            "train_indices": list(train),
            "test_indices": list(test),
            "config_json": config_dict,
            "config_hash": config_hash,
            "git_sha": git_sha,
        }
        for idx, (train, test) in enumerate(combos)
    ]


def _combo_result_to_row(run_id: str, out: dict, status: str) -> dict:
    """Build a cpcv_combinations row from a worker result dict."""
    return {
        "run_id": run_id,
        "combo_idx": int(out.get("combo_idx", -1)),
        "status": status,
        "train_indices": out.get("train_groups"),
        "test_indices": out.get("test_groups"),
        "oos_sharpe": out.get("oos_sharpe"),
        "return_pct": out.get("return_pct"),
        "n_trades": out.get("n_trades"),
        "n_test_dates": out.get("n_test_dates"),
        "elapsed_seconds": out.get("elapsed_seconds"),
        "git_sha": out.get("git_sha"),
        "error": out.get("error"),
    }


def _combo_trades_to_rows(run_id: str, combo_idx: int, trades: list[dict]) -> list[dict]:
    """Expand a combo's trade list into cpcv_trades rows."""
    rows = []
    for trade_idx, t in enumerate(trades or []):
        rows.append(
            {
                "run_id": run_id,
                "combo_idx": combo_idx,
                "trade_idx": trade_idx,
                "ticker": t.get("ticker"),
                "direction": t.get("direction"),
                "entry_date": t.get("entry_date"),
                "exit_date": t.get("exit_date"),
                "entry_price": t.get("entry_price"),
                "exit_price": t.get("exit_price"),
                "pnl_dollar": t.get("pnl_dollar"),
                "pnl_pct": t.get("pnl_pct"),
                "holding_days": t.get("holding_days"),
                "exit_reason": t.get("exit_reason"),
                "composite_score": t.get("composite_score"),
                "regime_at_entry": t.get("regime_at_entry"),
                "signals_at_entry_json": t.get("signals_at_entry"),
                "flags_json": t.get("flags"),
            }
        )
    return rows


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
    """End-to-end CPCV run. Returns a summary dict.

    `run_id`/`config_hash`/`git_sha` can be supplied by a caller that has
    already written a `queued` row (e.g. the FastAPI `POST /backtest/modal`
    kickoff, which needs to return the id to the client before dispatch
    completes). When `None`, identity is generated here as usual.
    """
    from quant.backtest import BacktestConfig
    from quant.config_hash import config_hash as _config_hash
    from quant.cpcv import CPCVResult, generate_cpcv_combinations
    from quant.git_sha import capture_git_sha

    assert isinstance(config, BacktestConfig), "config must be a BacktestConfig"
    if not config.tickers:
        raise ValueError("config.tickers is empty — resolve a universe before dispatch.")

    # Ensure orchestrator-side data providers are initialized before panel build.
    # Needed both for local=True runs (which execute combos in-process) and for
    # panel-build steps that pull from WRDS / FMP when regime-adjacent signals fire.
    from quant.backtest import init_providers_for_config

    _init = init_providers_for_config(config)
    if _init:
        logger.info("Orchestrator providers initialized: %s", _init)

    if run_id is None:
        run_id = uuid.uuid4().hex[:12]
    cfg_hash = config_hash or _config_hash(config)
    git_sha = git_sha or capture_git_sha(allow_dirty=allow_dirty)

    logger.info("Run %s | git_sha=%s | config_hash=%s", run_id, git_sha, cfg_hash)
    logger.info(
        "Universe=%d tickers  n_groups=%d  n_test=%d  max_combos=%s",
        len(config.tickers),
        n_groups,
        n_test_groups,
        max_combos,
    )

    config_dict = asdict(config)

    # Persist `queued` row before panel build so crashes are observable.
    run_row = {
        "run_id": run_id,
        "config_hash": cfg_hash,
        "git_sha": git_sha,
        "status": "queued",
        "universe": _infer_universe_label(config),
        "n_groups": n_groups,
        "n_test_groups": n_test_groups,
        "n_combinations": None,
        "config_json": config_dict,
        "started_at": time.time(),
    }
    cpcv_sqlite.upsert_run(run_row)
    supabase_backtest.upsert_run(_supabase_run_row(run_row))
    emit_event(
        run_id,
        EVENT_RUN_STARTED,
        {
            "n_groups": n_groups,
            "n_test_groups": n_test_groups,
            "tickers": config.tickers[:20],
            "n_tickers": len(config.tickers),
        },
    )

    t_panel = time.time()
    if local:
        from modal_app.panel import build_panel_locally, panel_to_cpcv_state

        panel = build_panel_locally(
            run_id,
            config,
            n_groups,
            n_test_groups,
            purge_months=purge_months,
            embargo_months=embargo_months,
        )
        panel_key = None
        local_state = panel_to_cpcv_state(panel)
    else:
        from modal_app.app import panels_volume
        from modal_app.panel import build_panel_locally, upload_panel_to_volume

        panel = build_panel_locally(
            run_id,
            config,
            n_groups,
            n_test_groups,
            purge_months=purge_months,
            embargo_months=embargo_months,
        )
        panel_key = upload_panel_to_volume(panel, panels_volume).replace(".pkl", "")
        local_state = None
    logger.info("Panel ready (%.1fs, %d tickers)", time.time() - t_panel, len(panel.universe_data))

    combos = generate_cpcv_combinations(n_groups, n_test_groups)
    logger.info("Generated %d combinations (C(%d, %d))", len(combos), n_groups, n_test_groups)

    if max_combos and max_combos < len(combos):
        rng = random.Random(seed)
        combos = rng.sample(combos, max_combos)
        logger.info("Sampled %d combinations (seed=%d)", len(combos), seed)

    result = CPCVResult(
        n_groups=n_groups,
        n_test_groups=n_test_groups,
        purge_months=purge_months,
        embargo_months=embargo_months,
        n_combinations=len(combos),
    )

    cpcv_sqlite.patch_run(run_id, {"status": "running", "n_combinations": len(combos)})
    supabase_backtest.patch_run(run_id, {"status": "running", "n_combinations": len(combos)})

    t_fanout = time.time()
    failures: list[dict] = []
    supabase_combo_buffer: list[dict] = []

    def _handle_combo_result(out: dict) -> None:
        """Persist one combo + its trades, emit an event, update aggregates.
        Mutates `result`, `failures`, and `supabase_combo_buffer` in the enclosing scope.
        """
        status = out.get("status", "complete")
        combo_idx = int(out.get("combo_idx", -1))

        if status == "skipped":
            result.n_combinations_skipped += 1
            combo_row = _combo_result_to_row(run_id, out, "skipped")
            cpcv_sqlite.insert_combinations_batch([combo_row])
            supabase_combo_buffer.append(combo_row)
            emit_event(
                run_id,
                EVENT_COMBO_SKIPPED,
                {
                    "skip_reason": out.get("skip_reason"),
                },
                combo_idx=combo_idx,
            )
            return

        if status == "error":
            failures.append(out)
            combo_row = _combo_result_to_row(run_id, out, "error")
            cpcv_sqlite.insert_combinations_batch([combo_row])
            supabase_combo_buffer.append(combo_row)
            emit_event(
                run_id,
                EVENT_COMBO_FAILED,
                {
                    "error": out.get("error"),
                    "traceback": out.get("traceback", "")[:1000],
                },
                combo_idx=combo_idx,
            )
            _capture_sentry(run_id, cfg_hash, combo_idx, f"CPCV combo failed: {out.get('error')}")
            return

        result.oos_sharpes.append(out["oos_sharpe"])
        result.combination_details.append(out)
        result.n_combinations_completed += 1

        combo_row = _combo_result_to_row(run_id, out, "complete")
        cpcv_sqlite.insert_combinations_batch([combo_row])
        supabase_combo_buffer.append(combo_row)

        trades = out.get("trades") or []
        if trades:
            trade_rows = _combo_trades_to_rows(run_id, combo_idx, trades)
            cpcv_sqlite.insert_trades_batch(trade_rows)
            supabase_backtest.insert_trades_batch(trade_rows)

        emit_event(
            run_id,
            EVENT_COMBO_COMPLETED,
            {
                "oos_sharpe": out.get("oos_sharpe"),
                "return_pct": out.get("return_pct"),
                "n_trades": out.get("n_trades"),
                "elapsed_seconds": out.get("elapsed_seconds"),
            },
            combo_idx=combo_idx,
        )

        if len(supabase_combo_buffer) >= _supabase_combo_flush_size():
            supabase_backtest.insert_combinations_batch(supabase_combo_buffer)
            supabase_combo_buffer.clear()

        completed = result.n_combinations_completed
        if completed % 25 == 0 and result.oos_sharpes:
            sorted_sharpes = sorted(result.oos_sharpes)
            median = float(sorted_sharpes[len(sorted_sharpes) // 2])
            logger.info("%d combos complete  median_oos_sharpe=%.3f", completed, median)

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
                    _handle_combo_result(
                        {
                            "combo_idx": idx,
                            "status": "skipped",
                            "skip_reason": "no_trades_or_sharpe",
                        }
                    )
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
                    len(supabase_combo_buffer),
                    run_id,
                    flush_exc,
                )
            supabase_combo_buffer.clear()

    elapsed = time.time() - t_fanout
    result.elapsed_seconds = round(elapsed, 1)
    result.compute_summary_stats()

    n_total = len(combos)
    n_failed = len(failures)
    failure_rate = n_failed / max(n_total, 1)
    result.status = "degraded" if failure_rate > 0.02 else "complete"
    if failure_rate > 0.02:
        result.error = f"{n_failed}/{n_total} combos failed ({failure_rate:.1%})"

    summary = {
        "run_id": run_id,
        "git_sha": git_sha,
        "config_hash": cfg_hash,
        "n_groups": n_groups,
        "n_test_groups": n_test_groups,
        "n_combinations": n_total,
        "n_completed": result.n_combinations_completed,
        "n_skipped": result.n_combinations_skipped,
        "n_failed": n_failed,
        "status": result.status,
        "elapsed_seconds": result.elapsed_seconds,
        "oos_sharpe_median": (
            float(sorted(result.oos_sharpes)[len(result.oos_sharpes) // 2])
            if result.oos_sharpes
            else None
        ),
        "oos_sharpe_min": min(result.oos_sharpes) if result.oos_sharpes else None,
        "oos_sharpe_max": max(result.oos_sharpes) if result.oos_sharpes else None,
        "pbo": getattr(result, "pbo", None),
        "deflated_sharpe": getattr(result, "deflated_sharpe", None),
        "failures_sample": failures[:5],
        "panel_key": panel_key,
    }

    final_patch = {
        "status": result.status,
        "n_completed": result.n_combinations_completed,
        "n_skipped": result.n_combinations_skipped,
        "n_failed": n_failed,
        "median_oos_sharpe": summary["oos_sharpe_median"],
        "oos_sharpe_min": summary["oos_sharpe_min"],
        "oos_sharpe_max": summary["oos_sharpe_max"],
        "pbo": summary["pbo"],
        "deflated_sharpe": summary["deflated_sharpe"],
        "error": result.error,
        "finished_at": time.time(),
    }
    cpcv_sqlite.patch_run(run_id, final_patch)
    supabase_backtest.patch_run(run_id, final_patch)

    terminal_event = (
        EVENT_RUN_DEGRADED
        if result.status == "degraded"
        else EVENT_RUN_FAILED
        if result.status == "failed"
        else EVENT_RUN_COMPLETED
    )
    emit_event(
        run_id,
        terminal_event,
        {
            "n_completed": result.n_combinations_completed,
            "n_skipped": result.n_combinations_skipped,
            "n_failed": n_failed,
            "median_oos_sharpe": summary["oos_sharpe_median"],
            "elapsed_seconds": result.elapsed_seconds,
        },
    )

    if print_leaderboard:
        _print_leaderboard(result, summary)

    return summary


def _infer_universe_label(config: "BacktestConfig") -> Optional[str]:
    """Best-effort name for `cpcv_runs.universe` from the ticker set.

    Matches the CLI's `--universe` flag values when possible so the dedup
    UI can filter. Falls back to a ticker count for custom sets.
    """
    try:
        from quant.universe import LIQUID_10, LIQUID_20, LIQUID_50

        tickers = set(config.tickers)
        for label, members in [
            ("liquid_10", LIQUID_10),
            ("liquid_20", LIQUID_20),
            ("liquid_50", LIQUID_50),
        ]:
            if tickers == set(members):
                return label
    except Exception:
        pass
    return f"custom_{len(config.tickers)}"


def _supabase_run_row(row: dict[str, Any]) -> dict[str, Any]:
    """Shape a run row for Supabase (drop `started_at` so Postgres defaults)."""
    out = {k: v for k, v in row.items() if k != "started_at"}
    return out


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
    """Kick off a CPCV dispatch on a background thread and return immediately.

    Used by the FastAPI POST endpoint: we need to return a `run_id` to the
    client before the long dispatch has even uploaded the panel. This
    writes the `queued` row synchronously (so it's visible to polling GETs),
    then spawns a thread that runs the full dispatcher.

    Returns `{run_id, config_hash, git_sha, status}` for the response body.
    """
    from quant.backtest import BacktestConfig
    from quant.config_hash import config_hash as _config_hash_fn
    from quant.git_sha import capture_git_sha

    assert isinstance(config, BacktestConfig), "config must be a BacktestConfig"
    if not config.tickers:
        raise ValueError("config.tickers is empty — resolve a universe before dispatch.")

    run_id = uuid.uuid4().hex[:12]
    cfg_hash = _config_hash_fn(config)
    # `allow_dirty=True` is safe here because Railway/remote environments are
    # handled inside capture_git_sha — the resulting SHA reflects the deployed
    # revision (MODAL_GIT_SHA / RAILWAY_GIT_COMMIT_SHA), not a local dirty tree.
    git_sha = capture_git_sha(allow_dirty=True)

    # Write queued row synchronously so the client's immediate GET succeeds.
    run_row = {
        "run_id": run_id,
        "config_hash": cfg_hash,
        "git_sha": git_sha,
        "status": "queued",
        "universe": _infer_universe_label(config),
        "n_groups": n_groups,
        "n_test_groups": n_test_groups,
        "n_combinations": None,
        "config_json": asdict(config),
        "started_at": time.time(),
    }
    cpcv_sqlite.upsert_run(run_row)
    supabase_backtest.upsert_run(_supabase_run_row(run_row))
    # NB: intentionally no EVENT_RUN_STARTED here — `dispatch_cpcv` emits its
    # own with the full tickers/n_groups payload once it reaches the fan-out.

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
            _capture_sentry(run_id, cfg_hash, None, f"background dispatch failed: {exc}", exc=exc)
            cpcv_sqlite.patch_run(
                run_id,
                {
                    "status": "failed",
                    "error": str(exc)[:500],
                    "finished_at": time.time(),
                },
            )
            supabase_backtest.patch_run(
                run_id,
                {
                    "status": "failed",
                    "error": str(exc)[:500],
                    "finished_at": time.time(),
                },
            )
            emit_event(run_id, EVENT_RUN_FAILED, {"error": str(exc)[:500]})
        finally:
            _unregister_thread(_threading.current_thread())

    thread = _threading.Thread(target=_run, daemon=False, name=f"cpcv-{run_id}")
    _register_thread(thread)
    thread.start()

    return {
        "run_id": run_id,
        "config_hash": cfg_hash,
        "git_sha": git_sha,
        "status": "queued",
    }


def _print_leaderboard(result, summary: dict, top_n: int = 10) -> None:
    """Pretty-print the CPCV run summary + top/bottom N combos by OOS Sharpe."""
    print()
    print("═" * 78)
    print("CPCV VALIDATION RESULTS")
    print("═" * 78)
    print(f"  run_id            : {summary['run_id']}")
    print(f"  git_sha           : {summary['git_sha']}")
    print(f"  config_hash       : {summary['config_hash']}")
    print(f"  status            : {summary['status']}")
    print(
        f"  combinations      : {summary['n_completed']} / {summary['n_combinations']} "
        f"completed  (skipped={summary['n_skipped']}  failed={summary['n_failed']})"
    )
    print(f"  elapsed           : {summary['elapsed_seconds']:.1f} s")
    if summary["oos_sharpe_median"] is not None:
        print(f"  median_oos_sharpe : {summary['oos_sharpe_median']:+.3f}")
        print(
            f"  min / max         : {summary['oos_sharpe_min']:+.3f} / "
            f"{summary['oos_sharpe_max']:+.3f}"
        )
    if summary.get("pbo") is not None:
        print(f"  PBO               : {summary['pbo']:.3f}")
    if summary.get("deflated_sharpe") is not None:
        print(f"  deflated_sharpe   : {summary['deflated_sharpe']:+.3f}")

    if not result.combination_details:
        print("─" * 78)
        return

    ranked = sorted(
        result.combination_details,
        key=lambda c: c.get("oos_sharpe", float("-inf")),
        reverse=True,
    )
    print("─" * 78)
    print(f"  Top {min(top_n, len(ranked))} combos by OOS Sharpe:")
    for c in ranked[:top_n]:
        print(
            f"    combo {c['combo_idx']:>4}  sharpe={c.get('oos_sharpe', 0):+.3f}  "
            f"ret={c.get('return_pct', 0):+.2f}%  "
            f"trades={c.get('n_trades', 0):>3}  "
            f"test_dates={c.get('n_test_dates', 0)}"
        )
    if len(ranked) > top_n:
        print(f"  Bottom {min(top_n, len(ranked))} combos:")
        for c in ranked[-top_n:]:
            print(
                f"    combo {c['combo_idx']:>4}  sharpe={c.get('oos_sharpe', 0):+.3f}  "
                f"ret={c.get('return_pct', 0):+.2f}%  "
                f"trades={c.get('n_trades', 0):>3}  "
                f"test_dates={c.get('n_test_dates', 0)}"
            )
    print("═" * 78)


__all__ = ["dispatch_cpcv"]
