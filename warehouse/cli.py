"""
CLI for warehouse operations.

Usage:
    python -m warehouse.cli bootstrap TICKER [TICKER...]
    python -m warehouse.cli refresh [TICKER...]
    python -m warehouse.cli status
    python -m warehouse.cli drop TICKER
"""

import argparse
import logging
import sys
import time

from sec.client import SECClient
from warehouse.db import WarehouseDB
from warehouse.bootstrap import bootstrap_ticker
from warehouse.change_detector import incremental_update

logger = logging.getLogger(__name__)


def _ts_fmt(ts: float | None) -> str:
    if ts is None:
        return "never"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


def cmd_bootstrap(args: argparse.Namespace) -> None:
    db = WarehouseDB()
    sec = SECClient()
    for ticker in args.tickers:
        ticker = ticker.upper()
        print(f"Bootstrapping {ticker} ...")
        try:
            result = bootstrap_ticker(ticker, db, sec)
            print(f"  {ticker}: {result}")
        except Exception as exc:
            print(f"  {ticker}: ERROR – {exc}", file=sys.stderr)


def cmd_refresh(args: argparse.Namespace) -> None:
    db = WarehouseDB()
    sec = SECClient()
    tickers = [t.upper() for t in args.tickers] if args.tickers else db.list_tracked_tickers()
    if not tickers:
        print("No tracked tickers to refresh.")
        return
    for ticker in tickers:
        print(f"Refreshing {ticker} ...")
        try:
            result = incremental_update(ticker, db, sec)
            print(f"  {ticker}: {result}")
        except Exception as exc:
            print(f"  {ticker}: ERROR – {exc}", file=sys.stderr)


def cmd_status(args: argparse.Namespace) -> None:
    db = WarehouseDB()
    tickers = db.list_tracked_tickers()
    if not tickers:
        print("No tickers tracked in warehouse.")
        return

    header = f"{'Ticker':<8} {'Bootstrapped':<18} {'Last Checked':<18} {'Filings':>8} {'Facts':>8}"
    print(header)
    print("-" * len(header))

    for ticker in tickers:
        company = db.get_company(ticker)
        filings = db.get_filings(ticker, limit=10000)
        facts = db.get_xbrl_facts(ticker)

        bootstrapped = _ts_fmt(company.get("bootstrapped_at") if company else None)
        last_checked = _ts_fmt(company.get("last_checked_at") if company else None)
        print(
            f"{ticker:<8} {bootstrapped:<18} {last_checked:<18} {len(filings):>8} {len(facts):>8}"
        )


def cmd_drop(args: argparse.Namespace) -> None:
    db = WarehouseDB()
    ticker = args.ticker.upper()

    company = db.get_company(ticker)
    if company is None:
        print(f"{ticker} is not tracked in the warehouse.")
        return

    import sqlite3

    conn = sqlite3.connect(db._db_path)
    try:
        tables = ["companies", "filings", "xbrl_facts", "market_snapshots", "filing_sections"]
        for table in tables:
            conn.execute(f"DELETE FROM {table} WHERE ticker = ?", (ticker,))
        conn.commit()
        print(f"Dropped all data for {ticker}.")
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s – %(message)s",
    )

    parser = argparse.ArgumentParser(
        prog="warehouse",
        description="AI Financial Analyst – warehouse management CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_boot = sub.add_parser("bootstrap", help="Bootstrap one or more tickers")
    p_boot.add_argument("tickers", nargs="+", metavar="TICKER")
    p_boot.set_defaults(func=cmd_bootstrap)

    p_refresh = sub.add_parser("refresh", help="Incremental update for tickers (all if none given)")
    p_refresh.add_argument("tickers", nargs="*", metavar="TICKER")
    p_refresh.set_defaults(func=cmd_refresh)

    p_status = sub.add_parser("status", help="Show tracked tickers and stats")
    p_status.set_defaults(func=cmd_status)

    p_drop = sub.add_parser("drop", help="Remove a ticker from the warehouse")
    p_drop.add_argument("ticker", metavar="TICKER")
    p_drop.set_defaults(func=cmd_drop)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
