"""CPCV orchestrator.

Runs on the operator's box (dev) or inside a FastAPI endpoint (future Session 3).
Responsibilities:

  1. Resolve universe + build a `BacktestConfig`.
  2. Stamp the run: UUID, `config_hash`, `git_sha`.
  3. Build the CPCV panel LOCALLY (using cached price CSVs → fast).
  4. Upload panel to the Modal Volume.
  5. Generate all CPCV combinations; optionally sample `max_combos`.
  6. Dispatch via `CPCVWorker.run_combo.map(...)`.
  7. Stream results into a `CPCVResult` and print a leaderboard.

Returns a Python dict suitable for pickling to `runs/{run_id}.pkl`.
"""
from __future__ import annotations

import logging
import random
import time
import uuid
from dataclasses import asdict
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _build_combo_specs(
    run_id: str,
    panel_key: str,
    combos: list,
    config_dict: dict,
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
        }
        for idx, (train, test) in enumerate(combos)
    ]


def dispatch_cpcv(
    config,
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
) -> dict[str, Any]:
    """End-to-end CPCV run. Returns a summary dict."""
    from quant.backtest import BacktestConfig
    from quant.config_hash import config_hash as _config_hash
    from quant.cpcv import CPCVResult, generate_cpcv_combinations
    from quant.git_sha import capture_git_sha

    assert isinstance(config, BacktestConfig), "config must be a BacktestConfig"
    if not config.tickers:
        raise ValueError("config.tickers is empty — resolve a universe before dispatch.")

    run_id = uuid.uuid4().hex[:12]
    cfg_hash = _config_hash(config)
    git_sha = capture_git_sha(allow_dirty=allow_dirty)

    logger.info("Run %s | git_sha=%s | config_hash=%s", run_id, git_sha, cfg_hash)
    logger.info("Universe=%d tickers  n_groups=%d  n_test=%d  max_combos=%s",
                len(config.tickers), n_groups, n_test_groups, max_combos)

    config_dict = asdict(config)

    t_panel = time.time()
    if local:
        from modal_app.panel import build_panel_locally, panel_to_cpcv_state
        panel = build_panel_locally(
            run_id, config, n_groups, n_test_groups,
            purge_months=purge_months, embargo_months=embargo_months,
        )
        panel_key = None
        local_state = panel_to_cpcv_state(panel)
    else:
        from modal_app.app import panels_volume
        from modal_app.panel import build_panel_locally, upload_panel_to_volume
        panel = build_panel_locally(
            run_id, config, n_groups, n_test_groups,
            purge_months=purge_months, embargo_months=embargo_months,
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

    t_fanout = time.time()
    failures: list[dict] = []

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
                if out is None:
                    result.n_combinations_skipped += 1
                    continue
                out["status"] = "complete"
                result.oos_sharpes.append(out["oos_sharpe"])
                result.combination_details.append(out)
                result.n_combinations_completed += 1
            except Exception as exc:
                failures.append({"combo_idx": idx, "error": f"{type(exc).__name__}: {exc}"})
    else:
        from modal_app.app import app
        from modal_app.functions.cpcv_combo import CPCVWorker
        specs = _build_combo_specs(run_id, panel_key, combos, config_dict)
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
                    failures.append({"combo_idx": -1, "error": f"{type(out).__name__}: {out}"})
                    continue

                status = out.get("status")
                idx = int(out.get("combo_idx", -1))
                if status == "skipped":
                    result.n_combinations_skipped += 1
                    continue
                if status == "error":
                    failures.append(out)
                    continue
                result.oos_sharpes.append(out["oos_sharpe"])
                result.combination_details.append(out)
                result.n_combinations_completed += 1

                completed = len(result.oos_sharpes)
                if completed % 25 == 0:
                    logger.info("%d/%d combos complete  median_oos_sharpe=%.3f",
                                completed, len(specs),
                                float(sorted(result.oos_sharpes)[len(result.oos_sharpes)//2]))

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
            if result.oos_sharpes else None
        ),
        "oos_sharpe_min": min(result.oos_sharpes) if result.oos_sharpes else None,
        "oos_sharpe_max": max(result.oos_sharpes) if result.oos_sharpes else None,
        "pbo": getattr(result, "pbo", None),
        "deflated_sharpe": getattr(result, "deflated_sharpe", None),
        "failures_sample": failures[:5],
        "panel_key": panel_key,
    }

    if print_leaderboard:
        _print_leaderboard(result, summary)

    return summary


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
    print(f"  combinations      : {summary['n_completed']} / {summary['n_combinations']} "
          f"completed  (skipped={summary['n_skipped']}  failed={summary['n_failed']})")
    print(f"  elapsed           : {summary['elapsed_seconds']:.1f} s")
    if summary["oos_sharpe_median"] is not None:
        print(f"  median_oos_sharpe : {summary['oos_sharpe_median']:+.3f}")
        print(f"  min / max         : {summary['oos_sharpe_min']:+.3f} / "
              f"{summary['oos_sharpe_max']:+.3f}")
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
        print(f"    combo {c['combo_idx']:>4}  sharpe={c.get('oos_sharpe', 0):+.3f}  "
              f"ret={c.get('return_pct', 0):+.2f}%  "
              f"trades={c.get('n_trades', 0):>3}  "
              f"test_dates={c.get('n_test_dates', 0)}")
    if len(ranked) > top_n:
        print(f"  Bottom {min(top_n, len(ranked))} combos:")
        for c in ranked[-top_n:]:
            print(f"    combo {c['combo_idx']:>4}  sharpe={c.get('oos_sharpe', 0):+.3f}  "
                  f"ret={c.get('return_pct', 0):+.2f}%  "
                  f"trades={c.get('n_trades', 0):>3}  "
                  f"test_dates={c.get('n_test_dates', 0)}")
    print("═" * 78)


__all__ = ["dispatch_cpcv"]
