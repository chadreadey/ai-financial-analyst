"""
Poll worker: scans tracked tickers for new SEC filings every POLL_INTERVAL seconds.

Reads tickers from Supabase (or falls back to SQLite for local dev).
Checks data.sec.gov/submissions/{CIK}.json for each ticker.
Enqueues a job when a new accession is detected.

Environment:
    POLL_INTERVAL              seconds between full sweeps (default: 300)
    DATABASE_URL               Supabase postgres connection string (or blank for SQLite)
    WAREHOUSE_DB_PATH          SQLite path used when DATABASE_URL is blank (default: .warehouse.db)
    SEC_USER_AGENT             User-Agent header for SEC EDGAR (default: AIFinancialAnalyst admin@example.com)
    UPSTASH_REDIS_REST_URL
    UPSTASH_REDIS_REST_TOKEN
"""

import json
import logging
import os
import sys
import time

import requests

# ── project root on sys.path so we can import warehouse/config ───────────────
_INFRA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_INFRA_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))

from infra.worker.queue_client import (
    enqueue_filing_update,
    is_processing,
    set_ticker_cik,
    set_ticker_last_accession,
    set_ticker_last_checked,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [poll_worker] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── constants ─────────────────────────────────────────────────────────────────
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "300"))
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik_padded}.json"
# SEC enforces ~10 req/s; we aim for 8 req/s to stay safely under the limit.
SEC_MIN_INTERVAL = 0.125


# =============================================================================
# Database access — Supabase or SQLite fallback
# =============================================================================

def _load_tickers_sqlite() -> list[dict]:
    """
    Load tracked tickers from the local SQLite warehouse DB.
    Returns list of dicts: [{ticker, cik, last_accession}, ...]
    """
    import sqlite3
    db_path = os.environ.get("WAREHOUSE_DB_PATH", ".warehouse.db")
    # Resolve relative to project root
    if not os.path.isabs(db_path):
        db_path = os.path.join(_PROJECT_ROOT, db_path)

    if not os.path.exists(db_path):
        logger.warning("SQLite warehouse not found at %s — no tickers to poll", db_path)
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT ticker, cik, last_accession FROM companies ORDER BY last_checked_at ASC NULLS FIRST"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _load_tickers_postgres(database_url: str) -> list[dict]:
    """
    Load tracked tickers from Supabase (PostgreSQL).
    Returns list of dicts: [{ticker, cik, last_accession}, ...]
    """
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT ticker, cik, last_accession "
                "FROM companies "
                "ORDER BY last_checked_at ASC NULLS FIRST"
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]
    finally:
        conn.close()


def load_tickers() -> list[dict]:
    """Load tickers from Supabase if DATABASE_URL is set, else SQLite."""
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        logger.info("loading tickers from Supabase (PostgreSQL)")
        return _load_tickers_postgres(database_url)
    logger.info("DATABASE_URL not set — loading tickers from SQLite")
    return _load_tickers_sqlite()


def _update_last_checked_postgres(database_url: str, ticker: str, accession: str) -> None:
    import psycopg2

    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE companies SET last_checked_at = NOW(), "
                "last_accession = COALESCE(NULLIF(%s, ''), last_accession) "
                "WHERE ticker = %s",
                (accession, ticker.upper()),
            )
        conn.commit()
    finally:
        conn.close()


def _update_last_checked_sqlite(ticker: str, accession: str) -> None:
    import sqlite3

    db_path = os.environ.get("WAREHOUSE_DB_PATH", ".warehouse.db")
    if not os.path.isabs(db_path):
        db_path = os.path.join(_PROJECT_ROOT, db_path)

    conn = sqlite3.connect(db_path)
    try:
        now = time.time()
        conn.execute(
            "UPDATE companies SET last_checked_at = ? WHERE ticker = ?",
            (now, ticker.upper()),
        )
        if accession:
            conn.execute(
                "UPDATE companies SET last_accession = ? "
                "WHERE ticker = ? AND (last_accession IS NULL OR last_accession != ?)",
                (accession, ticker.upper(), accession),
            )
        conn.commit()
    finally:
        conn.close()


def update_last_checked(ticker: str, accession: str) -> None:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        _update_last_checked_postgres(database_url, ticker, accession)
    else:
        _update_last_checked_sqlite(ticker, accession)


# =============================================================================
# SEC EDGAR polling
# =============================================================================

def _make_session() -> requests.Session:
    user_agent = os.environ.get(
        "SEC_USER_AGENT", "AIFinancialAnalyst admin@example.com"
    )
    session = requests.Session()
    session.headers.update({
        "User-Agent": user_agent,
        "Accept": "application/json",
    })
    return session


