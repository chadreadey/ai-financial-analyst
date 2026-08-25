"""Tests for the AI-pick XGBoost meta-model (Phase 4)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.ai_pick_meta_model import (
    DEFAULT_FEATURE_COLUMNS,
    SECTOR_TO_ETF,
    TrainedMetaModel,
    build_training_frame,
    load_model,
    save_model,
    train_meta_model,
)


def _mk_price(dates: pd.DatetimeIndex, start: float, daily_ret: float) -> pd.DataFrame:
    prices = start * (1 + daily_ret) ** np.arange(len(dates))
    return pd.DataFrame({"close": prices}, index=dates)


def _mk_prices_dict(dates, spec: dict[str, float]) -> dict[str, pd.DataFrame]:
    return {t: _mk_price(dates, 100.0, r) for t, r in spec.items()}


class TestBuildTrainingFrame:
    def test_row_per_pick_with_target(self):
        dates = pd.date_range("2024-01-01", periods=250, freq="B")
        prices = _mk_prices_dict(
            dates,
            {"AAA": 0.002, "BBB": 0.0005, "XLK": 0.001},
        )
        ai_picks = {}
        candidates = {}
        for date_str in ["2024-01-31", "2024-02-29", "2024-03-29"]:
            ai_picks[date_str] = {
                "portfolio": {
                    "picks": [
                        {"ticker": "AAA", "weight": 0.5, "rationale": ""},
                        {"ticker": "BBB", "weight": 0.5, "rationale": ""},
                    ],
                    "cash_weight": 0.0,
                    "source": "heuristic",
                }
            }
            candidates[date_str] = {
                "candidates": [
                    {
                        "ticker": "AAA",
                        "composite": 0.5,
                        "sector": "Technology",
                        "contributions": {
                            "qmj_score": 0.2,
                            "sue_earnings_score": 0.15,
                            "erm_earnings_score": 0.15,
                        },
                    },
                    {
                        "ticker": "BBB",
                        "composite": 0.3,
                        "sector": "Technology",
                        "contributions": {
                            "qmj_score": 0.1,
                            "sue_earnings_score": 0.1,
                            "erm_earnings_score": 0.1,
                        },
                    },
                ]
            }

        frame = build_training_frame(ai_picks, candidates, prices, horizon_days=21)
        assert len(frame) > 0
        assert set(DEFAULT_FEATURE_COLUMNS).issubset(set(frame.columns))
        assert "beat_sector_21d" in frame.columns
        assert set(frame["beat_sector_21d"].unique()).issubset({0, 1})

    def test_drops_rows_missing_forward_return(self):
        dates = pd.date_range("2024-01-01", periods=30, freq="B")
        prices = _mk_prices_dict(dates, {"AAA": 0.001, "XLK": 0.001})
        ai_picks = {
            "2024-01-31": {
                "portfolio": {
                    "picks": [
                        {"ticker": "AAA", "weight": 0.5, "rationale": ""},
                        {"ticker": "NOPRICE", "weight": 0.5, "rationale": ""},
                    ],
                    "cash_weight": 0.0,
                    "source": "heuristic",
                }
            }
        }
        candidates = {
            "2024-01-31": {
                "candidates": [
                    {
                        "ticker": "AAA",
                        "composite": 0.5,
                        "sector": "Technology",
                        "contributions": {},
                    },
                    {
                        "ticker": "NOPRICE",
                        "composite": 0.4,
                        "sector": "Technology",
                        "contributions": {},
                    },
                ]
            }
        }
        frame = build_training_frame(ai_picks, candidates, prices)
        assert "NOPRICE" not in frame.get("ticker", pd.Series([])).values


class TestTrainMetaModel:
    def _mk_random_frame(self, n=100, seed=0) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        rows = []
        for i in range(n):
            composite = float(rng.uniform(-0.5, 0.5))
            beat = int(composite + rng.normal(0, 0.2) > 0)
            rows.append(
                {
                    "rebalance_date": f"2024-{(i % 12) + 1:02d}-15",
                    "composite": composite,
                    "contrib_qmj": composite * 0.5,
                    "contrib_sue": composite * 0.3,
                    "contrib_erm": composite * 0.2,
                    "pick_weight": 0.1,
                    "portfolio_cash_weight": 0.0,
                    "portfolio_n_picks": 10,
                    "portfolio_source_is_llm": 0,
                    "candidate_rank": i % 50,
                    "beat_sector_21d": beat,
                }
            )
        return pd.DataFrame(rows)

    def test_train_learns_composite_signal(self):
        frame = self._mk_random_frame(n=200, seed=42)
        trained = train_meta_model(frame, test_frac=0.2)
        assert trained.metrics["train_accuracy"] > 0.60
        auc = trained.metrics["test_auc"]
        assert auc is None or auc > 0.5

    def test_predict_proba_shape(self):
        frame = self._mk_random_frame(n=100, seed=0)
        trained = train_meta_model(frame)
        probs = trained.predict_proba(frame.head(5))
        assert probs.shape == (5,)
        assert (0.0 <= probs).all() and (probs <= 1.0).all()

    def test_train_raises_on_too_few_rows(self):
        frame = self._mk_random_frame(n=5)
        with pytest.raises(ValueError):
            train_meta_model(frame)


class TestSectorMap:
    def test_covers_all_gics_sectors(self):
        gics = {
            "Information Technology",
            "Financials",
            "Health Care",
            "Consumer Discretionary",
            "Consumer Staples",
            "Industrials",
            "Energy",
            "Materials",
            "Utilities",
            "Real Estate",
            "Communication Services",
        }
        for s in gics:
            assert s in SECTOR_TO_ETF, f"{s} missing from SECTOR_TO_ETF"


class TestSaveLoad:
    def test_roundtrip(self, tmp_path):
        frame = pd.DataFrame(
            {
                "rebalance_date": [f"2024-01-{i:02d}" for i in range(1, 26)],
                "composite": np.linspace(-0.5, 0.5, 25),
                "contrib_qmj": [0.0] * 25,
                "contrib_sue": [0.0] * 25,
                "contrib_erm": [0.0] * 25,
                "pick_weight": [0.1] * 25,
                "portfolio_cash_weight": [0.0] * 25,
                "portfolio_n_picks": [10] * 25,
                "portfolio_source_is_llm": [0] * 25,
                "candidate_rank": list(range(25)),
                "beat_sector_21d": [i % 2 for i in range(25)],
            }
        )
        trained = train_meta_model(frame)
        path = str(tmp_path / "model.pkl")
        save_model(trained, path)
        loaded = load_model(path)
        assert isinstance(loaded, TrainedMetaModel)
        assert loaded.feature_columns == trained.feature_columns
