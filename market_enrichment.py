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

    target_mean = info.get("targetMeanPrice")
    if target_mean is not None:
        lines.append(f"Analyst Mean Target: ${float(target_mean):.2f}")
    num_analysts = info.get("numberOfAnalystOpinions")
    if num_analysts is not None:
        lines.append(f"Number of Analysts: {num_analysts}")
    rec = info.get("recommendationKey")
    if rec:
        lines.append(f"Recommendation: {rec}")
    forward_eps = info.get("forwardEps")
    if forward_eps is not None:
        lines.append(f"Forward EPS: ${float(forward_eps):.2f}")
    trailing_eps = info.get("trailingEps")
    if trailing_eps is not None:
        lines.append(f"Trailing EPS: ${float(trailing_eps):.2f}")

    section_text = "\n".join(lines)
    section_text = trim_text(
        section_text,
        int(os.getenv("MAX_MARKET_SECTION_CHARS", "1200")),
    )
    return section_text, ["Yahoo Finance"]


def _analyst_estimates_section(ticker: str) -> tuple[str, List[str]]:
    """Pull analyst estimates and consensus from yfinance."""
    import yfinance as yf

    stock = yf.Ticker(ticker)
    lines = ["=== Analyst Estimates & Consensus ==="]

    try:
        targets = stock.analyst_price_targets
        if targets is not None and not (hasattr(targets, "empty") and targets.empty):
            if isinstance(targets, dict):
                for k, v in targets.items():
                    if v is not None:
                        lines.append(f"  Price Target {k}: ${float(v):.2f}" if "count" not in k.lower() else f"  Analysts Count: {v}")
            else:
                lines.append(f"  Price Targets: {targets}")
    except Exception:
        pass

    try:
        ee = stock.earnings_estimate
        if ee is not None and not (hasattr(ee, "empty") and ee.empty):
            lines.append("  -- EPS Estimates --")
            lines.append(f"  {ee.to_string()}")
    except Exception:
        pass

    try:
        re = stock.revenue_estimate
        if re is not None and not (hasattr(re, "empty") and re.empty):
            lines.append("  -- Revenue Estimates --")
            lines.append(f"  {re.to_string()}")
    except Exception:
        pass

    try:
        et = stock.earnings_trend
        if et is not None and not (hasattr(et, "empty") and et.empty):
            lines.append("  -- Earnings Trend (Revisions) --")
            lines.append(f"  {et.to_string()}")
    except Exception:
        pass

    try:
        ge = stock.growth_estimates
        if ge is not None and not (hasattr(ge, "empty") and ge.empty):
            lines.append("  -- Growth Estimates --")
            lines.append(f"  {ge.to_string()}")
    except Exception:
        pass

    if len(lines) <= 1:
        return "", []

    section = "\n".join(lines)
    section = trim_text(section, int(os.getenv("MAX_ESTIMATES_SECTION_CHARS", "1200")))
    return section, ["Yahoo Finance (analyst estimates)"]


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
    snippet_chars = int(os.getenv("TAVILY_SNIPPET_CHARS", "600"))
    lines = [f"=== {header} ==="]
    for idx, item in enumerate(results[:max_items], start=1):
        title = item.get("title", "Untitled")
        url = item.get("url", "")
        raw = (item.get("raw_content", "") or "").strip()
        content = raw if raw else (item.get("content", "") or "").strip()
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

    use_raw = env_flag("TAVILY_RAW_CONTENT", True)

    company = client.search(
        query=company_query,
        topic="news",
        days=90,
        search_depth="advanced",
        max_results=max_results,
        include_raw_content=use_raw,
    )
    industry = client.search(
        query=industry_query,
        topic="general",
        time_range="month",
        search_depth="advanced",
        max_results=max_results,
        include_raw_content=use_raw,
    )
    risks = client.search(
        query=risks_query,
        topic="news",
        days=90,
        search_depth="advanced",
        max_results=max_results,
        include_raw_content=use_raw,
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
            int(os.getenv("MAX_EXTERNAL_COMPANY_SECTION_CHARS", "2500")),
        ),
        "external_industry": trim_text(
            industry_text,
            int(os.getenv("MAX_EXTERNAL_INDUSTRY_SECTION_CHARS", "2500")),
        ),
        "external_risks": trim_text(
            risks_text,
            int(os.getenv("MAX_EXTERNAL_RISKS_SECTION_CHARS", "2500")),
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


SECTOR_ETF_MAP = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financial Services": "XLF",
    "Financials": "XLF",
    "Energy": "XLE",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Communication Services": "XLC",
}


