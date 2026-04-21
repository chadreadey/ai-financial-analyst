# Alpaca Paper Trading Execution

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing paper trading system to Alpaca's paper trading API so positions are executed as real (paper) market orders, synced back to SQLite, and rebalanced monthly on a schedule.

**Architecture:** New `AlpacaPaperClient` wraps `alpaca-py` SDK for order submission and account queries. The existing `_auto_paper_trade()` in `orchestrator.py` gains an Alpaca execution path gated by `auto_paper_trade`. A scheduler runs monthly rebalance (analysis -> diff -> trade). Three new API endpoints expose Alpaca account info, order history, and manual rebalance trigger. Frontend gets an AccountPanel and OrderHistory table.

**Tech Stack:** Python/FastAPI, `alpaca-py>=0.28.0`, `APScheduler>=3.10`, SQLite, React/TypeScript

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `requirements.txt` | Modify | Add `alpaca-py>=0.28.0` and `APScheduler>=3.10.4` |
| `config.py` | Modify | Add `alpaca_api_key`, `alpaca_secret_key`, `alpaca_paper_base_url`, `paper_rebalance_cron` |
| `backend/alpaca_paper_client.py` | Create | Wraps alpaca-py: submit orders, get account, get positions, get orders, sync to SQLite |
| `orchestrator.py` | Modify | Add Alpaca order submission inside `_auto_paper_trade()` |
| `backend/paper_scheduler.py` | Create | APScheduler monthly rebalance job |
| `backend/routers/paper_trading.py` | Modify | Add GET /account, GET /orders, POST /rebalance endpoints |
| `backend/main.py` | Modify | Start scheduler in lifespan, register new endpoints |
| `frontend/src/api/client.ts` | Modify | Add `getAlpacaAccount`, `getAlpacaOrders`, `triggerRebalance` |
| `frontend/src/api/types.ts` | Modify | Add `AlpacaAccount`, `AlpacaOrder` interfaces |
| `frontend/src/components/paper-trading/AccountPanel.tsx` | Create | Alpaca balance/buying power display |
| `frontend/src/components/paper-trading/OrderHistoryTable.tsx` | Create | Order history table |
| `frontend/src/pages/PaperTradingPage.tsx` | Modify | Add AccountPanel, OrderHistory, rebalance button |
| `frontend/src/hooks/usePaperTrading.ts` | Modify | Fetch account and orders data |
| `tests/test_alpaca_paper_client.py` | Create | Unit tests for client |
| `tests/test_paper_scheduler.py` | Create | Unit tests for scheduler |
| `tests/test_paper_trading_router.py` | Create | Integration tests for new endpoints |

---

## Task 1: Alpaca Paper Client

**Files:**
- Create: `backend/alpaca_paper_client.py`
- Create: `tests/test_alpaca_paper_client.py`
- Modify: `requirements.txt`
- Modify: `config.py`

- [ ] **Step 1: Add dependencies to requirements.txt**

Append to `requirements.txt`:

```
# Alpaca paper trading
alpaca-py>=0.28.0

# Scheduling
APScheduler>=3.10.4
```

- [ ] **Step 2: Add Alpaca config fields to config.py**

Add these fields to the `Settings` class in `config.py`, after the existing `auto_paper_trade_min_conviction` line:

```python
    # ── Alpaca paper trading ──────────────────────────────────────────
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_paper_base_url: str = "https://paper-api.alpaca.markets"
    paper_default_qty: int = 10
    paper_rebalance_cron: str = "0 9 1 * *"  # 1st of month at 9:00 AM ET
```

- [ ] **Step 3: Write failing tests**

Create `tests/test_alpaca_paper_client.py`:

