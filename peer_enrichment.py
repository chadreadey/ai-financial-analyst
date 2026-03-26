"""
Peer comparison data enrichment.

Discovers peer companies dynamically per-request using industry
classification, market cap range, and validated ticker resolution.
Formats a structured comparison table with sector medians.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from importlib import import_module
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

from config import settings
from context_budget import trim_text
from utils import env_flag, format_money
from yahoo_cache import YahooLookupCache

logger = logging.getLogger(__name__)


PEER_METRICS = [
    ("marketCap", "Market Cap"),
    ("trailingPE", "P/E (TTM)"),
    ("forwardPE", "P/E (Fwd)"),
    ("priceToSalesTrailing12Months", "P/S"),
    ("enterpriseToEbitda", "EV/EBITDA"),
    ("grossMargins", "Gross Margin"),
    ("operatingMargins", "Op Margin"),
    ("totalRevenue", "Revenue"),
    ("revenueGrowth", "Rev Growth"),
]

TICKER_BLOCKLIST = {
    "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN", "HAD",
    "HER", "WAS", "ONE", "OUR", "OUT", "ITS", "HAS", "HIS", "HOW", "TOP",
    "NEW", "NOW", "OLD", "SEE", "WAY", "WHO", "DID", "GET", "LET", "SAY",
    "SHE", "TOO", "USE", "CEO", "CFO", "COO", "IPO", "ETF", "GDP", "USA",
    "NYSE", "SEC", "AI", "EPS", "PE", "PS", "ROE", "ROA", "FCF", "YOY",
    "QOQ", "VS", "EST", "AVG", "TTM", "FWD", "USD", "EUR", "GBP", "CAD",
    "WITH", "FROM", "THIS", "THAT", "WILL", "HAVE", "BEEN", "ALSO", "THAN",
    "MOST", "INTO", "OVER", "SUCH", "MORE", "SOME", "VERY", "WHEN", "WHAT",
    "INC", "LLC", "LTD", "CORP",
}


def _validate_ticker(
    sym: str, cache: Optional[YahooLookupCache] = None, fmp_cache=None
) -> Optional[Dict[str, Any]]:
    """Check that a string is a real tradeable ticker and return its info."""
    import yfinance as yf

    if sym in TICKER_BLOCKLIST or len(sym) < 2:
        return None

    if fmp_cache and env_flag("ENABLE_FMP"):
        try:
            q = fmp_cache.get_quote(sym)
            if q.get("marketCap") and q.get("marketCap") > 0:
                return {
                    "marketCap": q.get("marketCap"),
                    "quoteType": "EQUITY",
                    "shortName": q.get("name", sym),
                    "sector": q.get("sector", ""),
                    "industry": "",
                }
        except Exception:
            logger.debug("FMP validation failed for %s, trying Yahoo", sym, exc_info=True)

    try:
        if cache is not None:
            info = cache.get_info(sym)
        else:
            info = yf.Ticker(sym).info or {}
        if info.get("marketCap") and info.get("quoteType") in ("EQUITY", None):
            return info
    except Exception:
        logger.debug("Ticker validation failed for %s", sym, exc_info=True)
    return None


def _industry_match_score(
    candidate_industry: str,
    candidate_sector: str,
    target_industry: str,
    target_sector: str,
) -> int:
    if candidate_industry == target_industry:
        return 3

    target_words = set(target_industry.lower().replace("-", " ").replace("\u2014", " ").split())
    cand_words = set(candidate_industry.lower().replace("-", " ").replace("\u2014", " ").split())
    filler = {"", "and", "of", "the", "other", "general", "diversified", "specialty"}
    target_words -= filler
    cand_words -= filler
    if target_words and cand_words and target_words & cand_words:
        return 2

    if candidate_sector == target_sector:
        return 1

    return 0


def _market_cap_proximity(subject_cap: float, peer_cap: float) -> float:
    import math
    if subject_cap <= 0 or peer_cap <= 0:
        return 0.0
    ratio = max(subject_cap, peer_cap) / min(subject_cap, peer_cap)
    return max(0.0, 1.0 - math.log10(ratio) / 3.0)


def discover_peers(
    ticker: str,
    company_name: str,
    max_peers: int = 5,
    cache: Optional[YahooLookupCache] = None,
    fmp_cache=None,
) -> List[str]:
    """
    Dynamically discover peer tickers for each request.
    """
    import yfinance as yf

    ticker = ticker.upper()
    sector = ""
    industry = ""
    subject_cap = 0

    if fmp_cache and env_flag("ENABLE_FMP"):
        try:
            q = fmp_cache.get_quote(ticker)
            sector = q.get("sector", "")
            industry = ""
            subject_cap = int(q.get("marketCap") or 0)
        except Exception:
            pass

    if not sector:
        if cache is not None:
            info = cache.get_info(ticker)
        else:
            info = yf.Ticker(ticker).info or {}
        sector = info.get("sector", "")
        industry = info.get("industry", "")
        subject_cap = info.get("marketCap", 0) or 0

    raw_candidates: List[str] = []

    if settings.enable_tavily:
        queries = []
        if industry:
            queries.append(
                f'"{industry}" publicly traded companies competitors '
                f"of {company_name} stock ticker symbols list"
            )
        queries.append(
            f"{company_name} ({ticker}) top direct competitors "
            f"publicly traded stock ticker symbols"
        )

        try:
            key = settings.tavily_api_key.strip()
            if key:
                tavily_module = import_module("tavily")
                client = getattr(tavily_module, "TavilyClient")(api_key=key)
                for query in queries:
                    if len(raw_candidates) >= max_peers * 3:
                        break
                    results = client.search(
                        query=query,
                        topic="general",
                        search_depth="advanced",
                        max_results=5,
                    )
                    for item in results.get("results", []):
                        text = f"{item.get('title', '')} {item.get('content', '')}"
                        found = re.findall(
                            r'(?:^|[\s(,;|])([A-Z]{2,5})(?:[\s),;|.]|$)', text
                        )
                        for t in found:
                            t = t.strip()
                            if (
                                t != ticker
                                and t not in raw_candidates
                                and t not in TICKER_BLOCKLIST
                            ):
                                raw_candidates.append(t)
        except Exception:
            logger.debug("Tavily peer discovery failed", exc_info=True)

    unique_ordered: List[str] = []
    seen_syms = set()
    for sym in raw_candidates:
        if sym in seen_syms:
            continue
        seen_syms.add(sym)
        unique_ordered.append(sym)

    validated_map: Dict[str, Optional[Dict[str, Any]]] = {}
    max_val_workers = max(1, settings.peer_validation_max_workers)
    with ThreadPoolExecutor(max_workers=max_val_workers) as pool:
        future_to_sym = {
            pool.submit(_validate_ticker, sym, cache, fmp_cache): sym for sym in unique_ordered
        }
        for fut in as_completed(future_to_sym):
            sym = future_to_sym[fut]
            validated_map[sym] = fut.result()

    scored: List[Tuple[float, str, Dict[str, Any]]] = []
    for sym in unique_ordered:
        peer_info = validated_map.get(sym)
        if peer_info is None:
            continue

        peer_industry = peer_info.get("industry", "")
        peer_sector = peer_info.get("sector", "")
        peer_cap = peer_info.get("marketCap", 0) or 0

        ind_score = _industry_match_score(
            peer_industry, peer_sector, industry, sector
        )
        cap_score = _market_cap_proximity(subject_cap, peer_cap) if subject_cap else 0.5

        composite = ind_score * 3.0 + cap_score

        scored.append((composite, sym, peer_info))

    scored.sort(key=lambda x: x[0], reverse=True)

    result = [sym for _, sym, _ in scored[:max_peers]]

    if result:
        best_ind_score = _industry_match_score(
            scored[0][2].get("industry", ""),
            scored[0][2].get("sector", ""),
            industry,
            sector,
        )
        peer_ind = scored[0][2].get("industry", "unknown")
        match_label = {3: "exact", 2: "related", 1: "same sector", 0: "cross-sector"}
        logger.info(
            "Peer discovery: %d peers found, best match: %s (%s)",
            len(result),
            match_label.get(best_ind_score, "?"),
            peer_ind,
        )

    return result


def _fetch_peer_metrics(
    peer_ticker: str, cache: Optional[YahooLookupCache] = None, fmp_cache=None
) -> Optional[Dict[str, Any]]:
    """Fetch key metrics for a single peer ticker."""
    import yfinance as yf

    if fmp_cache and env_flag("ENABLE_FMP"):
        try:
            q = fmp_cache.get_quote(peer_ticker)
            km = fmp_cache.get_key_metrics(peer_ticker)
            if not q.get("marketCap"):
                raise ValueError("no marketCap")
            return {
                "ticker": peer_ticker,
                "marketCap": int(q.get("marketCap") or 0),
                "trailingPE": q.get("pe") if q.get("pe") and q["pe"] > 0 else None,
                "forwardPE": None,
                "priceToSalesTrailing12Months": km.get("priceToSalesRatioTTM") if km else None,
                "enterpriseToEbitda": km.get("evToEbitdaTTM") if km else None,
                "grossMargins": km.get("grossProfitMarginTTM") if km else None,
                "operatingMargins": km.get("operatingProfitMarginTTM") if km else None,
                "totalRevenue": None,
                "revenueGrowth": None,
                "shortName": q.get("name", peer_ticker),
                "industry": "",
                "sector": q.get("sector", ""),
            }
        except Exception:
            logger.debug("FMP peer metrics failed for %s, trying Yahoo", peer_ticker, exc_info=True)

    try:
        if cache is not None:
            info = cache.get_info(peer_ticker)
        else:
            info = yf.Ticker(peer_ticker).info or {}
        if not info.get("marketCap"):
            return None
        result: Dict[str, Any] = {"ticker": peer_ticker}
        for key, _ in PEER_METRICS:
            result[key] = info.get(key)
        result["shortName"] = info.get("shortName", peer_ticker)
        result["industry"] = info.get("industry", "")
        result["sector"] = info.get("sector", "")
        return result
    except Exception:
        logger.debug("Failed to fetch peer metrics for %s", peer_ticker, exc_info=True)
        return None


def build_peer_comparison(
    ticker: str,
    company_name: str,
    peers: Optional[List[str]] = None,
    cache: Optional[YahooLookupCache] = None,
    fmp_cache=None,
) -> tuple[str, List[str]]:
    """
    Build a formatted peer comparison section.
    Returns (section_text, sources_list).
    """
    import yfinance as yf

    ticker = ticker.upper()
    if peers is None:
        peers = discover_peers(ticker, company_name, cache=cache, fmp_cache=fmp_cache)

    if not peers:
        return "", []

    subject: Optional[Dict[str, Any]] = None
    subject_industry = "Unknown"
    subject_sector = "Unknown"
    if fmp_cache and env_flag("ENABLE_FMP"):
        try:
            q = fmp_cache.get_quote(ticker)
            km = fmp_cache.get_key_metrics(ticker)
            subject = {"ticker": ticker, "shortName": company_name}
            for key, _ in PEER_METRICS:
                if key == "marketCap":
                    subject[key] = int(q.get("marketCap") or 0)
                elif key == "trailingPE":
                    pe = q.get("pe")
                    subject[key] = pe if pe and pe > 0 else None
                elif key == "priceToSalesTrailing12Months":
                    subject[key] = km.get("priceToSalesRatioTTM") if km else None
                elif key == "enterpriseToEbitda":
                    subject[key] = km.get("evToEbitdaTTM") if km else None
                elif key == "grossMargins":
                    subject[key] = km.get("grossProfitMarginTTM") if km else None
                elif key == "operatingMargins":
                    subject[key] = km.get("operatingProfitMarginTTM") if km else None
                else:
                    subject[key] = None
            subject_industry = q.get("sector", "Unknown")
            subject_sector = q.get("sector", "Unknown")
        except Exception:
            subject = None

    if subject is None:
        if cache is not None:
            subject_info = cache.get_info(ticker)
        else:
            subject_info = yf.Ticker(ticker).info or {}
        subject = {"ticker": ticker, "shortName": company_name}
        for key, _ in PEER_METRICS:
            subject[key] = subject_info.get(key)
        subject_industry = subject_info.get("industry", "Unknown")
        subject_sector = subject_info.get("sector", "Unknown")

    max_workers = max(1, settings.peer_validation_max_workers)
    peer_data: List[Dict[str, Any]] = []
    metrics_by_ticker: Dict[str, Optional[Dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        fut_to_peer = {
            pool.submit(_fetch_peer_metrics, p, cache, fmp_cache): p for p in peers
        }
        for fut in as_completed(fut_to_peer):
            p = fut_to_peer[fut]
            metrics_by_ticker[p] = fut.result()
    for p in peers:
        data = metrics_by_ticker.get(p)
        if data:
            peer_data.append(data)

    if not peer_data:
        return "", []

    lines = ["=== Peer Comparison ==="]
    lines.append(f"Subject: {company_name} ({ticker})")
    lines.append(f"Industry: {subject_industry} | Sector: {subject_sector}")
    lines.append(f"Peers: {', '.join(d['ticker'] for d in peer_data)}")

    peer_industries = {d.get("industry", "") for d in peer_data if d.get("industry")}
    if peer_industries:
        if peer_industries == {subject_industry}:
            lines.append("Peer match quality: EXACT industry match")
        elif all(
            _industry_match_score(pi, "", subject_industry, "") >= 2
            for pi in peer_industries
        ):
            lines.append("Peer match quality: RELATED industries")
        else:
            lines.append(
                f"Peer industries: {', '.join(sorted(peer_industries))}"
            )
    lines.append("")

    medians: Dict[str, Optional[float]] = {}
    for key, label in PEER_METRICS:
        vals = [d[key] for d in peer_data if d.get(key) is not None]
        medians[key] = median(vals) if vals else None

    header = f"{'Metric':<16} {'Subject':>12} {'Peer Median':>12}"
    lines.append(header)
    lines.append("-" * len(header))

    for key, label in PEER_METRICS:
        sub_val = subject.get(key)
        med_val = medians.get(key)

        def _fmt(v: Any, k: str) -> str:
            if v is None:
                return "N/A"
            if k in ("marketCap", "totalRevenue"):
                return format_money(v)
            if k in ("grossMargins", "operatingMargins", "revenueGrowth"):
                return f"{float(v)*100:.1f}%"
            return f"{float(v):.2f}"

        lines.append(f"{label:<16} {_fmt(sub_val, key):>12} {_fmt(med_val, key):>12}")

    lines.append("")
    lines.append("Individual peers:")
    for d in peer_data:
        name = d.get("shortName", d["ticker"])
        ind = d.get("industry", "")
        cap = format_money(d.get("marketCap"))
        pe = f"P/E {float(d['trailingPE']):.1f}" if d.get("trailingPE") else "P/E N/A"
        gm = f"GM {float(d['grossMargins'])*100:.0f}%" if d.get("grossMargins") else "GM N/A"
        ind_tag = f" [{ind}]" if ind and ind != subject_industry else ""
        lines.append(f"  {d['ticker']} ({name}): {cap} | {pe} | {gm}{ind_tag}")

    section = "\n".join(lines)
    section = trim_text(section, settings.max_peer_section_chars)
    source_label = "FMP (peer data)" if fmp_cache and env_flag("ENABLE_FMP") else "Yahoo Finance (peer data)"
    return section, [source_label]