def _price_history_section(ticker: str) -> tuple[str, List[str]]:
    """2-year weekly price history with pre-computed stats."""
    import yfinance as yf
    import numpy as np

    stock = yf.Ticker(ticker)

    daily = stock.history(period="2y", interval="1d")
    weekly = stock.history(period="2y", interval="1wk")

    if weekly.empty or len(weekly) < 4:
        return "", []

    close = daily["Close"] if not daily.empty else weekly["Close"]
    latest = float(close.iloc[-1])

    lines = ["=== Price History & Technical Data ==="]
    lines.append(f"Current Price: ${latest:.2f}")

    for label, days in [("1M", 21), ("3M", 63), ("6M", 126), ("1Y", 252), ("2Y", 504)]:
        if len(close) > days:
            ret = (latest / float(close.iloc[-days]) - 1)
            lines.append(f"  {label} Return: {ret*100:+.1f}%")

    high_52 = float(close.tail(252).max()) if len(close) >= 252 else float(close.max())
    low_52 = float(close.tail(252).min()) if len(close) >= 252 else float(close.min())
    pct_range = (latest - low_52) / (high_52 - low_52) * 100 if high_52 != low_52 else 50
    lines.append(f"  52-Week High: ${high_52:.2f}")
    lines.append(f"  52-Week Low: ${low_52:.2f}")
    lines.append(f"  Position in 52W Range: {pct_range:.0f}th percentile")

    if len(close) >= 50:
        sma50 = float(close.tail(50).mean())
        lines.append(f"  50-Day SMA: ${sma50:.2f} ({'above' if latest > sma50 else 'below'})")
    if len(close) >= 200:
        sma200 = float(close.tail(200).mean())
        lines.append(f"  200-Day SMA: ${sma200:.2f} ({'above' if latest > sma200 else 'below'})")
        if len(close) >= 50:
            cross = "bullish (golden cross)" if sma50 > sma200 else "bearish (death cross)"
            lines.append(f"  50/200 SMA State: {cross}")

    if len(close) >= 252:
        returns = close.pct_change().dropna()
        ann_vol = float(np.std(returns) * np.sqrt(252))
        lines.append(f"  Annualized Volatility: {ann_vol*100:.1f}%")

    if "Volume" in daily.columns and len(daily) >= 21:
        avg_vol = float(daily["Volume"].tail(252).mean()) if len(daily) >= 252 else float(daily["Volume"].mean())
        recent_vol = float(daily["Volume"].tail(21).mean())
        lines.append(f"  Avg Daily Volume: {avg_vol:,.0f}")
        lines.append(f"  Recent 21-Day Avg Volume: {recent_vol:,.0f}")

    section = "\n".join(lines)
    section = trim_text(section, int(os.getenv("MAX_PRICE_HISTORY_CHARS", "1500")))
    return section, ["Yahoo Finance (price history)"]


