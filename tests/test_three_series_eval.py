"""Tests for the three-series eval (Phase 3)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.three_series_eval import (
    Portfolio,
    attribution,
    build_series,
    build_spy_series,
    format_markdown_report,
    portfolios_from_ai_picks,
    portfolios_from_candidate_lists,
)


def _make_trend_price(dates: pd.DatetimeIndex, start: float, daily_ret: float) -> pd.DataFrame:
    prices = start * (1 + daily_ret) ** np.arange(len(dates))
    return pd.DataFrame(
        {"open": prices, "high": prices, "low": prices, "close": prices, "volume": 1e6},
        index=dates,
    )


class TestPortfolioNormalization:
    def test_normalizes_weights_and_cash(self):
        p = Portfolio(pd.Timestamp("2024-01-31"), {"A": 2.0, "B": 1.0}, cash_weight=1.0)
        n = p.normalized()
        assert abs(sum(n.weights.values()) + n.cash_weight - 1.0) < 1e-6

    def test_all_zero_returns_all_cash(self):
        p = Portfolio(pd.Timestamp("2024-01-31"), {"A": 0.0}, cash_weight=0.0)
        n = p.normalized()
        assert n.cash_weight == 1.0


class TestBuildSeries:
    def test_trending_portfolio_earns_positive_return(self):
        dates = pd.date_range("2024-01-01", periods=250, freq="B")
        prices = {
            "AAA": _make_trend_price(dates, 100.0, 0.001),
            "BBB": _make_trend_price(dates, 50.0, 0.001),
        }
        portfolios = {
            pd.Timestamp("2024-01-01"): Portfolio(
                pd.Timestamp("2024-01-01"), {"AAA": 0.5, "BBB": 0.5}
            ),
        }
        result = build_series("test", portfolios, prices)
        assert result.metrics["total_return_pct"] > 5.0
        assert result.metrics["sharpe"] is not None and result.metrics["sharpe"] > 0

    def test_flat_prices_zero_return(self):
        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        prices = {"AAA": _make_trend_price(dates, 100.0, 0.0)}
        portfolios = {
            pd.Timestamp("2024-01-01"): Portfolio(pd.Timestamp("2024-01-01"), {"AAA": 1.0}),
        }
        result = build_series("flat", portfolios, prices)
        assert abs(result.metrics["total_return_pct"]) < 0.01

    def test_missing_ticker_dropped(self):
        dates = pd.date_range("2024-01-01", periods=50, freq="B")
        prices = {"AAA": _make_trend_price(dates, 100.0, 0.001)}
        portfolios = {
            pd.Timestamp("2024-01-01"): Portfolio(
                pd.Timestamp("2024-01-01"), {"AAA": 0.5, "MISSING": 0.5}
            ),
        }
        result = build_series("mixed", portfolios, prices)
        assert result.metrics["total_return_pct"] > 0

    def test_empty_portfolios_empty_result(self):
        result = build_series("empty", {}, {})
        assert result.metrics == {}
        assert len(result.daily_returns) == 0


class TestPortfoliosFromCandidateLists:
    def test_top_n_and_sector_cap(self):
        payload = {
            "candidates": [
                {"ticker": f"T{i}", "composite": 1.0 - 0.01 * i, "sector": "Tech"}
                for i in range(20)
            ]
        }
        ports = portfolios_from_candidate_lists(
            {"2024-01-31": payload}, n_positions=10, max_per_sector=3
        )
        assert len(ports) == 1
        p = ports[pd.Timestamp("2024-01-31")]
        assert len(p.weights) == 3
        assert sum(p.weights.values()) == pytest.approx(1.0)


class TestPortfoliosFromAIPicks:
    def test_maps_picks_to_weights(self):
        payload = {
            "portfolio": {
                "picks": [
                    {"ticker": "AAPL", "weight": 0.4, "rationale": ""},
                    {"ticker": "MSFT", "weight": 0.6, "rationale": ""},
                ],
                "cash_weight": 0.0,
            }
        }
        ports = portfolios_from_ai_picks({"2024-01-31": payload})
        p = ports[pd.Timestamp("2024-01-31")]
        assert p.weights == {"AAPL": 0.4, "MSFT": 0.6}
        assert p.cash_weight == 0.0


class TestBuildSpySeries:
    def test_extracts_period_returns(self):
        dates = pd.date_range("2024-01-01", periods=300, freq="B")
        spy = _make_trend_price(dates, 400.0, 0.0005)
        result = build_spy_series(spy, pd.Timestamp("2024-01-15"), pd.Timestamp("2024-06-15"))
        assert result.name == "SPY"
        assert result.metrics["total_return_pct"] > 0
        assert result.metrics["n_days"] > 100


class TestAttribution:
    def test_positive_delta_for_better_ai(self):
        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        ai_p = build_series(
            "ai",
            {pd.Timestamp("2024-01-01"): Portfolio(pd.Timestamp("2024-01-01"), {"AI": 1.0})},
            {"AI": _make_trend_price(dates, 100.0, 0.002)},
        )
        q_p = build_series(
            "q",
            {pd.Timestamp("2024-01-01"): Portfolio(pd.Timestamp("2024-01-01"), {"Q": 1.0})},
            {"Q": _make_trend_price(dates, 100.0, 0.0005)},
        )
        s_p = build_series(
            "s",
            {pd.Timestamp("2024-01-01"): Portfolio(pd.Timestamp("2024-01-01"), {"S": 1.0})},
            {"S": _make_trend_price(dates, 100.0, 0.0003)},
        )
        attr = attribution(ai_p, q_p, s_p)
        assert attr["ai_vs_quant"]["annual_return_delta_pp"] > 0
        assert attr["ai_vs_quant"]["sharpe_delta"] is not None

    def test_diff_handles_none(self):
        empty = build_series("e", {}, {})
        real = build_series(
            "r",
            {pd.Timestamp("2024-01-01"): Portfolio(pd.Timestamp("2024-01-01"), {"X": 1.0})},
            {
                "X": _make_trend_price(
                    pd.date_range("2024-01-01", periods=100, freq="B"), 100.0, 0.001
                )
            },
        )
        attr = attribution(real, empty, empty)
        assert attr["ai_vs_quant"]["sharpe_delta"] is None


class TestSharedEndDate:
    def test_end_date_caps_final_holding_period(self):
        dates = pd.date_range("2024-01-01", periods=500, freq="B")
        prices = {"AAA": _make_trend_price(dates, 100.0, 0.001)}
        portfolios = {
            pd.Timestamp("2024-01-01"): Portfolio(pd.Timestamp("2024-01-01"), {"AAA": 1.0}),
        }
        capped = build_series("capped", portfolios, prices, end_date=pd.Timestamp("2024-03-01"))
        uncapped = build_series("uncapped", portfolios, prices)
        assert len(capped.daily_returns) < len(uncapped.daily_returns)
        assert capped.daily_returns.index[-1] <= pd.Timestamp("2024-03-01")

    def test_no_end_date_runs_to_eod(self):
        dates = pd.date_range("2024-01-01", periods=50, freq="B")
        prices = {"AAA": _make_trend_price(dates, 100.0, 0.001)}
        portfolios = {
            pd.Timestamp("2024-01-01"): Portfolio(pd.Timestamp("2024-01-01"), {"AAA": 1.0}),
        }
        result = build_series("uncapped", portfolios, prices)
        assert result.daily_returns.index[-1] == dates[-1]


class TestMarkdownReport:
    def test_report_contains_verdict(self):
        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        p = build_series(
            "p",
            {pd.Timestamp("2024-01-01"): Portfolio(pd.Timestamp("2024-01-01"), {"X": 1.0})},
            {"X": _make_trend_price(dates, 100.0, 0.001)},
        )
        attr = attribution(p, p, p)
        md = format_markdown_report(p, p, p, attr)
        assert "Three-Series Eval" in md
        assert "Verdict" in md
