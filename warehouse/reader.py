"""
Warehouse reader – translates warehouse rows into AnalysisData structures.

Keeps warehouse concerns out of orchestrator.py and agents.
"""

import logging
import time
from typing import Any, Optional

from config import settings
from models import AnalysisData, FilingInfo
from utils import format_money
from warehouse.db import WarehouseDB

logger = logging.getLogger(__name__)

REVENUE_CONCEPTS = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
]


def _latest_10k_value(
    facts: list[dict],
    concepts: list[str],
) -> Optional[float]:
    """Return the most recent 10-K value for the first matching concept."""
    for concept in concepts:
        for f in facts:
            if f["concept"] == concept and f.get("form") == "10-K":
                return f["value"]
    return None


def _annual_series(
    facts: list[dict],
    concept: str,
    years: int = 8,
) -> list[dict]:
    """Return up to *years* annual 10-K rows for *concept*, newest first.

    Facts are already sorted by period_end DESC from the DB query.
    Deduplicates by fiscal_year, keeping the first (latest) row.
    """
    seen_years: set[int | None] = set()
    rows: list[dict] = []
    for f in facts:
        if f["concept"] != concept or f.get("form") != "10-K":
            continue
        fy = f.get("fiscal_year")
        if fy in seen_years:
            continue
        seen_years.add(fy)
        rows.append(f)
        if len(rows) >= years:
            break
    return rows


def _compute_cagr(series: list[dict], years: int) -> Optional[float]:
    if len(series) < years + 1:
        return None
    end_val = series[0]["value"]
    start_val = series[years]["value"]
    if start_val <= 0 or end_val <= 0:
        return None
    return round((end_val / start_val) ** (1.0 / years) - 1, 4)


def _resolve_revenue_series(facts: list[dict], years: int = 8) -> list[dict]:
    for concept in REVENUE_CONCEPTS:
        series = _annual_series(facts, concept, years)
        if series:
            return series
    return []


def _reconstruct_metrics(facts: list[dict]) -> dict[str, Any]:
    """Mirror XBRLParser.compute_metrics() from warehouse xbrl_facts rows."""
    metrics: dict[str, Any] = {}

    revenue = _latest_10k_value(facts, REVENUE_CONCEPTS)
    metrics["revenue"] = revenue

    net_income = _latest_10k_value(facts, ["NetIncomeLoss"])
    metrics["net_income"] = net_income

    gross_profit = _latest_10k_value(facts, ["GrossProfit"])
    metrics["gross_profit"] = gross_profit

    operating_income = _latest_10k_value(facts, ["OperatingIncomeLoss"])
    metrics["operating_income"] = operating_income

    if revenue and revenue != 0:
        if gross_profit is not None:
            metrics["gross_margin"] = round(gross_profit / revenue, 4)
        if operating_income is not None:
            metrics["operating_margin"] = round(operating_income / revenue, 4)
        if net_income is not None:
            metrics["net_margin"] = round(net_income / revenue, 4)

    total_assets = _latest_10k_value(facts, ["Assets"])
    total_liabilities = _latest_10k_value(facts, ["Liabilities"])
    equity = _latest_10k_value(facts, ["StockholdersEquity"])
    cash = _latest_10k_value(facts, ["CashAndCashEquivalentsAtCarryingValue"])
    long_term_debt = _latest_10k_value(
        facts, ["LongTermDebt", "LongTermDebtNoncurrent"]
    )
    metrics["total_assets"] = total_assets
    metrics["total_liabilities"] = total_liabilities
    metrics["stockholders_equity"] = equity
    metrics["cash"] = cash
    metrics["long_term_debt"] = long_term_debt

    if equity and equity != 0:
        if total_liabilities is not None:
            metrics["debt_to_equity"] = round(total_liabilities / equity, 4)
        if net_income is not None:
            metrics["roe"] = round(net_income / equity, 4)

    if total_assets and total_assets != 0 and net_income is not None:
        metrics["roa"] = round(net_income / total_assets, 4)

    operating_cf = _latest_10k_value(
        facts, ["NetCashProvidedByUsedInOperatingActivities"]
    )
    capex = _latest_10k_value(
        facts, ["PaymentsToAcquirePropertyPlantAndEquipment"]
    )
    metrics["operating_cash_flow"] = operating_cf
    metrics["capex"] = capex
    if operating_cf is not None and capex is not None:
        metrics["free_cash_flow"] = operating_cf - capex

    metrics["eps_basic"] = _latest_10k_value(facts, ["EarningsPerShareBasic"])
    metrics["eps_diluted"] = _latest_10k_value(facts, ["EarningsPerShareDiluted"])
    metrics["shares_outstanding"] = _latest_10k_value(
        facts, ["CommonStockSharesOutstanding"]
    )

    rev_series = _resolve_revenue_series(facts)
    if len(rev_series) >= 2:
        latest = rev_series[0]["value"]
        prior = rev_series[1]["value"]
        if prior != 0:
            metrics["revenue_growth_yoy"] = round((latest - prior) / prior, 4)

    metrics["revenue_cagr_3y"] = _compute_cagr(rev_series, 3)
    metrics["revenue_cagr_5y"] = _compute_cagr(rev_series, 5)

    ni_series = _annual_series(facts, "NetIncomeLoss", 8)
    metrics["net_income_cagr_3y"] = _compute_cagr(ni_series, 3)
    metrics["net_income_cagr_5y"] = _compute_cagr(ni_series, 5)

    oi_series = _annual_series(facts, "OperatingIncomeLoss", 8)
    rev_cagr = metrics.get("revenue_cagr_5y")
    oi_cagr = _compute_cagr(oi_series, 5)
    if rev_cagr is not None and oi_cagr is not None and rev_cagr != 0:
        metrics["operating_leverage_5y"] = round(oi_cagr / rev_cagr, 2)
    else:
        metrics["operating_leverage_5y"] = None

    return metrics


