"""
Eval execution.

The runner drives the *production* code paths — ``Orchestrator.run_phase2`` for
synthesis, the real agent classes for Phase 1 — with a provider swapped in
underneath. Nothing about prompt assembly, context trimming, or extraction is
re-implemented here, so a regression in any of those shows up as an eval
failure rather than passing unnoticed because the harness took a shortcut.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence

from agents import (
    CompetitiveAgent,
    DCFAgent,
    EarningsAgent,
    MacroAgent,
    PatternAgent,
    RiskAgent,
)
from evals.checks import Sample, grade_agent, grade_synthesis
from evals.dataset import AgentCase, SynthesisCase
from evals.replay import Cassette, CassetteProvider
from evals.report import EvalReport
from llm import LLMProvider
from models import AgentReport, AnalysisData

logger = logging.getLogger(__name__)

AGENT_REGISTRY: dict[str, type] = {
    "dcf": DCFAgent,
    "risk": RiskAgent,
    "earnings": EarningsAgent,
    "competitive": CompetitiveAgent,
    "pattern": PatternAgent,
    "macro": MacroAgent,
}


@dataclass
class RunConfig:
    suite: str
    mode: str = "replay"
    model: Optional[str] = None
    concurrency: int = 4
    #: Repeats per case. Only meaningful against a live provider, where it
    #: measures run-to-run variance at temperature 0 (which is not zero).
    repeats: int = 1
    case_filter: Optional[str] = None


def _select(cases: Sequence[Any], case_filter: Optional[str]) -> list:
    if not case_filter:
        return list(cases)
    return [c for c in cases if case_filter in c.id or case_filter in getattr(c, "tags", [])]


async def _bounded(
    coros: Sequence[Callable[[], Any]], concurrency: int
) -> list:
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def guarded(factory):
        async with semaphore:
            return await factory()

    return await asyncio.gather(*(guarded(c) for c in coros))


async def _timed(call: Callable[[], Any]) -> tuple[str, Optional[str], float]:
    started = time.perf_counter()
    try:
        output = await call()
        error = None
    except Exception as exc:
        output, error = "", f"{type(exc).__name__}: {exc}"
        logger.debug("eval call failed", exc_info=True)
    return output or "", error, (time.perf_counter() - started) * 1000


async def run_synthesis_suite(
    cases: Sequence[SynthesisCase],
    provider: LLMProvider,
    config: RunConfig,
) -> EvalReport:
    from orchestrator import Orchestrator

    orchestrator = Orchestrator(provider=provider, model=config.model)
    selected = _select(cases, config.case_filter)

    def make(case: SynthesisCase) -> Callable[[], Any]:
        async def run() -> Sample:
            reports = [
                AgentReport(agent_name=r.agent_name, analysis=r.text)
                for r in case.agent_reports
            ]
            output, error, latency = await _timed(
                lambda: orchestrator.run_phase2(
                    case.ticker, case.company_name, reports
                )
            )
            return grade_synthesis(case, output, latency_ms=latency, error=error)

        return run

    factories = [make(c) for c in selected for _ in range(config.repeats)]
    samples = await _bounded(factories, config.concurrency)
    return _build_report(config, provider, samples)


async def run_agent_suite(
    cases: Sequence[AgentCase],
    provider: LLMProvider,
    config: RunConfig,
) -> EvalReport:
    selected = _select(cases, config.case_filter)

    def make(case: AgentCase) -> Callable[[], Any]:
        async def run() -> Sample:
            agent_cls = AGENT_REGISTRY.get(case.agent)
            if agent_cls is None:
                return grade_agent(
                    case, "", error=f"unknown agent {case.agent!r}", latency_ms=0.0
                )
            agent = agent_cls(provider=provider, model=config.model)
            data = AnalysisData.model_validate(case.analysis_data)
            output, error, latency = await _timed(lambda: agent.analyze(data))
            return grade_agent(case, output, latency_ms=latency, error=error)

        return run

    factories = [make(c) for c in selected for _ in range(config.repeats)]
    samples = await _bounded(factories, config.concurrency)
    return _build_report(config, provider, samples)


def _build_report(
    config: RunConfig, provider: LLMProvider, samples: List[Sample]
) -> EvalReport:
    hits = getattr(provider, "hits", 0)
    misses = getattr(provider, "misses", 0)
    model = config.model or getattr(provider, "default_model", "unknown")
    return EvalReport(
        suite=config.suite,
        mode=config.mode,
        model=model,
        samples=list(samples),
        cassette_hits=hits,
        cassette_misses=misses,
    )


def build_provider(
    config: RunConfig,
    cassette: Cassette,
    live_provider_name: Optional[str] = None,
) -> CassetteProvider:
    """
    Wrap (or stand in for) a live provider with the cassette layer.

    In ``replay`` mode no live provider is constructed at all, so the suite runs
    without an API key present.
    """
    inner: Optional[LLMProvider] = None
    if config.mode != "replay":
        from llm import get_provider

        inner = get_provider(live_provider_name)
    return CassetteProvider(cassette=cassette, inner=inner, mode=config.mode)
