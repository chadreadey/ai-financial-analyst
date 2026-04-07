"""
FundamentalProvider protocol — unified interface for fundamental data access.

Both the FMP/Tiingo cache (live) and the WRDS point-in-time store (backtest)
satisfy this protocol. The backtest engine selects provider based on config.

The key difference: as_of_date.
- FMP cache ignores as_of_date (always returns latest snapshot)
- WRDS store filters on rdq/statpers (point-in-time discipline)
"""

from __future__ import annotations

from datetime import date
from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class FundamentalProvider(Protocol):
    """
    Abstract interface for fundamental data access.

    All implementations must respect point-in-time discipline when
    as_of_date is provided: only return data that was publicly available
    on or before as_of_date.

    When as_of_date is None, return the most recent data (live mode).
    """

    def get_balance_sheet_quarterly(
        self, ticker: str, limit: int = 4, as_of_date: Optional[date] = None,
    ) -> list[dict]:
        """Return quarterly balance sheet data, most recent first."""
        ...

    def get_income_statement_quarterly(
        self, ticker: str, limit: int = 8, as_of_date: Optional[date] = None,
    ) -> list[dict]:
        """Return quarterly income statement data, most recent first."""
        ...

    def get_analyst_estimates(
        self, ticker: str, limit: int = 4, as_of_date: Optional[date] = None,
    ) -> list[dict]:
        """Return analyst consensus estimates, most recent first."""
        ...


class WRDSFundamentalProvider:
    """
    WRDS point-in-time provider.

    Wraps WRDSPointInTimeStore to satisfy FundamentalProvider protocol.
    Converts WRDS field names to FMP-compatible names so downstream
    signal code needs no changes.

    Handles IBES ticker translation: our ticker (META) → IBES ticker (FBK).
    """

    def __init__(self, store) -> None:
        from quant.wrds_store import WRDSPointInTimeStore
        self._store: WRDSPointInTimeStore = store
        self._ibes_map: dict[str, str] = {}  # our_ticker → ibes_ticker
        self._build_ibes_map()

    def _build_ibes_map(self) -> None:
        """Build ticker → IBES ticker mapping from the link table."""
        import sqlite3
        conn = sqlite3.connect(self._store._db_path)
        rows = conn.execute(
            "SELECT ticker, ibes_ticker FROM ticker_link WHERE ibes_ticker IS NOT NULL"
        ).fetchall()
        conn.close()
        for ticker, ibes_ticker in rows:
            if ibes_ticker and ibes_ticker != ticker:
                self._ibes_map[ticker.upper()] = ibes_ticker.upper()

    def _ibes_ticker(self, ticker: str) -> str:
        """Get the IBES ticker for a given exchange ticker."""
        return self._ibes_map.get(ticker.upper(), ticker.upper())

    def get_balance_sheet_quarterly(
        self, ticker: str, limit: int = 4, as_of_date: Optional[date] = None,
    ) -> list[dict]:
        date_str = str(as_of_date) if as_of_date else "2099-12-31"
        return self._store.get_fundamentals_as_of(ticker, date_str, n_quarters=limit)

    def get_income_statement_quarterly(
        self, ticker: str, limit: int = 8, as_of_date: Optional[date] = None,
    ) -> list[dict]:
        # Compustat fundq has both balance sheet and income in one row
        # get_fundamentals_as_of already returns FMP-compatible dicts with both
        date_str = str(as_of_date) if as_of_date else "2099-12-31"
        return self._store.get_fundamentals_as_of(ticker, date_str, n_quarters=limit)

    def get_analyst_estimates(
        self, ticker: str, limit: int = 4, as_of_date: Optional[date] = None,
    ) -> list[dict]:
        date_str = str(as_of_date) if as_of_date else "2099-12-31"
        # Try our ticker first, then IBES ticker if different
        ibes_tk = self._ibes_ticker(ticker)
        rows = self._store.get_ibes_consensus_as_of(ticker, date_str, n_periods=limit)
        if not rows and ibes_tk != ticker.upper():
            rows = self._store.get_ibes_consensus_as_of(ibes_tk, date_str, n_periods=limit)
        # Convert IBES fields to FMP-compatible names
        return [{
            "date": r.get("statpers", ""),
            "fpedats": r.get("fpedats", ""),
            "epsAvg": r.get("meanest"),
            "epsMedian": r.get("medest"),
            "numAnalystsEps": r.get("numest"),
            "epsStdev": r.get("stdev"),
            "numUp": r.get("numup"),
            "numDown": r.get("numdown"),
        } for r in rows]