def _build_summary_text(company_name: str, metrics: dict[str, Any]) -> str:
    """Reproduce XBRLParser.to_summary_text() from a metrics dict."""

    def fmt(val: Any, is_dollars: bool = True, is_pct: bool = False) -> str:
        if val is None:
            return "N/A"
        if is_pct:
            return f"{val * 100:.1f}%"
        if is_dollars:
            return format_money(val)
        return str(val)

    lines = [f"=== Financial Summary: {company_name} ===\n"]

    lines.append("── Income Statement (Latest Annual) ──")
    lines.append(f"  Revenue:          {fmt(metrics.get('revenue'))}")
    lines.append(f"  Gross Profit:     {fmt(metrics.get('gross_profit'))}")
    lines.append(f"  Operating Income: {fmt(metrics.get('operating_income'))}")
    lines.append(f"  Net Income:       {fmt(metrics.get('net_income'))}")
    lines.append(f"  EPS (Diluted):    {fmt(metrics.get('eps_diluted'), is_dollars=False)}")
    lines.append(f"  Revenue Growth:   {fmt(metrics.get('revenue_growth_yoy'), is_pct=True)}")
    lines.append("")

    lines.append("── Margins ──")
    lines.append(f"  Gross Margin:     {fmt(metrics.get('gross_margin'), is_pct=True)}")
    lines.append(f"  Operating Margin: {fmt(metrics.get('operating_margin'), is_pct=True)}")
    lines.append(f"  Net Margin:       {fmt(metrics.get('net_margin'), is_pct=True)}")
    lines.append("")

    lines.append("── Balance Sheet ──")
    lines.append(f"  Total Assets:     {fmt(metrics.get('total_assets'))}")
    lines.append(f"  Total Liabilities:{fmt(metrics.get('total_liabilities'))}")
    lines.append(f"  Equity:           {fmt(metrics.get('stockholders_equity'))}")
    lines.append(f"  Cash:             {fmt(metrics.get('cash'))}")
    lines.append(f"  Long-Term Debt:   {fmt(metrics.get('long_term_debt'))}")
    lines.append("")

    lines.append("── Ratios ──")
    lines.append(f"  Debt/Equity:      {fmt(metrics.get('debt_to_equity'), is_dollars=False)}")
    lines.append(f"  ROE:              {fmt(metrics.get('roe'), is_pct=True)}")
    lines.append(f"  ROA:              {fmt(metrics.get('roa'), is_pct=True)}")
    lines.append("")

    lines.append("── Cash Flow ──")
    lines.append(f"  Operating CF:     {fmt(metrics.get('operating_cash_flow'))}")
    lines.append(f"  CapEx:            {fmt(metrics.get('capex'))}")
    lines.append(f"  Free Cash Flow:   {fmt(metrics.get('free_cash_flow'))}")
    lines.append("")

    lines.append(f"  Shares Out:       {fmt(metrics.get('shares_outstanding'), is_dollars=False)}")

    lines.append("")
    lines.append("── Trends ──")
    lines.append(f"  Revenue CAGR (3Y): {fmt(metrics.get('revenue_cagr_3y'), is_pct=True)}")
    lines.append(f"  Revenue CAGR (5Y): {fmt(metrics.get('revenue_cagr_5y'), is_pct=True)}")
    lines.append(f"  Net Income CAGR (3Y): {fmt(metrics.get('net_income_cagr_3y'), is_pct=True)}")
    lines.append(f"  Net Income CAGR (5Y): {fmt(metrics.get('net_income_cagr_5y'), is_pct=True)}")
    ol = metrics.get("operating_leverage_5y")
    lines.append(f"  Operating Leverage (5Y): {ol if ol is not None else 'N/A'}")

    return "\n".join(lines)


