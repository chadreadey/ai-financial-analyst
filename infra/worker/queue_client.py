"""
Upstash Redis queue client for the filing update pipeline.

Uses the upstash-redis HTTP SDK — no persistent TCP connection required.
Safe for serverless deployments (Fly.io machines, Lambda, etc.).

Install:
    pip install upstash-redis

Environment:
    UPSTASH_REDIS_REST_URL    — Upstash REST endpoint, e.g. https://xxx.upstash.io
    UPSTASH_REDIS_REST_TOKEN  — Upstash REST token
"""

import json
import logging
import os
import time

from upstash_redis import Redis

logger = logging.getLogger(__name__)

# ── Redis key constants ───────────────────────────────────────────────────────
QUEUE_KEY = "queue:filing_updates"
DEAD_LETTER_KEY = "queue:filing_updates:dead"
PROCESSING_SET_KEY = "processing:accessions"
PROCESSING_TTL_SECONDS = 3600  # 1 hour — stale entries expire automatically


def _get_redis() -> Redis:
    """Create a Redis client from environment variables."""
    url = os.environ.get("UPSTASH_REDIS_REST_URL", "").strip()
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "").strip()
    if not url or not token:
        raise EnvironmentError(
            "UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN must be set."
        )
    return Redis(url=url, token=token)


# ── Public API ────────────────────────────────────────────────────────────────

def enqueue_filing_update(
    ticker: str,
    accession: str,
    form: str,
    filing_date: str,
) -> None:
    """
    Push a filing update job to the head of the queue (LPUSH).

    The consumer uses RPOP which pops from the tail, giving FIFO order
    when jobs are pushed one at a time.

    Args:
        ticker:       Uppercase ticker symbol, e.g. "AAPL"
        accession:    SEC accession number, e.g. "0000320193-25-000079"
        form:         Filing form type, e.g. "10-K"
        filing_date:  Filing date string, e.g. "2025-11-01"
    """
    payload = {
        "ticker": ticker.upper(),
        "accession": accession,
        "form": form,
        "filing_date": filing_date,
        "enqueued_at": time.time(),
    }
    redis = _get_redis()
    redis.lpush(QUEUE_KEY, json.dumps(payload))
    logger.debug("enqueued job for %s accession=%s", ticker, accession)


def dequeue_job(block_seconds: int = 5) -> dict | None:
    """
    Pop a job from the tail of the queue (RPOP), polling until block_seconds elapses.

    Upstash HTTP SDK does not support BRPOP (blocking ops require a persistent
    TCP connection). We poll with RPOP in a tight loop instead — on Fly.io this
    is a local network call so latency is negligible.

    Returns the parsed job dict, or None if the queue was empty for the
    entire polling window.
    """
    redis = _get_redis()
    deadline = time.time() + block_seconds
    while time.time() < deadline:
        raw = redis.rpop(QUEUE_KEY)
        if raw is not None:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                logger.error("failed to parse job payload: %r", raw)
                return None
        time.sleep(0.25)
    return None


def mark_processing(accession: str) -> None:
    """
    Add an accession to the processing set (SADD) and refresh the set TTL.

    The TTL is applied to the whole set key. Because Upstash Redis does not
    support per-member TTLs in sets, the TTL is reset on every write. This
    means the set won't expire while any worker is active — which is the
    desired behavior.
    """
    redis = _get_redis()
    redis.sadd(PROCESSING_SET_KEY, accession)
    redis.expire(PROCESSING_SET_KEY, PROCESSING_TTL_SECONDS)
    logger.debug("marked processing: %s", accession)


def unmark_processing(accession: str) -> None:
    """Remove an accession from the processing set (SREM)."""
    redis = _get_redis()
    redis.srem(PROCESSING_SET_KEY, accession)
    logger.debug("unmarked processing: %s", accession)


def is_processing(accession: str) -> bool:
    """Return True if the accession is currently in the processing set (SISMEMBER)."""
    redis = _get_redis()
    return bool(redis.sismember(PROCESSING_SET_KEY, accession))


def send_to_dead_letter(job: dict, error: str) -> None:
    """
    Push a failed job to the dead letter queue with error metadata (LPUSH).

    Args:
        job:   The original job dict as returned by dequeue_job().
        error: String representation of the exception or error message.
    """
    payload = {
        **job,
        "error": str(error),
        "failed_at": time.time(),
    }
    redis = _get_redis()
    redis.lpush(DEAD_LETTER_KEY, json.dumps(payload))
    logger.warning(
        "sent to dead letter: ticker=%s accession=%s error=%s",
        job.get("ticker"), job.get("accession"), error,
    )


def queue_depth() -> int:
    """Return the number of jobs currently waiting in the queue (LLEN)."""
    redis = _get_redis()
    return redis.llen(QUEUE_KEY)


# ── Per-ticker Redis metadata helpers ────────────────────────────────────────
# Used by poll_worker.py to cache CIK + last_accession without DB round-trips.

def get_ticker_last_accession(ticker: str) -> str | None:
    """Return the cached last-known accession for a ticker, or None."""
    redis = _get_redis()
    val = redis.get(f"ticker:{ticker.upper()}:last_accession")
    return val if val else None


def set_ticker_last_accession(ticker: str, accession: str) -> None:
    """Cache the latest accession seen for a ticker."""
    redis = _get_redis()
    redis.set(f"ticker:{ticker.upper()}:last_accession", accession)


def set_ticker_cik(ticker: str, cik_padded: str) -> None:
    """Cache the padded CIK for a ticker."""
    redis = _get_redis()
    redis.set(f"ticker:{ticker.upper()}:cik", cik_padded)


def get_ticker_cik(ticker: str) -> str | None:
    """Return the cached padded CIK for a ticker, or None."""
    redis = _get_redis()
    val = redis.get(f"ticker:{ticker.upper()}:cik")
    return val if val else None


def set_ticker_last_checked(ticker: str) -> None:
    """Record the current unix timestamp as the last poll time for a ticker."""
    redis = _get_redis()
    redis.set(f"ticker:{ticker.upper()}:last_checked", str(int(time.time())))
