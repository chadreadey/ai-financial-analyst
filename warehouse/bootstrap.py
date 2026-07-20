"""
Cold-start ingestion for the filing warehouse.

Given a ticker, fetches all available SEC data (submissions, XBRL facts,
filing sections) and writes it into the local SQLite warehouse.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from config import settings
from sec.client import SECClient
from sec.filing_parser import parse_filing_sections, parse_tenq_sections
from sec.xbrl_parser import (
    BALANCE_SHEET_CONCEPTS,
    CASH_FLOW_CONCEPTS,
    INCOME_STATEMENT_CONCEPTS,
    XBRLParser,
)
from warehouse.db import WarehouseDB

logger = logging.getLogger(__name__)

EPS_CONCEPTS = {"EarningsPerShareBasic", "EarningsPerShareDiluted"}
SHARES_CONCEPTS = {"CommonStockSharesOutstanding"}

ALL_CONCEPTS = INCOME_STATEMENT_CONCEPTS + BALANCE_SHEET_CONCEPTS + CASH_FLOW_CONCEPTS


def _unit_for_concept(concept: str) -> str:
    if concept in EPS_CONCEPTS:
        return "USD/shares"
    if concept in SHARES_CONCEPTS:
        return "shares"
    return "USD"


@dataclass
class BootstrapResult:
    ticker: str
    filing_count: int
    fact_count: int
    sections_extracted: int
    elapsed_s: float


def bootstrap_ticker(
    ticker: str,
    db: WarehouseDB,
    sec_client: SECClient,
    form_types: list[str] | None = None,
    filing_limit: int | None = None,
) -> BootstrapResult:
    """Full cold-start ingestion of a single ticker into the warehouse."""
    t0 = time.monotonic()
    ticker = ticker.upper()
    if form_types is None:
        form_types = ["10-K", "10-Q", "8-K"]
    if filing_limit is None:
        filing_limit = settings.warehouse_filing_limit

    info = sec_client.resolve_ticker(ticker)
    cik = info["cik"]
    company_name = info["name"]
    logger.info("bootstrap %s  CIK=%s  name=%s", ticker, cik, company_name)

    filings = sec_client.get_recent_filings(
        ticker,
        form_types=form_types,
        limit=filing_limit,
    )
    filing_count = len(filings)

    db.upsert_filings_bulk(
        [
            {
                "ticker": ticker,
                "accession": f["accessionNumber"],
                "form": f["form"],
                "filing_date": f["filingDate"],
                "primary_doc": f.get("primaryDocument", ""),
            }
            for f in filings
        ]
    )

    company_facts = sec_client.get_company_facts(ticker)
    parser = XBRLParser(company_facts)
    fact_count = _ingest_xbrl_facts(ticker, parser, db)

    sections_extracted = 0
    if settings.enable_filing_text:
        sections_extracted = _ingest_10k_sections(ticker, sec_client, db)
        sections_extracted += _ingest_10q_sections(ticker, sec_client, db)

    last_accession = filings[0]["accessionNumber"] if filings else None
    db.upsert_company(
        ticker=ticker,
        cik=cik,
        name=company_name,
        last_accession=last_accession,
    )

    elapsed = round(time.monotonic() - t0, 2)
    logger.info(
        "bootstrap %s complete: %d filings, %d facts, %d sections in %.1fs",
        ticker,
        filing_count,
        fact_count,
        sections_extracted,
        elapsed,
    )
    return BootstrapResult(
        ticker=ticker,
        filing_count=filing_count,
        fact_count=fact_count,
        sections_extracted=sections_extracted,
        elapsed_s=elapsed,
    )


def _ingest_xbrl_facts(
    ticker: str,
    parser: XBRLParser,
    db: WarehouseDB,
) -> int:
    """Extract all tracked XBRL concepts and bulk-write to warehouse. Returns row count."""
    rows = []
    for concept in ALL_CONCEPTS:
        df = parser._extract_concept(concept)
        if df.empty:
            continue
        unit = _unit_for_concept(concept)
        for _, row in df.iterrows():
            period_end = (
                str(row["end"].date()) if isinstance(row["end"], pd.Timestamp) else str(row["end"])
            )
            rows.append(
                {
                    "ticker": ticker,
                    "concept": concept,
                    "unit": unit,
                    "period_end": period_end,
                    "value": float(row["val"]),
                    "form": row.get("form", ""),
                    "fiscal_year": _safe_int(row.get("fiscal_year")),
                    "fiscal_period": row.get("fiscal_period"),
                }
            )
    db.upsert_xbrl_facts_bulk(rows)
    return len(rows)


def _ingest_10k_sections(
    ticker: str,
    sec_client: SECClient,
    db: WarehouseDB,
) -> int:
    """
    Fetch and parse narrative sections from the N most recent 10-Ks.

    Uses a dedicated 10-K-only fetch so the section count isn't limited by
    the mixed-form filing list (10-K/10-Q/8-K). For the latest filing,
    edgartools is tried first; older filings use HTML parsing only.

    Returns total section count written.
    """
    limit = settings.warehouse_sections_limit
    tenks = sec_client.get_recent_filings(ticker, form_types=["10-K"], limit=limit)
    if not tenks:
        return 0

    total = 0
    for i, filing in enumerate(tenks):
        accession = filing["accessionNumber"]
        primary_doc = filing.get("primaryDocument", "")
        if not primary_doc:
            continue

        try:
            html = sec_client.get_filing_text(ticker, accession, primary_doc)
        except Exception:
            logger.warning(
                "failed to fetch 10-K text for %s (%s)", ticker, accession, exc_info=True
            )
            continue

        # Only use edgartools for the latest filing — it always returns the
        # most recent 10-K regardless of which accession we're processing.
        ticker_for_edgar = ticker if i == 0 else ""
        sections = parse_filing_sections(html, ticker=ticker_for_edgar)

        written = 0
        for key, text in sections.items():
            if text:
                db.upsert_filing_section(ticker, accession, key, text)
                written += 1

        logger.info(
            "%s  %s (%s)  %d sections extracted",
            ticker,
            accession,
            filing.get("filingDate", ""),
            written,
        )
        total += written

    return total


def _ingest_10q_sections(
    ticker: str,
    sec_client: SECClient,
    db: WarehouseDB,
) -> int:
    """
    Fetch and parse narrative sections from recent 10-Q filings.

    Uses edgartools for the latest 10-Q only; older filings use HTML parsing.
    Returns total section count written.
    """
    limit = settings.warehouse_tenq_limit
    tenqs = sec_client.get_recent_filings(ticker, form_types=["10-Q"], limit=limit)
    if not tenqs:
        return 0

    total = 0
    for i, filing in enumerate(tenqs):
        accession = filing["accessionNumber"]
        primary_doc = filing.get("primaryDocument", "")
        if not primary_doc:
            continue

        try:
            html = sec_client.get_filing_text(ticker, accession, primary_doc)
        except Exception:
            logger.warning(
                "failed to fetch 10-Q text for %s (%s)", ticker, accession, exc_info=True
            )
            continue

        ticker_for_edgar = ticker if i == 0 else ""
        sections = parse_tenq_sections(html, ticker=ticker_for_edgar)

        written = 0
        for key, text in sections.items():
            if text:
                db.upsert_filing_section(ticker, accession, key, text)
                written += 1

        logger.info(
            "%s  10-Q %s (%s)  %d sections extracted",
            ticker,
            accession,
            filing.get("filingDate", ""),
            written,
        )
        total += written

    return total


def _safe_int(val) -> Optional[int]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    return int(val)
