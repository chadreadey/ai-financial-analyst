"""
Optional market + external research enrichment for analysis context.

This module is intentionally fail-safe:
- If a provider is disabled or missing credentials, it returns empty sections.
- If network calls fail, it records a short warning and continues.
"""

import os
from importlib import import_module
from typing import Dict, List

from context_budget import trim_text
from utils import env_flag, format_money


def _yahoo_section(ticker: str) -> tuple[str, List[str]]:
    import yfinance as yf

    stock = yf.Ticker(ticker)
    info = stock.info or {}

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    market_cap = info.get("marketCap")
    trailing_pe = info.get("trailingPE")
    forward_pe = info.get("forwardPE")
    ps = info.get("priceToSalesTrailing12Months")
    ev_ebitda = info.get("enterpriseToEbitda")
    low_52 = info.get("fiftyTwoWeekLow")
    high_52 = info.get("fiftyTwoWeekHigh")
    beta = info.get("beta")

    lines = ["=== Live Market Data (Yahoo Finance) ==="]
    if price is not None:
        lines.append(f"Current Price: ${float(price):.2f}")
    lines.append(f"Market Cap: {format_money(market_cap)}")
    if trailing_pe is not None:
        lines.append(f"P/E (TTM): {float(trailing_pe):.2f}")
    if forward_pe is not None:
        lines.append(f"P/E (Forward): {float(forward_pe):.2f}")
    if ps is not None:
        lines.append(f"P/S (TTM): {float(ps):.2f}")
    if ev_ebitda is not None:
        lines.append(f"EV/EBITDA: {float(ev_ebitda):.2f}")
    if low_52 is not None and high_52 is not None:
        lines.append(f"52-Week Range: ${float(low_52):.2f} - ${float(high_52):.2f}")
    if beta is not None:
        lines.append(f"Beta: {float(beta):.2f}")

    section_text = "\n".join(lines)
    section_text = trim_text(
        section_text,
        int(os.getenv("MAX_MARKET_SECTION_CHARS", "900")),
    )
    return section_text, ["Yahoo Finance"]


def _tavily_client():
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key:
        raise ValueError("TAVILY_API_KEY is not set")
    tavily_module = import_module("tavily")
    tavily_client_cls = getattr(tavily_module, "TavilyClient")
    return tavily_client_cls(api_key=key)


def _tavily_results_to_lines(header: str, results: List[dict], max_items: int = 3) -> List[str]:
    if not results:
        return []
    snippet_chars = int(os.getenv("TAVILY_SNIPPET_CHARS", "220"))
    lines = [f"=== {header} ==="]
    for idx, item in enumerate(results[:max_items], start=1):
        title = item.get("title", "Untitled")
        url = item.get("url", "")
        content = (item.get("content", "") or "").strip()
        snippet = trim_text(content, snippet_chars, marker="...")
        lines.append(f"{idx}. {title}")
        if url:
            lines.append(f"   Source: {url}")
        if snippet:
            lines.append(f"   {snippet}")
    return lines


def _tavily_section(
    ticker: str, company_name: str
) -> tuple[Dict[str, str], List[str], Dict[str, int]]:
    client = _tavily_client()
    max_results = int(os.getenv("TAVILY_MAX_RESULTS", "3"))

    company_query = f"{company_name} ({ticker}) stock analysis latest developments"
    industry_query = f"{company_name} industry overview competitive landscape"
    risks_query = f"{company_name} ({ticker}) risks concerns bear case"

    company = client.search(
        query=company_query,
        topic="news",
        days=90,
        search_depth="advanced",
        max_results=max_results,
    )
    industry = client.search(
        query=industry_query,
        topic="general",
        time_range="month",
        search_depth="advanced",
        max_results=max_results,
    )
    risks = client.search(
        query=risks_query,
        topic="news",
        days=90,
        search_depth="advanced",
        max_results=max_results,
    )

    company_results_raw = company.get("results", [])
    industry_results_raw = industry.get("results", [])
    risk_results_raw = risks.get("results", [])

    company_results = company_results_raw
    industry_results = industry_results_raw
    risk_results = risk_results_raw

    company_text = "\n".join(
        _tavily_results_to_lines("External Research - Company", company_results, max_results)
    )
    industry_text = "\n".join(
        _tavily_results_to_lines("External Research - Industry", industry_results, max_results)
    )
    risks_text = "\n".join(
        _tavily_results_to_lines("External Research - Risks", risk_results, max_results)
    )

    sections = {
        "external_company": trim_text(
            company_text,
            int(os.getenv("MAX_EXTERNAL_COMPANY_SECTION_CHARS", "1200")),
        ),
        "external_industry": trim_text(
            industry_text,
            int(os.getenv("MAX_EXTERNAL_INDUSTRY_SECTION_CHARS", "1200")),
        ),
        "external_risks": trim_text(
            risks_text,
            int(os.getenv("MAX_EXTERNAL_RISKS_SECTION_CHARS", "1200")),
        ),
    }

    sources: List[str] = []
    for block in [company_results, industry_results, risk_results]:
        for item in block[:max_results]:
            title = item.get("title", "Untitled")
            url = item.get("url", "")
            if url:
                sources.append(f"{title} - {url}")

    stats = {
        "company_kept": len(company_results[:max_results]),
        "industry_kept": len(industry_results[:max_results]),
        "risks_kept": len(risk_results[:max_results]),
        "company_dropped": 0,
        "industry_dropped": 0,
        "risks_dropped": 0,
    }
    return sections, sources, stats


def build_enrichment_context(ticker: str, company_name: str) -> Dict[str, object]:
    """
    Build optional enrichment context for downstream prompts.

    Returns:
      {
        "text": str,
        "warnings": list[str],
        "sources": list[str],
      }
    """
    warnings: List[str] = []
    sources: List[str] = []
    sections: List[str] = []
    section_map: Dict[str, str] = {}
    filter_stats: Dict[str, int] = {}

    if env_flag("ENABLE_YAHOO", True):
        try:
            yahoo_text, yahoo_sources = _yahoo_section(ticker)
            sections.append(yahoo_text)
            section_map["market_data"] = yahoo_text
            sources.extend(yahoo_sources)
        except Exception as exc:
            warnings.append(f"Yahoo enrichment unavailable: {exc}")

    if env_flag("ENABLE_TAVILY", True):
        try:
            tavily_sections, tavily_sources, filter_stats = _tavily_section(ticker, company_name)
            for key in ("external_company", "external_industry", "external_risks"):
                if tavily_sections.get(key):
                    section_map[key] = tavily_sections[key]
                    sections.append(tavily_sections[key])
            sources.extend(tavily_sources)
        except Exception as exc:
            warnings.append(f"Tavily enrichment unavailable: {exc}")

    if warnings:
        warn_text = "\n".join(f"- {w}" for w in warnings)
        sections.append(f"=== Enrichment Warnings ===\n{warn_text}")

    text = "\n\n".join(s for s in sections if s)
    text = trim_text(text, int(os.getenv("ENRICHMENT_MAX_CHARS", "3500")))

    return {
        "text": text,
        "sections": section_map,
        "warnings": warnings,
        "sources": sources,
        "filter_stats": filter_stats,
    }

