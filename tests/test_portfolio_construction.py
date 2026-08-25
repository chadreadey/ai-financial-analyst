"""Tests for the Portfolio Construction agent (Phase 2)."""

from __future__ import annotations

import json

import pytest

from agents.portfolio_construction import (
    PortfolioConstructionAgent,
    _extract_json,
    _parse_llm_response,
    select_deterministic,
)


def _mk_candidates(n=15, base_composite=0.5):
    """Return n candidates with descending composites, mixed sectors."""
    sectors = ["Tech", "Financials", "Health Care", "Industrials", "Consumer Discretionary"]
    return [
        {
            "ticker": f"T{i:02d}",
            "composite": base_composite - i * 0.01,
            "sector": sectors[i % len(sectors)],
            "contributions": {
                "qmj_score": 0.2,
                "sue_earnings_score": 0.1,
                "erm_earnings_score": 0.1,
            },
        }
        for i in range(n)
    ]


class TestDeterministicSelect:
    def test_picks_top_by_composite(self):
        candidates = _mk_candidates(15)
        p = select_deterministic(candidates, n_positions=10, max_per_sector=4)
        assert p.picks[0].ticker == "T00"

    def test_respects_sector_cap(self):
        candidates = [
            {"ticker": f"TECH{i}", "composite": 0.5 - i * 0.01, "sector": "Tech"} for i in range(15)
        ]
        p = select_deterministic(candidates, n_positions=10, max_per_sector=3)
        assert len(p.picks) == 3
        assert p.cash_weight == pytest.approx(0.7)
        assert sum(pk.weight for pk in p.picks) + p.cash_weight == pytest.approx(1.0)

    def test_weights_equal_when_full(self):
        candidates = _mk_candidates(20)
        p = select_deterministic(candidates, n_positions=10, max_per_sector=4)
        assert len(p.picks) == 10
        for pk in p.picks:
            assert pk.weight == pytest.approx(0.1)
        assert p.cash_weight == 0.0

    def test_source_is_heuristic(self):
        p = select_deterministic(_mk_candidates(15))
        assert p.source == "heuristic"

    def test_min_composite_filters(self):
        p = select_deterministic(_mk_candidates(15), n_positions=10, min_composite=0.45)
        assert len(p.picks) <= 6

    def test_empty_candidates_all_cash(self):
        p = select_deterministic([], n_positions=10)
        assert p.picks == []
        assert p.cash_weight == 1.0

    def test_to_dict_schema(self):
        p = select_deterministic(_mk_candidates(15))
        d = p.to_dict()
        assert set(d.keys()) == {"picks", "cash_weight", "reasoning", "risk_notes", "source"}
        for pick in d["picks"]:
            assert set(pick.keys()) == {"ticker", "weight", "rationale"}


class TestJSONExtraction:
    def test_extracts_pure_json(self):
        text = '{"picks": [{"ticker": "AAPL", "weight": 1.0}]}'
        assert _extract_json(text) == {"picks": [{"ticker": "AAPL", "weight": 1.0}]}

    def test_extracts_from_markdown_fence(self):
        text = 'Here is the response:\n```json\n{"picks": []}\n```\nDone.'
        assert _extract_json(text) == {"picks": []}

    def test_returns_none_on_malformed(self):
        assert _extract_json("no json here") is None
        assert _extract_json("{unclosed") is None


class TestParseLLMResponse:
    def test_drops_invented_tickers(self):
        candidates = _mk_candidates(5)
        raw = {
            "picks": [
                {"ticker": "T00", "weight": 0.5, "rationale": "strong quality"},
                {"ticker": "FAKE", "weight": 0.5, "rationale": "hallucinated"},
            ],
            "cash_weight": 0.0,
        }
        p = _parse_llm_response(raw, candidates)
        assert [pk.ticker for pk in p.picks] == ["T00"]

    def test_normalizes_weights_to_sum_1(self):
        candidates = _mk_candidates(5)
        raw = {
            "picks": [
                {"ticker": "T00", "weight": 2.0},
                {"ticker": "T01", "weight": 1.0},
                {"ticker": "T02", "weight": 1.0},
            ],
            "cash_weight": 0.0,
        }
        p = _parse_llm_response(raw, candidates)
        assert sum(pk.weight for pk in p.picks) + p.cash_weight == pytest.approx(1.0)
        assert p.picks[0].weight > p.picks[1].weight

    def test_source_is_llm(self):
        raw = {"picks": [], "cash_weight": 1.0}
        p = _parse_llm_response(raw, [])
        assert p.source == "llm"


class _FakeProvider:
    name = "fake"
    default_model = "fake-model"

    def __init__(self, response: str):
        self._response = response

    async def generate(self, system: str, user: str, model=None, max_tokens=4000):
        return self._response


class _ExplodingProvider:
    name = "fake"
    default_model = "fake"

    async def generate(self, system, user, model=None, max_tokens=4000):
        raise RuntimeError("api down")


class TestAgentIntegration:
    @pytest.mark.asyncio
    async def test_agent_returns_portfolio_from_valid_json(self):
        candidates = _mk_candidates(5)
        response = json.dumps(
            {
                "picks": [
                    {"ticker": "T00", "weight": 0.4, "rationale": "top composite"},
                    {"ticker": "T01", "weight": 0.6, "rationale": "quality growth"},
                ],
                "cash_weight": 0.0,
                "reasoning": "concentrated conviction",
                "risk_notes": "sector overweight",
            }
        )
        agent = PortfolioConstructionAgent(provider=_FakeProvider(response))
        p = await agent.select(candidates)
        assert p.source == "llm"
        assert len(p.picks) == 2
        assert p.reasoning == "concentrated conviction"

    @pytest.mark.asyncio
    async def test_agent_falls_back_on_bad_json(self):
        candidates = _mk_candidates(15)
        agent = PortfolioConstructionAgent(provider=_FakeProvider("not json"))
        p = await agent.select(candidates)
        assert p.source == "fallback"
        assert len(p.picks) > 0

    @pytest.mark.asyncio
    async def test_agent_falls_back_on_llm_exception(self):
        candidates = _mk_candidates(15)
        agent = PortfolioConstructionAgent(provider=_ExplodingProvider())
        p = await agent.select(candidates)
        assert p.source == "fallback"
        assert len(p.picks) > 0

    @pytest.mark.asyncio
    async def test_agent_empty_candidates(self):
        agent = PortfolioConstructionAgent(provider=_FakeProvider("{}"))
        p = await agent.select([])
        assert p.picks == []
        assert p.cash_weight == 1.0
