import pytest
from quant.backtest import BacktestConfig, compute_etf_ladder_tier, ETF_LADDER_TIERS


def _cfg(**kwargs):
    return BacktestConfig(vix_smoothing=True, enable_dynamic_risk_off=True, **kwargs)


def test_tier_none_below_mild():
    """ratio < 1.2 → no tier, full equity."""
    tier = compute_etf_ladder_tier(vix_ratio=1.1, copper_bearish=False, config=_cfg())
    assert tier is None


def test_tier_mild():
    tier = compute_etf_ladder_tier(vix_ratio=1.3, copper_bearish=False, config=_cfg())
    assert tier == "mild"


def test_tier_moderate():
    tier = compute_etf_ladder_tier(vix_ratio=1.7, copper_bearish=False, config=_cfg())
    assert tier == "moderate"


def test_tier_severe():
    tier = compute_etf_ladder_tier(vix_ratio=2.5, copper_bearish=False, config=_cfg())
    assert tier == "severe"


def test_tier_crisis_requires_copper():
    """ratio > 3.0 alone → severe, not crisis (copper gates crisis tier)."""
    tier = compute_etf_ladder_tier(vix_ratio=3.5, copper_bearish=False, config=_cfg())
    assert tier == "severe"


def test_tier_crisis_with_copper():
    tier = compute_etf_ladder_tier(vix_ratio=3.5, copper_bearish=True, config=_cfg())
    assert tier == "crisis"


def test_all_tier_weights_sum_to_one():
    """ETF allocations + equity_frac must sum to 1.0 for each tier."""
    for tier_name, alloc in ETF_LADDER_TIERS.items():
        etf_weight = sum(v for k, v in alloc.items() if k != "equity_frac")
        total = etf_weight + alloc["equity_frac"]
        assert total == pytest.approx(1.0), f"Tier {tier_name} weights sum to {total}"


def test_dynamic_risk_off_disabled_returns_none():
    """enable_dynamic_risk_off=False → always returns None (use raw cash logic)."""
    cfg = BacktestConfig(vix_smoothing=True, enable_dynamic_risk_off=False)
    tier = compute_etf_ladder_tier(vix_ratio=2.0, copper_bearish=False, config=cfg)
    assert tier is None
