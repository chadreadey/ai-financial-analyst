from __future__ import annotations

import logging
import math
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)


class BacktestConfig:
    def __init__(self, tickers: list[str], start_date: str = "", end_date: str = ""):
        self.tickers = [t.upper().strip() for t in tickers]
        self.start_date = start_date or "2020-01-01"
        self.end_date = end_date or datetime.now().strftime("%Y-%m-%d")


class BacktestResult:
    def __init__(self):
        self.status: str = "pending"
        self.sharpe: Optional[float] = None
        self.sortino: Optional[float] = None
        self.calmar: Optional[float] = None
        self.max_drawdown_pct: Optional[float] = None
        self.win_rate_pct: Optional[float] = None
        self.hit_rate_pct: Optional[float] = None
        self.equity_curve: list[dict] = []
        self.trade_log: list[dict] = []
        self.walk_forward: list[dict] = []
        self.error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "calmar": self.calmar,
            "max_drawdown_pct": self.max_drawdown_pct,
            "win_rate_pct": self.win_rate_pct,
            "hit_rate_pct": self.hit_rate_pct,
            "equity_curve": self.equity_curve,
            "trade_log": self.trade_log,
            "walk_forward": self.walk_forward,
            "error": self.error,
        }


def _get_cached_prices(ticker: str, conn: sqlite3.Connection) -> dict[str, float]:
    try:
        rows = conn.execute(
            "SELECT date_str, close_price FROM price_history_cache WHERE ticker = ? ORDER BY date_str",
            (ticker,),
        ).fetchall()
        return {r[0]: r[1] for r in rows}
    except sqlite3.OperationalError:
        return {}


