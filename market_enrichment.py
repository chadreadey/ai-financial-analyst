"""
Optional market + external research enrichment for analysis context.

This module is intentionally fail-safe:
- If a provider is disabled or missing credentials, it returns empty sections.
- If network calls fail, it records a short warning and continues.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from importlib import import_module
from typing import Any, Dict, List, Optional, Tuple

from config import settings
from context_budget import trim_text
from utils import format_money
from yahoo_cache import YahooLookupCache

logger = logging.getLogger(__name__)

# Merge order for parallel enrichment tasks (stable prompts / tests).
_ENRICHMENT_TASK_ORDER = (
    "yahoo",
    "tavily",
    "peers",
    "estimates",
    "price",
    "macro",
    "rag",
)


def _yahoo_section(ticker: str, cache: YahooLookupCache) -> tuple[str, List[str]]:
    info = cache.get_info(ticker)

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
    section_text = trim_text(section_text, settings.max_market_section_chars)
    return section_text, ["Yahoo Finance"]


def _analyst_estimates_section(
    ticker: str, cache: YahooLookupCache
) -> tuple[str, List[str]]:
    """Pull analyst estimates and consensus from yfinance."""
    import yfinance as yf

    cache.get_info(ticker)
    stock = yf.Ticker(ticker)
    lines = ["=== Analyst Estimates & Consensus ==="]

    try:
        targets = stock.analyst_price_targets
        if targets is not None and not (hasattr(targets, "empty") and targets.empty):
            if isinstance(targets, dict):
                for k, v in targets.items():
                    if v is not None:
                        lines.append(
                            f"  Price Target {k}: ${float(v):.2f}"
                            if "count" not in k.lower()
                            else f"  Analysts Count: {v}"
                        )
            else:
                lines.append(f"  Price Targets: {targets}")
    except Exception:
        logger.debug("analyst_price_targets unavailable", exc_info=True)

    try:
        ee = stock.earnings_estimate
        if ee is not None and not (hasattr(ee, "empty") and ee.empty):
            lines.append("  -- EPS Estimates --")
            lines.append(f"  {ee.to_string()}")
    except Exception:
        logger.debug("earnings_estimate unavailable", exc_info=True)

    try:
        re = stock.revenue_estimate
        if re is not None and not (hasattr(re, "empty") and re.empty):
            lines.append("  -- Revenue Estimates --")
            lines.append(f"  {re.to_string()}")
    except Exception:
        logger.debug("revenue_estimate unavailable", exc_info=True)

    try:
        et = stock.earnings_trend
        if et is not None and not (hasattr(et, "empty") and et.empty):
            lines.append("  -- Earnings Trend (Revisions) --")
            lines.append(f"  {et.to_string()}")
    except Exception:
        logger.debug("earnings_trend unavailable", exc_info=True)

    try:
        ge = stock.growth_estimates
        if ge is not None and not (hasattr(ge, "empty") and ge.empty):
            lines.append("  -- Growth Estimates --")
            lines.append(f"  {ge.to_string()}")
    except Exception:
        logger.debug("growth_estimates unavailable", exc_info=True)

    if len(lines) <= 1:
        return "", []

    section = "\n".join(lines)
    section = trim_text(section, settings.max_estimates_section_chars)
    return section, ["Yahoo Finance (analyst estimates)"]


def _tavily_client():
    key = settings.tavily_api_key.strip()
    if not key:
        raise ValueError("TAVILY_API_KEY is not set")
    tavily_module = import_module("tavily")
    tavily_client_cls = getattr(tavily_module, "TavilyClient")
    return tavily_client_cls(api_key=key)


def _tavily_results_to_lines(header: str, results: List[dict], max_items: int = 3) -> List[str]:
    if not results:
        return []
    snippet_chars = settings.tavily_snippet_chars
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
    max_results = settings.tavily_max_results

    company_query = f"{company_name} ({ticker}) stock analysis latest developments"
    industry_query = f"{company_name} industry overview competitive landscape"
    risks_query = f"{company_name} ({ticker}) risks concerns bear case"

    use_raw = settings.tavily_raw_content

    def _search_company() -> dict:
        return client.search(
            query=company_query,
            topic="news",
            days=90,
            search_depth="advanced",
            max_results=max_results,
            include_raw_content=use_raw,
        )

    def _search_industry() -> dict:
        return client.search(
            query=industry_query,
            topic="general",
            time_range="month",
            search_depth="advanced",
            max_results=max_results,
            include_raw_content=use_raw,
        )

    def _search_risks() -> dict:
        return client.search(
            query=risks_query,
            topic="news",
            days=90,
            search_depth="advanced",
            max_results=max_results,
            include_raw_content=use_raw,
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        f_company = pool.submit(_search_company)
        f_industry = pool.submit(_search_industry)
        f_risks = pool.submit(_search_risks)
        company = f_company.result()
        industry = f_industry.result()
        risks = f_risks.result()

    company_results = company.get("results", [])
    industry_results = industry.get("results", [])
    risk_results = risks.get("results", [])

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
            settings.max_external_company_section_chars,
        ),
        "external_industry": trim_text(
            industry_text,
            settings.max_external_industry_section_chars,
        ),
        "external_risks": trim_text(
            risks_text,
            settings.max_external_risks_section_chars,
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


def _price_history_section(ticker: str, cache: YahooLookupCache) -> tuple[str, List[str]]:
    """2-year weekly price history with pre-computed stats."""
    import numpy as np
    import yfinance as yf

    cache.get_info(ticker)
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
            ret = latest / float(close.iloc[-days]) - 1
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
        avg_vol = (
            float(daily["Volume"].tail(252).mean())
            if len(daily) >= 252
            else float(daily["Volume"].mean())
        )
        recent_vol = float(daily["Volume"].tail(21).mean())
        lines.append(f"  Avg Daily Volume: {avg_vol:,.0f}")
        lines.append(f"  Recent 21-Day Avg Volume: {recent_vol:,.0f}")

    section = "\n".join(lines)
    section = trim_text(section, settings.max_price_history_chars)
    return section, ["Yahoo Finance (price history)"]


def _fred_fetch_one(
    fred: Any, series_id: str, label: str, unit: str, one_year_ago: str
) -> Tuple[str, str, str, Optional[Any]]:
    try:
        data = fred.get_series(series_id, observation_start=one_year_ago)
        data = data.dropna()
        return series_id, label, unit, data
    except Exception:
        logger.debug("FRED series %s unavailable", series_id, exc_info=True)
        return series_id, label, unit, None


def _fred_macro_data() -> tuple[List[str], List[str]]:
    """Fetch authoritative macro indicators from FRED (Federal Reserve)."""
    from fredapi import Fred

    api_key = settings.fred_api_key.strip()
    if not api_key:
        return [], []

    fred = Fred(api_key=api_key)
    lines: List[str] = []
    sources: List[str] = ["FRED (Federal Reserve Economic Data)"]

    series_map = {
        "DGS10": ("10-Year Treasury Yield", "%"),
        "DGS2": ("2-Year Treasury Yield", "%"),
        "FEDFUNDS": ("Fed Funds Rate", "%"),
        "CPIAUCSL": ("CPI (Inflation Index)", ""),
        "UNRATE": ("Unemployment Rate", "%"),
        "BAMLH0A0HYM2": ("High Yield Credit Spread", "%"),
        "BAMLC0A0CM": ("IG Credit Spread", "%"),
        "UMCSENT": ("Consumer Sentiment (UMich)", ""),
    }

    one_year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    series_data: Dict[str, Any] = {}
    max_w = max(1, settings.fred_max_workers)
    with ThreadPoolExecutor(max_workers=max_w) as pool:
        futs = {
            pool.submit(_fred_fetch_one, fred, sid, lab, u, one_year_ago): sid
            for sid, (lab, u) in series_map.items()
        }
        for fut in as_completed(futs):
            series_id, label, unit, data = fut.result()
            series_data[series_id] = (label, unit, data)

    for series_id, (label, unit) in series_map.items():
        tup = series_data.get(series_id)
        if not tup:
            continue
        _, _, data = tup
        if data is None or getattr(data, "empty", True):
            continue
        current = float(data.iloc[-1])
        prior = float(data.iloc[0])
        delta = current - prior
        if unit == "%":
            lines.append(f"  {label}: {current:.2f}% (1Y chg: {delta:+.2f}pp)")
        else:
            lines.append(f"  {label}: {current:,.1f} (1Y chg: {delta:+,.1f})")

    dgs10_tup = series_data.get("DGS10")
    dgs2_tup = series_data.get("DGS2")
    try:
        dgs10 = dgs10_tup[2] if dgs10_tup else None
        dgs2 = dgs2_tup[2] if dgs2_tup else None
        if (
            dgs10 is not None
            and dgs2 is not None
            and not dgs10.empty
            and not dgs2.empty
        ):
            spread = float(dgs10.iloc[-1]) - float(dgs2.iloc[-1])
            state = "INVERTED" if spread < 0 else "NORMAL"
            lines.append(f"  2s10s Spread: {spread:+.2f}pp ({state})")
    except Exception:
        logger.debug("Yield curve spread unavailable", exc_info=True)

    return lines, sources


def _macro_section(ticker: str, cache: YahooLookupCache) -> tuple[str, List[str]]:
    """Current macro environment: FRED primary, Yahoo for indices/sector ETF."""
    import yfinance as yf

    lines = ["=== Macro Environment ==="]
    sources: List[str] = []

    if settings.enable_fred:
        try:
            fred_lines, fred_sources = _fred_macro_data()
            if fred_lines:
                lines.append("-- Rates & Economic Indicators (FRED) --")
                lines.extend(fred_lines)
                sources.extend(fred_sources)
        except Exception:
            logger.debug("FRED macro data unavailable", exc_info=True)

    if not any("Treasury" in l for l in lines):
        sources.append("Yahoo Finance (macro)")
        yield_tickers = {
            "^TNX": "10-Year Treasury Yield",
            "^FVX": "5-Year Treasury Yield",
            "^IRX": "13-Week T-Bill Rate",
        }
        for sym, label in yield_tickers.items():
            try:
                info = cache.get_info(sym)
                val = info.get("regularMarketPrice") or info.get("previousClose")
                if val is not None:
                    lines.append(f"  {label}: {float(val):.2f}%")
            except Exception:
                logger.debug("Yahoo yield ticker %s unavailable", sym, exc_info=True)

    lines.append("-- Market Indices --")
    index_tickers = {"^GSPC": "S&P 500", "^VIX": "VIX"}
    for sym, label in index_tickers.items():
        try:
            info = cache.get_info(sym)
            price = info.get("regularMarketPrice") or info.get("previousClose")
            if price is not None:
                lines.append(f"  {label}: {float(price):,.2f}")
            t = yf.Ticker(sym)
            hist = t.history(period="ytd")
            if not hist.empty and len(hist) > 1:
                ytd_ret = float(hist["Close"].iloc[-1]) / float(hist["Close"].iloc[0]) - 1
                lines.append(f"  {label} YTD: {ytd_ret*100:+.1f}%")
        except Exception:
            logger.debug("Yahoo index ticker %s unavailable", sym, exc_info=True)

    try:
        stock_info = cache.get_info(ticker)
        sector = stock_info.get("sector", "")
        etf_sym = SECTOR_ETF_MAP.get(sector)
        if etf_sym:
            etf = yf.Ticker(etf_sym)
            hist = etf.history(period="ytd")
            if not hist.empty and len(hist) > 1:
                ytd = float(hist["Close"].iloc[-1]) / float(hist["Close"].iloc[0]) - 1
                lines.append(f"  Sector ETF ({etf_sym} - {sector}) YTD: {ytd*100:+.1f}%")
    except Exception:
        logger.debug("Sector ETF data unavailable for %s", ticker, exc_info=True)

    if settings.enable_tavily:
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
            logger.debug("Tavily macro search unavailable", exc_info=True)

    section = "\n".join(lines)
    section = trim_text(section, settings.max_macro_section_chars)
    return section, sources


def _task_yahoo(ticker: str, cache: YahooLookupCache) -> Dict[str, Any]:
    try:
        text, src = _yahoo_section(ticker, cache)
        entries = [("market_data", text)] if text else []
        return {
            "section_entries": entries,
            "sources": list(src),
            "warnings": [],
            "filter_stats": {},
        }
    except Exception as exc:
        return {
            "section_entries": [],
            "sources": [],
            "warnings": [f"Yahoo enrichment unavailable: {exc}"],
            "filter_stats": {},
        }


def _task_tavily(ticker: str, company_name: str) -> Dict[str, Any]:
    try:
        tavily_sections, tavily_sources, filter_stats = _tavily_section(
            ticker, company_name
        )
        entries: List[Tuple[str, str]] = []
        for key in ("external_company", "external_industry", "external_risks"):
            if tavily_sections.get(key):
                entries.append((key, tavily_sections[key]))
        return {
            "section_entries": entries,
            "sources": list(tavily_sources),
            "warnings": [],
            "filter_stats": dict(filter_stats),
        }
    except Exception as exc:
        return {
            "section_entries": [],
            "sources": [],
            "warnings": [f"Tavily enrichment unavailable: {exc}"],
            "filter_stats": {},
        }


def _task_peers(ticker: str, company_name: str, cache: YahooLookupCache) -> Dict[str, Any]:
    try:
        from peer_enrichment import build_peer_comparison

        peer_text, peer_sources = build_peer_comparison(
            ticker, company_name, cache=cache
        )
        entries = [("peer_comparison", peer_text)] if peer_text else []
        return {
            "section_entries": entries,
            "sources": list(peer_sources),
            "warnings": [],
            "filter_stats": {},
        }
    except Exception as exc:
        return {
            "section_entries": [],
            "sources": [],
            "warnings": [f"Peer comparison unavailable: {exc}"],
            "filter_stats": {},
        }


def _task_estimates(ticker: str, cache: YahooLookupCache) -> Dict[str, Any]:
    try:
        est_text, est_sources = _analyst_estimates_section(ticker, cache)
        entries = [("analyst_estimates", est_text)] if est_text else []
        return {
            "section_entries": entries,
            "sources": list(est_sources),
            "warnings": [],
            "filter_stats": {},
        }
    except Exception as exc:
        return {
            "section_entries": [],
            "sources": [],
            "warnings": [f"Analyst estimates unavailable: {exc}"],
            "filter_stats": {},
        }


def _task_price(ticker: str, cache: YahooLookupCache) -> Dict[str, Any]:
    try:
        ph_text, ph_sources = _price_history_section(ticker, cache)
        entries = [("price_history", ph_text)] if ph_text else []
        return {
            "section_entries": entries,
            "sources": list(ph_sources),
            "warnings": [],
            "filter_stats": {},
        }
    except Exception as exc:
        return {
            "section_entries": [],
            "sources": [],
            "warnings": [f"Price history unavailable: {exc}"],
            "filter_stats": {},
        }


def _task_macro(ticker: str, cache: YahooLookupCache) -> Dict[str, Any]:
    try:
        macro_text, macro_sources = _macro_section(ticker, cache)
        entries = [("macro_data", macro_text)] if macro_text else []
        return {
            "section_entries": entries,
            "sources": list(macro_sources),
            "warnings": [],
            "filter_stats": {},
        }
    except Exception as exc:
        return {
            "section_entries": [],
            "sources": [],
            "warnings": [f"Macro data unavailable: {exc}"],
            "filter_stats": {},
        }


def _task_rag(ticker: str) -> Dict[str, Any]:
    try:
        from rag_enrichment import fetch_rag_section

        rag_text = fetch_rag_section(ticker)
        entries = [("rag_research", rag_text)] if rag_text else []
        return {
            "section_entries": entries,
            "sources": ["RAG Vector DB"] if rag_text else [],
            "warnings": [],
            "filter_stats": {},
        }
    except Exception as exc:
        return {
            "section_entries": [],
            "sources": [],
            "warnings": [f"RAG enrichment unavailable: {exc}"],
            "filter_stats": {},
        }


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
    cache = YahooLookupCache()
    warnings: List[str] = []
    sources: List[str] = []
    sections: List[str] = []
    section_map: Dict[str, str] = {}
    filter_stats: Dict[str, int] = {}

    worker_cap = max(1, settings.enrichment_max_workers)
    futures: Dict[str, Any] = {}

    with ThreadPoolExecutor(max_workers=worker_cap) as pool:
        if settings.enable_yahoo:
            futures["yahoo"] = pool.submit(_task_yahoo, ticker, cache)
        if settings.enable_tavily:
            futures["tavily"] = pool.submit(_task_tavily, ticker, company_name)
        if settings.enable_peers:
            futures["peers"] = pool.submit(_task_peers, ticker, company_name, cache)
        if settings.enable_estimates:
            futures["estimates"] = pool.submit(_task_estimates, ticker, cache)
        if settings.enable_price_history:
            futures["price"] = pool.submit(_task_price, ticker, cache)
        if settings.enable_macro:
            futures["macro"] = pool.submit(_task_macro, ticker, cache)
        if settings.enable_rag:
            futures["rag"] = pool.submit(_task_rag, ticker)

        for name in _ENRICHMENT_TASK_ORDER:
            fut = futures.get(name)
            if fut is None:
                continue
            r = fut.result()
            for key, text in r["section_entries"]:
                if text:
                    sections.append(text)
                    section_map[key] = text
            sources.extend(r["sources"])
            warnings.extend(r["warnings"])
            filter_stats.update(r.get("filter_stats", {}))

    if warnings:
        warn_text = "\n".join(f"- {w}" for w in warnings)
        sections.append(f"=== Enrichment Warnings ===\n{warn_text}")

    text = "\n\n".join(s for s in sections if s)
    text = trim_text(text, settings.enrichment_max_chars)

    return {
        "text": text,
        "sections": section_map,
        "warnings": warnings,
        "sources": sources,
        "filter_stats": filter_stats,
    }
