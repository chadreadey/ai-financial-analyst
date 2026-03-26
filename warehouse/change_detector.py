"""
Change detection and incremental update logic for the filing warehouse.

Compares the latest SEC accession against what's stored locally to decide
whether new filings need ingestion, then performs a targeted update.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

from config import settings
from sec.client import SECClient
from warehouse.bootstrap import _ingest_latest_10k_sections, _ingest_xbrl_facts
from warehouse.db import WarehouseDB

logger = logging.getLogger(__name__)


@dataclass
class UpdateResult:
    ticker: str
    had_changes: bool
    new_filing_count: int
    elapsed_s: float


def get_latest_accession_from_sec(
    ticker: str, sec_client: SECClient,
) -> Optional[str]:
    """
    Fetch the most recent accessionNumber directly from SEC EDGAR,
    bypassing the local SECCache so we always get fresh state.
    """
    info = sec_client.resolve_ticker(ticker)
    cik_padded = info["cik_padded"]
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"

    try:
        sec_client._throttle()
        resp = sec_client.session.get(url)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.warning(
            "failed to fetch fresh submissions for %s", ticker, exc_info=True,
        )
        return None

    accessions = (
        data.get("filings", {}).get("recent", {}).get("accessionNumber", [])
    )
    return accessions[0] if accessions else None


def needs_update(
    ticker: str, db: WarehouseDB, sec_client: SECClient,
) -> bool:
    """
    Return True when the warehouse data for *ticker* is stale:
      - company row doesn't exist yet
      - SEC has a newer accession than what we stored
      - last_checked_at is older than warehouse_check_interval_hours
    """
    ticker = ticker.upper()
    company = db.get_company(ticker)
    if company is None:
        return True

    last_checked = company.get("last_checked_at")
    if last_checked is not None:
        hours_ago = (time.time() - last_checked) / 3600
        if hours_ago < settings.warehouse_check_interval_hours:
            return False

    sec_accession = get_latest_accession_from_sec(ticker, sec_client)
    if sec_accession is None:
        return False

    stored_accession = company.get("last_accession")
    return sec_accession != stored_accession


def incremental_update(
    ticker: str,
    db: WarehouseDB,
    sec_client: SECClient,
    form_types: list[str] | None = None,
) -> UpdateResult:
    """
    Check for new filings and ingest only what's changed.

    Steps:
      1. Short-circuit if no update needed
      2. Fetch current filings from SEC and diff against stored accessions
      3. Upsert new filing rows
      4. Re-ingest full XBRL fact history (idempotent upsert)
      5. Extract 10-K sections if a new 10-K appeared
      6. Bump last_accession + last_checked_at
    """
    t0 = time.monotonic()
    ticker = ticker.upper()
    if form_types is None:
        form_types = ["10-K", "10-Q", "8-K"]

    if not needs_update(ticker, db, sec_client):
        return UpdateResult(
            ticker=ticker,
            had_changes=False,
            new_filing_count=0,
            elapsed_s=round(time.monotonic() - t0, 2),
        )

    filings = sec_client.get_recent_filings(
        ticker, form_types=form_types, limit=settings.warehouse_filing_limit,
    )

    stored = {
        f["accession"]
        for f in db.get_filings(ticker, limit=1000)
    }
    new_filings = [f for f in filings if f["accessionNumber"] not in stored]

    for f in new_filings:
        db.upsert_filing(
            ticker=ticker,
            accession=f["accessionNumber"],
            form=f["form"],
            filing_date=f["filingDate"],
            primary_doc=f.get("primaryDocument", ""),
        )

    from sec.xbrl_parser import XBRLParser

    company_facts = sec_client.get_company_facts(ticker)
    parser = XBRLParser(company_facts)
    _ingest_xbrl_facts(ticker, parser, db)

    if settings.enable_filing_text:
        new_10k = [f for f in new_filings if f["form"] == "10-K"]
        if new_10k:
            _ingest_latest_10k_sections(ticker, new_10k, sec_client, db)

    latest_accession = filings[0]["accessionNumber"] if filings else None
    if latest_accession:
        db.update_last_checked(ticker, latest_accession)

    elapsed = round(time.monotonic() - t0, 2)
    logger.info(
        "incremental update %s: %d new filings in %.1fs",
        ticker, len(new_filings), elapsed,
    )
    return UpdateResult(
        ticker=ticker,
        had_changes=len(new_filings) > 0,
        new_filing_count=len(new_filings),
        elapsed_s=elapsed,
    )
