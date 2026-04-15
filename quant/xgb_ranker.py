"""
XGBoost meta-model for signal combination.

Replaces hand-tuned linear signal weights with a learned ranking model.
Uses XGBRanker with pairwise objective (LambdaMART) — trains on the
feature matrix from xgb_features.py.

Conservative hyperparameters by default. Must pass CPCV gate before
integration into the live pipeline.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

FEATURE_COLS = [
    "obv_trend", "earnings", "inst_flow", "sentiment",
    "quality", "price_mom", "insider", "event_timing",
    "atr_pct", "vix_level",
]


class XGBMetaModel:
    """XGBoost ranking model for signal combination."""

    def __init__(self, params: dict | None = None) -> None:
        self._model = None
        self._params = params or {
            "objective": "rank:pairwise",
            "max_depth": 3,
            "n_estimators": 200,
            "learning_rate": 0.05,
            "subsample": 0.7,
            "colsample_bytree": 0.8,
            "min_child_weight": 10,
            "reg_alpha": 1.0,
            "reg_lambda": 1.0,
            "random_state": 42,
        }

    def fit(self, X: pd.DataFrame, y: pd.Series, qid: pd.Series) -> None:
        """Train the ranker."""
        from xgboost import XGBRanker

        self._model = XGBRanker(**self._params)
        self._model.fit(X, y, qid=qid)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Return ranking scores (higher = better)."""
        if self._model is None:
            raise ValueError("Model not trained — call fit() first")
        return self._model.predict(X)

    def feature_importance(self) -> dict[str, float]:
        """Return gain-based feature importance."""
        if self._model is None:
            return {}
        imp = self._model.feature_importances_
        names = self._model.get_booster().feature_names or FEATURE_COLS
        total = sum(imp)
        if total == 0:
            return {n: 0.0 for n in names}
        return {n: round(float(v / total), 4) for n, v in zip(names, imp)}

    def save(self, path: str) -> None:
        if self._model is not None:
            self._model.save_model(path)

    def load(self, path: str) -> None:
        from xgboost import XGBRanker
        self._model = XGBRanker()
        self._model.load_model(path)


def train_with_temporal_split(
    feature_matrix: pd.DataFrame,
    train_end_date: str,
    val_months: int = 6,
) -> tuple[XGBMetaModel, dict]:
    """
    Train XGBRanker with temporal train/validation split.

    No lookahead: validation period is always after training period.

    Returns (model, validation_metrics).
    """
    from scipy.stats import spearmanr

    fm = feature_matrix.copy()
    fm["date"] = pd.to_datetime(fm["date"])

    train_end = pd.Timestamp(train_end_date)
    val_end = train_end + pd.DateOffset(months=val_months)

    train = fm[fm["date"] <= train_end]
    val = fm[(fm["date"] > train_end) & (fm["date"] <= val_end)]

    if len(train) < 100 or len(val) < 50:
        raise ValueError(f"Insufficient data: {len(train)} train, {len(val)} val rows")

    X_train = train[FEATURE_COLS]
    y_train = train["fwd_21d_return"]
    qid_train = train["qid"]

    X_val = val[FEATURE_COLS]
    y_val = val["fwd_21d_return"]

    model = XGBMetaModel()
    model.fit(X_train, y_train, qid_train)

    # Validation metrics
    val_pred = model.predict(X_val)

    # Spearman IC (rank correlation between predicted rank and actual return)
    ic, ic_pval = spearmanr(val_pred, y_val)

    # Top-decile return (mean return of stocks XGB ranked in top 10%)
    n_top = max(1, len(val) // 10)
    top_idx = np.argsort(val_pred)[-n_top:]
    top_decile_return = float(y_val.iloc[top_idx].mean()) * 100

    # Bottom-decile return
    bottom_idx = np.argsort(val_pred)[:n_top]
    bottom_decile_return = float(y_val.iloc[bottom_idx].mean()) * 100

    # Long-short spread
    ls_spread = top_decile_return - bottom_decile_return

    metrics = {
        "train_rows": len(train),
        "val_rows": len(val),
        "train_dates": f"{train['date'].min().date()} to {train['date'].max().date()}",
        "val_dates": f"{val['date'].min().date()} to {val['date'].max().date()}",
        "spearman_ic": round(float(ic), 4),
        "ic_pval": round(float(ic_pval), 4),
        "top_decile_return_pct": round(top_decile_return, 2),
        "bottom_decile_return_pct": round(bottom_decile_return, 2),
        "long_short_spread_pct": round(ls_spread, 2),
        "feature_importance": model.feature_importance(),
    }

    return model, metrics
