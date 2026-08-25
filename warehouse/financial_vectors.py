"""
Pinecone time-series vectors for quarterly company financials.

Fetches FMP quarterly income / balance-sheet / cash-flow statements,
merges on filing date, computes YoY and QoQ growth rates, formats a
structured text snapshot, and upserts to the `financial_ts` namespace.

Vector ID format: {TICKER}_fts_{YYYYQQ}  e.g. AAPL_fts_2024Q1

Fields stored per record:
  _id, text, ticker, period, fiscal_year, fiscal_quarter,
  revenue, net_income, operating_cash_flow, free_cash_flow,
  gross_margin, operating_margin, net_margin
"""

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── helpers ────────────────────────────────────────────────────────────────


def _safe(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _fmt_billions(v: float) -> str:
    if abs(v) >= 1e9:
        return f"${v / 1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v / 1e6:.2f}M"
    return f"${v:.0f}"


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _growth_str(current: float, prior: float) -> str:
    if prior == 0:
        return "n/a"
    g = (current - prior) / abs(prior)
    sign = "+" if g >= 0 else ""
    return f"{sign}{g * 100:.1f}%"


def _quarter_label(date_str: str) -> str:
    """Convert '2024-03-31' → '2024Q1' (calendar quarter from end date)."""
    try:
        from datetime import date

        d = date.fromisoformat(date_str[:10])
        q = (d.month - 1) // 3 + 1
        return f"{d.year}Q{q}"
    except Exception:
        return date_str[:7].replace("-", "Q")


def _merge_statements(
    income: list,
    balance: list,
    cashflow: list,
) -> List[Dict]:
    """
    Left-join income, balance, cashflow on 'date' field.
    Returns list of merged dicts sorted oldest-first.
    """
    bal_map = {r.get("date", ""): r for r in balance}
    cf_map = {r.get("date", ""): r for r in cashflow}

    merged = []
    for row in income:
        d = row.get("date", "")
        merged_row = dict(row)
        merged_row.update(bal_map.get(d, {}))
        merged_row.update(cf_map.get(d, {}))
        merged.append(merged_row)

    # sort oldest → newest so growth can be computed forward
    merged.sort(key=lambda r: r.get("date", ""))
    return merged


def _build_financial_text(row: Dict, yoy: Dict, qoq: Dict) -> str:
    """Format a quarterly snapshot into ~4000-char text for embedding."""
    ticker = row.get("symbol", "").upper()
    period = row.get("date", "")[:10]
    ql = _quarter_label(period)
    rev = _safe(row.get("revenue"))
    gross_profit = _safe(row.get("grossProfit"))
    op_income = _safe(row.get("operatingIncome"))
    net_income = _safe(row.get("netIncome"))
    ebitda = _safe(row.get("ebitda"))
    total_assets = _safe(row.get("totalAssets"))
    total_debt = _safe(row.get("totalDebt"))
    cash = _safe(row.get("cashAndCashEquivalents") or row.get("cash"))
    op_cf = _safe(row.get("operatingCashFlow"))
    capex = _safe(row.get("capitalExpenditure"))
    fcf = op_cf + capex  # capex is typically negative in FMP
    shares = _safe(row.get("weightedAverageShsOutDil") or row.get("weightedAverageShsOut"))
    eps = _safe(row.get("epsdiluted") or row.get("eps"))

    gross_margin = gross_profit / rev if rev else 0.0
    op_margin = op_income / rev if rev else 0.0
    net_margin = net_income / rev if rev else 0.0

    lines = [
        f"{ticker} Quarterly Financial Snapshot — {ql} (period ending {period})",
        "",
        "=== Income Statement ===",
        f"Revenue: {_fmt_billions(rev)}  YoY: {yoy.get('rev', 'n/a')}  QoQ: {qoq.get('rev', 'n/a')}",
        f"Gross Profit: {_fmt_billions(gross_profit)}  Gross Margin: {_pct(gross_margin)}",
        f"Operating Income: {_fmt_billions(op_income)}  Op Margin: {_pct(op_margin)}",
        f"Net Income: {_fmt_billions(net_income)}  Net Margin: {_pct(net_margin)}  YoY: {yoy.get('ni', 'n/a')}",
        f"EBITDA: {_fmt_billions(ebitda)}",
        f"EPS (diluted): ${eps:.2f}  Shares: {_fmt_billions(shares)}",
        "",
        "=== Balance Sheet ===",
        f"Total Assets: {_fmt_billions(total_assets)}",
        f"Total Debt: {_fmt_billions(total_debt)}",
        f"Cash & Equivalents: {_fmt_billions(cash)}",
        f"Net Debt: {_fmt_billions(total_debt - cash)}",
        "",
        "=== Cash Flow ===",
        f"Operating Cash Flow: {_fmt_billions(op_cf)}  YoY: {yoy.get('ocf', 'n/a')}",
        f"Capital Expenditure: {_fmt_billions(capex)}",
        f"Free Cash Flow: {_fmt_billions(fcf)}  YoY: {yoy.get('fcf', 'n/a')}",
    ]
    return "\n".join(lines)


# ── public API ─────────────────────────────────────────────────────────────


def build_financial_records(
    ticker: str,
    income: list,
    balance: list,
    cashflow: list,
) -> List[Dict]:
    """
    Merge quarterly statements and return a list of Pinecone-ready records.

    Each record has _id, text, ticker, period, and key metric fields for
    metadata filtering.
    """
    merged = _merge_statements(income, balance, cashflow)
    if not merged:
        return []

    records = []
    for i, row in enumerate(merged):
        period = row.get("date", "")[:10]
        ql = _quarter_label(period)

        # YoY = compare against 4 quarters back; QoQ = 1 quarter back
        prior_yoy = merged[i - 4] if i >= 4 else None
        prior_qoq = merged[i - 1] if i >= 1 else None

        rev = _safe(row.get("revenue"))
        ni = _safe(row.get("netIncome"))
        op_cf = _safe(row.get("operatingCashFlow"))
        capex = _safe(row.get("capitalExpenditure"))
        fcf = op_cf + capex

        def _yoy_growth(field: str) -> str:
            if not prior_yoy:
                return "n/a"
            return _growth_str(_safe(row.get(field)), _safe(prior_yoy.get(field)))

        def _qoq_growth(field: str) -> str:
            if not prior_qoq:
                return "n/a"
            return _growth_str(_safe(row.get(field)), _safe(prior_qoq.get(field)))

        yoy = {
            "rev": _yoy_growth("revenue"),
            "ni": _yoy_growth("netIncome"),
            "ocf": _yoy_growth("operatingCashFlow"),
            "fcf": _growth_str(
                fcf,
                _safe(prior_yoy.get("operatingCashFlow", 0))
                + _safe(prior_yoy.get("capitalExpenditure", 0)),
            )
            if prior_yoy
            else "n/a",
        }
        qoq = {
            "rev": _qoq_growth("revenue"),
            "ni": _qoq_growth("netIncome"),
            "ocf": _qoq_growth("operatingCashFlow"),
            "fcf": "n/a",
        }

        text = _build_financial_text(row, yoy, qoq)

        gross_profit = _safe(row.get("grossProfit"))
        op_income = _safe(row.get("operatingIncome"))
        net_income = _safe(row.get("netIncome"))
        gross_margin = gross_profit / rev if rev else 0.0
        op_margin = op_income / rev if rev else 0.0
        net_margin = net_income / rev if rev else 0.0

        records.append(
            {
                "_id": f"{ticker.upper()}_fts_{ql}",
                "text": text[:4000],
                "ticker": ticker.upper(),
                "period": period,
                "quarter_label": ql,
                "revenue": rev,
                "net_income": net_income,
                "operating_cash_flow": op_cf,
                "free_cash_flow": fcf,
                "gross_margin": round(gross_margin, 4),
                "operating_margin": round(op_margin, 4),
                "net_margin": round(net_margin, 4),
            }
        )

    return records


def upsert_ticker_financials(
    ticker: str,
    fmp_client,
    index,
    namespace: str,
    batch_size: int = 50,
    dry_run: bool = False,
    limit: int = 5,
) -> int:
    """
    Fetch quarterly statements via FMP, build records, and upsert to Pinecone.
    Returns number of records upserted (or previewed in dry-run).
    """
    sym = ticker.upper()
    logger.info("[%s] Fetching quarterly financials from FMP...", sym)

    income = fmp_client.get_income_statement_quarterly(sym, limit)
    if not income:
        logger.warning("[%s] No quarterly income data from FMP — skipping", sym)
        return 0

    balance = fmp_client.get_balance_sheet_quarterly(sym, limit)
    cashflow = fmp_client.get_cash_flow_quarterly(sym, limit)

    records = build_financial_records(sym, income, balance, cashflow)
    if not records:
        logger.warning("[%s] No records built — skipping", sym)
        return 0

    logger.info("[%s] Built %d quarterly records", sym, len(records))

    ns = namespace or "financial_ts"
    total = 0
    for i in range(0, len(records), batch_size):
        chunk = records[i : i + batch_size]
        if dry_run:
            logger.info("[%s] DRY RUN — would upsert %d records", sym, len(chunk))
        else:
            try:
                index.upsert_records(ns, chunk)
                logger.info("[%s] Upserted records %d–%d", sym, i, i + len(chunk) - 1)
            except Exception as exc:
                logger.error("[%s] Upsert failed at offset %d: %s", sym, i, exc)
                continue
        total += len(chunk)
        time.sleep(0.05)

    return total


def upsert_all_financial_vectors(
    tickers: List[str],
    fmp_client,
    index,
    namespace: str = "financial_ts",
    batch_size: int = 50,
    dry_run: bool = False,
    limit: int = 5,
    delay_between_tickers: float = 0.5,
) -> Dict[str, int]:
    """
    Upsert quarterly financial vectors for every ticker in `tickers`.
    Returns {ticker: count_upserted} summary.
    """
    summary: Dict[str, int] = {}
    for ticker in tickers:
        count = upsert_ticker_financials(
            ticker=ticker,
            fmp_client=fmp_client,
            index=index,
            namespace=namespace,
            batch_size=batch_size,
            dry_run=dry_run,
            limit=limit,
        )
        summary[ticker.upper()] = count
        time.sleep(delay_between_tickers)

    total = sum(summary.values())
    logger.info(
        "Financial vectors done. %s %d records for %d tickers.",
        "Previewed" if dry_run else "Upserted",
        total,
        len(summary),
    )
    return summary