```python
"""Tests for Alpaca paper trading client."""
from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_settings(tmp_path):
    """Settings with a temp DB path and fake Alpaca keys."""
    from config import Settings
    return Settings(
        alpaca_api_key="test-key-id",
        alpaca_secret_key="test-secret-key",
        alpaca_paper_base_url="https://paper-api.alpaca.markets",
        warehouse_db_path=str(tmp_path / "test.db"),
        paper_default_qty=10,
    )


@patch("backend.alpaca_paper_client.TradingClient")
def test_get_account(mock_tc_class, mock_settings):
    mock_tc = MagicMock()
    account = MagicMock()
    account.cash = "100000.00"
    account.equity = "100000.00"
    account.buying_power = "200000.00"
    account.portfolio_value = "100000.00"
    account.currency = "USD"
    mock_tc.get_account.return_value = account
    mock_tc_class.return_value = mock_tc

    from backend.alpaca_paper_client import AlpacaPaperClient
    client = AlpacaPaperClient(mock_settings)
    result = client.get_account()

    assert result["cash"] == 100000.00
    assert result["buying_power"] == 200000.00
    assert result["equity"] == 100000.00


@patch("backend.alpaca_paper_client.TradingClient")
def test_submit_market_order(mock_tc_class, mock_settings):
    mock_tc = MagicMock()
    order = MagicMock()
    order.id = "order-123"
    order.status = "accepted"
    order.symbol = "AAPL"
    order.qty = "10"
    order.side = "buy"
    order.filled_avg_price = None
    order.filled_at = None
    order.submitted_at = "2026-04-15T14:30:00Z"
    mock_tc.submit_order.return_value = order
    mock_tc_class.return_value = mock_tc

    from backend.alpaca_paper_client import AlpacaPaperClient
    client = AlpacaPaperClient(mock_settings)
    result = client.submit_market_order("AAPL", qty=10, side="buy")

    assert result["order_id"] == "order-123"
    assert result["status"] == "accepted"
    assert result["symbol"] == "AAPL"
    mock_tc.submit_order.assert_called_once()


@patch("backend.alpaca_paper_client.TradingClient")
def test_get_positions(mock_tc_class, mock_settings):
    mock_tc = MagicMock()
    pos = MagicMock()
    pos.symbol = "AAPL"
    pos.qty = "10"
    pos.avg_entry_price = "150.00"
    pos.current_price = "155.00"
    pos.unrealized_pl = "50.00"
    pos.unrealized_plpc = "0.0333"
    pos.market_value = "1550.00"
    pos.side = "long"
    mock_tc.get_all_positions.return_value = [pos]
    mock_tc_class.return_value = mock_tc

    from backend.alpaca_paper_client import AlpacaPaperClient
    client = AlpacaPaperClient(mock_settings)
    positions = client.get_positions()

    assert len(positions) == 1
    assert positions[0]["symbol"] == "AAPL"
    assert positions[0]["qty"] == 10
    assert positions[0]["avg_entry_price"] == 150.00


@patch("backend.alpaca_paper_client.TradingClient")
def test_get_orders(mock_tc_class, mock_settings):
    mock_tc = MagicMock()
    order = MagicMock()
    order.id = "order-456"
    order.symbol = "MSFT"
    order.qty = "5"
    order.side = "buy"
    order.status = "filled"
    order.filled_avg_price = "400.00"
    order.filled_at = "2026-04-15T14:31:00Z"
    order.submitted_at = "2026-04-15T14:30:00Z"
    order.order_type = "market"
    mock_tc.get_orders.return_value = [order]
    mock_tc_class.return_value = mock_tc

    from backend.alpaca_paper_client import AlpacaPaperClient
    client = AlpacaPaperClient(mock_settings)
    orders = client.get_orders()

    assert len(orders) == 1
    assert orders[0]["order_id"] == "order-456"
    assert orders[0]["filled_avg_price"] == 400.00


@patch("backend.alpaca_paper_client.TradingClient")
def test_sync_positions_to_sqlite(mock_tc_class, mock_settings):
    mock_tc = MagicMock()
    pos = MagicMock()
    pos.symbol = "AAPL"
    pos.qty = "10"
    pos.avg_entry_price = "150.00"
    pos.current_price = "155.00"
    pos.unrealized_pl = "50.00"
    pos.unrealized_plpc = "0.0333"
    pos.market_value = "1550.00"
    pos.side = "long"
    mock_tc.get_all_positions.return_value = [pos]
    mock_tc_class.return_value = mock_tc

    from backend.alpaca_paper_client import AlpacaPaperClient
    client = AlpacaPaperClient(mock_settings)
    client.sync_positions_to_db()

    conn = sqlite3.connect(mock_settings.warehouse_db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM paper_positions").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["entry_price"] == 150.00


@patch("backend.alpaca_paper_client.TradingClient")
def test_close_position(mock_tc_class, mock_settings):
    mock_tc = MagicMock()
    order = MagicMock()
    order.id = "close-789"
    order.status = "accepted"
    order.symbol = "AAPL"
    order.qty = "10"
    order.side = "sell"
    order.filled_avg_price = None
    order.filled_at = None
    order.submitted_at = "2026-04-15T15:00:00Z"
    mock_tc.close_position.return_value = order
    mock_tc_class.return_value = mock_tc

    from backend.alpaca_paper_client import AlpacaPaperClient
    client = AlpacaPaperClient(mock_settings)
    result = client.close_position("AAPL")

    assert result["order_id"] == "close-789"
    mock_tc.close_position.assert_called_once_with("AAPL")
```