def _cache_prices(ticker: str, prices: dict[str, float], conn: sqlite3.Connection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_history_cache (
            ticker TEXT, date_str TEXT, close_price REAL,
            PRIMARY KEY (ticker, date_str)
        )
    """)
    for date_str, price in prices.items():
        conn.execute(
            "INSERT OR REPLACE INTO price_history_cache (ticker, date_str, close_price) VALUES (?, ?, ?)",
            (ticker, date_str, price),
        )
    conn.commit()


def _fetch_prices(ticker: str, conn: sqlite3.Connection) -> dict[str, float]:
    cached = _get_cached_prices(ticker, conn)
    if len(cached) > 100:
        return cached

    try:
        from price_provider import get_price_provider

        client = get_price_provider()
        start = (datetime.now() - timedelta(days=1825)).strftime("%Y-%m-%d")
        data = client.get_eod_history(ticker, start)
        if data:
            prices = {}
            for d in data:
                date_str = str(d.get("date", ""))[:10]
                close = float(d.get("adjClose") or d.get("close", 0))
                if close > 0:
                    prices[date_str] = close
            _cache_prices(ticker, prices, conn)
            return prices
    except Exception as exc:
        logger.warning("Price fetch failed for %s: %s", ticker, exc)

    return cached


def _get_recommendations(tickers: list[str], conn_warehouse: sqlite3.Connection) -> list[dict]:
    recs = []
    try:
        for ticker in tickers:
            rows = conn_warehouse.execute(
                "SELECT ticker, run_at, verdict, conviction, composite_score "
                "FROM analysis_history WHERE ticker = ? ORDER BY run_at",
                (ticker,),
            ).fetchall()
            for r in rows:
                recs.append(
                    {
                        "ticker": r[0],
                        "run_at": r[1],
                        "verdict": r[2],
                        "conviction": r[3] if len(r) > 3 else "",
                        "composite_score": r[4] if len(r) > 4 else None,
                    }
                )
    except sqlite3.OperationalError:
        pass
    return recs


class BacktestEngine:
    TRANSACTION_COST = 0.001
    STOP_LOSS_PCT = 0.15
    TIME_DECAY_DAYS = 90

    def run(self, config: BacktestConfig) -> BacktestResult:
        result = BacktestResult()
        result.status = "running"

        db_path = settings.warehouse_db_path
        conn_warehouse = sqlite3.connect(db_path)
        conn_cache = sqlite3.connect(db_path)

        try:
            recs = _get_recommendations(config.tickers, conn_warehouse)
            if len(recs) < 10:
                result.status = "insufficient_data"
                return result

            all_prices: dict[str, dict[str, float]] = {}
            for ticker in config.tickers:
                all_prices[ticker] = _fetch_prices(ticker, conn_cache)

            trades = []
            for rec in recs:
                ticker = rec["ticker"]
                prices = all_prices.get(ticker, {})
                if not prices:
                    continue

                verdict = (rec.get("verdict") or "").upper()
                if "BUY" not in verdict and "SELL" not in verdict:
                    continue

                is_buy = "BUY" in verdict
                rec_date = datetime.fromtimestamp(rec["run_at"]).strftime("%Y-%m-%d")
                sorted_dates = sorted(prices.keys())
                entry_candidates = [d for d in sorted_dates if d > rec_date]
                if not entry_candidates:
                    continue

                entry_date = entry_candidates[0]
                entry_price = prices[entry_date]

                exit_date = None
                exit_price = None
                exit_reason = "time_decay"
                deadline = (
                    datetime.strptime(entry_date, "%Y-%m-%d") + timedelta(days=self.TIME_DECAY_DAYS)
                ).strftime("%Y-%m-%d")

                for d in sorted_dates:
                    if d <= entry_date:
                        continue
                    if d > deadline:
                        exit_date = d
                        exit_price = prices[d]
                        exit_reason = "time_decay"
                        break

                    p = prices[d]
                    if is_buy:
                        pnl_pct = (p - entry_price) / entry_price
                        if pnl_pct <= -self.STOP_LOSS_PCT:
                            exit_date = d
                            exit_price = p
                            exit_reason = "stop_loss"
                            break
                    else:
                        pnl_pct = (entry_price - p) / entry_price
                        if pnl_pct <= -self.STOP_LOSS_PCT:
                            exit_date = d
                            exit_price = p
                            exit_reason = "stop_loss"
                            break

                if not exit_date:
                    last_date = sorted_dates[-1]
                    if last_date > entry_date:
                        exit_date = last_date
                        exit_price = prices[last_date]
                        exit_reason = "time_decay"
                    else:
                        continue

                if is_buy:
                    pnl_pct = (exit_price - entry_price) / entry_price - self.TRANSACTION_COST * 2
                else:
                    pnl_pct = (entry_price - exit_price) / entry_price - self.TRANSACTION_COST * 2

                trades.append(
                    {
                        "ticker": ticker,
                        "entry_date": entry_date,
                        "entry_price": round(entry_price, 2),
                        "exit_date": exit_date,
                        "exit_price": round(exit_price, 2),
                        "pnl_pct": round(pnl_pct * 100, 2),
                        "exit_reason": exit_reason,
                        "verdict": verdict,
                    }
                )

            if not trades:
                result.status = "insufficient_data"
                return result

            result.trade_log = trades
            wins = sum(1 for t in trades if t["pnl_pct"] > 0)
            result.win_rate_pct = round(wins / len(trades) * 100, 1)
            result.hit_rate_pct = result.win_rate_pct

            trades_sorted = sorted(trades, key=lambda t: t["entry_date"])
            equity = 10000.0
            curve = [{"date": trades_sorted[0]["entry_date"], "equity": equity}]
            peak = equity
            max_dd = 0.0
            returns = []

            for t in trades_sorted:
                ret = t["pnl_pct"] / 100
                returns.append(ret)
                equity *= 1 + ret
                curve.append({"date": t["exit_date"], "equity": round(equity, 2)})
                if equity > peak:
                    peak = equity
                dd = (peak - equity) / peak
                if dd > max_dd:
                    max_dd = dd

            result.equity_curve = curve
            result.max_drawdown_pct = round(max_dd * 100, 2)

            if len(returns) > 1:
                import pandas as pd
                from quant.metrics import compute_sharpe, compute_sortino, compute_calmar

                returns_series = pd.Series(returns)
                result.sharpe = compute_sharpe(returns_series, min_observations=2)
                result.sortino = compute_sortino(returns_series, min_observations=2)
                annual_return = (equity / 10000) ** (
                    252 / (len(returns) * self.TIME_DECAY_DAYS)
                ) - 1
                result.calmar = compute_calmar(annual_return * 100, result.max_drawdown_pct)

            result.status = "complete"
        except Exception as exc:
            result.status = "error"
            result.error = str(exc)
            logger.error("Backtest failed: %s", exc)
        finally:
            conn_warehouse.close()
            conn_cache.close()

        return result
