"""Tests for parallel enrichment merge order and helpers."""

from unittest.mock import patch

import pytest

from config import settings
from market_enrichment import build_enrichment_context


@pytest.fixture
def enrichment_only_yahoo_tavily(monkeypatch):
    """Disable all enrichment sections except Yahoo + Tavily."""
    monkeypatch.setattr(settings, "enable_yahoo", True)
    monkeypatch.setattr(settings, "enable_tavily", True)
    monkeypatch.setattr(settings, "enable_peers", False)
    monkeypatch.setattr(settings, "enable_estimates", False)
    monkeypatch.setattr(settings, "enable_price_history", False)
    monkeypatch.setattr(settings, "enable_macro", False)
    monkeypatch.setattr(settings, "enable_rag", False)
    monkeypatch.setattr(settings, "enrichment_max_workers", 4)


def test_build_enrichment_context_merge_order_yahoo_before_tavily(
    enrichment_only_yahoo_tavily, monkeypatch
):
    """Stable ordering: market_data section precedes Tavily sections in merged text."""

    def fake_yahoo(ticker, cache):
        return {
            "section_entries": [("market_data", "===MARKER_YAHOO===")],
            "sources": ["Y"],
            "warnings": [],
            "filter_stats": {},
        }

    def fake_tavily(ticker, company_name):
        return {
            "section_entries": [("external_company", "===MARKER_TAVILY===")],
            "sources": [],
            "warnings": [],
            "filter_stats": {"company_kept": 1},
        }

    with patch("market_enrichment._task_yahoo", side_effect=fake_yahoo), patch(
        "market_enrichment._task_tavily", side_effect=fake_tavily
    ):
        out = build_enrichment_context("ZZZ", "Z Corp")

    text = out["text"]
    assert text.index("===MARKER_YAHOO===") < text.index("===MARKER_TAVILY===")
    assert out["sections"]["market_data"] == "===MARKER_YAHOO==="
    assert out["sections"]["external_company"] == "===MARKER_TAVILY==="
    assert out["filter_stats"].get("company_kept") == 1
