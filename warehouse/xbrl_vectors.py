"""
Pinecone time-series vectors for quarterly company financials — XBRL source.

Uses SEC EDGAR company facts (free, no API key needed) via the existing
SECClient.get_company_facts() pipeline and XBRLParser.

For each ticker, extracts every available 10-Q quarterly period, merges
income-statement, balance-sheet, and cash-flow concepts into a single
structured text snapshot, and upserts to the `financial_ts` namespace.

Vector ID format: {TICKER}_fts_{YYYYQQ}  e.g. AAPL_fts_2024Q2

Fields stored per record:
  _id, text, ticker, period, quarter_label,
  revenue, net_income, operating_income, gross_profit,
  operating_cash_flow, free_cash_flow,
  gross_margin, operating_margin, net_margin
"""

import logging
import time
from typing import Dict, List, Optional, Set

import pandas as pd

logger = logging.getLogger(__name__)


# ── concept lists ─────────────────────────────────────────────────────────────

_REVENUE_CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
]
_INCOME_CONCEPTS = [
    ("gross_profit",     "GrossProfit"),
    ("operating_income", "OperatingIncomeLoss"),
    ("net_income",       "NetIncomeLoss"),
    ("eps_diluted",      "EarningsPerShareDiluted"),
    ("rd_expense",       "ResearchAndDevelopmentExpense"),
    ("sga_expense",      "SellingGeneralAndAdministrativeExpense"),
]
_BALANCE_CONCEPTS = [
    ("total_assets",     "Assets"),
    ("total_liabilities","Liabilities"),
    ("equity",           "StockholdersEquity"),
    ("cash",             "CashAndCashEquivalentsAtCarryingValue"),
    ("long_term_debt",   "LongTermDebt"),
    ("short_term_debt",  "ShortTermBorrowings"),
]
_CASHFLOW_CONCEPTS = [
    ("operating_cf",     "NetCashProvidedByUsedInOperatingActivities"),
    ("investing_cf",     "NetCashProvidedByUsedInInvestingActivities"),
    ("capex",            "PaymentsToAcquirePropertyPlantAndEquipment"),
    ("depreciation",     "DepreciationDepletionAndAmortization"),
]

_QUARTERLY_FORMS = {"10-Q", "6-K"}


# ── helpers ───────────────────────────────────────────────────────────────────

