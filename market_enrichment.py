"""
Optional market + external research enrichment for analysis context.

This module is intentionally fail-safe:
- If a provider is disabled or missing credentials, it returns empty sections.
- If network calls fail, it records a short warning and continues.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from importlib import import_module
from typing import Any, Dict, List, Optional, Tuple

from config import settings
from context_budget import trim_text
from utils import env_flag, format_money
from yahoo_cache import YahooLookupCache

logger = logging.getLogger(__name__)

_ENRICHMENT_TASK_ORDER = (
    "market_data",
    "tavily",
    "peers",
    "estimates",
    "price",
    "computed_signals",
    "macro",
    "rag",
    "fmp_extra",
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


def _tiingo_quote_section(ticker: str, tiingo_cache) -> tuple[str, list[str]]:
    """Tiingo EOD quote — price, 52W range, volume."""
    quote = tiingo_cache.get_quote(ticker)
    meta = tiingo_cache.get_meta(ticker)
    if not quote:
        return "", []

    close = quote.get("close")
    date_str = str(quote.get("date", ""))[:10]
    lines = [f"=== Market Data (Tiingo EOD, as of {date_str} close) ==="]
    if close is not None:
        lines.append(f"Current Price: ${float(close):.2f}")
    prev = quote.get("prevClose")
    if prev is not None and close is not None:
        chg = float(close) - float(prev)
        pct = chg / float(prev) * 100 if float(prev) != 0 else 0
        lines.append(f"Day Change: {chg:+.2f} ({pct:+.1f}%)")
    low52 = quote.get("low52Week")
    high52 = quote.get("high52Week")
    if low52 is not None and high52 is not None:
        lines.append(f"52-Week Range: ${float(low52):.2f} - ${float(high52):.2f}")
    vol = quote.get("volume")
    if vol is not None:
        lines.append(f"Volume: {int(vol):,}")

    section = "\n".join(lines)
    section = trim_text(section, settings.max_market_section_chars)
    return section, ["Tiingo (market data)"]


def _fmp_valuation_section(ticker: str, fmp_cache) -> tuple[str, list[str]]:
    """FMP valuation multiples — P/E, EV/EBITDA, P/S, beta, market cap."""
    quote = fmp_cache.get_quote(ticker)
    km = fmp_cache.get_key_metrics(ticker)
    if not quote and not km:
        return "", []

    lines = ["=== Valuation (FMP) ==="]
    mc = quote.get("marketCap")
    if mc:
        lines.append(f"Market Cap: {format_money(mc)}")
    pe = quote.get("pe")
    if pe is not None and pe > 0:
        lines.append(f"P/E (TTM): {float(pe):.2f}")
    else:
        lines.append("P/E (TTM): N/A")
    beta = quote.get("beta")
    if beta is not None:
        lines.append(f"Beta: {float(beta):.2f}")
    ev_ebitda = km.get("evToEbitdaTTM") if km else None
    if ev_ebitda is not None:
        lines.append(f"EV/EBITDA: {float(ev_ebitda):.2f}")
    ps = km.get("priceToSalesRatioTTM") if km else None
    if ps is not None:
        lines.append(f"P/S (TTM): {float(ps):.2f}")

    section = "\n".join(lines)
    section = trim_text(section, settings.max_market_section_chars)
    return section, ["FMP (Financial Modeling Prep)"]


def _fmp_estimates_section(ticker: str, fmp_cache) -> tuple[str, list[str]]:
    """FMP analyst estimates, price targets, earnings surprises."""
    lines = ["=== Analyst Estimates & Consensus (FMP) ==="]

    pt = fmp_cache.get_price_target(ticker)
    if pt:
        for field in ("targetHigh", "targetLow", "targetConsensus", "targetMedian"):
            val = pt.get(field)
            if val is not None:
                label = field.replace("target", "Price Target ")
                lines.append(f"  {label}: ${float(val):.2f}")
        count = pt.get("numberOfAnalysts")
        if count is not None:
            lines.append(f"  Analysts Count: {count}")

    estimates = fmp_cache.get_analyst_estimates(ticker)
    if estimates:
        lines.append("  -- Forward Estimates --")
        for est in estimates[:4]:
            date = est.get("date", "?")
            rev = est.get("estimatedRevenueAvg")
            eps = est.get("estimatedEpsAvg")
            parts = [f"  {date}:"]
            if rev is not None:
                parts.append(f"Rev {format_money(rev)}")
            if eps is not None:
                parts.append(f"EPS ${float(eps):.2f}")
            lines.append(" | ".join(parts))

    surprises = fmp_cache.get_earnings_surprises(ticker)
    if surprises:
        lines.append("  -- Recent Earnings Surprises --")
        for s in surprises[:4]:
            date = s.get("date", "?")
            actual = s.get("epsActual") or s.get("actualEarningResult")
            est_eps = s.get("epsEstimated") or s.get("estimatedEarning")
            if actual is not None and est_eps is not None:
                beat = "BEAT" if float(actual) > float(est_eps) else "MISS"
                lines.append(f"  {date}: ${float(actual):.2f} vs ${float(est_eps):.2f} ({beat})")

    if len(lines) <= 1:
        return "", []

    section = "\n".join(lines)
    section = trim_text(section, settings.max_fmp_estimates_section_chars)
    return section, ["FMP (analyst estimates)"]


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


SECTOR_TAVILY_QUERIES: Dict[str, str] = {
    "Healthcare": "pharmaceutical biotech FDA drug pipeline patent cliff payer pricing regulatory approval",
    "Technology": "cloud SaaS AI enterprise software cybersecurity semiconductor TAM platform",
    "Energy": "oil gas renewable energy transition upstream midstream ESG carbon breakeven",
    "Financial Services": "banking interest rate credit NIM capital adequacy fintech regulation",
    "Financials": "banking interest rate credit NIM capital adequacy fintech regulation",
    "Consumer Cyclical": "retail consumer spending DTC e-commerce brand pricing discretionary",
    "Consumer Defensive": "staples grocery CPG private label input cost consumer demand defensive",
}


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
    ticker: str, company_name: str, sector: str = ""
) -> tuple[Dict[str, str], List[str], Dict[str, int]]:
    client = _tavily_client()
    max_results = settings.tavily_max_results

    company_query = f"{company_name} ({ticker}) stock analysis latest developments"
    industry_query = f"{company_name} industry overview competitive landscape"
    risks_query = f"{company_name} ({ticker}) risks concerns bear case"

    use_raw = settings.tavily_raw_content
    sector_terms = SECTOR_TAVILY_QUERIES.get(sector, "")

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

    def _search_sector() -> dict:
        return client.search(
            query=f"{sector_terms} industry outlook trends {datetime.now().year}",
            topic="general",
            time_range="month",
            search_depth="advanced",
            max_results=max_results,
            include_raw_content=use_raw,
        )

    pool_size = 4 if sector_terms else 3
    with ThreadPoolExecutor(max_workers=pool_size) as pool:
        f_company = pool.submit(_search_company)
        f_industry = pool.submit(_search_industry)
        f_risks = pool.submit(_search_risks)
        f_sector = pool.submit(_search_sector) if sector_terms else None
        company = f_company.result()
        industry = f_industry.result()
        risks = f_risks.result()
        sector_res = f_sector.result() if f_sector else {}

    company_results = company.get("results", [])
    industry_results = industry.get("results", [])
    risk_results = risks.get("results", [])
    sector_results = sector_res.get("results", []) if sector_res else []

    company_text = "\n".join(
        _tavily_results_to_lines("External Research - Company", company_results, max_results)
    )
    industry_text = "\n".join(
        _tavily_results_to_lines("External Research - Industry", industry_results, max_results)
    )
    risks_text = "\n".join(
        _tavily_results_to_lines("External Research - Risks", risk_results, max_results)
    )

    sections: Dict[str, str] = {
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

    if sector_results:
        sector_text = "\n".join(
            _tavily_results_to_lines(
                f"External Research - Sector ({sector})", sector_results, max_results
            )
        )
        sections["external_sector"] = trim_text(
            sector_text, settings.max_sector_tavily_chars
        )

    all_blocks = [company_results, industry_results, risk_results, sector_results]
    sources: List[str] = []
    for block in all_blocks:
        for item in block[:max_results]:
            title = item.get("title", "Untitled")
            url = item.get("url", "")
            if url:
                sources.append(f"{title} - {url}")

    stats = {
        "company_kept": len(company_results[:max_results]),
        "industry_kept": len(industry_results[:max_results]),
        "risks_kept": len(risk_results[:max_results]),
        "sector_kept": len(sector_results[:max_results]),
        "company_dropped": 0,
        "industry_dropped": 0,
        "risks_dropped": 0,
        "sector_dropped": 0,
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

    try:
        daily = stock.history(period="2y", interval="1d")
        weekly = stock.history(period="2y", interval="1wk")
    except Exception:
        logger.debug("Price history unavailable for %s", ticker, exc_info=True)
        return "", []

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


def _tiingo_price_history_section(ticker: str, tiingo_cache) -> tuple[str, list[str]]:
    """2-year daily price history from Tiingo with pre-computed stats."""
    import numpy as np
    import pandas as pd

    two_years_ago = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
    data = tiingo_cache.get_eod_history(ticker, two_years_ago)
    if not data or len(data) < 20:
        return "", []

    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_convert(None)
    df = df.sort_values("date")
    close = df["adjClose"]
    latest = float(close.iloc[-1])

    lines = ["=== Price History & Technical Data (Tiingo) ==="]
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

    if "volume" in df.columns and len(df) >= 21:
        vol_col = df["volume"]
        avg_vol = float(vol_col.tail(252).mean()) if len(df) >= 252 else float(vol_col.mean())
        recent_vol = float(vol_col.tail(21).mean())
        lines.append(f"  Avg Daily Volume: {avg_vol:,.0f}")
        lines.append(f"  Recent 21-Day Avg Volume: {recent_vol:,.0f}")

    section = "\n".join(lines)
    section = trim_text(section, settings.max_price_history_chars)
    return section, ["Tiingo (price history)"]


def _tiingo_index_section(tiingo_cache, sector: str = "") -> tuple[list[str], list[str]]:
    """YTD returns for SPY and sector ETFs via Tiingo."""
    jan1 = datetime(datetime.now().year, 1, 1).strftime("%Y-%m-%d")
    lines: list[str] = []
    sources: list[str] = []

    spy_data = tiingo_cache.get_eod_history("SPY", jan1)
    if spy_data and len(spy_data) >= 2:
        first = float(spy_data[0].get("adjClose", 0))
        last = float(spy_data[-1].get("adjClose", 0))
        if first > 0:
            ytd = (last / first - 1) * 100
            lines.append(f"  S&P 500 (SPY proxy): ${last:,.2f} | YTD: {ytd:+.1f}%")
            sources.append("Tiingo (indices)")

    etf_sym = SECTOR_ETF_MAP.get(sector)
    if etf_sym:
        etf_data = tiingo_cache.get_eod_history(etf_sym, jan1)
        if etf_data and len(etf_data) >= 2:
            first = float(etf_data[0].get("adjClose", 0))
            last = float(etf_data[-1].get("adjClose", 0))
            if first > 0:
                ytd = (last / first - 1) * 100
                lines.append(f"  Sector ETF ({etf_sym} - {sector}) YTD: {ytd:+.1f}%")

    return lines, sources


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
        "VIXCLS": ("CBOE VIX", ""),
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


def _macro_section(
    ticker: str, cache: YahooLookupCache, tiingo_cache=None, sector: str = ""
) -> tuple[str, List[str]]:
    """Current macro environment: FRED primary, Tiingo/Yahoo for indices/sector ETF."""
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
    if tiingo_cache is not None and env_flag("ENABLE_TIINGO"):
        idx_lines, idx_sources = _tiingo_index_section(tiingo_cache, sector)
        lines.extend(idx_lines)
        sources.extend(idx_sources)
    else:
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
            sec = stock_info.get("sector", "")
            etf_sym = SECTOR_ETF_MAP.get(sec)
            if etf_sym:
                etf = yf.Ticker(etf_sym)
                hist = etf.history(period="ytd")
                if not hist.empty and len(hist) > 1:
                    ytd = float(hist["Close"].iloc[-1]) / float(hist["Close"].iloc[0]) - 1
                    lines.append(f"  Sector ETF ({etf_sym} - {sec}) YTD: {ytd*100:+.1f}%")
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


def _task_market_data(
    ticker: str, cache: YahooLookupCache, tiingo_cache=None, fmp_cache=None
) -> Dict[str, Any]:
    sector = ""
    industry = ""
    current_price: Optional[float] = None
    entries: list[tuple[str, str]] = []
    sources: list[str] = []
    warnings: list[str] = []

    tiingo_ok = False
    if tiingo_cache and env_flag("ENABLE_TIINGO"):
        try:
            text, src = _tiingo_quote_section(ticker, tiingo_cache)
            if text:
                entries.append(("market_data", text))
                sources.extend(src)
                tiingo_ok = True
                logger.info("market_data served by tiingo for %s", ticker)
                meta = tiingo_cache.get_meta(ticker)
                sector = meta.get("sector", "") or ""
                industry = meta.get("industry", "") or ""
                # Extract current price from Tiingo quote
                try:
                    tq = tiingo_cache.get_quote(ticker)
                    current_price = float(tq.get("last") or tq.get("close") or 0) or None
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("tiingo quote failed for %s, falling back to FMP: %s", ticker, exc)

    if fmp_cache and env_flag("ENABLE_FMP"):
        try:
            fmp_text, fmp_src = _fmp_valuation_section(ticker, fmp_cache)
            if fmp_text:
                entries.append(("valuation", fmp_text))
                sources.extend(fmp_src)
                if not tiingo_ok:
                    logger.info("market_data served by fmp for %s", ticker)
                fmp_quote = fmp_cache.get_quote(ticker)
                if not sector:
                    sector = fmp_quote.get("sector", "") or ""
                if current_price is None:
                    current_price = float(fmp_quote.get("price") or 0) or None
        except Exception as exc:
            if not tiingo_ok:
                logger.warning("fmp quote failed for %s, falling back to Yahoo: %s", ticker, exc)

    if not entries and env_flag("ENABLE_YAHOO_FALLBACK", default=True):
        try:
            text, src = _yahoo_section(ticker, cache)
            if text:
                entries.append(("market_data", text))
                sources.extend(src)
                logger.info("market_data served by yahoo for %s", ticker)
                if current_price is None:
                    try:
                        info = cache.get_info(ticker)
                        current_price = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0) or None
                    except Exception:
                        pass
        except Exception as exc:
            warnings.append(f"Yahoo enrichment unavailable: {exc}")

    if not entries:
        logger.info("market_data served by empty for %s", ticker)

    if not sector:
        try:
            info = cache.get_info(ticker)
            sector = info.get("sector", "")
            industry = info.get("industry", "")
        except Exception:
            pass

    return {
        "section_entries": entries,
        "sources": sources,
        "warnings": warnings,
        "filter_stats": {},
        "sector": sector,
        "industry": industry,
        "current_price": current_price,
    }


def _task_tavily(
    ticker: str, company_name: str, cache: YahooLookupCache, pre_sector: str = ""
) -> Dict[str, Any]:
    try:
        sector = pre_sector
        if not sector:
            try:
                info = cache.get_info(ticker)
                sector = info.get("sector", "")
            except Exception:
                sector = ""
        tavily_sections, tavily_sources, filter_stats = _tavily_section(
            ticker, company_name, sector=sector
        )
        entries: List[Tuple[str, str]] = []
        for key in ("external_company", "external_industry", "external_risks", "external_sector"):
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


def _task_peers(
    ticker: str, company_name: str, cache: YahooLookupCache, fmp_cache=None
) -> Dict[str, Any]:
    try:
        from peer_enrichment import build_peer_comparison

        peer_text, peer_sources = build_peer_comparison(
            ticker, company_name, cache=cache, fmp_cache=fmp_cache
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


def _task_estimates(
    ticker: str, cache: YahooLookupCache, fmp_cache=None
) -> Dict[str, Any]:
    if fmp_cache and env_flag("ENABLE_FMP"):
        try:
            fmp_text, fmp_src = _fmp_estimates_section(ticker, fmp_cache)
            if fmp_text:
                logger.info("estimates served by fmp for %s", ticker)
                return {
                    "section_entries": [("analyst_estimates", fmp_text)],
                    "sources": fmp_src,
                    "warnings": [],
                    "filter_stats": {},
                }
        except Exception as exc:
            logger.warning("FMP estimates failed for %s, falling back to Yahoo: %s", ticker, exc)

    if env_flag("ENABLE_YAHOO_FALLBACK", default=True):
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

    return {
        "section_entries": [],
        "sources": [],
        "warnings": [],
        "filter_stats": {},
    }


def _task_price(
    ticker: str, cache: YahooLookupCache, tiingo_cache=None
) -> Dict[str, Any]:
    if tiingo_cache and env_flag("ENABLE_TIINGO"):
        try:
            text, src = _tiingo_price_history_section(ticker, tiingo_cache)
            if text:
                logger.info("price_history served by tiingo for %s", ticker)
                return {
                    "section_entries": [("price_history", text)],
                    "sources": src,
                    "warnings": [],
                    "filter_stats": {},
                }
        except Exception as exc:
            logger.warning("Tiingo price history failed for %s: %s", ticker, exc)

    if env_flag("ENABLE_YAHOO_FALLBACK", default=True):
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

    return {
        "section_entries": [],
        "sources": [],
        "warnings": [],
        "filter_stats": {},
    }


def _task_computed_signals(ticker: str, tiingo_cache=None) -> Dict[str, Any]:
    """Compute mathematical technical signals (deterministic, no LLM)."""
    try:
        from quant.signals import compute_signal_vector_from_tiingo
        api_key = os.getenv("TIINGO_API_KEY", "").strip()
        if not api_key or not tiingo_cache:
            return {"section_entries": [], "sources": [], "warnings": [], "filter_stats": {}}

        sv = compute_signal_vector_from_tiingo(ticker, api_key)
        if sv is None:
            return {"section_entries": [], "sources": [], "warnings": [], "filter_stats": {}}

        text = sv.to_enrichment_text()
        return {
            "section_entries": [("computed_signals", text)],
            "sources": ["Computed Technical Signals (math-based)"],
            "warnings": [],
            "filter_stats": {},
            "signal_vector": sv.to_dict(),
        }
    except Exception:
        logger.debug("Computed signals failed for %s", ticker, exc_info=True)
        return {"section_entries": [], "sources": [], "warnings": [], "filter_stats": {}}


def _task_macro(
    ticker: str, cache: YahooLookupCache, tiingo_cache=None, sector: str = ""
) -> Dict[str, Any]:
    if os.getenv("ENABLE_WAREHOUSE", "").lower() == "true":
        try:
            from warehouse.db import WarehouseDB
            from warehouse.reader import get_macro_for_context
            db = WarehouseDB()
            cached_macro = get_macro_for_context(db)
            if cached_macro:
                return {
                    "section_entries": [("macro_data", cached_macro)],
                    "sources": ["Warehouse (macro)"],
                    "warnings": [],
                    "filter_stats": {},
                }
        except Exception:
            logger.debug("Warehouse macro fallback to live", exc_info=True)

    try:
        macro_text, macro_sources = _macro_section(
            ticker, cache, tiingo_cache=tiingo_cache, sector=sector
        )
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


def _task_rag(ticker: str, sector: str = "") -> Dict[str, Any]:
    try:
        from rag_enrichment import fetch_rag_section, fetch_research_rag_section

        entries = []
        sources = []

        rag_text = fetch_rag_section(ticker)
        if rag_text:
            entries.append(("rag_filings", rag_text))
            sources.append("RAG Vector DB (SEC Filings)")

        research_text = fetch_research_rag_section(ticker, sector)
        if research_text:
            entries.append(("rag_research", research_text))
            sources.append("RAG Vector DB (Research Library)")

        return {
            "section_entries": entries,
            "sources": sources,
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


def _fmp_analyst_grades_section(ticker: str, fmp_cache) -> tuple[str, List[str]]:
    """Analyst grades consensus from FMP."""
    grades = fmp_cache.get_grades_summary(ticker)
    if not grades:
        return "", []
    g = grades[0]
    consensus = g.get("consensus", "N/A")
    strong_buy = g.get("strongBuy", 0)
    buy = g.get("buy", 0)
    hold = g.get("hold", 0)
    sell = g.get("sell", 0)
    strong_sell = g.get("strongSell", 0)
    total = strong_buy + buy + hold + sell + strong_sell
    if total == 0:
        return "", []
    lines = ["=== Analyst Grades Consensus (FMP) ==="]
    lines.append(f"  Consensus: {consensus} ({total} analysts)")
    lines.append(f"  Strong Buy: {strong_buy}  |  Buy: {buy}  |  Hold: {hold}  |  Sell: {sell}  |  Strong Sell: {strong_sell}")
    section = "\n".join(lines)
    return section, ["FMP (analyst grades)"]


def _fmp_news_section(ticker: str, fmp_cache) -> tuple[str, List[str]]:
    """Recent stock news from FMP."""
    news = fmp_cache.get_stock_news(ticker, limit=5)
    if not news:
        return "", []
    lines = ["=== Recent News (FMP) ==="]
    for n in news[:5]:
        title = n.get("title", "")
        date = (n.get("publishedDate") or "")[:10]
        source = n.get("site", "")
        lines.append(f"  [{date}] {title} ({source})")
    section = "\n".join(lines)
    return trim_text(section, 800), ["FMP (news)"]


def _fmp_dcf_section(ticker: str, fmp_cache) -> tuple[str, List[str]]:
    """FMP's automated DCF valuation for cross-check."""
    dcf = fmp_cache.get_dcf_valuation(ticker)
    if not dcf:
        return "", []
    price = dcf.get("Stock Price") or dcf.get("stockPrice")
    dcf_val = dcf.get("dcf")
    if dcf_val is None:
        return "", []
    lines = ["=== DCF Cross-Check (FMP) ==="]
    lines.append(f"  FMP DCF Fair Value: ${float(dcf_val):.2f}")
    if price is not None:
        upside = (float(dcf_val) - float(price)) / float(price) * 100
        lines.append(f"  Current Price: ${float(price):.2f}")
        lines.append(f"  Implied Upside/Downside: {upside:+.1f}%")
    return "\n".join(lines), ["FMP (DCF valuation)"]


