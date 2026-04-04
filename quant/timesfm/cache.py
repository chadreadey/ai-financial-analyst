from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_redis_client = None
_redis_checked = False


def get_redis_client():
    global _redis_client, _redis_checked
    if _redis_checked:
        return _redis_client
    _redis_checked = True

    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return None

    try:
        import redis
        client = redis.Redis.from_url(url, decode_responses=True)
        client.ping()
        _redis_client = client
        logger.info("Redis connected: %s", url.split("@")[-1] if "@" in url else url)
        return _redis_client
    except Exception as exc:
        logger.debug("Redis unavailable: %s", exc)
        return None


def get_signals(ticker: str) -> Optional[dict]:
    try:
        client = get_redis_client()
        if client is None:
            return None

        prefix = f"timesfm:{ticker.upper()}:"
        keys = client.keys(f"{prefix}*")
        if not keys:
            return None

        values = client.mget(keys)
        result = {}
        for key, val in zip(keys, values):
            if val is None:
                continue
            signal_type = key.replace(prefix, "")
            try:
                result[signal_type] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                continue

        return result if result else None
    except Exception as exc:
        logger.debug("get_signals(%s) failed: %s", ticker, exc)
        return None


def put_signals(
    ticker: str,
    signal_type: str,
    payload: dict,
    ttl_seconds: int = 86400,
) -> bool:
    try:
        client = get_redis_client()
        if client is None:
            return False

        key = f"timesfm:{ticker.upper()}:{signal_type}"
        client.setex(key, ttl_seconds, json.dumps(payload))
        return True
    except Exception as exc:
        logger.debug("put_signals(%s, %s) failed: %s", ticker, signal_type, exc)
        return False