def _safe(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _fmt_b(v: Optional[float]) -> str:
    if v is None:
        return "n/a"
    if abs(v) >= 1e9:
        return f"${v / 1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v / 1e6:.2f}M"
    return f"${v:.0f}"


def _pct(v: Optional[float]) -> str:
    return f"{v * 100:.1f}%" if v is not None else "n/a"


def _growth(curr: Optional[float], prior: Optional[float]) -> str:
    if curr is None or prior is None or prior == 0:
        return "n/a"
    g = (curr - prior) / abs(prior)
    return f"{'+'if g>=0 else ''}{g*100:.1f}%"


def _quarter_label(end_date) -> str:
    """pd.Timestamp or str → '2024Q2'"""
    try:
        d = pd.Timestamp(end_date)
        q = (d.month - 1) // 3 + 1
        return f"{d.year}Q{q}"
    except Exception:
        return str(end_date)[:7]


def _latest_quarterly_series(parser, concept: str) -> pd.DataFrame:
    """Extract quarterly (10-Q/6-K) time series for a concept, oldest-first."""
    df = parser._extract_concept(concept, form_filter=["10-Q"])
    if df.empty:
        return df
    df = df.copy()
    df["end"] = pd.to_datetime(df["end"])
    return df.sort_values("end").reset_index(drop=True)


def _resolve_revenue_quarterly(parser) -> pd.DataFrame:
    """Pick the revenue concept with the most recent data."""
    best: pd.DataFrame = pd.DataFrame()
    for concept in _REVENUE_CONCEPTS:
        df = _latest_quarterly_series(parser, concept)
        if df.empty:
            continue
        if best.empty or df.iloc[-1]["end"] > best.iloc[-1]["end"]:
            best = df
    return best


# ── build records from a parsed ticker ───────────────────────────────────────

def build_xbrl_quarterly_records(
    ticker: str,
    parser,
    limit: Optional[int] = None,
) -> List[Dict]:
    """
    Extract all available 10-Q periods from an XBRLParser instance and
    return a list of Pinecone-ready records (oldest-first).

    `limit` caps the number of quarters (most recent N if set).
    """
    # ── revenue ──
    rev_df = _resolve_revenue_quarterly(parser)
    if rev_df.empty:
        logger.debug("[%s] No quarterly revenue data in XBRL", ticker)
        return []

    # ── all other concepts ──
    series: Dict[str, pd.DataFrame] = {"revenue": rev_df}
    for key, concept in _INCOME_CONCEPTS + _BALANCE_CONCEPTS + _CASHFLOW_CONCEPTS:
        df = _latest_quarterly_series(parser, concept)
        if not df.empty:
            series[key] = df

    # Index all series by end date → value
    def _to_map(df: pd.DataFrame) -> Dict:
        return {row["end"]: _safe(row["val"]) for _, row in df.iterrows()}

    maps = {k: _to_map(v) for k, v in series.items()}

    # Use the revenue dates as the spine of periods
    periods = sorted(rev_df["end"].tolist())
    if limit:
        periods = periods[-limit:]

    records = []
    for i, end_ts in enumerate(periods):
        ql = _quarter_label(end_ts)
        period_str = end_ts.strftime("%Y-%m-%d")

        rev   = maps["revenue"].get(end_ts)
        gp    = maps.get("gross_profit", {}).get(end_ts)
        oi    = maps.get("operating_income", {}).get(end_ts)
        ni    = maps.get("net_income", {}).get(end_ts)
        eps   = maps.get("eps_diluted", {}).get(end_ts)
        rd    = maps.get("rd_expense", {}).get(end_ts)
        sga   = maps.get("sga_expense", {}).get(end_ts)
        assets= maps.get("total_assets", {}).get(end_ts)
        liab  = maps.get("total_liabilities", {}).get(end_ts)
        eq    = maps.get("equity", {}).get(end_ts)
        cash  = maps.get("cash", {}).get(end_ts)
        ltd   = maps.get("long_term_debt", {}).get(end_ts)
        std   = maps.get("short_term_debt", {}).get(end_ts)
        ocf   = maps.get("operating_cf", {}).get(end_ts)
        capex = maps.get("capex", {}).get(end_ts)
        depr  = maps.get("depreciation", {}).get(end_ts)

        # CapEx is a payment (positive in XBRL cash outflow) — store as negative
        if capex is not None and capex > 0:
            capex = -capex
        fcf = (ocf + capex) if ocf is not None and capex is not None else None

        total_debt = (ltd or 0) + (std or 0) if (ltd is not None or std is not None) else None
        net_debt = (total_debt - cash) if total_debt is not None and cash is not None else None

        gm = gp / rev if gp is not None and rev else None
        om = oi / rev if oi is not None and rev else None
        nm = ni / rev if ni is not None and rev else None

        # YoY comparisons (4 quarters back)
        prior_end = periods[i - 4] if i >= 4 else None
        prior_rev = maps["revenue"].get(prior_end) if prior_end else None
        prior_ni  = maps.get("net_income", {}).get(prior_end) if prior_end else None
        prior_ocf = maps.get("operating_cf", {}).get(prior_end) if prior_end else None

        currency = getattr(parser, "reporting_currency", "USD")
        curr_sym = {"TWD": "NT$", "EUR": "€", "GBP": "£", "JPY": "¥",
                    "CNY": "¥", "KRW": "₩", "DKK": "DKK "}.get(currency, "$")
        curr_note = f" (values in {currency})" if currency != "USD" else ""

        lines = [
            f"{ticker.upper()} Quarterly Financial Snapshot — {ql} (period ending {period_str}){curr_note}",
            "",
            "=== Income Statement ===",
            f"Revenue: {_fmt_b(rev)}  YoY: {_growth(rev, prior_rev)}",
            f"Gross Profit: {_fmt_b(gp)}  Gross Margin: {_pct(gm)}",
            f"Operating Income: {_fmt_b(oi)}  Op Margin: {_pct(om)}",
            f"Net Income: {_fmt_b(ni)}  Net Margin: {_pct(nm)}  YoY: {_growth(ni, prior_ni)}",
            f"EPS (diluted): {f'{curr_sym}{eps:.2f}' if eps is not None else 'n/a'}",
            f"R&D: {_fmt_b(rd)}  SG&A: {_fmt_b(sga)}",
            "",
            "=== Balance Sheet ===",
            f"Total Assets: {_fmt_b(assets)}  Total Liabilities: {_fmt_b(liab)}",
            f"Stockholders Equity: {_fmt_b(eq)}",
            f"Cash & Equivalents: {_fmt_b(cash)}",
            f"Total Debt: {_fmt_b(total_debt)}  Net Debt: {_fmt_b(net_debt)}",
            "",
            "=== Cash Flow ===",
            f"Operating CF: {_fmt_b(ocf)}  YoY: {_growth(ocf, prior_ocf)}",
            f"CapEx: {_fmt_b(capex)}  Free Cash Flow: {_fmt_b(fcf)}",
            f"D&A: {_fmt_b(depr)}",
        ]
        text = "\n".join(lines)

        record: Dict = {
            "_id": f"{ticker.upper()}_fts_{ql}",
            "text": text[:4000],
            "ticker": ticker.upper(),
            "period": period_str,
            "quarter_label": ql,
        }
        for fld, val in [
            ("revenue", rev), ("gross_profit", gp), ("operating_income", oi),
            ("net_income", ni), ("operating_cash_flow", ocf), ("free_cash_flow", fcf),
            ("gross_margin", round(gm, 4) if gm is not None else None),
            ("operating_margin", round(om, 4) if om is not None else None),
            ("net_margin", round(nm, 4) if nm is not None else None),
        ]:
            if val is not None:
                record[fld] = val

        records.append(record)

    return records


# ── per-ticker upsert ─────────────────────────────────────────────────────────

def upsert_ticker_xbrl_financials(
    ticker: str,
    sec_client,
    index,
    namespace: str = "financial_ts",
    batch_size: int = 50,
    dry_run: bool = False,
    limit: Optional[int] = None,
    existing_ids: Optional[Set[str]] = None,
) -> int:
    """
    Fetch XBRL facts for a ticker, build quarterly records, upsert to Pinecone.
    Skips any record whose _id is already in `existing_ids`.
    Returns number of records upserted (or previewed).
    """
    from sec.xbrl_parser import XBRLParser

    sym = ticker.upper()
    try:
        facts = sec_client.get_company_facts(sym)
    except Exception as exc:
        logger.warning("[%s] Failed to fetch XBRL facts: %s", sym, exc)
        return 0

    parser = XBRLParser(facts)
    records = build_xbrl_quarterly_records(sym, parser, limit=limit)

    if not records:
        logger.debug("[%s] No quarterly XBRL records built", sym)
        return 0

    # Apply skip-existing filter
    if existing_ids:
        before = len(records)
        records = [r for r in records if r["_id"] not in existing_ids]
        skipped = before - len(records)
        if skipped:
            logger.debug("[%s] Skipping %d already-seeded records", sym, skipped)

    if not records:
        logger.info("[%s] All records already seeded — skipping", sym)
        return 0

    logger.info("[%s] Upserting %d quarterly records", sym, len(records))
    total = 0
    for i in range(0, len(records), batch_size):
        chunk = records[i : i + batch_size]
        if dry_run:
            logger.info("[%s] DRY RUN — would upsert %d records", sym, len(chunk))
            total += len(chunk)
            continue

        # Retry with exponential backoff on 429 (Pinecone embedding rate limit)
        for attempt in range(5):
            try:
                index.upsert_records(namespace, chunk)
                total += len(chunk)
                break
            except Exception as exc:
                msg = str(exc)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "Too Many Requests" in msg:
                    wait = 2 ** attempt * 15  # 15s, 30s, 60s, 120s, 240s
                    logger.warning("[%s] Rate limited (attempt %d) — waiting %ds", sym, attempt + 1, wait)
                    time.sleep(wait)
                else:
                    logger.error("[%s] Upsert failed at offset %d: %s", sym, i, exc)
                    break
        else:
            logger.error("[%s] Gave up after 5 attempts at offset %d", sym, i)
            return total  # partial — don't mark ticker as seeded

        time.sleep(1.0)  # 1s between batches to stay under 250k tokens/min

    return total


# ── bulk upsert ───────────────────────────────────────────────────────────────

def fetch_existing_tickers(index, namespace: str) -> Set[str]:
    """
    Query Pinecone to find which tickers already have vectors in the namespace.
    Uses describe_index_stats + a probe query per ticker (no list-all-IDs API).
    Returns a set of ticker strings already present.

    This is done by checking stats: if the namespace has vectors, we do a
    metadata-filter query for each ticker. For large namespaces a local file
    cache is more efficient — see `load_seeded_tickers_file`.
    """
    try:
        stats = index.describe_index_stats()
        ns_stats = stats.get("namespaces", {}).get(namespace, {})
        if ns_stats.get("vector_count", 0) == 0:
            return set()
    except Exception:
        return set()

    # We can't list all IDs in Pinecone free tier, so we return empty here
    # and rely on the seeded-tickers file instead.
    return set()


def load_seeded_tickers_file(path: str) -> Set[str]:
    """Load the set of already-seeded tickers from a local text file (one per line)."""
    import os
    if not os.path.exists(path):
        return set()
    with open(path) as f:
        return {line.strip().upper() for line in f if line.strip()}


def save_seeded_ticker(path: str, ticker: str) -> None:
    """Append a ticker to the seeded-tickers file."""
    with open(path, "a") as f:
        f.write(ticker.upper() + "\n")


def upsert_all_xbrl_financial_vectors(
    tickers: List[str],
    sec_client,
    index,
    namespace: str = "financial_ts",
    batch_size: int = 50,
    dry_run: bool = False,
    limit: Optional[int] = None,
    delay_between_tickers: float = 0.15,
    skip_existing: bool = False,
    seeded_tickers_file: str = ".seeded_tickers.txt",
) -> Dict[str, int]:
    """
    Upsert quarterly XBRL financial vectors for every ticker in `tickers`.

    skip_existing: if True, tickers already recorded in `seeded_tickers_file`
                   are skipped entirely without hitting the SEC API.

    Returns {ticker: count_upserted} summary.
    """
    seeded: Set[str] = set()
    if skip_existing:
        seeded = load_seeded_tickers_file(seeded_tickers_file)
        if seeded:
            logger.info("Skip-existing: %d tickers already seeded", len(seeded))

    summary: Dict[str, int] = {}
    for ticker in tickers:
        sym = ticker.upper()
        if skip_existing and sym in seeded:
            logger.debug("[%s] Already seeded — skipping", sym)
            summary[sym] = 0
            continue

        count = upsert_ticker_xbrl_financials(
            ticker=sym,
            sec_client=sec_client,
            index=index,
            namespace=namespace,
            batch_size=batch_size,
            dry_run=dry_run,
            limit=limit,
        )
        summary[sym] = count

        if not dry_run and count > 0:
            save_seeded_ticker(seeded_tickers_file, sym)

        time.sleep(delay_between_tickers)

    total = sum(summary.values())
    logger.info(
        "XBRL financial vectors done. %s %d records for %d/%d tickers.",
        "Previewed" if dry_run else "Upserted",
        total,
        sum(1 for v in summary.values() if v > 0),
        len(summary),
    )
    return summary
