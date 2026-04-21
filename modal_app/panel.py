"""CPCV panel: preloaded price / macro / hedge data shared across combos.

Session 1 strategy (per architect recommendation §5):
  - Orchestrator pre-fetches the panel **locally** using the existing
    price-provider + on-disk `.price_cache/` (fast, no rate-limit risk).
  - Serializes the panel as a pickle blob.
  - Uploads one pickle per run to the `cpcv-panels` Modal Volume.
  - Each `CPCVWorker` container reads the panel ONCE at `@modal.enter` time
    and reuses it across every combo routed to that container.

This avoids the two failure modes a naive approach would hit:
  a) Passing the panel as a `.map()` argument → 30 MB × N over the wire.
  b) Having each container re-fetch prices from Tiingo/FMP → rate-limit death
     when `max_containers=200`.
"""
from __future__ import annotations

import logging
import pickle
from dataclasses import dataclass
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

PANELS_MOUNT_PATH = "/panels"


@dataclass
class CPCVPanel:
    """Serialized, pickleable bundle of data CPCV combos need."""
    run_id: str
    universe_data: dict[str, pd.DataFrame]
    benchmark_df: Optional[pd.DataFrame]
    vix_df: Optional[pd.DataFrame]
    hy_oas_series: Optional[pd.Series]
    t10y3m_series: Optional[pd.Series]
    copper_series: Optional[pd.Series]
    hedge_prices: dict[str, pd.DataFrame]
    groups: list
    all_rebalance_dates: pd.DatetimeIndex
    trading_dates: pd.DatetimeIndex
    n_groups: int
    n_test_groups: int
    purge_months: int
    embargo_months: int


def build_panel_locally(
    run_id: str,
    config,
    n_groups: int,
    n_test_groups: int,
    purge_months: int = 1,
    embargo_months: int = 1,
    include_hedge: bool = True,
    include_macro: bool = True,
) -> CPCVPanel:
    """Load all data CPCV combos need. Runs on the orchestrator box."""
    from datetime import datetime, timedelta
    from price_provider import get_price_provider
    from quant.backtest import (
        load_universe_data,
        load_vix_data,
        _load_hedge_etf_data,
        _load_sector_etf_data,
        HEDGE_ETFS,
        generate_rebalance_dates,
    )
    from quant.cpcv import make_cpcv_groups
    from quant.universe import BENCHMARK

    provider = get_price_provider()

    fetch_start = (
        datetime.strptime(config.start_date, "%Y-%m-%d")
        - timedelta(days=config.lookback_days + 30)
    ).strftime("%Y-%m-%d")

    all_tickers = list(set(list(config.tickers) + [BENCHMARK]))
    logger.info("Loading universe data for %d tickers from %s", len(all_tickers), fetch_start)
    universe_data = load_universe_data(all_tickers, fetch_start, provider=provider)

    if len(universe_data) < 3:
        raise RuntimeError(
            f"Panel build failed: only loaded {len(universe_data)} tickers "
            f"(needed {len(all_tickers)})"
        )

    benchmark_df = universe_data.pop(BENCHMARK, None)

    vix_df = None
    hy_oas_series = t10y3m_series = copper_series = None
    if config.enable_regime_filter and include_macro:
        vix_df = load_vix_data(fetch_start)
        _load_sector_etf_data(fetch_start, provider)
        try:
            from quant.macro_signals import load_fred_macro_data
            hy_oas_series, t10y3m_series, copper_series = load_fred_macro_data(fetch_start)
        except Exception as exc:
            logger.warning("FRED macro load failed (continuing without): %s", exc)

    hedge_prices: dict[str, pd.DataFrame] = {}
    if config.enable_dynamic_risk_off and include_hedge:
        hedge_prices = _load_hedge_etf_data(fetch_start, config.end_date)
        for ticker, df in hedge_prices.items():
            universe_data[ticker] = df

    all_dates = sorted(set().union(*(df.index for df in universe_data.values())))
    trading_dates = pd.DatetimeIndex(all_dates)

    groups = make_cpcv_groups(config.start_date, config.end_date, n_groups, trading_dates)
    all_rebalance_dates = generate_rebalance_dates(
        pd.Timestamp(config.start_date),
        pd.Timestamp(config.end_date),
        config.rebalance_freq,
        trading_dates,
    )

    return CPCVPanel(
        run_id=run_id,
        universe_data=universe_data,
        benchmark_df=benchmark_df,
        vix_df=vix_df,
        hy_oas_series=hy_oas_series,
        t10y3m_series=t10y3m_series,
        copper_series=copper_series,
        hedge_prices=hedge_prices,
        groups=groups,
        all_rebalance_dates=all_rebalance_dates,
        trading_dates=trading_dates,
        n_groups=n_groups,
        n_test_groups=n_test_groups,
        purge_months=purge_months,
        embargo_months=embargo_months,
    )


def pickle_panel(panel: CPCVPanel) -> bytes:
    return pickle.dumps(panel, protocol=pickle.HIGHEST_PROTOCOL)


def unpickle_panel(blob: bytes) -> CPCVPanel:
    return pickle.loads(blob)


def panel_to_cpcv_state(panel: CPCVPanel):
    """Adapt a `CPCVPanel` into a `quant.backtest.CPCVState` for the combo runner."""
    from quant.backtest import CPCVState
    return CPCVState(
        universe_data=panel.universe_data,
        benchmark_df=panel.benchmark_df,
        vix_df=panel.vix_df,
        hy_oas_series=panel.hy_oas_series,
        t10y3m_series=panel.t10y3m_series,
        copper_series=panel.copper_series,
        hedge_prices=panel.hedge_prices,
        trading_dates=panel.trading_dates,
        groups=panel.groups,
        all_rebalance_dates=panel.all_rebalance_dates,
        purge_months=panel.purge_months,
        embargo_months=panel.embargo_months,
    )


def upload_panel_to_volume(panel: CPCVPanel, panels_volume) -> str:
    """Write `panel` to the Modal Volume. Returns the object key."""
    import io
    blob = pickle_panel(panel)
    key = f"{panel.run_id}.pkl"
    size_mb = len(blob) / (1024 * 1024)
    logger.info("Uploading panel %s to Modal Volume (%.1f MB)", key, size_mb)
    with panels_volume.batch_upload(force=True) as batch:
        batch.put_file(io.BytesIO(blob), f"/{key}")
    return key


__all__ = [
    "CPCVPanel",
    "PANELS_MOUNT_PATH",
    "build_panel_locally",
    "panel_to_cpcv_state",
    "pickle_panel",
    "unpickle_panel",
    "upload_panel_to_volume",
]
