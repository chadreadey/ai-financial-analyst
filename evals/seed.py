"""
Write authored responses into a cassette as if a model had produced them.

Two uses:

**Pinning a regression.** When a bad output reaches production, paste it into
``evals/cases/fixture_responses/<case_id>.md`` and seed it. The failure then has
a permanent, zero-cost home in the suite and cannot silently come back, without
needing the model to reproduce it on demand.

**Bootstrapping.** The checked-in fixtures let ``python -m evals run`` work on a
fresh clone with no API key, which is what keeps the harness itself under test
in CI. They are authored, not sampled — they say nothing about how any real
model behaves. To measure that, run ``python -m evals record``.

The cassette key covers the fully rendered prompt, so seeding has to build that
prompt exactly as the runner would. Cases are therefore processed one at a time
with a capturing provider, then written with the authored body.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional, Sequence

from evals.dataset import AgentCase, SynthesisCase, load_agent_cases, load_synthesis_cases
from evals.replay import Cassette, open_cassette, request_key
from evals.runner import RunConfig, run_agent_suite, run_synthesis_suite
from llm import LLMProvider

FIXTURE_DIR = Path(__file__).parent / "cases" / "fixture_responses"

#: Recorded under the provider/model a fresh checkout would replay against.
SEED_PROVIDER = "anthropic"
SEED_MODEL = "claude-sonnet-4-20250514"


class _CapturingProvider(LLMProvider):
    """Records the rendered prompt for a single call and returns nothing."""

    name = SEED_PROVIDER
    default_model = SEED_MODEL

    def __init__(self) -> None:
        self.system: Optional[str] = None
        self.user: Optional[str] = None

    async def generate(
        self,
        system: str,
        user: str,
        model: Optional[str] = None,
        max_tokens: int = 4096,
    ) -> str:
        self.system, self.user = system, user
        return ""


def fixture_path(case_id: str) -> Path:
    return FIXTURE_DIR / f"{case_id}.md"


def load_fixture(case_id: str) -> Optional[str]:
    path = fixture_path(case_id)
    return path.read_text(encoding="utf-8").strip() if path.exists() else None


async def _capture_prompt(case, suite: str) -> tuple[str, str]:
    provider = _CapturingProvider()
    config = RunConfig(suite=suite, mode="record", model=SEED_MODEL, concurrency=1)
    if suite == "synthesis":
        await run_synthesis_suite([case], provider, config)
    else:
        await run_agent_suite([case], provider, config)
    if provider.system is None or provider.user is None:
        raise RuntimeError(f"case {case.id} issued no LLM call")
    return provider.system, provider.user


async def seed_suite(suite: str, cases: Optional[Sequence] = None) -> tuple[int, int]:
    """Seed every case in ``suite`` that has an authored fixture."""
    if cases is None:
        cases = load_synthesis_cases() if suite == "synthesis" else load_agent_cases()
    cassette: Cassette = open_cassette(suite)

    seeded = skipped = 0
    for case in cases:
        body = load_fixture(case.id)
        if body is None:
            skipped += 1
            continue
        system, user = await _capture_prompt(case, suite)
        key = request_key(SEED_PROVIDER, SEED_MODEL, system, user)
        cassette.put(key, model=SEED_MODEL, system=system, user=user, response=body)
        seeded += 1
    cassette.save()
    return seeded, skipped


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m evals.seed", description=__doc__)
    parser.add_argument("--suite", choices=("synthesis", "agents", "all"), default="all")
    args = parser.parse_args(argv)

    suites = ("synthesis", "agents") if args.suite == "all" else (args.suite,)
    for suite in suites:
        seeded, skipped = asyncio.run(seed_suite(suite))
        print(f"  {suite}: seeded {seeded} fixture(s), skipped {skipped} case(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
