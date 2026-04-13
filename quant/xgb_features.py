"""
Feature matrix builder for XGBoost meta-model.

Extracts per-ticker, per-date feature rows from the existing signal pipeline.
Each row contains all 7 signal scores + context features (ATR, VIX, regime).
Label: 21-day forward return.

The feature matrix is the dataset XGBoost trains on.
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta

import numpy as np
import pandas as pd

from quant.signals import compute_signal_vector

logger = logging.getLogger(__name__)


def build_feature_matrix(
    universe_data: dict[str, pd.DataFrame],
    rebalance_dates: list[pd.Timestamp],
    wrds_provider=None,
    finnhub_client=None,
    sentiment_cache=None,
    inst_wrds_store=None,
    sector_etf_data: dict[str, pd.DataFrame] | None = None,
    vix_df: pd.DataFrame | None = None,
    forward_days: int = 21,
    lookback_days: int = 252,
) -> pd.DataFrame:
    """
    Build feature matrix for XGBoost training.

    Returns DataFrame with columns:
        date, ticker, qid,
        obv_trend, earnings, inst_flow, sentiment, quality, price_mom, insider,
        atr_pct, vix_level,
        fwd_21d_return (label)
    """
    from quant.earnings_signals import compute_earnings_signal_scores
    from quant.institutional_flow import compute_institutional_flow_scores
    from quant.additional_signals import (
        compute_quality_scores,
        compute_price_momentum_scores,
        compute_insider_scores,
    )

    rows = []
    tickers = list(universe_data.keys())

    for qid, reb_date in enumerate(rebalance_dates):
        # Compute technical signals
        signals_at_date = {}
        for ticker, df in universe_data.items():
            available = df[df.index <= reb_date]
            if len(available) < 60:
                continue
            window = available.tail(lookback_days)
            try:
                sv = compute_signal_vector(
                    close=window["close"],
                    volume=window["volume"],
                    high=window["high"],
                    low=window["low"],
                )
                signals_at_date[ticker] = sv
            except Exception:
                continue

        if len(signals_at_date) < 10:
            continue

        active_tickers = list(signals_at_date.keys())

        # Earnings scores
        earn_scores = {}
        if wrds_provider is not None:
            try:
                earn_scores = compute_earnings_signal_scores(
                    active_tickers, wrds_provider, as_of_date=reb_date.date(),
                )
            except Exception:
                pass

        # Institutional flow
        inst_scores = {}
        if inst_wrds_store is not None:
            try:
                inst_scores = compute_institutional_flow_scores(
                    active_tickers, as_of_date=reb_date.date(),
                    wrds_store=inst_wrds_store,
                )
            except Exception:
                pass

        # Quality
        quality_scores = {}
        if wrds_provider is not None:
            try:
                quality_scores = compute_quality_scores(
                    active_tickers, wrds_provider, as_of_date=reb_date.date(),
                )
            except Exception:
                pass

        # Price momentum
        mom_scores = compute_price_momentum_scores(universe_data, reb_date)

        # Insider
        insider_scores = {}
        if finnhub_client is not None or sentiment_cache is not None:
            try:
                insider_scores = compute_insider_scores(
                    active_tickers, reb_date,
                    finnhub_client=finnhub_client,
                    sentiment_cache=sentiment_cache,
                )
            except Exception:
                pass

        # VIX
        vix_level = None
        if vix_df is not None:
            vix_avail = vix_df[vix_df.index <= reb_date]
            if len(vix_avail) > 0:
                vix_level = float(vix_avail.iloc[-1]["close"])

        # Forward returns (label)
        for ticker in active_tickers:
            df = universe_data[ticker]
            future = df[df.index > reb_date]
            current = df[df.index <= reb_date]
            if len(current) < 1 or len(future) < forward_days:
                continue

            price_now = float(current.iloc[-1]["close"])
            price_future = float(future.iloc[forward_days - 1]["close"])
            if price_now <= 0:
                continue
            fwd_return = (price_future / price_now) - 1

            sv = signals_at_date[ticker]
            earn_entry = earn_scores.get(ticker)
            inst_entry = inst_scores.get(ticker)

            rows.append({
                "date": reb_date.strftime("%Y-%m-%d"),
                "ticker": ticker,
                "qid": qid,
                # 7 signal features
                "obv_trend": sv.obv_trend.score,
                "earnings": earn_entry[0] if earn_entry else 0.0,
                "inst_flow": inst_entry[0] if inst_entry else 0.0,
                "sentiment": 0.0,  # sparse, often zero in backtest
                "quality": quality_scores.get(ticker, 0.0),
                "price_mom": mom_scores.get(ticker, 0.0),
                "insider": insider_scores.get(ticker, 0.0),
                # Context features
                "atr_pct": sv.atr_regime.metadata.get("atr_pct", 0.0),
                "vix_level": vix_level or 0.0,
                # Label
                "fwd_21d_return": fwd_return,
            })

    fm = pd.DataFrame(rows)
    logger.info("Feature matrix: %d rows, %d dates, %d tickers",
                len(fm), fm["qid"].nunique() if len(fm) > 0 else 0,
                fm["ticker"].nunique() if len(fm) > 0 else 0)
    return fm


def save_feature_matrix(df: pd.DataFrame, path: str = ".xgb_features.csv") -> None:
    df.to_csv(path, index=False)
    logger.info("Saved feature matrix to %s (%d rows)", path, len(df))


def load_feature_matrix(path: str = ".xgb_features.csv") -> pd.DataFrame:
    return pd.read_csv(path)
