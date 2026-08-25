"""
XGBoost meta-model over AI recommendations (Phase 4 of PLAN_LEAN_QUANT_STRONG_AI).

Target from the strategic memo:
    "Will this AI pick beat its sector benchmark over the next 21 days?"

Features per (rebalance_date, ticker) row:
    - Screener composite (qmj/sue/erm contributions and total)
    - Position weight the PC agent assigned
    - Portfolio-level: number of picks, cash weight, source (llm/heuristic)
    - Rank of the pick within the candidate list (higher = further from top
      of the screener → more AI conviction; a proxy for AI disagreement)

This lets us learn a binary quality classifier that gates AI picks at run
time (drop picks the meta-model says are <threshold likely to beat sector)
or scales positions (weight = base_weight * meta_prob).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


SECTOR_TO_ETF = {
    "Technology": "XLK",
    "Information Technology": "XLK",
    "Healthcare": "XLV",
    "Health Care": "XLV",
    "Financials": "XLF",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Energy": "XLE",
    "Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}


@dataclass
class TrainedMetaModel:
    model: object  # xgboost.XGBClassifier
    feature_columns: list[str]
    metrics: dict = field(default_factory=dict)
    threshold: float = 0.5

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        X = features[self.feature_columns].fillna(0.0).to_numpy()
        return self.model.predict_proba(X)[:, 1]


def _forward_return(prices: pd.DataFrame, as_of: pd.Timestamp, days: int) -> Optional[float]:
    if prices is None or prices.empty:
        return None
    future = prices[prices.index > as_of]
    current = prices[prices.index <= as_of]
    if len(current) < 1 or len(future) < days:
        return None
    p_now = float(current.iloc[-1]["close"])
    p_fwd = float(future.iloc[days - 1]["close"])
    if p_now <= 0:
        return None
    return (p_fwd / p_now) - 1


def build_training_frame(
    ai_pick_files: dict[str, dict],
    candidate_files: dict[str, dict],
    prices: dict[str, pd.DataFrame],
    horizon_days: int = 21,
) -> pd.DataFrame:
    """One row per (rebalance_date, ticker). Drops rows with undefined target."""
    rows: list[dict] = []
    for date_str, ai_payload in ai_pick_files.items():
        cand_payload = candidate_files.get(date_str, {})
        candidates = {c["ticker"]: c for c in cand_payload.get("candidates", [])}
        rank_by_ticker = {
            c["ticker"]: idx for idx, c in enumerate(cand_payload.get("candidates", []))
        }

        picks = ai_payload.get("portfolio", {}).get("picks", [])
        source = ai_payload.get("portfolio", {}).get("source", "heuristic")
        cash_w = float(ai_payload.get("portfolio", {}).get("cash_weight", 0.0))
        n_picks = len(picks)
        as_of = pd.Timestamp(date_str)

        for pk in picks:
            ticker = pk["ticker"]
            cand = candidates.get(ticker, {})
            sector = cand.get("sector", "Unknown")
            contribs = cand.get("contributions", {})

            sector_etf = SECTOR_TO_ETF.get(sector)
            fwd = _forward_return(prices.get(ticker), as_of, horizon_days)
            if fwd is None:
                continue
            sector_fwd = (
                _forward_return(prices.get(sector_etf), as_of, horizon_days) if sector_etf else None
            )
            if sector_fwd is None:
                continue

            rows.append(
                {
                    "rebalance_date": date_str,
                    "ticker": ticker,
                    "sector": sector,
                    "composite": float(cand.get("composite", 0.0)),
                    "contrib_qmj": float(contribs.get("qmj_score", 0.0)),
                    "contrib_sue": float(contribs.get("sue_earnings_score", 0.0)),
                    "contrib_erm": float(contribs.get("erm_earnings_score", 0.0)),
                    "pick_weight": float(pk.get("weight", 0.0)),
                    "portfolio_cash_weight": cash_w,
                    "portfolio_n_picks": n_picks,
                    "portfolio_source_is_llm": 1 if source == "llm" else 0,
                    "candidate_rank": int(rank_by_ticker.get(ticker, -1)),
                    "forward_return_21d": fwd,
                    "sector_forward_return_21d": sector_fwd,
                    "excess_return_21d": fwd - sector_fwd,
                    "beat_sector_21d": int(fwd > sector_fwd),
                }
            )
    return pd.DataFrame(rows)


DEFAULT_FEATURE_COLUMNS = [
    "composite",
    "contrib_qmj",
    "contrib_sue",
    "contrib_erm",
    "pick_weight",
    "portfolio_cash_weight",
    "portfolio_n_picks",
    "portfolio_source_is_llm",
    "candidate_rank",
]


def train_meta_model(
    frame: pd.DataFrame,
    feature_columns: Optional[list[str]] = None,
    target_col: str = "beat_sector_21d",
    test_frac: float = 0.2,
    random_state: int = 42,
    n_estimators: int = 200,
    max_depth: int = 3,
    learning_rate: float = 0.05,
) -> TrainedMetaModel:
    """Time-ordered split; last test_frac rows are the test set."""
    if feature_columns is None:
        feature_columns = DEFAULT_FEATURE_COLUMNS

    frame = frame.dropna(subset=feature_columns + [target_col]).copy()
    frame = frame.sort_values("rebalance_date").reset_index(drop=True)

    if len(frame) < 20:
        raise ValueError(f"Not enough rows to train meta-model (got {len(frame)}, need ≥20)")

    split = int(len(frame) * (1 - test_frac))
    train, test = frame.iloc[:split], frame.iloc[split:]
    X_train = train[feature_columns].fillna(0.0).to_numpy()
    y_train = train[target_col].to_numpy()
    X_test = test[feature_columns].fillna(0.0).to_numpy()
    y_test = test[target_col].to_numpy()

    import xgboost as xgb
    from sklearn.metrics import accuracy_score, f1_score, roc_auc_score

    model = xgb.XGBClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        random_state=random_state,
        eval_metric="logloss",
        tree_method="hist",
    )
    model.fit(X_train, y_train)

    train_prob = model.predict_proba(X_train)[:, 1]
    test_prob = model.predict_proba(X_test)[:, 1]

    base_rate_train = float(y_train.mean()) if len(y_train) else 0.0
    base_rate_test = float(y_test.mean()) if len(y_test) else 0.0

    metrics = {
        "n_train": int(len(train)),
        "n_test": int(len(test)),
        "base_rate_train": base_rate_train,
        "base_rate_test": base_rate_test,
        "train_accuracy": float(accuracy_score(y_train, (train_prob > 0.5).astype(int))),
        "test_accuracy": float(accuracy_score(y_test, (test_prob > 0.5).astype(int))),
        "train_f1": float(f1_score(y_train, (train_prob > 0.5).astype(int), zero_division=0)),
        "test_f1": float(f1_score(y_test, (test_prob > 0.5).astype(int), zero_division=0)),
        "train_auc": (float(roc_auc_score(y_train, train_prob)) if len(set(y_train)) > 1 else None),
        "test_auc": (float(roc_auc_score(y_test, test_prob)) if len(set(y_test)) > 1 else None),
        "features": list(feature_columns),
    }

    return TrainedMetaModel(model=model, feature_columns=list(feature_columns), metrics=metrics)


def save_model(trained: TrainedMetaModel, path: str) -> None:
    import json
    import pickle

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        pickle.dump({"model": trained.model, "feature_columns": trained.feature_columns}, fh)
    meta_path = path + ".metrics.json"
    with open(meta_path, "w") as fh:
        json.dump(trained.metrics, fh, indent=2)


def load_model(path: str) -> TrainedMetaModel:
    import json
    import pickle

    with open(path, "rb") as fh:
        payload = pickle.load(fh)
    metrics = {}
    meta_path = path + ".metrics.json"
    if os.path.exists(meta_path):
        with open(meta_path) as fh:
            metrics = json.load(fh)
    return TrainedMetaModel(
        model=payload["model"],
        feature_columns=payload["feature_columns"],
        metrics=metrics,
    )
