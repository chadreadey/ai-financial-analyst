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
from sec.filing_parser import parse_filing_sections
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

ALL_CONCEPTS = (
    INCOME_STATEMENT_CONCEPTS
    + BALANCE_SHEET_CONCEPTS
    + CASH_FLOW_CONCEPTS
)


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
        ticker, form_types=form_types, limit=filing_limit,
    )
    filing_count = len(filings)

    for f in filings:
        db.upsert_filing(
            ticker=ticker,
            accession=f["accessionNumber"],
            form=f["form"],
            filing_date=f["filingDate"],
            primary_doc=f.get("primaryDocument", ""),
        )

    company_facts = sec_client.get_company_facts(ticker)
    parser = XBRLParser(company_facts)
    fact_count = _ingest_xbrl_facts(ticker, parser, db)

    sections_extracted = 0
    if settings.enable_filing_text:
        sections_extracted = _ingest_latest_10k_sections(
            ticker, filings, sec_client, db,
        )

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
        ticker, filing_count, fact_count, sections_extracted, elapsed,
    )
    return BootstrapResult(
        ticker=ticker,
        filing_count=filing_count,
        fact_count=fact_count,
        sections_extracted=sections_extracted,
        elapsed_s=elapsed,
    )


def _ingest_xbrl_facts(
    ticker: str, parser: XBRLParser, db: WarehouseDB,
) -> int:
    """Extract all tracked XBRL concepts and write to warehouse. Returns row count."""
    count = 0
    for concept in ALL_CONCEPTS:
        df = parser._extract_concept(concept)
        if df.empty:
            continue
        unit = _unit_for_concept(concept)
        for _, row in df.iterrows():
            period_end = (
                str(row["end"].date())
                if isinstance(row["end"], pd.Timestamp)
                else str(row["end"])
            )
            db.upsert_xbrl_fact(
                ticker=ticker,
                concept=concept,
                unit=unit,
                period_end=period_end,
                value=float(row["val"]),
                form=row.get("form", ""),
                fiscal_year=_safe_int(row.get("fiscal_year")),
                fiscal_period=row.get("fiscal_period"),
            )
            count += 1
    return count


def _ingest_latest_10k_sections(
    ticker: str,
    filings: list[dict],
    sec_client: SECClient,
    db: WarehouseDB,
) -> int:
    """Fetch + parse the most recent 10-K's narrative sections. Returns section count."""
    tenk = next((f for f in filings if f["form"] == "10-K"), None)
    if tenk is None:
        return 0

    accession = tenk["accessionNumber"]
    primary_doc = tenk.get("primaryDocument", "")
    if not primary_doc:
        return 0

    try:
        html = sec_client.get_filing_text(ticker, accession, primary_doc)
    except Exception:
        logger.warning("failed to fetch 10-K text for %s (%s)", ticker, accession, exc_info=True)
        return 0

    sections = parse_filing_sections(html, ticker=ticker)
    written = 0
    for key, text in sections.items():
        if text:
            db.upsert_filing_section(ticker, accession, key, text)
            written += 1
    return written


def _safe_int(val) -> Optional[int]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    return int(val)
