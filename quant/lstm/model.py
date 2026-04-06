"""
LSTM model for financial time-series prediction.

Lightweight 2-layer LSTM trained on quant signals + price features
to predict forward returns. Produces a momentum_score in [-1, +1]
that plugs into the same interface as the TimesFM/Chronos overlay.

Designed for walk-forward training: train on N months of data,
predict the next window, slide forward.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Feature list — must stay in sync with build_features()
FEATURE_NAMES = [
    "sma_trend", "mean_reversion_z", "bollinger_pctb", "rsi", "obv_trend",
    "return_5d", "return_20d", "volatility_20d", "volume_ratio",
    "price_vs_sma50", "price_vs_sma200",
]


@dataclass
class LSTMConfig:
    """Hyperparameters for the LSTM model."""
    hidden_size: int = 64
    num_layers: int = 2
    dropout: float = 0.3
    lookback_days: int = 60        # sequence length (trading days)
    forecast_horizon: int = 20     # predict N-day forward return
    learning_rate: float = 1e-3
    batch_size: int = 32
    max_epochs: int = 100
    patience: int = 10             # early stopping patience
    validation_split: float = 0.15
    target_type: str = "return"    # "return" (MSE) or "direction" (BCE)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build feature matrix from OHLCV data.

    Input: DataFrame with columns [open, high, low, close, volume] indexed by date.
    Output: DataFrame with FEATURE_NAMES columns, NaN-filled where insufficient history.
    """
    close = df["close"]
    volume = df["volume"]

    feats = pd.DataFrame(index=df.index)

    # SMA crossover signal
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    feats["sma_trend"] = ((sma50 - sma200) / sma200).clip(-1, 1)

    # Mean reversion Z-score (20d)
    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    feats["mean_reversion_z"] = ((close - ma20) / std20.replace(0, np.nan)).clip(-3, 3) / 3.0

    # Bollinger %B
    upper = ma20 + 2 * std20
    lower = ma20 - 2 * std20
    bw = upper - lower
    feats["bollinger_pctb"] = ((close - lower) / bw.replace(0, np.nan) - 0.5).clip(-1, 1)

    # RSI (14-day)
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    feats["rsi"] = ((rsi - 50) / 50).clip(-1, 1)

    # OBV trend (normalized slope of 20-day OBV)
    obv = (np.sign(delta.fillna(0)) * volume).cumsum()
    obv_ma = obv.rolling(20).mean()
    obv_std = obv.rolling(20).std().replace(0, np.nan)
    feats["obv_trend"] = ((obv - obv_ma) / obv_std).clip(-1, 1)

    # Price returns
    feats["return_5d"] = close.pct_change(5).clip(-0.3, 0.3) / 0.3
    feats["return_20d"] = close.pct_change(20).clip(-0.5, 0.5) / 0.5

    # Realized volatility (20-day)
    daily_ret = close.pct_change()
    vol20 = daily_ret.rolling(20).std() * np.sqrt(252)
    vol_median = vol20.rolling(252).median()
    feats["volatility_20d"] = ((vol20 / vol_median.replace(0, np.nan)) - 1).clip(-1, 1)

    # Volume ratio (current vs 20-day average)
    vol_ma = volume.rolling(20).mean()
    feats["volume_ratio"] = ((volume / vol_ma.replace(0, np.nan)) - 1).clip(-2, 2) / 2.0

    # Price vs SMAs (normalized distance)
    feats["price_vs_sma50"] = ((close - sma50) / sma50.replace(0, np.nan)).clip(-0.3, 0.3) / 0.3
    feats["price_vs_sma200"] = ((close - sma200) / sma200.replace(0, np.nan)).clip(-0.3, 0.3) / 0.3

    return feats[FEATURE_NAMES]


def build_target(df: pd.DataFrame, horizon: int = 20, target_type: str = "return") -> pd.Series:
    """
    Build prediction target: forward return or direction.

    Returns a Series aligned with df.index.
    """
    fwd = df["close"].pct_change(horizon).shift(-horizon)
    if target_type == "direction":
        return (fwd > 0).astype(float)
    # Clip extreme returns for stability
    return fwd.clip(-0.5, 0.5)


