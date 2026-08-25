"""
Alpaca paper trading client.

Wraps the alpaca-py SDK to submit market orders, fetch account info,
and sync positions back to the SQLite paper_positions table.
All calls target Alpaca's paper trading environment.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from typing import Any, Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus

from config import Settings, settings as default_settings

logger = logging.getLogger(__name__)


class AlpacaPaperClient:
    """Thin wrapper around alpaca-py TradingClient for paper trading."""

    def __init__(self, cfg: Optional[Settings] = None) -> None:
        self._cfg = cfg or default_settings
        if not self._cfg.alpaca_api_key or not self._cfg.alpaca_secret_key:
            raise EnvironmentError(
                "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set for paper trading"
            )
        self._client = TradingClient(
            api_key=self._cfg.alpaca_api_key,
            secret_key=self._cfg.alpaca_secret_key,
            paper=True,
        )

    def get_account(self) -> dict[str, Any]:
        """Return account summary dict."""
        acct = self._client.get_account()
        return {
            "cash": float(acct.cash),
            "equity": float(acct.equity),
            "buying_power": float(acct.buying_power),
            "portfolio_value": float(acct.portfolio_value),
            "currency": str(acct.currency),
        }

    def submit_market_order(
        self,
        symbol: str,
        qty: int,
        side: str = "buy",
    ) -> dict[str, Any]:
        """Submit a market order. Returns order summary dict."""
        order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
        req = MarketOrderRequest(
            symbol=symbol.upper(),
            qty=qty,
            side=order_side,
            time_in_force=TimeInForce.DAY,
        )
        order = self._client.submit_order(req)
        return self._order_to_dict(order)

    def get_positions(self) -> list[dict[str, Any]]:
        """Return all open positions from Alpaca."""
        positions = self._client.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": int(p.qty),
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
                "market_value": float(p.market_value),
                "side": str(p.side),
            }
            for p in positions
        ]

    def get_orders(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent orders from Alpaca."""
        req = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=limit)
        orders = self._client.get_orders(req)
        return [self._order_to_dict(o) for o in orders]

    def close_position(self, symbol: str) -> dict[str, Any]:
        """Close an entire position by symbol."""
        order = self._client.close_position(symbol.upper())
        return self._order_to_dict(order)

    def close_all_positions(self) -> list[dict[str, Any]]:
        """Close all open positions."""
        responses = self._client.close_all_positions(cancel_orders=True)
        return [self._order_to_dict(r) for r in responses if hasattr(r, "id")]

    def sync_positions_to_db(self) -> int:
        """Sync Alpaca positions into SQLite paper_positions table. Returns count synced."""
        positions = self.get_positions()
        conn = sqlite3.connect(self._cfg.warehouse_db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_positions (
                ticker TEXT PRIMARY KEY, entry_price REAL, entry_date TEXT,
                current_price REAL, verdict TEXT DEFAULT '', exit_conditions TEXT DEFAULT '',
                direction TEXT DEFAULT 'LONG', conviction_score REAL
            )
        """)
        for p in positions:
            direction = "LONG" if p["side"] == "long" else "SHORT"
            conn.execute(
                "INSERT OR REPLACE INTO paper_positions "
                "(ticker, entry_price, entry_date, current_price, direction) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    p["symbol"],
                    p["avg_entry_price"],
                    time.strftime("%Y-%m-%d"),
                    p["current_price"],
                    direction,
                ),
            )
        conn.commit()
        conn.close()
        logger.info("Synced %d Alpaca positions to SQLite", len(positions))
        return len(positions)

    @staticmethod
    def _order_to_dict(order: Any) -> dict[str, Any]:
        """Convert an alpaca Order object to a plain dict."""
        return {
            "order_id": str(order.id),
            "symbol": str(order.symbol),
            "qty": int(order.qty) if order.qty else 0,
            "side": str(order.side),
            "status": str(order.status),
            "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
            "filled_at": str(order.filled_at) if order.filled_at else None,
            "submitted_at": str(order.submitted_at) if order.submitted_at else None,
            "order_type": str(getattr(order, "order_type", "market")),
        }


# Module-level singleton (lazy)
_client: Optional[AlpacaPaperClient] = None


def get_alpaca_client() -> AlpacaPaperClient:
    """Get or create the singleton Alpaca paper client."""
    global _client
    if _client is None:
        _client = AlpacaPaperClient()
    return _client