- [ ] **Step 4: Run tests to confirm failure**

```bash
python -m pytest tests/test_alpaca_paper_client.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'backend.alpaca_paper_client'`

- [ ] **Step 5: Install dependencies**

```bash
pip install "alpaca-py>=0.28.0" "APScheduler>=3.10.4"
```

- [ ] **Step 6: Implement `backend/alpaca_paper_client.py`**

Create `backend/alpaca_paper_client.py`:

```python
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
        """
        Sync Alpaca positions into SQLite paper_positions table.
        Returns number of positions synced.
        """
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
```

- [ ] **Step 7: Run tests**

```bash
python -m pytest tests/test_alpaca_paper_client.py -v
```

Expected: All 6 tests pass.

- [ ] **Step 8: Commit**

```bash
git add backend/alpaca_paper_client.py tests/test_alpaca_paper_client.py requirements.txt config.py
git commit -m "feat: add Alpaca paper trading client with tests"
```

---

## Task 2: Wire Auto-Execution to Alpaca

**Files:**
- Modify: `orchestrator.py`

The existing `_auto_paper_trade()` function writes directly to SQLite. We add Alpaca order submission so the position is both tracked locally and executed on Alpaca.

- [ ] **Step 1: Find `_auto_paper_trade()` in orchestrator.py**

```bash
grep -n "_auto_paper_trade\|auto_paper_trade" orchestrator.py | head -20
```

- [ ] **Step 2: Add Alpaca submission inside `_auto_paper_trade()`**

After the existing SQLite commit/close (after `conn.close()`), before the success log, add:

```python
        # Submit to Alpaca paper trading if keys are configured
        if settings.alpaca_api_key and settings.alpaca_secret_key:
            try:
                from backend.alpaca_paper_client import get_alpaca_client
                alpaca = get_alpaca_client()
                side = "buy" if direction == "LONG" else "sell"
                order = alpaca.submit_market_order(
                    symbol=ticker,
                    qty=settings.paper_default_qty,
                    side=side,
                )
                logger.info(
                    "Auto-paper-trade: Alpaca order %s %s %s qty=%d status=%s",
                    order["order_id"], side, ticker, settings.paper_default_qty, order["status"],
                )
            except Exception as alpaca_exc:
                logger.warning("Auto-paper-trade: Alpaca order failed for %s: %s", ticker, alpaca_exc)
```

- [ ] **Step 3: Run smoke test**

```bash
python scripts/run_backtest.py --tickers AAPL,MSFT,GOOGL --start 2023-01-01 --end 2024-01-01 2>&1 | tail -5
```

Expected: completes without error (Alpaca block skipped when keys empty).

- [ ] **Step 4: Commit**

```bash
git add orchestrator.py
git commit -m "feat: wire auto paper trade to Alpaca order submission"
```

---

## Task 3: Paper Scheduler

**Files:**
- Create: `backend/paper_scheduler.py`
- Create: `tests/test_paper_scheduler.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_paper_scheduler.py`:

```python
"""Tests for paper trading scheduler."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@patch("backend.paper_scheduler.get_alpaca_client")
@patch("backend.paper_scheduler.run_analysis_job")
@patch("backend.paper_scheduler.create_job")
def test_rebalance_job_runs_analysis_and_submits_orders(
    mock_create_job, mock_run_analysis, mock_get_client
):
    from backend.paper_scheduler import run_rebalance

    mock_client = MagicMock()
    mock_client.get_positions.return_value = [
        {"symbol": "AAPL", "qty": 10, "side": "long"},
    ]
    mock_client.close_position.return_value = {"order_id": "close-1", "status": "accepted"}
    mock_client.submit_market_order.return_value = {"order_id": "buy-1", "status": "accepted"}
    mock_client.sync_positions_to_db.return_value = 2
    mock_get_client.return_value = mock_client

    mock_job = MagicMock()
    mock_job.status = "complete"
    mock_job.result = MagicMock()
    mock_job.result.structured_verdict = {
        "verdict": "BUY",
        "conviction_score": 0.75,
        "entry_price": 180.0,
    }
    mock_create_job.return_value = mock_job

    result = run_rebalance(target_tickers=["MSFT"])

    assert result["status"] == "ok"
    assert result["closed"] == ["AAPL"]
    assert result["opened"] == ["MSFT"]


def test_scheduler_starts_without_error():
    from backend.paper_scheduler import create_scheduler
    scheduler = create_scheduler(start=False)
    assert scheduler is not None
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
python -m pytest tests/test_paper_scheduler.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'backend.paper_scheduler'`