def fetch_latest_accession(
    cik_padded: str,
    session: requests.Session,
    last_request_time: list,
) -> tuple[str | None, str | None, str | None]:
    """
    Fetch the most recent accession from SEC EDGAR for a given padded CIK.

    Returns (accession, form, filing_date) or (None, None, None) on failure.
    last_request_time is a one-element list used as a mutable reference for
    rate-limit tracking across calls.
    """
    # Respect SEC 10 req/s rate limit
    elapsed = time.time() - last_request_time[0]
    if elapsed < SEC_MIN_INTERVAL:
        time.sleep(SEC_MIN_INTERVAL - elapsed)
    last_request_time[0] = time.time()

    url = SEC_SUBMISSIONS_URL.format(cik_padded=cik_padded)
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("SEC fetch failed for CIK %s: %s", cik_padded, exc)
        return None, None, None

    recent = data.get("filings", {}).get("recent", {})
    accessions = recent.get("accessionNumber", [])
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])

    if not accessions:
        return None, None, None

    return (
        accessions[0],
        forms[0] if forms else None,
        dates[0] if dates else None,
    )


# =============================================================================
# Main poll loop
# =============================================================================

def run_sweep(session: requests.Session, last_request_time: list) -> None:
    """
    One full sweep: load tickers, check each for new filings, enqueue jobs.
    """
    tickers = load_tickers()
    if not tickers:
        logger.info("no tickers tracked — sleeping until next sweep")
        return

    logger.info("sweep starting: %d tickers", len(tickers))

    # Distribute sleep budget across tickers to honor SEC rate limit.
    # The fetch itself already throttles, but we also yield between tickers
    # to avoid bursting when sweeps restart quickly.
    inter_ticker_sleep = max(0.0, POLL_INTERVAL / len(tickers) - SEC_MIN_INTERVAL)

    changed = 0
    for ticker_row in tickers:
        ticker = ticker_row["ticker"].upper()
        cik_raw = ticker_row.get("cik", "")
        stored_accession = ticker_row.get("last_accession")

        if not cik_raw:
            logger.warning("skipping %s — no CIK stored", ticker)
            continue

        cik_padded = str(cik_raw).zfill(10)

        # Warm Redis cache with CIK
        try:
            set_ticker_cik(ticker, cik_padded)
        except Exception as exc:
            logger.warning("redis set_ticker_cik failed for %s: %s", ticker, exc)

        latest_accession, form, filing_date = fetch_latest_accession(
            cik_padded, session, last_request_time
        )

        if latest_accession is None:
            logger.debug("no accession returned for %s — skipping", ticker)
            continue

        # Update Redis last_checked regardless of whether there is a new filing
        try:
            set_ticker_last_checked(ticker)
        except Exception as exc:
            logger.warning("redis set_ticker_last_checked failed for %s: %s", ticker, exc)

        update_last_checked(ticker, latest_accession)

        if latest_accession == stored_accession:
            logger.debug("%s — no change (accession=%s)", ticker, latest_accession)
            continue

        # New filing detected
        logger.info(
            "new accession for %s: %s (form=%s, date=%s)",
            ticker, latest_accession, form, filing_date,
        )

        # Dedup: skip if already being processed by another worker
        try:
            if is_processing(latest_accession):
                logger.info(
                    "%s accession %s already processing — skipping enqueue",
                    ticker, latest_accession,
                )
                continue
        except Exception as exc:
            logger.warning("redis is_processing check failed for %s: %s", ticker, exc)

        try:
            enqueue_filing_update(
                ticker=ticker,
                accession=latest_accession,
                form=form or "",
                filing_date=filing_date or "",
            )
            set_ticker_last_accession(ticker, latest_accession)
            changed += 1
        except Exception as exc:
            logger.error("failed to enqueue job for %s: %s", ticker, exc)

        # Polite sleep between tickers (on top of fetch throttle)
        if inter_ticker_sleep > 0:
            time.sleep(inter_ticker_sleep)

    logger.info("sweep complete: %d/%d tickers had new filings", changed, len(tickers))


def main() -> None:
    logger.info(
        "poll worker starting (POLL_INTERVAL=%ds)", POLL_INTERVAL
    )
    session = _make_session()
    last_request_time = [0.0]  # mutable reference for rate-limit tracking

    while True:
        sweep_start = time.monotonic()
        try:
            run_sweep(session, last_request_time)
        except Exception as exc:
            logger.error("sweep error: %s", exc, exc_info=True)

        elapsed = time.monotonic() - sweep_start
        sleep_time = max(0.0, POLL_INTERVAL - elapsed)
        logger.info("next sweep in %.0fs", sleep_time)
        time.sleep(sleep_time)


if __name__ == "__main__":
    main()
