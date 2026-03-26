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

    def fake_market_data(ticker, cache, tiingo_cache=None, fmp_cache=None):
        return {
            "section_entries": [("market_data", "===MARKER_YAHOO===")],
            "sources": ["Y"],
            "warnings": [],
            "filter_stats": {},
            "sector": "",
            "industry": "",
        }

    def fake_tavily(ticker, company_name, cache, pre_sector=""):
        return {
            "section_entries": [("external_company", "===MARKER_TAVILY===")],
            "sources": [],
            "warnings": [],
            "filter_stats": {"company_kept": 1},
        }

    with patch("market_enrichment._task_market_data", side_effect=fake_market_data), patch(
        "market_enrichment._task_tavily", side_effect=fake_tavily
    ):
        out = build_enrichment_context("ZZZ", "Z Corp")

    text = out["text"]
    assert text.index("===MARKER_YAHOO===") < text.index("===MARKER_TAVILY===")
    assert out["sections"]["market_data"] == "===MARKER_YAHOO==="
    assert out["sections"]["external_company"] == "===MARKER_TAVILY==="
    assert out["filter_stats"].get("company_kept") == 1


def test_sector_surfaces_from_yahoo(enrichment_only_yahoo_tavily, monkeypatch):
    """sector/industry from Yahoo task propagate to the return dict."""

    def fake_market_data(ticker, cache, tiingo_cache=None, fmp_cache=None):
        return {
            "section_entries": [("market_data", "data")],
            "sources": [],
            "warnings": [],
            "filter_stats": {},
            "sector": "Healthcare",
            "industry": "Drug Manufacturers",
        }

    def fake_tavily(ticker, company_name, cache, pre_sector=""):
        return {
            "section_entries": [],
            "sources": [],
            "warnings": [],
            "filter_stats": {},
        }

    with patch("market_enrichment._task_market_data", side_effect=fake_market_data), patch(
        "market_enrichment._task_tavily", side_effect=fake_tavily
    ):
        out = build_enrichment_context("PFE", "Pfizer Inc.")

    assert out["sector"] == "Healthcare"
    assert out["industry"] == "Drug Manufacturers"


def test_external_sector_present_for_mapped_sector(
    enrichment_only_yahoo_tavily, monkeypatch
):
    """When Yahoo returns a mapped sector, Tavily task includes external_sector."""

    def fake_market_data(ticker, cache, tiingo_cache=None, fmp_cache=None):
        return {
            "section_entries": [],
            "sources": [],
            "warnings": [],
            "filter_stats": {},
            "sector": "Technology",
            "industry": "Software",
        }

    def fake_tavily(ticker, company_name, cache, pre_sector=""):
        return {
            "section_entries": [
                ("external_company", "company"),
                ("external_sector", "===SECTOR_INTEL==="),
            ],
            "sources": [],
            "warnings": [],
            "filter_stats": {"sector_kept": 3},
        }

    with patch("market_enrichment._task_market_data", side_effect=fake_market_data), patch(
        "market_enrichment._task_tavily", side_effect=fake_tavily
    ):
        out = build_enrichment_context("MSFT", "Microsoft Corp")

    assert "external_sector" in out["sections"]
    assert out["sections"]["external_sector"] == "===SECTOR_INTEL==="


def test_external_sector_absent_for_unmapped_sector(
    enrichment_only_yahoo_tavily, monkeypatch
):
    """When Yahoo returns an unmapped sector, no external_sector key appears."""

    def fake_market_data(ticker, cache, tiingo_cache=None, fmp_cache=None):
        return {
            "section_entries": [],
            "sources": [],
            "warnings": [],
            "filter_stats": {},
            "sector": "Utilities",
            "industry": "Electric Utilities",
        }

    def fake_tavily(ticker, company_name, cache, pre_sector=""):
        return {
            "section_entries": [("external_company", "company")],
            "sources": [],
            "warnings": [],
            "filter_stats": {},
        }

    with patch("market_enrichment._task_market_data", side_effect=fake_market_data), patch(
        "market_enrichment._task_tavily", side_effect=fake_tavily
    ):
        out = build_enrichment_context("NEE", "NextEra Energy")

    assert "external_sector" not in out["sections"]