- [ ] **Step 3: Implement `backend/paper_scheduler.py`**

Create `backend/paper_scheduler.py`:

```python
"""
Monthly paper trading rebalance scheduler.

Uses APScheduler to run a rebalance job on the 1st of each month at
market open (9:30 AM ET). The job:
1. Fetches current Alpaca positions
2. Runs analysis on target tickers (from watchlist or top quant picks)
3. Diffs current vs desired positions
4. Closes stale positions, opens new ones
5. Syncs Alpaca state back to SQLite
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import settings
from backend.alpaca_paper_client import get_alpaca_client

logger = logging.getLogger(__name__)


def _get_watchlist_tickers() -> list[str]:
    """Pull tickers from the watchlist table."""
    try:
        conn = sqlite3.connect(settings.warehouse_db_path)
        rows = conn.execute("SELECT ticker FROM watchlist").fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def run_rebalance(target_tickers: Optional[list[str]] = None) -> dict[str, Any]:
    """
    Execute a full rebalance cycle.

    1. Get current Alpaca positions
    2. Determine target tickers (passed in or from watchlist)
    3. Close positions not in target list
    4. For each target, run analysis and open position if conviction passes
    5. Sync back to SQLite
    """
    from backend.jobs import create_job, run_analysis_job
    from backend.schemas import RunAnalysisRequest

    client = get_alpaca_client()

    current_positions = client.get_positions()
    current_symbols = {p["symbol"] for p in current_positions}

    if not target_tickers:
        target_tickers = _get_watchlist_tickers()
    target_set = {t.upper() for t in target_tickers}

    closed: list[str] = []
    opened: list[str] = []
    errors: list[str] = []

    # Close positions not in target list
    for symbol in current_symbols:
        if symbol not in target_set:
            try:
                client.close_position(symbol)
                closed.append(symbol)
                logger.info("Rebalance: closed %s (not in target list)", symbol)
            except Exception as exc:
                errors.append(f"close {symbol}: {exc}")
                logger.warning("Rebalance: failed to close %s: %s", symbol, exc)

    # Open new positions based on analysis
    for ticker in target_set:
        if ticker in current_symbols:
            continue  # Already holding

        try:
            request = RunAnalysisRequest(ticker=ticker)
            job = create_job(ticker)
            run_analysis_job(job, request)

            if job.status != "complete" or not job.result:
                logger.warning("Rebalance: analysis failed for %s: %s", ticker, job.error)
                errors.append(f"analysis {ticker}: {job.error}")
                continue

            structured = job.result.structured_verdict
            conviction = float(structured.get("conviction_score", 0))
            verdict = (structured.get("verdict") or "").upper()

            if conviction < settings.auto_paper_trade_min_conviction:
                logger.info("Rebalance: %s conviction %.2f below threshold, skip", ticker, conviction)
                continue

            if "BUY" in verdict:
                side = "buy"
            elif "SELL" in verdict:
                side = "sell"
            else:
                logger.info("Rebalance: %s verdict=%s, skipping", ticker, verdict)
                continue

            order = client.submit_market_order(
                symbol=ticker,
                qty=settings.paper_default_qty,
                side=side,
            )
            opened.append(ticker)
            logger.info("Rebalance: opened %s %s qty=%d order=%s",
                        side, ticker, settings.paper_default_qty, order["order_id"])

        except Exception as exc:
            errors.append(f"open {ticker}: {exc}")
            logger.warning("Rebalance: failed to open %s: %s", ticker, exc)

    # Sync Alpaca state back to SQLite
    try:
        client.sync_positions_to_db()
    except Exception as exc:
        logger.warning("Rebalance: sync failed: %s", exc)

    result = {
        "status": "ok" if not errors else "partial",
        "closed": closed,
        "opened": opened,
        "errors": errors,
    }
    logger.info("Rebalance complete: %s", result)
    return result


def _scheduled_rebalance():
    """Wrapper for the scheduled job."""
    logger.info("Scheduled monthly rebalance starting...")
    try:
        result = run_rebalance()
        logger.info("Scheduled rebalance result: %s", result)
    except Exception as exc:
        logger.error("Scheduled rebalance failed: %s", exc, exc_info=True)


def create_scheduler(start: bool = True) -> BackgroundScheduler:
    """Create and optionally start the APScheduler background scheduler."""
    scheduler = BackgroundScheduler(timezone="US/Eastern")

    parts = settings.paper_rebalance_cron.split()
    if len(parts) == 5:
        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )
    else:
        trigger = CronTrigger(minute=30, hour=9, day=1)

    scheduler.add_job(
        _scheduled_rebalance,
        trigger=trigger,
        id="paper_rebalance",
        name="Monthly paper trading rebalance",
        replace_existing=True,
    )

    if start:
        scheduler.start()
        logger.info("Paper trading scheduler started (cron=%s)", settings.paper_rebalance_cron)

    return scheduler
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_paper_scheduler.py -v
```

