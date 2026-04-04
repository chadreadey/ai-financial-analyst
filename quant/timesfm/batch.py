from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from config import settings

logger = logging.getLogger(__name__)


def run_batch(tickers: list[str]) -> dict[str, str]:
    from quant.timesfm.model import TimesFMModel
    from quant.timesfm.signals import extract_signals
    from quant.timesfm import cache

    logger.info("Starting TimesFM batch for %d tickers", len(tickers))

    model = TimesFMModel.get()

    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from tiingo_client import TiingoClient
    from fmp_client import FMPClient

    tiingo = TiingoClient(settings.tiingo_api_key)
    fmp = FMPClient(settings.fmp_api_key)

    results: dict[str, str] = {}

    for ticker in tickers:
        ticker = ticker.upper().strip()
        try:
            prices_raw = tiingo.get_eod_history(ticker, days=settings.timesfm_price_lookback_days)
            if not prices_raw:
                results[ticker] = "error: no price data from Tiingo"
                logger.warning("%s: no price data from Tiingo", ticker)
                continue

            prices = [float(p.get("adjClose") or p.get("close", 0)) for p in prices_raw]
            if len(prices) < 64:
                results[ticker] = f"error: insufficient price data ({len(prices)} points)"
                logger.warning("%s: insufficient price data (%d points)", ticker, len(prices))
                continue

            horizon = settings.timesfm_horizon_days
            point, quantiles = model.forecast(prices, horizon=horizon, freq=0)
            price_signals = extract_signals(
                current_value=prices[-1],
                point_forecast=point,
                quantiles=quantiles,
            )
            cache.put_signals(ticker, "price_forecast", price_signals, ttl_seconds=settings.timesfm_ttl_seconds)
            logger.info("%s: price_forecast cached (%d points -> %d-step forecast)", ticker, len(prices), horizon)

            try:
                income = fmp.get_income_statement_quarterly(ticker, limit=20)
                if income and len(income) >= 8:
                    eps_pairs = []
                    for stmt in income:
                        date_str = stmt.get("date", "")
                        eps_val = stmt.get("eps")
                        if date_str and eps_val is not None:
                            eps_pairs.append((date_str, float(eps_val)))
                    eps_pairs.sort(key=lambda x: x[0])

                    if len(eps_pairs) >= 8:
                        eps_values = [e[1] for e in eps_pairs]
                        eps_point, eps_quantiles = model.forecast(eps_values, horizon=4, freq=2)
                        eps_signals = extract_signals(
                            current_value=eps_values[-1],
                            point_forecast=eps_point,
                            quantiles=eps_quantiles,
                        )
                        cache.put_signals(ticker, "eps_forecast", eps_signals, ttl_seconds=settings.timesfm_ttl_seconds)
                        logger.info("%s: eps_forecast cached (%d quarters)", ticker, len(eps_pairs))
                    else:
                        logger.warning("%s: insufficient EPS data (%d pairs), skipping eps_forecast", ticker, len(eps_pairs))
                else:
                    qcount = len(income) if income else 0
                    logger.warning("%s: insufficient EPS data (%d quarters), skipping eps_forecast", ticker, qcount)
            except Exception as eps_exc:
                logger.warning("%s: EPS forecast failed — %s", ticker, eps_exc)

            results[ticker] = "ok"

        except Exception as exc:
            results[ticker] = f"error: {exc}"
            logger.error("%s: batch failed — %s", ticker, exc)

    return results