def _macro_section(ticker: str) -> tuple[str, List[str]]:
    """Current macro environment: yields, indices, sector ETF."""
    import yfinance as yf
    from datetime import datetime

    lines = ["=== Macro Environment ==="]
    sources: List[str] = ["Yahoo Finance (macro)"]

    yield_tickers = {
        "^TNX": "10-Year Treasury Yield",
        "^FVX": "5-Year Treasury Yield",
        "^IRX": "13-Week T-Bill Rate",
    }
    for sym, label in yield_tickers.items():
        try:
            info = yf.Ticker(sym).info or {}
            val = info.get("regularMarketPrice") or info.get("previousClose")
            if val is not None:
                lines.append(f"  {label}: {float(val):.2f}%")
        except Exception:
            pass

    index_tickers = {"^GSPC": "S&P 500", "^VIX": "VIX"}
    for sym, label in index_tickers.items():
        try:
            t = yf.Ticker(sym)
            info = t.info or {}
            price = info.get("regularMarketPrice") or info.get("previousClose")
            if price is not None:
                lines.append(f"  {label}: {float(price):,.2f}")
            hist = t.history(period="ytd")
            if not hist.empty and len(hist) > 1:
                ytd_ret = float(hist["Close"].iloc[-1]) / float(hist["Close"].iloc[0]) - 1
                lines.append(f"  {label} YTD: {ytd_ret*100:+.1f}%")
        except Exception:
            pass

    try:
        stock_info = yf.Ticker(ticker).info or {}
        sector = stock_info.get("sector", "")
        etf_sym = SECTOR_ETF_MAP.get(sector)
        if etf_sym:
            etf = yf.Ticker(etf_sym)
            hist = etf.history(period="ytd")
            if not hist.empty and len(hist) > 1:
                ytd = float(hist["Close"].iloc[-1]) / float(hist["Close"].iloc[0]) - 1
                lines.append(f"  Sector ETF ({etf_sym} - {sector}) YTD: {ytd*100:+.1f}%")
    except Exception:
        pass

    if env_flag("ENABLE_TAVILY", True):
        try:
            client = _tavily_client()
            year = datetime.now().year
            macro_results = client.search(
                query=f"US economic outlook GDP inflation interest rates {year}",
                topic="news",
                days=30,
                search_depth="basic",
                max_results=2,
            )
            for item in macro_results.get("results", [])[:2]:
                content = (item.get("content", "") or "").strip()
                if content:
                    lines.append(f"  Macro Context: {trim_text(content, 300, marker='...')}")
                    sources.append(f"Tavily macro: {item.get('url', '')}")
                    break
        except Exception:
            pass

    section = "\n".join(lines)
    section = trim_text(section, int(os.getenv("MAX_MACRO_SECTION_CHARS", "1500")))
    return section, sources


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

    if env_flag("ENABLE_PEERS", True):
        try:
            from peer_enrichment import build_peer_comparison
            peer_text, peer_sources = build_peer_comparison(ticker, company_name)
            if peer_text:
                sections.append(peer_text)
                section_map["peer_comparison"] = peer_text
                sources.extend(peer_sources)
        except Exception as exc:
            warnings.append(f"Peer comparison unavailable: {exc}")

    if env_flag("ENABLE_ESTIMATES", True):
        try:
            est_text, est_sources = _analyst_estimates_section(ticker)
            if est_text:
                sections.append(est_text)
                section_map["analyst_estimates"] = est_text
                sources.extend(est_sources)
        except Exception as exc:
            warnings.append(f"Analyst estimates unavailable: {exc}")

    if env_flag("ENABLE_PRICE_HISTORY", True):
        try:
            ph_text, ph_sources = _price_history_section(ticker)
            if ph_text:
                sections.append(ph_text)
                section_map["price_history"] = ph_text
                sources.extend(ph_sources)
        except Exception as exc:
            warnings.append(f"Price history unavailable: {exc}")

    if env_flag("ENABLE_MACRO", True):
        try:
            macro_text, macro_sources = _macro_section(ticker)
            if macro_text:
                sections.append(macro_text)
                section_map["macro_data"] = macro_text
                sources.extend(macro_sources)
        except Exception as exc:
            warnings.append(f"Macro data unavailable: {exc}")

    if warnings:
        warn_text = "\n".join(f"- {w}" for w in warnings)
        sections.append(f"=== Enrichment Warnings ===\n{warn_text}")

    text = "\n\n".join(s for s in sections if s)
    text = trim_text(text, int(os.getenv("ENRICHMENT_MAX_CHARS", "8000")))

    return {
        "text": text,
        "sections": section_map,
        "warnings": warnings,
        "sources": sources,
        "filter_stats": filter_stats,
    }