class ReturnForecaster:
    """
    PyTorch LSTM for forward return prediction.

    Wraps model creation, training, and inference. The model is intentionally
    small (~50K params) to avoid overfitting on limited financial data.
    """

    def __init__(self, config: Optional[LSTMConfig] = None):
        self.config = config or LSTMConfig()
        self._model = None
        self._fitted = False

    def fit(
        self,
        features: pd.DataFrame,
        target: pd.Series,
    ) -> dict:
        """
        Train the LSTM on features/target. Returns training metrics.

        Both inputs must share the same DatetimeIndex. Rows with NaN
        in either features or target are dropped.
        """
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset

        cfg = self.config

        # Align and drop NaNs
        combined = features.join(target.rename("_target")).dropna()
        if len(combined) < cfg.lookback_days + 50:
            logger.warning("Insufficient data for training: %d rows", len(combined))
            return {"error": "insufficient_data", "rows": len(combined)}

        feat_arr = combined[FEATURE_NAMES].values.astype(np.float32)
        tgt_arr = combined["_target"].values.astype(np.float32)

        # Build sequences: (lookback_days, n_features) → target at end of window
        X_seqs, y_seqs = [], []
        for i in range(cfg.lookback_days, len(feat_arr)):
            X_seqs.append(feat_arr[i - cfg.lookback_days : i])
            y_seqs.append(tgt_arr[i])

        X = np.array(X_seqs, dtype=np.float32)
        y = np.array(y_seqs, dtype=np.float32)

        # Train/val split (temporal — no shuffling)
        val_size = max(1, int(len(X) * cfg.validation_split))
        X_train, X_val = X[:-val_size], X[-val_size:]
        y_train, y_val = y[:-val_size], y[-val_size:]

        # Build model
        n_features = X.shape[2]
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        model = _LSTMNet(
            n_features=n_features,
            hidden_size=cfg.hidden_size,
            num_layers=cfg.num_layers,
            dropout=cfg.dropout,
            output_type=cfg.target_type,
        ).to(device)

        if cfg.target_type == "direction":
            criterion = nn.BCEWithLogitsLoss()
        else:
            criterion = nn.MSELoss()

        optimizer = torch.optim.Adam(model.parameters(), lr=cfg.learning_rate)
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode="min", factor=0.5, patience=5,
        )

        train_ds = TensorDataset(torch.from_numpy(X_train), torch.from_numpy(y_train))
        val_ds = TensorDataset(torch.from_numpy(X_val), torch.from_numpy(y_val))
        train_dl = DataLoader(train_ds, batch_size=cfg.batch_size, shuffle=True)
        val_dl = DataLoader(val_ds, batch_size=cfg.batch_size)

        # Training loop with early stopping
        best_val_loss = float("inf")
        patience_counter = 0
        best_state = None

        for epoch in range(cfg.max_epochs):
            model.train()
            train_loss = 0.0
            for xb, yb in train_dl:
                xb, yb = xb.to(device), yb.to(device)
                pred = model(xb).squeeze(-1)
                loss = criterion(pred, yb)
                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                train_loss += loss.item() * len(xb)
            train_loss /= len(train_ds)

            model.eval()
            val_loss = 0.0
            with torch.no_grad():
                for xb, yb in val_dl:
                    xb, yb = xb.to(device), yb.to(device)
                    pred = model(xb).squeeze(-1)
                    val_loss += criterion(pred, yb).item() * len(xb)
            val_loss /= len(val_ds)

            scheduler.step(val_loss)

            if val_loss < best_val_loss:
                best_val_loss = val_loss
                patience_counter = 0
                best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
            else:
                patience_counter += 1

            if patience_counter >= cfg.patience:
                logger.info("Early stopping at epoch %d (val_loss=%.6f)", epoch + 1, best_val_loss)
                break

        if best_state is not None:
            model.load_state_dict(best_state)
        model.eval()
        self._model = model
        self._device = device
        self._fitted = True

        metrics = {
            "epochs": epoch + 1,
            "train_loss": round(train_loss, 6),
            "val_loss": round(best_val_loss, 6),
            "train_samples": len(X_train),
            "val_samples": len(X_val),
            "device": str(device),
        }
        logger.info("LSTM training complete: %s", metrics)
        return metrics

    def predict(self, features: pd.DataFrame) -> pd.Series:
        """
        Generate predictions for each row where a full lookback window exists.

        Returns a Series of raw predictions indexed by date.
        NaN for rows without sufficient lookback.
        """
        import torch

        if not self._fitted:
            raise RuntimeError("Model not fitted — call .fit() first")

        cfg = self.config
        feat_arr = features[FEATURE_NAMES].values.astype(np.float32)
        preds = np.full(len(feat_arr), np.nan, dtype=np.float32)

        # Build all valid sequences
        valid_indices = []
        sequences = []
        for i in range(cfg.lookback_days, len(feat_arr)):
            window = feat_arr[i - cfg.lookback_days : i]
            if not np.isnan(window).any():
                valid_indices.append(i)
                sequences.append(window)

        if not sequences:
            return pd.Series(preds, index=features.index, name="lstm_prediction")

        X = np.array(sequences, dtype=np.float32)
        self._model.eval()
        with torch.no_grad():
            X_t = torch.from_numpy(X).to(self._device)
            raw = self._model(X_t).squeeze(-1).cpu().numpy()

        if cfg.target_type == "direction":
            # Sigmoid → map to [-1, +1]
            raw = 2.0 / (1.0 + np.exp(-raw)) - 1.0
        else:
            # Clip raw return predictions
            raw = np.clip(raw, -0.5, 0.5)

        for idx, val in zip(valid_indices, raw):
            preds[idx] = float(val)

        return pd.Series(preds, index=features.index, name="lstm_prediction")

    def predict_momentum_score(self, features: pd.DataFrame) -> pd.Series:
        """
        Convert raw predictions to momentum scores in [-1, +1].

        For return targets: normalize by scaling predicted return.
        For direction targets: already in [-1, +1] from predict().
        """
        raw = self.predict(features)

        if self.config.target_type == "return":
            # Scale: a 10% predicted return maps to score ~1.0
            scores = (raw / 0.10).clip(-1, 1)
        else:
            scores = raw.clip(-1, 1)

        return scores.rename("lstm_momentum_score")

    def save(self, path: str | Path) -> None:
        """Save model weights and config."""
        import torch
        import json

        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)

        if self._model is not None:
            torch.save(self._model.state_dict(), path / "lstm_weights.pt")

        with open(path / "lstm_config.json", "w") as f:
            json.dump(self.config.__dict__, f, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> "ReturnForecaster":
        """Load a saved model."""
        import torch
        import json

        path = Path(path)

        with open(path / "lstm_config.json") as f:
            cfg_dict = json.load(f)
        config = LSTMConfig(**cfg_dict)

        forecaster = cls(config)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        model = _LSTMNet(
            n_features=len(FEATURE_NAMES),
            hidden_size=config.hidden_size,
            num_layers=config.num_layers,
            dropout=config.dropout,
            output_type=config.target_type,
        ).to(device)

        state = torch.load(path / "lstm_weights.pt", map_location=device, weights_only=True)
        model.load_state_dict(state)
        model.eval()

        forecaster._model = model
        forecaster._device = device
        forecaster._fitted = True
        return forecaster


class _LSTMNet:
    """PyTorch LSTM network — defined as a class to defer torch import."""

    def __new__(cls, *args, **kwargs):
        import torch.nn as nn

        class Net(nn.Module):
            def __init__(self, n_features, hidden_size, num_layers, dropout, output_type):
                super().__init__()
                self.lstm = nn.LSTM(
                    input_size=n_features,
                    hidden_size=hidden_size,
                    num_layers=num_layers,
                    dropout=dropout if num_layers > 1 else 0.0,
                    batch_first=True,
                )
                self.dropout = nn.Dropout(dropout)
                self.fc = nn.Linear(hidden_size, 1)
                self.output_type = output_type

            def forward(self, x):
                # x: (batch, seq_len, n_features)
                lstm_out, _ = self.lstm(x)
                # Use last time step
                last = lstm_out[:, -1, :]
                out = self.fc(self.dropout(last))
                return out

        return Net(*args, **kwargs)
