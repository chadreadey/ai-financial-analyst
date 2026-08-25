"""
Record/replay cassettes for LLM calls.

Live model calls make evals slow, expensive, and non-deterministic, which is a
bad fit for a pre-merge gate. Recording responses once and replaying them turns
the same suite into something that runs offline in seconds with no API key.

The cassette key is a hash of (provider, model, system prompt, user message), so
editing ``prompts/synthesis.md`` invalidates every entry it covers and the
replay run fails loudly with a miss. That is the intended behaviour: a prompt
change is exactly when you owe the repo a fresh live recording.

Modes:

``replay``
    Never calls a model. Raises :class:`CassetteMiss` on an unknown key.
``record``
    Always calls the wrapped provider and overwrites the entry.
``auto``
    Replays known keys, calls the wrapped provider for the rest.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Iterable, Optional

from llm import LLMProvider

CASSETTE_DIR = Path(__file__).parent / "cassettes"
CASSETTE_VERSION = 1
_PREVIEW_CHARS = 320


class CassetteMiss(RuntimeError):
    """Raised in replay mode when no recording exists for a request."""


def request_key(provider: str, model: str, system: str, user: str) -> str:
    payload = json.dumps(
        {"provider": provider, "model": model, "system": system, "user": user},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


class Cassette:
    """A JSON file of recorded responses, keyed by request hash."""

    def __init__(self, path: Path):
        self.path = path
        self.records: dict[str, dict] = {}
        self._dirty = False
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("version") != CASSETTE_VERSION:
                raise ValueError(
                    f"{path} was written by cassette format v{raw.get('version')}, "
                    f"this build expects v{CASSETTE_VERSION}; re-record it"
                )
            self.records = raw.get("records", {})

    def get(self, key: str) -> Optional[str]:
        record = self.records.get(key)
        return record.get("response") if record else None

    def put(self, key: str, *, model: str, system: str, user: str, response: str) -> None:
        self.records[key] = {
            "model": model,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "system_preview": system[:_PREVIEW_CHARS],
            "user_preview": user[:_PREVIEW_CHARS],
            "response": response,
        }
        self._dirty = True

    def retain(self, keys: Iterable[str]) -> int:
        """
        Drop every record outside ``keys``; returns the number removed.

        Keys are content-addressed, so a prompt edit leaves the superseded
        recording behind as dead weight that also masks a stale cassette from
        the count checks in ``tests/test_evals_harness.py``.
        """
        keep = set(keys)
        stale = [k for k in self.records if k not in keep]
        for key in stale:
            del self.records[key]
        self._dirty = self._dirty or bool(stale)
        return len(stale)

    def save(self) -> None:
        if not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": CASSETTE_VERSION,
            "records": dict(sorted(self.records.items())),
        }
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        self._dirty = False


class CassetteProvider(LLMProvider):
    """An :class:`~llm.LLMProvider` that reads from, and optionally writes to, a cassette."""

    name = "cassette"

    def __init__(
        self,
        cassette: Cassette,
        inner: Optional[LLMProvider] = None,
        mode: str = "replay",
        provider_name: str = "anthropic",
        default_model: str = "claude-sonnet-4-20250514",
    ):
        if mode not in ("replay", "record", "auto"):
            raise ValueError(f"unknown cassette mode {mode!r}")
        if mode != "replay" and inner is None:
            raise ValueError(f"mode={mode!r} needs a live provider to record from")
        self.cassette = cassette
        self.inner = inner
        self.mode = mode
        self.provider_name = inner.name if inner else provider_name
        self.default_model = inner.default_model if inner else default_model
        self.hits = 0
        self.misses = 0
        self._lock = asyncio.Lock()

    async def generate(
        self,
        system: str,
        user: str,
        model: Optional[str] = None,
        max_tokens: int = 4096,
    ) -> str:
        selected = model or self.default_model
        key = request_key(self.provider_name, selected, system, user)

        if self.mode != "record":
            cached = self.cassette.get(key)
            if cached is not None:
                self.hits += 1
                return cached

        self.misses += 1
        if self.mode == "replay":
            raise CassetteMiss(
                f"No recording for key {key} (model={selected}) in {self.cassette.path.name}. "
                "Prompts or case inputs changed since the cassette was made. "
                "Re-record with: python -m evals record --suite <suite>"
            )

        assert self.inner is not None
        response = await self.inner.generate(
            system=system, user=user, model=selected, max_tokens=max_tokens
        )
        async with self._lock:
            self.cassette.put(key, model=selected, system=system, user=user, response=response)
        return response


def open_cassette(suite: str) -> Cassette:
    return Cassette(CASSETTE_DIR / f"{suite}.json")
