from __future__ import annotations

import logging
import sqlite3

from fastapi import APIRouter

from config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/history/{ticker}")
async def get_recommendation_history(ticker: str):
    ticker = ticker.upper()
    try:
        conn = sqlite3.connect(settings.warehouse_db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM analysis_history WHERE ticker = ? ORDER BY run_at DESC",
            (ticker,),
        ).fetchall()
        conn.close()

        records = []
        for r in rows:
            entry = r["entry_price_at_run"] if "entry_price_at_run" in r.keys() else None
            target = r["price_target"] if "price_target" in r.keys() else None
            records.append(
                {
                    "run_at": r["run_at"],
                    "verdict": r["verdict"],
                    "conviction": r["conviction"] or "",
                    "composite_score": r["composite_score"],
                    "entry_price": entry,
                    "target_price": target,
                    "time_horizon": r["time_horizon"] if "time_horizon" in r.keys() else None,
                    "outcome": None,
                    "outcome_price": None,
                    "outcome_date": None,
                }
            )
        return {"records": records}
    except sqlite3.OperationalError:
        return {"records": []}
