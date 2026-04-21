"""FastAPI endpoints for Modal CPCV backtests (Session 2b).

Read side is served via `backend.backtest_reader` which prefers Supabase when
configured and transparently falls back to SQLite. The POST dispatch spawns
the orchestrator in a daemon thread and returns the new run_id immediately
so the frontend can navigate to the detail view before the run completes.
"""
from __future__ import annotations

import hmac
import logging
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from backend import backtest_reader, cpcv_sqlite, supabase_backtest
from config import settings

logger = logging.getLogger(__name__)


def _require_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> None:
    """Dependency: validates X-API-Key against INTERNAL_API_KEY env var.

    Raises 403 (not 401) to avoid leaking that the endpoint exists and
    requires auth — returning 401 would invite credential-stuffing loops.
    Raises 500 at startup-time if the key is not configured so misconfigured
    deployments fail loudly.
    """
    configured = settings.internal_api_key
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server misconfigured: INTERNAL_API_KEY not set.",
        )
    if not hmac.compare_digest(configured, x_api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden.",
        )


router = APIRouter(dependencies=[Depends(_require_api_key)])


_TICKER_RE = re.compile(r'^[A-Z]{1,5}$')


class ModalCPCVRequest(BaseModel):
    """Payload for POST /backtest/modal.

    Mirrors `scripts/run_modal_cpcv.py` flags. All fields optional beyond
    tickers/universe so the frontend can send a minimal payload with sensible
    defaults.
    """
    tickers: Optional[list[str]] = Field(
        default=None,
        max_length=50,
        description="Up to 50 ticker symbols. Each must match [A-Z]{1,5}.",
    )
    universe: Optional[str] = Field(
        default=None,
        description="Named universe: liquid_10, liquid_20, liquid_50. Used when tickers is omitted.",
    )
    start_date: str = "2020-01-01"
    end_date: str = ""
    n_groups: int = Field(default=16, ge=2, le=24)
    n_test_groups: int = Field(default=8, ge=1, le=12)
    purge_months: int = Field(default=1, ge=0, le=12)
    embargo_months: int = Field(default=1, ge=0, le=12)
    max_combos: Optional[int] = Field(default=None, ge=1, le=12870)
    seed: int = 42
    local: bool = Field(
        default=False,
        description="Run in-process instead of Modal. Useful for debugging only.",
    )

    @field_validator("tickers", mode="before")
    @classmethod
    def validate_tickers(cls, v: object) -> object:
        if v is None:
            return v
        if not isinstance(v, list):
            raise ValueError("tickers must be a list")
        if len(v) > 50:
            raise ValueError(f"tickers list exceeds 50-item limit (got {len(v)})")
        cleaned = []
        for raw in v:
            if not isinstance(raw, str):
                raise ValueError(f"each ticker must be a string, got {type(raw)}")
            t = raw.upper().strip()
            if not _TICKER_RE.match(t):
                raise ValueError(
                    f"Invalid ticker {raw!r}. Must be 1-5 uppercase ASCII letters."
                )
            cleaned.append(t)
        return cleaned


class ModalCPCVKickoff(BaseModel):
    run_id: str
    config_hash: str
    git_sha: str
    status: str


# ── POST: kick off a new CPCV run ─────────────────────────────────────────


