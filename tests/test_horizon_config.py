import pandas as pd
import pytest
from quant.backtest import HorizonConfig, _generate_rebalance_dates


def test_monthly_produces_month_start_dates():
    h = HorizonConfig(mode="monthly")
    dates = _generate_rebalance_dates(pd.Timestamp("2020-01-01"), pd.Timestamp("2020-06-30"), h)
    assert len(dates) == 6
    assert all(d.day == 1 for d in dates)


def test_weekly_produces_more_dates_than_monthly():
    h = HorizonConfig(mode="weekly", weekly_rebalance_days=5)
    dates = _generate_rebalance_dates(pd.Timestamp("2020-01-01"), pd.Timestamp("2020-06-30"), h)
    assert len(dates) > 20  # ~26 for 6 months


def test_hybrid_is_superset_of_monthly():
    monthly = _generate_rebalance_dates(
        pd.Timestamp("2020-01-01"), pd.Timestamp("2020-06-30"), HorizonConfig(mode="monthly")
    )
    hybrid = _generate_rebalance_dates(
        pd.Timestamp("2020-01-01"), pd.Timestamp("2020-06-30"), HorizonConfig(mode="hybrid")
    )
    for d in monthly:
        assert d in hybrid


def test_unknown_mode_raises():
    with pytest.raises(ValueError, match="Unknown horizon mode"):
        _generate_rebalance_dates(
            pd.Timestamp("2020-01-01"), pd.Timestamp("2020-06-30"), HorizonConfig(mode="daily")
        )


def test_horizon_config_defaults():
    h = HorizonConfig()
    assert h.mode == "monthly"
    assert h.weekly_rebalance_days == 5
    assert h.event_entry_days_before == 5
    assert h.event_exit_days_after == 3
