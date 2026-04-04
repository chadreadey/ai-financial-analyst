from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
import time
import uuid

from fastapi import APIRouter, HTTPException

from backend.schemas import (
    BacktestConfig as BacktestConfigSchema,
    NLBacktestRequest,
    BacktestRunCreated,
)
from config import settings
from llm import get_provider

logger = logging.getLogger(__name__)
router = APIRouter()

_jobs: dict[str, dict] = {}
CONFIG_VERSION = "1"


def _ensure_backtest_runs_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS backtest_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at REAL,
            config_json TEXT,
            result_json TEXT,
            nl_query TEXT DEFAULT '',
            parser_model TEXT DEFAULT '',
            config_version TEXT DEFAULT '1'
        )
        """
    )
    existing = {r[1] for r in conn.execute("PRAGMA table_info(backtest_runs)").fetchall()}
    if "nl_query" not in existing:
        conn.execute("ALTER TABLE backtest_runs ADD COLUMN nl_query TEXT DEFAULT ''")
    if "parser_model" not in existing:
        conn.execute("ALTER TABLE backtest_runs ADD COLUMN parser_model TEXT DEFAULT ''")
    if "config_version" not in existing:
        conn.execute("ALTER TABLE backtest_runs ADD COLUMN config_version TEXT DEFAULT '1'")
    conn.commit()


def _persist_run(config: BacktestConfigSchema, result: dict, nl_query: str = "", parser_model: str = "") -> None:
    conn = sqlite3.connect(settings.warehouse_db_path)
    try:
        _ensure_backtest_runs_table(conn)
        conn.execute(
            """
            INSERT INTO backtest_runs (run_at, config_json, result_json, nl_query, parser_model, config_version)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                time.time(),
                json.dumps(config.model_dump()),
                json.dumps(result),
                nl_query,
                parser_model,
                CONFIG_VERSION,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _run_backtest(job_id: str, config: BacktestConfigSchema, nl_query: str = "", parser_model: str = ""):
    from backend.backtest_engine import BacktestConfig, BacktestEngine

    _jobs[job_id]["status"] = "running"
    try:
        engine = BacktestEngine()
        bc = BacktestConfig(
            tickers=config.tickers,
            start_date=config.start_date,
            end_date=config.end_date,
        )
        result = engine.run(bc)
        result_dict = result.to_dict()
        _jobs[job_id] = result_dict
        _persist_run(config, result_dict, nl_query=nl_query, parser_model=parser_model)
    except Exception as exc:
        error_payload = {"status": "error", "error": str(exc)}
        _jobs[job_id] = error_payload
        _persist_run(config, error_payload, nl_query=nl_query, parser_model=parser_model)


@router.post("/run")
async def run_backtest(config: BacktestConfigSchema):
    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {"status": "pending"}
    t = threading.Thread(target=_run_backtest, args=(job_id, config, "", ""), daemon=True)
    t.start()
    return {"job_id": job_id}


def _extract_json_block(text: str) -> dict:
    import re

    match = re.search(r"```json\s*\n(\{.*?\})\s*\n```", text, re.DOTALL)
    raw = match.group(1).strip() if match else text.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        sanitized = re.sub(r",\s*([}\]])", r"\1", raw)
        return json.loads(sanitized)


@router.post("/nl", response_model=BacktestRunCreated)
async def run_backtest_nl(payload: NLBacktestRequest):
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    provider = get_provider()
    parser_model = provider.default_model
    schema_prompt = """
You convert natural language backtesting requests into strict JSON.
Output ONLY JSON in this schema:
{
  "tickers": ["AAPL","MSFT"],
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "notes": "short explanation"
}
Rules:
- tickers must be uppercase strings.
- If no dates are provided, default start_date to 2020-01-01 and end_date to today.
- Never include markdown outside the JSON block.
"""
    user_prompt = f"User query:\n{query}"

    try:
        raw = await provider.generate(system=schema_prompt, user=user_prompt, model=parser_model, max_tokens=500)
        parsed = _extract_json_block(raw)
        config = BacktestConfigSchema(
            tickers=[str(t).upper().strip() for t in parsed.get("tickers", []) if str(t).strip()],
            start_date=str(parsed.get("start_date") or "2020-01-01"),
            end_date=str(parsed.get("end_date") or time.strftime("%Y-%m-%d")),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not parse NL request: {exc}")

    if not config.tickers:
        raise HTTPException(status_code=400, detail="No tickers were extracted from the request")

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {"status": "pending", "nl_query": query}
    t = threading.Thread(
        target=_run_backtest,
        args=(job_id, config, query, parser_model),
        daemon=True,
    )
    t.start()
    return BacktestRunCreated(
        job_id=job_id,
        config_version=CONFIG_VERSION,
        parsed_config=config,
        parse_notes=str(parsed.get("notes") or ""),
    )


@router.get("/result/{job_id}")
async def get_backtest_result(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        return {"status": "not_found"}
    return job


@router.get("/history")
async def get_backtest_history():
    try:
        conn = sqlite3.connect(settings.warehouse_db_path)
        _ensure_backtest_runs_table(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM backtest_runs ORDER BY run_at DESC LIMIT 20").fetchall()
        conn.close()
        return {"runs": [dict(r) for r in rows]}
    except Exception:
        return {"runs": []}