@router.post("/modal", response_model=ModalCPCVKickoff)
async def dispatch_modal_cpcv(payload: ModalCPCVRequest) -> ModalCPCVKickoff:
    """Queue a CPCV run on Modal (or locally when local=True). Returns immediately
    with the new run_id so the UI can start polling /runs/{run_id}/events.
    """
    if not payload.tickers and not payload.universe:
        raise HTTPException(400, "Provide either `tickers` or `universe`.")

    try:
        if payload.tickers:
            tickers = list(payload.tickers)  # already validated + uppercased by the model
        else:
            from quant.universe import get_universe
            tickers = list(get_universe(payload.universe))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not resolve universe {payload.universe!r}: {exc}")

    if not tickers:
        raise HTTPException(400, "Resolved ticker list is empty.")

    from quant.backtest import BacktestConfig
    from modal_app.dispatcher import kickoff_cpcv_background

    config = BacktestConfig(
        tickers=tickers,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    try:
        kickoff = kickoff_cpcv_background(
            config,
            n_groups=payload.n_groups,
            n_test_groups=payload.n_test_groups,
            purge_months=payload.purge_months,
            embargo_months=payload.embargo_months,
            max_combos=payload.max_combos,
            seed=payload.seed,
            local=payload.local,
        )
    except Exception as exc:
        logger.exception("Modal kickoff failed")
        raise HTTPException(500, f"Kickoff failed: {exc}")

    return ModalCPCVKickoff(**kickoff)


# ── GET: read-side endpoints ──────────────────────────────────────────────


@router.get("/modal/source")
async def read_source() -> dict[str, Any]:
    """Which backend (supabase|sqlite) is currently serving reads."""
    return {"source": backtest_reader.source()}


@router.get("/modal/runs")
async def list_runs(
    status: Optional[str] = Query(None, pattern="^(queued|running|complete|degraded|failed)$"),
    config_hash: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    # Opportunistically mark obviously stale runs as failed before returning.
    # Cheap (single UPDATE) and avoids dashboards showing perpetual "running".
    try:
        cpcv_sqlite.sweep_stale_runs()
        supabase_backtest.sweep_stale_runs()
    except Exception:
        pass

    runs = backtest_reader.list_runs(
        status=status, config_hash=config_hash, limit=limit, offset=offset,
    )
    return {"source": backtest_reader.source(), "runs": runs, "count": len(runs)}


@router.get("/modal/runs/by-config-hash/{config_hash}")
async def runs_by_config_hash(config_hash: str, limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    runs = backtest_reader.find_runs_by_config_hash(config_hash, limit=limit)
    return {"config_hash": config_hash, "runs": runs, "count": len(runs)}


@router.get("/modal/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    row = backtest_reader.get_run(run_id)
    if not row:
        raise HTTPException(404, f"Run {run_id} not found")
    return row


@router.get("/modal/runs/{run_id}/combinations")
async def get_run_combinations(
    run_id: str,
    order_by: str = Query("oos_sharpe", pattern="^(oos_sharpe|combo_idx|return_pct|n_trades)$"),
    descending: bool = True,
    limit: Optional[int] = Query(None, ge=1, le=20000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    rows = backtest_reader.get_combinations(
        run_id, order_by=order_by, descending=descending,
        limit=limit, offset=offset,
    )
    return {"run_id": run_id, "combinations": rows, "count": len(rows)}


@router.get("/modal/runs/{run_id}/combinations/{combo_idx}/trades")
async def get_combo_trades(
    run_id: str,
    combo_idx: int,
    ticker: Optional[str] = None,
    limit: Optional[int] = Query(None, ge=1, le=5000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    rows = backtest_reader.get_trades(
        run_id, combo_idx=combo_idx, ticker=ticker,
        limit=limit, offset=offset,
    )
    return {
        "run_id": run_id,
        "combo_idx": combo_idx,
        "trades": rows,
        "count": len(rows),
    }


@router.get("/modal/runs/{run_id}/trades")
async def get_run_trades(
    run_id: str,
    ticker: Optional[str] = None,
    limit: Optional[int] = Query(None, ge=1, le=20000),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    rows = backtest_reader.get_trades(
        run_id, ticker=ticker, limit=limit, offset=offset,
    )
    return {"run_id": run_id, "trades": rows, "count": len(rows)}


@router.get("/modal/runs/{run_id}/events")
async def get_run_events(
    run_id: str,
    after_id: Optional[int] = Query(None, ge=0),
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, Any]:
    result = backtest_reader.get_events(run_id, after_id=after_id, limit=limit)
    rows = result["events"]
    return {
        "run_id": run_id,
        "source": result["source"],
        "events": rows,
        "count": len(rows),
    }
