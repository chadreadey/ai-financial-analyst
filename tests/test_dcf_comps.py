"""Tests for the DCF agent comparable company multiples (comps) layer."""

import pytest

from agents.dcf import DCFAgent
from models import AnalysisData


def _make_data(**kwargs) -> AnalysisData:
    defaults = dict(ticker="TEST", company_name="Test Corp")
    defaults.update(kwargs)
    return AnalysisData(**defaults)


# ---------------------------------------------------------------------------
# Test 1: comps block present when pe_ratio and ev_to_ebitda are in metrics
# ---------------------------------------------------------------------------


def test_comps_block_present_with_pe():
    data = _make_data(metrics={"pe_ratio": 25.0, "ev_to_ebitda": 18.0})
    agent = DCFAgent.__new__(DCFAgent)
    context = agent.build_context(data)

    assert "Sector Multiples" in context, "Expected 'Sector Multiples' header in context"
    assert "25.0" in context, "Expected P/E value 25.0 in context"
    assert "18.0" in context, "Expected EV/EBITDA value 18.0 in context"


# ---------------------------------------------------------------------------
# Test 2: no crash and valid output when metrics is empty
# ---------------------------------------------------------------------------


def test_comps_block_absent_without_metrics():
    data = _make_data(metrics={})
    agent = DCFAgent.__new__(DCFAgent)
    context = agent.build_context(data)

    # Must not raise and must return a non-empty string
    assert isinstance(context, str)
    assert len(context) > 0
    # Comps block should NOT appear when there are no multiples
    assert "Sector Multiples" not in context


# ---------------------------------------------------------------------------
# Test 3: system prompt contains MULTIPLES CALIBRATION step
# ---------------------------------------------------------------------------


def test_system_prompt_has_multiples_step():
    assert "MULTIPLES CALIBRATION" in DCFAgent.system_prompt, (
        "Expected 'MULTIPLES CALIBRATION' in DCFAgent.system_prompt"
    )