def _build_historical_revenue(facts: list[dict], years: int = 5) -> list[dict[str, Any]]:
    rev_series = _resolve_revenue_series(facts, years)
    return [
        {
            "period_end": f["period_end"],
            "fiscal_year": f.get("fiscal_year"),
            "revenue": f["value"],
        }
        for f in rev_series[:years]
    ]


def _build_historical_net_income(facts: list[dict], years: int = 5) -> list[dict[str, Any]]:
    ni_series = _annual_series(facts, "NetIncomeLoss", years)
    return [
        {
            "period_end": f["period_end"],
            "fiscal_year": f.get("fiscal_year"),
            "net_income": f["value"],
        }
        for f in ni_series[:years]
    ]


def _build_margin_trends(facts: list[dict], years: int = 8) -> list[dict[str, Any]]:
    rev_series = _resolve_revenue_series(facts, years)
    if not rev_series:
        return []

    gp_series = _annual_series(facts, "GrossProfit", years)
    oi_series = _annual_series(facts, "OperatingIncomeLoss", years)
    ni_series = _annual_series(facts, "NetIncomeLoss", years)

    def _by_fy(series: list[dict]) -> dict[int | None, float]:
        return {f.get("fiscal_year"): f["value"] for f in series}

    gp_by_fy = _by_fy(gp_series)
    oi_by_fy = _by_fy(oi_series)
    ni_by_fy = _by_fy(ni_series)

    results: list[dict[str, Any]] = []
    for row in rev_series:
        fy = row.get("fiscal_year")
        rev = row["value"]
        if rev == 0:
            continue
        entry: dict[str, Any] = {
            "fiscal_year": fy,
            "period_end": row["period_end"],
        }
        if fy in gp_by_fy:
            entry["gross_margin"] = round(gp_by_fy[fy] / rev, 4)
        if fy in oi_by_fy:
            entry["operating_margin"] = round(oi_by_fy[fy] / rev, 4)
        if fy in ni_by_fy:
            entry["net_margin"] = round(ni_by_fy[fy] / rev, 4)
        results.append(entry)
    return results


def _build_cash_flow_trends(facts: list[dict], years: int = 8) -> list[dict[str, Any]]:
    ocf_series = _annual_series(facts, "NetCashProvidedByUsedInOperatingActivities", years)
    if not ocf_series:
        return []

    capex_series = _annual_series(facts, "PaymentsToAcquirePropertyPlantAndEquipment", years)
    capex_by_fy = {f.get("fiscal_year"): f["value"] for f in capex_series}

    results: list[dict[str, Any]] = []
    for row in ocf_series:
        fy = row.get("fiscal_year")
        ocf = row["value"]
        entry: dict[str, Any] = {
            "fiscal_year": fy,
            "period_end": row["period_end"],
            "operating_cf": ocf,
        }
        if fy in capex_by_fy:
            cx = capex_by_fy[fy]
            entry["capex"] = cx
            entry["fcf"] = ocf - cx
        results.append(entry)
    return results


