"""Deterministic, version-stamped config hashing for reproducible backtest runs.

Two configs that produce identical backtest results MUST produce the same hash.
Two configs that produce different results MUST produce different hashes.

Design choices (documented in `.cursor/plans/modal-backtesting.md`):
  - Float rounding to 10 decimals to neutralize 0.1 + 0.2 != 0.3 drift.
  - list[str] fields semantically order-insensitive (e.g. `tickers`) are sorted.
  - datetime / pd.Timestamp coerced to YYYY-MM-DD strings.
  - numpy numeric types coerced to Python ints / floats.
  - Blocklist of fields known not to affect results (see `_EXCLUDED_FIELDS`).
  - Hash output prefixed with `CONFIG_HASH_VERSION` — bump whenever the
    serialization scheme or blocklist changes so old hashes don't silently
    become non-dedup'd.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, is_dataclass
from typing import Any, Iterable


CONFIG_HASH_VERSION = 1

_EXCLUDED_FIELDS: frozenset[str] = frozenset(
    {
        "verbose",
        "output_dir",
        "progress_cb",
        "end_date_is_today",
    }
)

_ORDER_INSENSITIVE_LIST_FIELDS: frozenset[str] = frozenset(
    {
        "tickers",
    }
)

_FLOAT_PRECISION = 10


def _coerce(value: Any) -> Any:
    """Recursively coerce values into JSON-serializable, hash-stable forms."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        # Non-finite floats are not valid JSON (RFC 8259). Map to
        # deterministic string sentinels so two configs with NaN in
        # the same slot still hash identically, but a strict JSON
        # consumer never sees `NaN`/`Infinity` literals.
        if math.isnan(value):
            return "__nan__"
        if math.isinf(value):
            return "__pos_inf__" if value > 0 else "__neg_inf__"
        return round(value, _FLOAT_PRECISION)
    if isinstance(value, str):
        return value
    try:
        import numpy as np

        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            v = float(value)
            if math.isnan(v):
                return "__nan__"
            if math.isinf(v):
                return "__pos_inf__" if v > 0 else "__neg_inf__"
            return round(v, _FLOAT_PRECISION)
    except ImportError:
        pass
    if hasattr(value, "isoformat"):
        iso = value.isoformat()
        return iso[:10] if len(iso) >= 10 else iso
    if isinstance(value, (list, tuple)):
        return [_coerce(v) for v in value]
    if isinstance(value, set):
        return sorted(_coerce(v) for v in value)
    if isinstance(value, dict):
        return {str(k): _coerce(v) for k, v in value.items()}
    return str(value)


def canonical_config(config: Any, extra_excluded: Iterable[str] = ()) -> dict[str, Any]:
    """Return a canonicalized, JSON-safe dict representation of `config`.

    Accepts a dataclass instance, a dict, or any object exposing `__dict__`.
    """
    if is_dataclass(config) and not isinstance(config, type):
        raw = asdict(config)
    elif isinstance(config, dict):
        raw = dict(config)
    elif hasattr(config, "__dict__"):
        raw = dict(vars(config))
    else:
        raise TypeError(
            f"Cannot canonicalize {type(config).__name__}: must be dataclass, dict, "
            "or object with __dict__."
        )

    excluded = _EXCLUDED_FIELDS | frozenset(extra_excluded)

    out: dict[str, Any] = {}
    for key in sorted(raw.keys()):
        if key in excluded:
            continue
        if key.startswith("_"):
            continue
        value = raw[key]
        if key in _ORDER_INSENSITIVE_LIST_FIELDS and isinstance(value, (list, tuple)):
            value = sorted(value)
        out[key] = _coerce(value)
    return out


def config_hash(config: Any, extra_excluded: Iterable[str] = ()) -> str:
    """Return a hex-encoded SHA-256 hash of `config`, prefixed with version.

    Bump `CONFIG_HASH_VERSION` whenever `_EXCLUDED_FIELDS`, `_FLOAT_PRECISION`,
    or the serialization scheme changes.
    """
    canonical = canonical_config(config, extra_excluded=extra_excluded)
    payload = {"_v": CONFIG_HASH_VERSION, "cfg": canonical}
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"v{CONFIG_HASH_VERSION}:{digest}"


__all__ = [
    "CONFIG_HASH_VERSION",
    "canonical_config",
    "config_hash",
]
