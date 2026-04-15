from __future__ import annotations

import logging
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class JobState:
    job_id: str
    ticker: str
    status: str = "pending"
    progress_queue: queue.Queue = field(default_factory=queue.Queue)
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)


_jobs: dict[str, JobState] = {}
_lock = threading.Lock()

MAX_JOB_AGE_S = 3600


def create_job(ticker: str) -> JobState:
    job_id = uuid.uuid4().hex[:12]
    job = JobState(job_id=job_id, ticker=ticker.upper())
    with _lock:
        _gc_old_jobs()
        _jobs[job_id] = job
    return job


def get_job(job_id: str) -> Optional[JobState]:
    with _lock:
        return _jobs.get(job_id)


def _gc_old_jobs() -> None:
    cutoff = time.time() - MAX_JOB_AGE_S
    stale = [k for k, v in _jobs.items() if v.created_at < cutoff]
    for k in stale:
        del _jobs[k]


class ProgressReporter:
    """Drop-in replacement for Streamlit's progress.write()."""

    def __init__(self, job: JobState) -> None:
        self._job = job
        self._step = 0
        self._total = 5

    def write(self, message: str, pct: Optional[int] = None) -> None:
        if pct is None:
            self._step += 1
            pct = min(int(self._step / self._total * 100), 99)
        else:
            pct = max(1, min(int(pct), 99))
        self._job.progress_queue.put({"step": message, "pct": pct})


def run_analysis_job(job: JobState, request) -> None:
    """Run the analysis pipeline in a background thread."""
    import asyncio

    job.status = "running"
    reporter = ProgressReporter(job)

    env_overrides = {
        "LLM_PROVIDER": request.provider,
        "ENABLE_YAHOO": "true" if request.enable_yahoo else "false",
        "ENABLE_TAVILY": "true" if request.enable_tavily else "false",
        "ENABLE_TIINGO": "true" if request.enable_tiingo else "false",
        "ENABLE_FMP": "true" if request.enable_fmp else "false",
        "ENABLE_YAHOO_FALLBACK": "true" if request.enable_yahoo else "false",
        "MAX_AGENT_CONTEXT_CHARS": str(request.max_agent_context_chars),
        "MAX_AGENT_OUTPUT_TOKENS": str(request.max_agent_output_tokens),
        "SYNTHESIS_REPORT_MAX_CHARS": str(request.synthesis_report_max_chars),
        "SYNTHESIS_INPUT_MAX_CHARS": str(request.synthesis_input_max_chars),
        "MAX_SYNTHESIS_OUTPUT_TOKENS": str(request.max_synthesis_output_tokens),
    }

    if request.api_key:
        if request.provider == "anthropic":
            env_overrides["ANTHROPIC_API_KEY"] = request.api_key
        elif request.provider == "openai":
            env_overrides["OPENAI_API_KEY"] = request.api_key
            # User-supplied key → hit real OpenAI, not the CBS proxy
            env_overrides["OPENAI_BASE_URL"] = "https://api.openai.com/v1"
    elif request.provider == "openai":
        cbs_key = os.getenv("OPENAI_CBS_API_KEY") or os.getenv("OPENAI_API_KEY")
        if cbs_key:
            env_overrides["OPENAI_API_KEY"] = cbs_key

    previous: dict[str, Optional[str]] = {}
    for key, value in env_overrides.items():
        previous[key] = os.getenv(key)
        os.environ[key] = value

    try:
        from sec.cache import SECCache
        from sec.client import SECClient
        from orchestrator import Orchestrator
        from report import save_report, save_pdf_report

        cache = SECCache()
        sec_client = SECClient(user_agent=os.getenv("SEC_USER_AGENT", "AIFinancialAnalyst admin@example.com"), cache=cache)
        orchestrator = Orchestrator(
            sec_client=sec_client,
            llm_provider_name=request.provider,
            model=(request.model.strip() if request.model else None),
        )

        async def _pipeline():
            reporter.write(f"Initializing analysis for {job.ticker}...", 2)
            return await orchestrator.run(job.ticker, progress_callback=reporter.write)

        try:
            result = asyncio.run(_pipeline())
        except RuntimeError as re_err:
            if "cannot be called from a running event loop" not in str(re_err):
                raise
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(_pipeline())
            finally:
                loop.close()

        result_dict = result.model_dump()
        save_report(result_dict)
        try:
            save_pdf_report(result_dict)
        except Exception:
            logger.debug("PDF save failed", exc_info=True)

        reporter.write("Analysis complete")
        job.result = result
        job.status = "complete"
        cache.close()

    except Exception as exc:
        logger.error("Analysis job %s failed: %s", job.job_id, exc, exc_info=True)
        job.error = str(exc)
        job.status = "error"
        job.progress_queue.put({"step": f"Error: {exc}", "pct": 100})
    finally:
        for key, old in previous.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