def _fmp_institutional_section(ticker: str, fmp_cache) -> tuple[str, List[str]]:
    """Top institutional holders from FMP."""
    holders = fmp_cache.get_institutional_holders(ticker)
    if not holders:
        return "", []
    lines = ["=== Top Institutional Holders (FMP) ==="]
    for h in holders[:10]:
        name = h.get("holder", "Unknown")
        shares = h.get("shares", 0)
        change = h.get("change", 0)
        change_str = f" ({change:+,} shares)" if change else ""
        lines.append(f"  {name}: {shares:,} shares{change_str}")
    section = "\n".join(lines)
    return trim_text(section, 800), ["FMP (institutional holders)"]


def _task_fmp_extra(ticker: str, fmp_cache) -> Dict[str, Any]:
    """Run the 4 FMP enrichment sections that aren't wired elsewhere."""
    entries: list[tuple[str, str]] = []
    sources: list[str] = []

    for name, fn in [
        ("fmp_analyst_grades", _fmp_analyst_grades_section),
        ("fmp_news", _fmp_news_section),
        ("fmp_dcf", _fmp_dcf_section),
        ("fmp_institutional", _fmp_institutional_section),
    ]:
        try:
            text, src = fn(ticker, fmp_cache)
            if text:
                entries.append((name, text))
                sources.extend(src)
        except Exception:
            logger.debug("FMP %s failed for %s", name, ticker, exc_info=True)

    return {
        "section_entries": entries,
        "sources": sources,
        "warnings": [],
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

    tiingo_cache = None
    tiingo_key = os.getenv("TIINGO_API_KEY", "").strip()
    if tiingo_key and env_flag("ENABLE_TIINGO"):
        try:
            from tiingo_client import TiingoClient, TiingoCache
            tiingo_cache = TiingoCache(TiingoClient(tiingo_key))
        except Exception:
            logger.debug("Tiingo client init failed", exc_info=True)

    fmp_cache = None
    fmp_key = os.getenv("FMP_API_KEY", "").strip()
    if fmp_key and env_flag("ENABLE_FMP"):
        try:
            from fmp_client import FMPClient, FMPCache
            fmp_cache = FMPCache(FMPClient(fmp_key))
        except Exception:
            logger.debug("FMP client init failed", exc_info=True)

    pre_sector = ""
    pre_industry = ""
    if fmp_cache:
        try:
            q = fmp_cache.get_quote(ticker)
            pre_sector = q.get("sector", "") or ""
        except Exception:
            pass
    if not pre_sector and tiingo_cache:
        try:
            m = tiingo_cache.get_meta(ticker)
            pre_sector = m.get("sector", "") or ""
        except Exception:
            pass

    warnings: List[str] = []
    sources: List[str] = []
    sections: List[str] = []
    section_map: Dict[str, str] = {}
    filter_stats: Dict[str, int] = {}

    worker_cap = max(1, settings.enrichment_max_workers)
    futures: Dict[str, Any] = {}

    with ThreadPoolExecutor(max_workers=worker_cap) as pool:
        futures["market_data"] = pool.submit(
            _task_market_data, ticker, cache, tiingo_cache, fmp_cache
        )
        if settings.enable_tavily:
            futures["tavily"] = pool.submit(
                _task_tavily, ticker, company_name, cache, pre_sector
            )
        if settings.enable_peers:
            futures["peers"] = pool.submit(
                _task_peers, ticker, company_name, cache, fmp_cache
            )
        if settings.enable_estimates:
            futures["estimates"] = pool.submit(
                _task_estimates, ticker, cache, fmp_cache
            )
        if settings.enable_price_history:
            futures["price"] = pool.submit(
                _task_price, ticker, cache, tiingo_cache
            )
        futures["computed_signals"] = pool.submit(
            _task_computed_signals, ticker, tiingo_cache
        )
        if settings.enable_macro:
            futures["macro"] = pool.submit(
                _task_macro, ticker, cache, tiingo_cache, pre_sector
            )
        if settings.enable_rag:
            futures["rag"] = pool.submit(_task_rag, ticker, pre_sector)
        if fmp_cache:
            futures["fmp_extra"] = pool.submit(_task_fmp_extra, ticker, fmp_cache)

        sector = ""
        industry = ""
        current_price = None
        signal_vector = None
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
            if name == "market_data":
                sector = r.get("sector", "") or sector
                industry = r.get("industry", "") or industry
                current_price = r.get("current_price")
            if name == "computed_signals" and r.get("signal_vector"):
                signal_vector = r["signal_vector"]

    if fmp_cache:
        logger.info("fmp_calls_this_run=%d", fmp_cache.call_count)

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
        "sector": sector,
        "industry": industry,
        "current_price": current_price,
        "signal_vector": signal_vector,
    }
