"""Per-run budgets reach the agents and synthesis (not just os.environ)."""

from unittest.mock import MagicMock

import pytest

from backend.jobs import create_job, run_analysis_job
from backend.schemas import RunAnalysisRequest
from config import settings
from context_budget import RunBudgets
from models import AgentReport
from orchestrator import Orchestrator
from tests.conftest import FakeProvider

BUDGETS = RunBudgets(
    agent_context_chars=5000,
    agent_output_tokens=2500,
    synthesis_report_max_chars=4000,
    synthesis_input_max_chars=28000,
    synthesis_output_tokens=2800,
)


class _CapturingProvider(FakeProvider):
    def __init__(self):
        super().__init__("synthesis")
        self.max_tokens = None

    async def generate(self, system, user, model=None, max_tokens=4096):
        self.max_tokens = max_tokens
        return self._response


def test_orchestrator_hands_budgets_to_every_agent():
    orch = Orchestrator(sec_client=MagicMock(), provider=FakeProvider(), budgets=BUDGETS)
    assert orch.agents
    for agent in orch.agents:
        assert agent.max_tokens == 2500
        assert agent.context_chars == 5000


def test_orchestrator_defaults_to_settings(monkeypatch):
    monkeypatch.setattr(settings, "max_agent_output_tokens", 1234)
    monkeypatch.setattr(settings, "max_synthesis_output_tokens", 4321)
    orch = Orchestrator(sec_client=MagicMock(), provider=FakeProvider())
    assert orch.budgets.synthesis_output_tokens == 4321
    assert all(a.max_tokens == 1234 for a in orch.agents)


def test_agent_context_limit_prefers_run_budget(monkeypatch):
    monkeypatch.setattr(settings, "max_agent_context_chars", 12000)
    orch = Orchestrator(sec_client=MagicMock(), provider=FakeProvider(), budgets=BUDGETS)
    dcf = next(a for a in orch.agents if a.name.startswith("DCF"))
    assert dcf.get_context_limit() == 5000


@pytest.mark.asyncio
async def test_synthesis_uses_run_output_budget():
    provider = _CapturingProvider()
    orch = Orchestrator(sec_client=MagicMock(), provider=provider, budgets=BUDGETS)
    await orch.run_phase2("TEST", "Test Corp", [AgentReport(agent_name="DCF", analysis="x")])
    assert provider.max_tokens == 2800


def test_run_analysis_job_passes_request_budgets(monkeypatch):
    import orchestrator
    import sec.cache
    import sec.client

    seen = {}

    class StopOrchestrator:
        def __init__(self, **kwargs):
            seen.update(kwargs)
            raise RuntimeError("stop before any network call")

    monkeypatch.setattr(orchestrator, "Orchestrator", StopOrchestrator)
    monkeypatch.setattr(sec.cache, "SECCache", MagicMock())
    monkeypatch.setattr(sec.client, "SECClient", MagicMock())

    req = RunAnalysisRequest(
        ticker="NVDA",
        provider="anthropic",
        max_agent_context_chars=5000,
        max_agent_output_tokens=2500,
        synthesis_report_max_chars=4000,
        synthesis_input_max_chars=28000,
        max_synthesis_output_tokens=2800,
    )
    job = create_job("NVDA")
    run_analysis_job(job, req, auto_paper_trade=False)

    assert job.status == "error"
    assert seen["budgets"] == BUDGETS
