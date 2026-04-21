"""Standalone Modal smoke function. Intentionally does NOT accept arbitrary
code (the old `run_smoke_test(smoke_test_code)` + `exec()` pattern has been
removed; see `.cursor/plans/modal-backtesting.md` §2).

Run via:
    modal run modal_app.functions.smoke::ping
    modal run modal_app.functions.smoke::run_tiny_cpcv
"""
from __future__ import annotations

import logging
import os
import time

from modal_app.app import app, image, secrets


logger = logging.getLogger(__name__)


@app.function(image=image, secrets=secrets, timeout=60)
def ping() -> dict:
    """Minimal liveness check: returns env var presence + container boot time."""
    t0 = time.time()
    env_keys_to_check = [
        "TIINGO_API_KEY",
        "FMP_API_KEY",
        "FINNHUB_API_KEY",
        "FRED_API_KEY",
        "ANTHROPIC_API_KEY",
    ]
    env_status = {k: bool(os.environ.get(k, "").strip()) for k in env_keys_to_check}
    return {
        "status": "ok",
        "git_sha": os.environ.get("MODAL_GIT_SHA", "dev"),
        "modal_mode": os.environ.get("MODAL_MODE", "dev"),
        "env_secrets_present": env_status,
        "elapsed_seconds": round(time.time() - t0, 3),
    }


@app.function(image=image, secrets=secrets, timeout=600, cpu=4, memory=8192)
def run_tiny_cpcv() -> dict:
    """Run a 3-combo CPCV on 5 tickers end-to-end, fully inside Modal.

    Exercises the full import chain + data load + combo runner. Intended as
    a pre-deploy smoke; use `scripts/run_modal_cpcv.py --smoke` as the
    orchestrator-driven equivalent.
    """
    t0 = time.time()
    from quant.backtest import run_cpcv, BacktestConfig

    cfg = BacktestConfig(
        tickers=["AAPL", "MSFT", "GOOGL", "AMZN", "JPM"],
        start_date="2023-01-01",
        end_date="2024-06-01",
        enable_regime_filter=False,
        enable_ic_calibration=False,
    )
    result = run_cpcv(cfg, n_groups=5, n_test_groups=2, max_combinations=3)

    return {
        "status": "ok" if not getattr(result, "error", None) else "error",
        "error": getattr(result, "error", None),
        "n_combinations": result.n_combinations,
        "n_completed": result.n_combinations_completed,
        "n_skipped": result.n_combinations_skipped,
        "oos_sharpes": list(result.oos_sharpes),
        "elapsed_seconds": round(time.time() - t0, 3),
        "git_sha": os.environ.get("MODAL_GIT_SHA", "dev"),
    }


__all__ = ["ping", "run_tiny_cpcv"]
