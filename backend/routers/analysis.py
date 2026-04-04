import asyncio
import logging
import threading
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.jobs import create_job, get_job, run_analysis_job, JobState
from backend.schemas import RunAnalysisRequest, JobCreated, JobStatus, HistoryDetail

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/run", response_model=JobCreated)
async def run_analysis(req: RunAnalysisRequest):
    job = create_job(req.ticker)
    thread = threading.Thread(
        target=run_analysis_job,
        args=(job, req),
        daemon=True,
    )
    thread.start()
    return JobCreated(job_id=job.job_id)


async def _event_generator(job: JobState) -> AsyncGenerator[str, None]:
    while True:
        try:
            msg = job.progress_queue.get_nowait()
        except Exception:
            if job.status in ("complete", "error"):
                break
            await asyncio.sleep(0.3)
            continue

        yield f"data: {__import__('json').dumps(msg)}\n\n"

    if job.status == "complete" and job.result is not None:
        import json
        payload = {"step": "complete", "result": job.result.model_dump()}
        yield f"data: {json.dumps(payload)}\n\n"
    elif job.status == "error":
        import json
        payload = {"step": "error", "error": job.error or "Unknown error"}
        yield f"data: {json.dumps(payload)}\n\n"


@router.get("/stream/{job_id}")
async def stream_progress(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return StreamingResponse(
        _event_generator(job),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/result/{job_id}")
async def get_result(job_id: str):
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "running" or job.status == "pending":
        return JobStatus(job_id=job_id, status=job.status)
    if job.status == "error":
        return JobStatus(job_id=job_id, status="error", error=job.error)
    if job.result is not None:
        return job.result.model_dump()
    return JobStatus(job_id=job_id, status=job.status)


@router.get("/history")
async def get_history(ticker: str = "", limit: int = 20, offset: int = 0):
    from sec.cache import SECCache
    from backend.history_outcomes import compute_outcome_metrics

    cache = SECCache()
    try:
        entries = cache.get_analysis_history(ticker.upper(), limit=limit, offset=offset)
        for entry in entries:
            entry.update(compute_outcome_metrics(entry))
        return {"entries": entries}
    finally:
        cache.close()


@router.get("/history/{analysis_id}", response_model=HistoryDetail)
async def get_history_detail(analysis_id: str):
    from sec.cache import SECCache
    from backend.history_outcomes import compute_outcome_metrics

    cache = SECCache()
    try:
        detail = cache.get_analysis_detail(analysis_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Analysis not found")
        detail.update(compute_outcome_metrics(detail))
        return HistoryDetail(**detail)
    finally:
        cache.close()
