"""
Eval case definitions and JSONL loading.

A case is a frozen input to one LLM stage plus whatever ground truth that input
implies. Cases live in ``evals/cases/*.jsonl`` — one JSON object per line so
that adding a case is a one-line diff and ``git blame`` stays useful.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from pydantic import BaseModel, Field

from evals.contracts import ExpectedDecision, signal_scores_from_reports

CASES_DIR = Path(__file__).parent / "cases"


class AgentReportFixture(BaseModel):
    """A canned Phase 1 agent report used as synthesis input."""

    agent_name: str
    #: Which synthesis signal this report feeds (``dcf``, ``risk``, ...).
    signal: str
    text: str


class SynthesisCase(BaseModel):
    """
    One synthesis (Phase 2) eval case.

    The agent reports carry explicit ``SIGNAL_SCORE`` lines, so the verdict the
    prompt's procedure implies is derivable — see :meth:`expected_decision`.
    """

    id: str
    ticker: str
    company_name: str
    agent_reports: list[AgentReportFixture]
    current_price: Optional[float] = None
    #: Free-form labels for slicing results (``adverse_macro``, ``conflict``...).
    tags: list[str] = Field(default_factory=list)
    #: Values that must be absent from the output because no input supports
    #: them, e.g. ``["analyst_consensus"]`` when no consensus was supplied.
    ungrounded_fields: list[str] = Field(default_factory=list)
    #: Optional hand-written overrides for cases where the derived expectation
    #: is not the whole story.
    expect: Dict[str, Any] = Field(default_factory=dict)

    def signal_scores(self) -> Dict[str, float]:
        return signal_scores_from_reports(
            [{"signal": r.signal, "text": r.text} for r in self.agent_reports]
        )

    def has_complete_signal_scores(self) -> bool:
        """
        True when every supplied report carries a ``SIGNAL_SCORE``.

        Only then is :meth:`expected_decision` ground truth. When some reports
        are prose-only the model has to invent those scores, so its weighted sum
        is unknowable in advance and only the internal-consistency checks apply.
        """
        return len(self.signal_scores()) == len(
            {r.signal for r in self.agent_reports if r.signal}
        )

    def expected_decision(self) -> ExpectedDecision:
        return ExpectedDecision.from_signals(self.signal_scores())


class AgentCase(BaseModel):
    """
    One Phase 1 agent eval case.

    ``analysis_data`` is a serialised :class:`models.AnalysisData`. ``null_fields``
    names the structured-output fields the prompt requires to be ``null``
    because the supporting data was deliberately withheld — the primary
    fabrication probe for the earnings agent.
    """

    id: str
    #: Agent key: ``dcf`` | ``risk`` | ``earnings`` | ``competitive`` | ``pattern`` | ``macro``.
    agent: str
    analysis_data: Dict[str, Any]
    tags: list[str] = Field(default_factory=list)
    null_fields: list[str] = Field(default_factory=list)
    #: Numbers that appear nowhere in the input and must not appear in output.
    forbidden_values: list[str] = Field(default_factory=list)
    expect: Dict[str, Any] = Field(default_factory=dict)


def _iter_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        raise FileNotFoundError(f"No eval case file at {path}")
    with path.open(encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno} is not valid JSON: {exc}") from exc


def load_synthesis_cases(path: Optional[Path] = None) -> list[SynthesisCase]:
    source = path or CASES_DIR / "synthesis.jsonl"
    cases = [SynthesisCase.model_validate(row) for row in _iter_jsonl(source)]
    _assert_unique_ids(cases, source)
    return cases


def load_agent_cases(path: Optional[Path] = None) -> list[AgentCase]:
    source = path or CASES_DIR / "agents.jsonl"
    cases = [AgentCase.model_validate(row) for row in _iter_jsonl(source)]
    _assert_unique_ids(cases, source)
    return cases


def _assert_unique_ids(cases: list, source: Path) -> None:
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            raise ValueError(f"Duplicate eval case id '{case.id}' in {source}")
        seen.add(case.id)
