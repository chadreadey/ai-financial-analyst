"""
Peer comparison data enrichment.

Discovers peer companies dynamically per-request using industry
classification, market cap range, and validated ticker resolution.
Formats a structured comparison table with sector medians.
"""

import os
import re
from importlib import import_module
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

from context_budget import trim_text
from utils import env_flag, format_money


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

# Common English words / abbreviations that look like tickers but aren't
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


def _validate_ticker(sym: str) -> Optional[Dict[str, Any]]:
    """Check that a string is a real tradeable ticker and return its info."""
    import yfinance as yf

    if sym in TICKER_BLOCKLIST or len(sym) < 2:
        return None
    try:
        info = yf.Ticker(sym).info or {}
        if info.get("marketCap") and info.get("quoteType") in ("EQUITY", None):
            return info
    except Exception:
        pass
    return None


def _industry_match_score(
    candidate_industry: str,
    candidate_sector: str,
    target_industry: str,
    target_sector: str,
) -> int:
    """
    Score how closely a candidate matches the target's industry.
    3 = exact industry match, 2 = overlapping industry keywords,
    1 = same sector, 0 = different sector.
    """
    if candidate_industry == target_industry:
        return 3

    target_words = set(target_industry.lower().replace("-", " ").replace("—", " ").split())
    cand_words = set(candidate_industry.lower().replace("-", " ").replace("—", " ").split())
    filler = {"", "and", "of", "the", "other", "general", "diversified", "specialty"}
    target_words -= filler
    cand_words -= filler
    if target_words and cand_words and target_words & cand_words:
        return 2

    if candidate_sector == target_sector:
        return 1

    return 0


def _market_cap_proximity(subject_cap: float, peer_cap: float) -> float:
    """Return a 0-1 score for how close two market caps are (log-scale)."""
    import math
    if subject_cap <= 0 or peer_cap <= 0:
        return 0.0
    ratio = max(subject_cap, peer_cap) / min(subject_cap, peer_cap)
    return max(0.0, 1.0 - math.log10(ratio) / 3.0)


def discover_peers(
    ticker: str,
    company_name: str,
    max_peers: int = 5,
) -> List[str]:
    """
    Dynamically discover peer tickers for each request using:
    1. yfinance recommendedSymbols (pre-validated by Yahoo)
    2. Tavily search with industry-specific queries
    3. Candidate validation: verify each ticker, filter by industry
       match and market cap proximity

    No static industry lists are used. Every comparison set is
    built fresh from the subject company's actual characteristics.
    """
    import yfinance as yf

    ticker = ticker.upper()
    stock = yf.Ticker(ticker)
    info = stock.info or {}
    sector = info.get("sector", "")
    industry = info.get("industry", "")
    subject_cap = info.get("marketCap", 0) or 0

    raw_candidates: List[str] = []

    # --- Source 1: yfinance recommended symbols (usually high quality) ---
    recommended = info.get("recommendedSymbols") or []
    if isinstance(recommended, list):
        for item in recommended:
            sym = item.get("symbol", item) if isinstance(item, dict) else str(item)
            sym = sym.upper().strip()
            if sym and sym != ticker and sym not in raw_candidates:
                raw_candidates.append(sym)

    # --- Source 2: Tavily search with industry-specific queries ---
    if env_flag("ENABLE_TAVILY", True):
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
            key = os.getenv("TAVILY_API_KEY", "").strip()
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
            pass

    # --- Validate and score each candidate ---
    scored: List[Tuple[float, str, Dict[str, Any]]] = []
    seen = set()
    for sym in raw_candidates:
        if sym in seen:
            continue
        seen.add(sym)

        peer_info = _validate_ticker(sym)
        if peer_info is None:
            continue

        peer_industry = peer_info.get("industry", "")
        peer_sector = peer_info.get("sector", "")
        peer_cap = peer_info.get("marketCap", 0) or 0

        ind_score = _industry_match_score(
            peer_industry, peer_sector, industry, sector
        )
        cap_score = _market_cap_proximity(subject_cap, peer_cap) if subject_cap else 0.5

        # Composite: industry match is 3x more important than cap proximity
        composite = ind_score * 3.0 + cap_score

        scored.append((composite, sym, peer_info))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Prefer industry matches; if we have none, take the best available
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
        print(
            f"  Peer discovery: {len(result)} peers found, "
            f"best match: {match_label.get(best_ind_score, '?')} "
            f"({peer_ind})"
        )

    return result


def _fetch_peer_metrics(peer_ticker: str) -> Optional[Dict[str, Any]]:
    """Fetch key metrics for a single peer ticker."""
    import yfinance as yf

    try:
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
        return None


def build_peer_comparison(
    ticker: str,
    company_name: str,
    peers: Optional[List[str]] = None,
) -> tuple[str, List[str]]:
    """
    Build a formatted peer comparison section.
    Returns (section_text, sources_list).
    """
    import yfinance as yf

    ticker = ticker.upper()
    if peers is None:
        peers = discover_peers(ticker, company_name)

    if not peers:
        return "", []

    subject_info = yf.Ticker(ticker).info or {}
    subject: Dict[str, Any] = {"ticker": ticker, "shortName": company_name}
    for key, _ in PEER_METRICS:
        subject[key] = subject_info.get(key)
    subject_industry = subject_info.get("industry", "Unknown")
    subject_sector = subject_info.get("sector", "Unknown")

    peer_data: List[Dict[str, Any]] = []
    for p in peers:
        data = _fetch_peer_metrics(p)
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
    section = trim_text(section, int(os.getenv("MAX_PEER_SECTION_CHARS", "2500")))
    return section, ["Yahoo Finance (peer data)"]
