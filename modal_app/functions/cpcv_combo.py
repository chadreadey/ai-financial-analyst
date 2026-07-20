"""Per-combo CPCV worker. Class-based so the heavy panel load amortizes
across every combo routed to a given container (see architect's §4 + §5).
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import modal

from modal_app.app import app, image, secrets, panels_volume
from modal_app.panel import PANELS_MOUNT_PATH


logger = logging.getLogger(__name__)


@app.cls(
    image=image,
    secrets=secrets,
    volumes={PANELS_MOUNT_PATH: panels_volume},
    # 30min per-combo budget: accommodates full-stack runs (WRDS + FMP + Finnhub
    # API calls per rebalance date). Lean-stack runs (providers off) finish in
    # 10-30s; full-stack runs with ~24 rebalance dates × ~50 tickers × network
    # round-trips can take 5-20min. 30min leaves ~2x headroom.
    timeout=1800,
    cpu=4,
    memory=8192,
    min_containers=0,
    buffer_containers=8,
    max_containers=200,
    scaledown_window=300,
    retries=modal.Retries(max_retries=2, backoff_coefficient=2.0),
)
class CPCVWorker:
    """One container = one panel load + many combos.

    Inputs are individual `ComboSpec`-shaped dicts; the worker returns per-combo
    result dicts shaped exactly like `quant.backtest._run_single_cpcv_combo`
    output plus `git_sha` + `elapsed_seconds` + error fields.
    """

    @modal.enter()
    def _load_panel(self):
        self._container_start = time.time()
        self._git_sha = os.environ.get("MODAL_GIT_SHA", "dev")
        self._panels_cache: dict[str, object] = {}
        self._state_cache: dict[str, object] = {}
        # Signature of the config we last initialized providers against.
        # We re-init only when the relevant enable_* flags change within
        # this container's lifetime (rare in practice — a container usually
        # runs combos for one run_id = one config).
        self._providers_signature: Optional[tuple] = None
        logger.info("CPCVWorker container ready (git_sha=%s)", self._git_sha)

    @staticmethod
    def _provider_signature(config) -> tuple:
        """Hashable tuple of the flags that gate provider initialization."""
        return (
            bool(getattr(config, "enable_news_sentiment", False)),
            bool(getattr(config, "enable_fundamentals", False)),
            bool(getattr(config, "enable_earnings_signals", False)),
            bool(getattr(config, "enable_institutional_flow", False)),
            str(getattr(config, "fundamental_provider", "fmp")),
            # Include a few tickers so a universe change doesn't silently reuse stale caches.
            tuple(sorted(getattr(config, "tickers", []) or [])[:5]),
        )

    def _ensure_providers(self, config) -> None:
        """Initialize module-level data-provider globals for this container.
        Idempotent within-container; re-runs if the relevant flags change."""
        sig = self._provider_signature(config)
        if sig == self._providers_signature:
            return
        from quant.backtest import init_providers_for_config

        initialized = init_providers_for_config(config)
        self._providers_signature = sig
        if initialized:
            logger.info("CPCVWorker providers initialized: %s", initialized)
        else:
            logger.info("CPCVWorker providers: nothing new to initialize (flags=%s)", sig)

    def _load_state(self, panel_key: str):
        """Load panel + adapt to CPCVState once per container-panel pair."""
        if panel_key in self._state_cache:
            return self._state_cache[panel_key]

        import pickle

        panel_path = f"{PANELS_MOUNT_PATH}/{panel_key}.pkl"
        t0 = time.time()
        with open(panel_path, "rb") as f:
            panel = pickle.load(f)
        logger.info("Panel %s loaded in %.2fs", panel_key, time.time() - t0)
        self._panels_cache[panel_key] = panel

        from modal_app.panel import panel_to_cpcv_state

        state = panel_to_cpcv_state(panel)
        self._state_cache[panel_key] = state
        return state

    @modal.method()
    def run_combo(self, spec: dict) -> dict:
        """Run one CPCV combination. Returns a result dict; never raises.

        Expected `spec` keys:
          - panel_key: str   — basename of panel pickle in the Volume
          - combo_idx: int
          - train_indices: list[int]
          - test_indices: list[int]
          - config_json: dict  (becomes BacktestConfig via `_rebuild_config`)
        """
        from quant.backtest import BacktestConfig, _run_single_cpcv_combo

        t0 = time.time()
        panel_key = spec["panel_key"]
        combo_idx = int(spec["combo_idx"])
        try:
            state = self._load_state(panel_key)
            config = _rebuild_config(spec["config_json"])
            self._ensure_providers(config)
            result = _run_single_cpcv_combo(
                state=state,
                train_indices=tuple(spec["train_indices"]),
                test_indices=tuple(spec["test_indices"]),
                combo_idx=combo_idx,
                config=config,
            )
            elapsed = time.time() - t0
            if result is None:
                return {
                    "combo_idx": combo_idx,
                    "status": "skipped",
                    "skip_reason": "insufficient_test_dates_or_no_trades",
                    "git_sha": self._git_sha,
                    "elapsed_seconds": round(elapsed, 3),
                }
            result["status"] = "complete"
            result["git_sha"] = self._git_sha
            result["elapsed_seconds"] = round(elapsed, 3)
            return result
        except Exception as exc:
            import traceback

            return {
                "combo_idx": combo_idx,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=20),
                "git_sha": self._git_sha,
                "elapsed_seconds": round(time.time() - t0, 3),
            }


def _rebuild_config(config_json: dict):
    """Reconstruct a BacktestConfig from a JSON-safe dict, ignoring unknown
    keys so old payloads remain compatible when fields are added."""
    from dataclasses import fields
    from quant.backtest import BacktestConfig

    allowed = {f.name for f in fields(BacktestConfig)}
    filtered = {k: v for k, v in config_json.items() if k in allowed}
    return BacktestConfig(**filtered)


__all__ = ["CPCVWorker"]