Expected: Both tests pass.

- [ ] **Step 5: Wire scheduler into FastAPI lifespan in `backend/main.py`**

Find the existing `lifespan` function in `backend/main.py`. Add scheduler startup inside it:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start paper trading scheduler if Alpaca keys are configured
    scheduler = None
    if settings.alpaca_api_key and settings.alpaca_secret_key:
        try:
            from backend.paper_scheduler import create_scheduler
            scheduler = create_scheduler(start=True)
            logger.info("Paper trading scheduler started")
        except Exception as exc:
            logger.warning("Failed to start paper trading scheduler: %s", exc)
    yield
    if scheduler:
        scheduler.shutdown(wait=False)
```

- [ ] **Step 6: Commit**

```bash
git add backend/paper_scheduler.py tests/test_paper_scheduler.py backend/main.py
git commit -m "feat: add monthly paper trading rebalance scheduler"
```

---

## Task 4: New Router Endpoints

**Files:**
- Modify: `backend/routers/paper_trading.py`
- Create: `tests/test_paper_trading_router.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_paper_trading_router.py`:

```python
"""Tests for paper trading router endpoints."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from backend.main import app
    return TestClient(app)


@patch("backend.routers.paper_trading.get_alpaca_client")
def test_get_account(mock_get_client, client):
    mock_alpaca = MagicMock()
    mock_alpaca.get_account.return_value = {
        "cash": 100000.0,
        "equity": 100000.0,
        "buying_power": 200000.0,
        "portfolio_value": 100000.0,
        "currency": "USD",
    }
    mock_get_client.return_value = mock_alpaca

    resp = client.get("/api/paper-trading/account")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cash"] == 100000.0
    assert data["buying_power"] == 200000.0


@patch("backend.routers.paper_trading.get_alpaca_client")
def test_get_orders(mock_get_client, client):
    mock_alpaca = MagicMock()
    mock_alpaca.get_orders.return_value = [
        {
            "order_id": "ord-1",
            "symbol": "AAPL",
            "qty": 10,
            "side": "buy",
            "status": "filled",
            "filled_avg_price": 150.0,
            "filled_at": "2026-04-15T14:31:00Z",
            "submitted_at": "2026-04-15T14:30:00Z",
            "order_type": "market",
        }
    ]
    mock_get_client.return_value = mock_alpaca

    resp = client.get("/api/paper-trading/orders")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["orders"]) == 1
    assert data["orders"][0]["symbol"] == "AAPL"


@patch("backend.routers.paper_trading.run_rebalance")
def test_trigger_rebalance(mock_rebalance, client):
    mock_rebalance.return_value = {
        "status": "ok",
        "closed": ["AAPL"],
        "opened": ["MSFT"],
        "errors": [],
    }

    resp = client.post("/api/paper-trading/rebalance", json={"tickers": ["MSFT"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "MSFT" in data["opened"]


@patch("backend.routers.paper_trading.get_alpaca_client")
def test_get_account_no_keys(mock_get_client, client):
    mock_get_client.side_effect = EnvironmentError("No keys")
    resp = client.get("/api/paper-trading/account")
    assert resp.status_code == 200
    data = resp.json()
    assert data["error"] == "Alpaca not configured"
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
python -m pytest tests/test_paper_trading_router.py -v 2>&1 | head -20
```

Expected: 404 errors (endpoints don't exist yet).

- [ ] **Step 3: Add new endpoints to `backend/routers/paper_trading.py`**

Append to the end of the file:

```python


# ── Alpaca integration endpoints ──────────────────────────────────


@router.get("/account")
async def get_alpaca_account():
    """Return Alpaca paper account info (balance, buying power)."""
    try:
        from backend.alpaca_paper_client import get_alpaca_client
        client = get_alpaca_client()
        return client.get_account()
    except EnvironmentError:
        return {"error": "Alpaca not configured"}
    except Exception as exc:
        logger.warning("Failed to get Alpaca account: %s", exc)
        return {"error": str(exc)}


@router.get("/orders")
async def get_alpaca_orders():
    """Return recent Alpaca order history."""
    try:
        from backend.alpaca_paper_client import get_alpaca_client
        client = get_alpaca_client()
        orders = client.get_orders()
        return {"orders": orders}
    except EnvironmentError:
        return {"orders": [], "error": "Alpaca not configured"}
    except Exception as exc:
        logger.warning("Failed to get Alpaca orders: %s", exc)
        return {"orders": [], "error": str(exc)}


@router.post("/rebalance")
async def trigger_rebalance(body: dict = None):
    """Trigger a manual rebalance. Optionally pass {"tickers": ["AAPL", "MSFT"]}."""
    try:
        from backend.paper_scheduler import run_rebalance
        tickers = (body or {}).get("tickers")
        result = run_rebalance(target_tickers=tickers)
        return result
    except Exception as exc:
        logger.error("Rebalance failed: %s", exc, exc_info=True)
        return {"status": "error", "error": str(exc)}
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_paper_trading_router.py -v
```

Expected: All 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/paper_trading.py tests/test_paper_trading_router.py
git commit -m "feat: add Alpaca account, orders, and rebalance endpoints"
```

---

## Task 5: Frontend Additions

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Create: `frontend/src/components/paper-trading/AccountPanel.tsx`
- Create: `frontend/src/components/paper-trading/OrderHistoryTable.tsx`
- Modify: `frontend/src/hooks/usePaperTrading.ts`
- Modify: `frontend/src/pages/PaperTradingPage.tsx`

- [ ] **Step 1: Add TypeScript types to `frontend/src/api/types.ts`**

Append to the end of the file:

```typescript

export interface AlpacaAccount {
  cash: number;
  equity: number;
  buying_power: number;
  portfolio_value: number;
  currency: string;
  error?: string;
}

export interface AlpacaOrder {
  order_id: string;
  symbol: string;
  qty: number;
  side: string;
  status: string;
  filled_avg_price: number | null;
  filled_at: string | null;
  submitted_at: string | null;
  order_type: string;
}

export interface RebalanceResult {
  status: string;
  closed: string[];
  opened: string[];
  errors: string[];
}
```

- [ ] **Step 2: Add API methods to `frontend/src/api/client.ts`**

Before the closing `};` of the `api` object, add:

```typescript

  getAlpacaAccount: () =>
    request<import("./types").AlpacaAccount>("/api/paper-trading/account"),

  getAlpacaOrders: () =>
    request<{ orders: import("./types").AlpacaOrder[] }>("/api/paper-trading/orders"),

  triggerRebalance: (tickers?: string[]) =>
    request<import("./types").RebalanceResult>("/api/paper-trading/rebalance", {
      method: "POST",
      body: JSON.stringify(tickers ? { tickers } : {}),
    }),
```

- [ ] **Step 3: Create `frontend/src/components/paper-trading/AccountPanel.tsx`**

```tsx
import { Card } from "@/components/ui/card";
import type { AlpacaAccount } from "../../api/types";

interface Props {
  account: AlpacaAccount | null;
}

function AccountStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] font-medium uppercase tracking-[0.8px] text-muted-foreground">
        {label}
      </div>
      <div className="text-sm font-semibold mt-0.5 text-foreground">{value}</div>
    </div>
  );
}

export function AccountPanel({ account }: Props) {
  if (!account || account.error) {
    return (
      <Card className="p-4">
        <div className="text-xs text-muted-foreground">
          {account?.error || "Alpaca account not connected"}
        </div>
      </Card>
    );
  }

  const fmt = (n: number) =>
    n.toLocaleString("en-US", { style: "currency", currency: "USD" });

  return (
    <Card className="p-4">
      <div className="text-xs font-medium text-muted-foreground mb-3">Alpaca Paper Account</div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <AccountStat label="Equity" value={fmt(account.equity)} />
        <AccountStat label="Cash" value={fmt(account.cash)} />
        <AccountStat label="Buying Power" value={fmt(account.buying_power)} />
        <AccountStat label="Portfolio Value" value={fmt(account.portfolio_value)} />
      </div>
    </Card>
  );
}
```

- [ ] **Step 4: Create `frontend/src/components/paper-trading/OrderHistoryTable.tsx`**

```tsx
import type { AlpacaOrder } from "../../api/types";

interface Props {
  orders: AlpacaOrder[];
}

const statusColor: Record<string, string> = {
  filled: "text-[--positive]",
  partially_filled: "text-amber-500",
  canceled: "text-muted-foreground",
  rejected: "text-[--negative]",
  accepted: "text-primary",
  new: "text-primary",
};

export function OrderHistoryTable({ orders }: Props) {
  if (orders.length === 0) {
    return (
      <div className="p-4 text-xs text-muted-foreground text-center">No orders yet</div>
    );
  }

  return (
    <div>
      <div className="px-4 py-2.5 border-b">
        <span className="text-xs font-medium text-muted-foreground">Alpaca Orders</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b text-muted-foreground">
              <th className="px-4 py-2 text-left font-medium">Symbol</th>
              <th className="px-4 py-2 text-left font-medium">Side</th>
              <th className="px-4 py-2 text-right font-medium">Qty</th>
              <th className="px-4 py-2 text-right font-medium">Fill Price</th>
              <th className="px-4 py-2 text-left font-medium">Status</th>
              <th className="px-4 py-2 text-left font-medium">Submitted</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.order_id} className="border-b last:border-0 hover:bg-muted/50">
                <td className="px-4 py-2 font-medium text-foreground">{o.symbol}</td>
                <td className="px-4 py-2">
                  <span className={o.side === "buy" ? "text-[--positive]" : "text-[--negative]"}>
                    {o.side.toUpperCase()}
                  </span>
                </td>
                <td className="px-4 py-2 text-right">{o.qty}</td>
                <td className="px-4 py-2 text-right">
                  {o.filled_avg_price ? `$${o.filled_avg_price.toFixed(2)}` : "\u2014"}
                </td>
                <td className={`px-4 py-2 ${statusColor[o.status] || "text-foreground"}`}>
                  {o.status}
                </td>
                <td className="px-4 py-2 text-muted-foreground">
                  {o.submitted_at ? new Date(o.submitted_at).toLocaleDateString() : "\u2014"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Replace `frontend/src/hooks/usePaperTrading.ts`**

Read the file first, then replace its content with:

```typescript
import { useState, useEffect, useCallback } from "react";
import { api } from "../api/client";
import type { PaperMetrics, AlpacaAccount, AlpacaOrder } from "../api/types";

export function usePaperTrading() {
  const [openPositions, setOpenPositions] = useState<any[]>([]);
  const [closedTrades, setClosedTrades] = useState<any[]>([]);
  const [equityCurve, setEquityCurve] = useState<{ date: string; equity: number }[]>([]);
  const [metrics, setMetrics] = useState<PaperMetrics | null>(null);
  const [account, setAccount] = useState<AlpacaAccount | null>(null);
  const [orders, setOrders] = useState<AlpacaOrder[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRebalancing, setIsRebalancing] = useState(false);

  const refresh = useCallback(() => {
    setIsLoading(true);
    Promise.all([
      api.getPaperPositions(),
      api.getPaperHistory(),
      api.getPaperMetrics(),
      api.getAlpacaAccount().catch(() => null),
      api.getAlpacaOrders().catch(() => ({ orders: [] })),
    ])
      .then(([pos, hist, met, acct, ord]) => {
        setOpenPositions(pos.positions);
        setClosedTrades(hist.trades);
        setEquityCurve(hist.equity_curve);
        setMetrics(met);
        if (acct) setAccount(acct);
        setOrders(ord.orders);
      })
      .catch(() => {})
      .finally(() => setIsLoading(false));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const addPosition = useCallback(async (position: any) => {
    await api.addPaperPosition(position);
    refresh();
  }, [refresh]);

  const closePosition = useCallback(async (ticker: string, exitPrice: number, exitReason: string) => {
    await api.closePaperPosition(ticker, { exit_price: exitPrice, exit_reason: exitReason });
    refresh();
  }, [refresh]);

  const triggerRebalance = useCallback(async (tickers?: string[]) => {
    setIsRebalancing(true);
    try {
      const result = await api.triggerRebalance(tickers);
      refresh();
      return result;
    } finally {
      setIsRebalancing(false);
    }
  }, [refresh]);

  return {
    openPositions, closedTrades, equityCurve, metrics,
    account, orders,
    isLoading, isRebalancing,
    addPosition, closePosition, triggerRebalance,
  };
}
```

- [ ] **Step 6: Update `frontend/src/pages/PaperTradingPage.tsx`**

Read the existing file, then replace with:

```tsx
import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PaperMetricsPanel } from "../components/paper-trading/PaperMetricsPanel";
import { OpenPositionsTable } from "../components/paper-trading/OpenPositionsTable";
import { ClosedTradesTable } from "../components/paper-trading/ClosedTradesTable";
import { AccountPanel } from "../components/paper-trading/AccountPanel";
import { OrderHistoryTable } from "../components/paper-trading/OrderHistoryTable";
import { usePaperTrading } from "../hooks/usePaperTrading";
import { Plus, X, RefreshCw } from "lucide-react";

export function PaperTradingPage() {
  const {
    openPositions, closedTrades, equityCurve, metrics,
    account, orders,
    isLoading, isRebalancing,
    addPosition, closePosition, triggerRebalance,
  } = usePaperTrading();
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ ticker: "", entry_price: "", verdict: "BUY" });

  const handleAdd = () => {
    const price = parseFloat(form.entry_price);
    if (!form.ticker.trim() || isNaN(price)) return;
    addPosition({
      ticker: form.ticker.toUpperCase(),
      entry_price: price,
      verdict: form.verdict,
    });
    setForm({ ticker: "", entry_price: "", verdict: "BUY" });
    setShowAdd(false);
  };

  if (isLoading) {
    return (
      <div className="p-6 max-w-6xl mx-auto space-y-4">
        <h1 className="text-lg font-semibold text-foreground">Paper Trading</h1>
        {[1, 2].map((i) => (
          <div key={i} className="rounded-xl border bg-card h-32 animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-foreground">Paper Trading</h1>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => triggerRebalance()}
            disabled={isRebalancing}
          >
            <RefreshCw size={13} className={`mr-1.5 ${isRebalancing ? "animate-spin" : ""}`} />
            {isRebalancing ? "Rebalancing..." : "Rebalance"}
          </Button>
          <Button size="sm" onClick={() => setShowAdd(!showAdd)}>
            {showAdd ? (
              <><X size={13} className="mr-1.5" />Cancel</>
            ) : (
              <><Plus size={13} className="mr-1.5" />Add Position</>
            )}
          </Button>
        </div>
      </div>

      {/* Alpaca Account */}
      <AccountPanel account={account} />

      {/* Add position form */}
      {showAdd && (
        <Card className="p-4">
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 items-end">
            <div>
              <label className="block text-[10px] uppercase tracking-wider font-medium text-muted-foreground mb-1">
                Ticker
              </label>
              <Input
                value={form.ticker}
                onChange={(e) => setForm({ ...form, ticker: e.target.value.toUpperCase() })}
                placeholder="AAPL"
                className="h-8 text-sm"
              />
            </div>
            <div>
              <label className="block text-[10px] uppercase tracking-wider font-medium text-muted-foreground mb-1">
                Entry Price
              </label>
              <Input
                value={form.entry_price}
                onChange={(e) => setForm({ ...form, entry_price: e.target.value })}
                placeholder="150.00"
                className="h-8 text-sm"
              />
            </div>
            <div>
              <label className="block text-[10px] uppercase tracking-wider font-medium text-muted-foreground mb-1">
                Verdict
              </label>
              <select
                value={form.verdict}
                onChange={(e) => setForm({ ...form, verdict: e.target.value })}
                className="flex h-8 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring text-foreground"
              >
                <option value="BUY">BUY</option>
                <option value="SELL">SELL</option>
                <option value="HOLD">HOLD</option>
              </select>
            </div>
            <Button onClick={handleAdd} size="sm" className="h-8">
              Add
            </Button>
          </div>
        </Card>
      )}

      {/* Metrics */}
      <PaperMetricsPanel metrics={metrics} />

      {/* Tables */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Card className="p-0 overflow-hidden">
          <OpenPositionsTable positions={openPositions} onClose={closePosition} />
        </Card>
        <Card className="p-0 overflow-hidden">
          <ClosedTradesTable trades={closedTrades} />
        </Card>
      </div>

      {/* Alpaca Orders */}
      {orders.length > 0 && (
        <Card className="p-0 overflow-hidden">
          <OrderHistoryTable orders={orders} />
        </Card>
      )}
    </div>
  );
}
```

- [ ] **Step 7: Verify frontend builds**

```bash
cd frontend && npm run build 2>&1 | tail -10
```

Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/components/paper-trading/AccountPanel.tsx frontend/src/components/paper-trading/OrderHistoryTable.tsx frontend/src/hooks/usePaperTrading.ts frontend/src/pages/PaperTradingPage.tsx
git commit -m "feat: frontend AccountPanel, OrderHistory, and rebalance button"
```

---

## Task 6: Final Integration Test

- [ ] **Step 1: Run all new paper trading tests**

```bash
python -m pytest tests/test_alpaca_paper_client.py tests/test_paper_scheduler.py tests/test_paper_trading_router.py -v
```

Expected: All tests pass.

- [ ] **Step 2: Run full test suite to verify no regressions**

```bash
python -m pytest tests/ -v --timeout=60 2>&1 | tail -20
```

Expected: No regressions.

- [ ] **Step 3: Final commit**

```bash
git add -A && git commit -m "feat: complete Alpaca paper trading integration"
```