def build_analysis_data_from_warehouse(
    ticker: str,
    db: WarehouseDB,
) -> Optional[AnalysisData]:
    """
    Build AnalysisData from warehouse rows.
    Returns None if ticker is untracked or critical data is missing.
    """
    ticker = ticker.upper()
    company = db.get_company(ticker)
    if company is None:
        logger.debug("Ticker %s not tracked in warehouse", ticker)
        return None

    facts = db.get_xbrl_facts(ticker)
    if not facts:
        logger.warning("No XBRL facts for %s – cannot build AnalysisData", ticker)
        return None

    metrics = _reconstruct_metrics(facts)
    company_name = company["name"]

    filings = db.get_filings(ticker, limit=20)
    recent_filings = [
        FilingInfo(
            form=f["form"],
            filingDate=f["filing_date"],
            accessionNumber=f["accession"],
            primaryDocument=f.get("primary_doc", ""),
        )
        for f in filings
    ]

    historical_revenue = _build_historical_revenue(facts)
    historical_net_income = _build_historical_net_income(facts)
    margin_trends = _build_margin_trends(facts)
    cash_flow_trends = _build_cash_flow_trends(facts)

    financial_core_summary = _build_summary_text(company_name, metrics)

    enrichment_sections: dict[str, str] = {}
    latest_10k_acc = None
    ten_k_filings = db.get_filings(ticker, form_types=["10-K"], limit=1)
    if ten_k_filings:
        latest_10k_acc = ten_k_filings[0]["accession"]

    if latest_10k_acc:
        section_map = {
            "mda": "filing_mda",
            "risk_factors": "filing_risk_factors",
            "business_description": "filing_business",
        }
        for db_key, enrichment_key in section_map.items():
            text = db.get_filing_section(ticker, latest_10k_acc, db_key)
            if text:
                enrichment_sections[enrichment_key] = text

    logger.info(
        "Built AnalysisData for %s from warehouse (%d facts, %d filings)",
        ticker,
        len(facts),
        len(filings),
    )

    return AnalysisData(
        ticker=ticker,
        company_name=company_name,
        metrics=metrics,
        recent_filings=recent_filings,
        historical_revenue=historical_revenue,
        historical_net_income=historical_net_income,
        margin_trends=margin_trends,
        cash_flow_trends=cash_flow_trends,
        financial_core_summary=financial_core_summary,
        enrichment_sections=enrichment_sections,
    )


# ── Market / Macro helpers ──────────────────────────────────────────


def get_market_snapshot_for_context(
    ticker: str,
    db: WarehouseDB,
    max_age_hours: int | None = None,
) -> Optional[str]:
    """Return formatted market section if fresh enough; None triggers live Yahoo fetch."""
    ttl = max_age_hours if max_age_hours is not None else settings.warehouse_market_ttl_hours
    snap = db.get_market_snapshot(ticker)
    if snap is None:
        return None

    age_hours = (time.time() - snap["ingested_at"]) / 3600
    if age_hours > ttl:
        logger.debug("Market snapshot for %s is %.1fh old (ttl=%dh), stale", ticker, age_hours, ttl)
        return None

    lines = [f"=== Market Data: {ticker} (as of {snap['as_of_date']}) ==="]

    def _fmt(label: str, val: Any, prefix: str = "$", suffix: str = "") -> str:
        if val is None:
            return f"  {label}: N/A"
        if prefix == "$":
            return f"  {label}: {format_money(val)}{suffix}"
        return f"  {label}: {prefix}{val}{suffix}"

    lines.append(_fmt("Price", snap.get("price")))
    lines.append(_fmt("Market Cap", snap.get("market_cap")))
    lines.append(_fmt("P/E (TTM)", snap.get("pe_ttm"), prefix="", suffix="x"))
    lines.append(_fmt("Forward P/E", snap.get("forward_pe"), prefix="", suffix="x"))
    lines.append(_fmt("P/S (TTM)", snap.get("ps_ttm"), prefix="", suffix="x"))
    lines.append(_fmt("EV/EBITDA", snap.get("ev_ebitda"), prefix="", suffix="x"))
    lines.append(_fmt("Beta", snap.get("beta"), prefix=""))
    lines.append(_fmt("52-Week High", snap.get("week52_high")))
    lines.append(_fmt("52-Week Low", snap.get("week52_low")))
    lines.append(_fmt("Analyst Target", snap.get("target_mean")))

    rec = snap.get("recommendation")
    if rec:
        lines.append(f"  Recommendation: {rec}")

    return "\n".join(lines)


def get_macro_for_context(
    db: WarehouseDB,
    max_age_hours: int | None = None,
) -> Optional[str]:
    """Return formatted macro section if fresh enough; None triggers live FRED fetch."""
    ttl = max_age_hours if max_age_hours is not None else settings.warehouse_macro_ttl_hours
    rows = db.get_macro_series()
    if not rows:
        return None

    newest_ingest = max(r["ingested_at"] for r in rows)
    age_hours = (time.time() - newest_ingest) / 3600
    if age_hours > ttl:
        logger.debug("Macro data is %.1fh old (ttl=%dh), stale", age_hours, ttl)
        return None

    latest_by_series: dict[str, dict] = {}
    for r in rows:
        sid = r["series_id"]
        if sid not in latest_by_series:
            latest_by_series[sid] = r

    lines = ["=== Macroeconomic Indicators ==="]
    for sid, r in sorted(latest_by_series.items()):
        lines.append(f"  {r['label']}: {r['value']} (as of {r['as_of_date']})")

    return "\n".join(lines)
