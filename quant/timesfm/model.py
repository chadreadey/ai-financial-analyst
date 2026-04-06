from __future__ import annotations

import logging
import threading
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_model_lock = threading.Lock()
_instance: Optional["TimesFMModel"] = None


class TimesFMModel:
    """
    Time-series foundation model wrapper.

    Tries Google TimesFM first (requires `timesfm` + GPU recommended).
    Falls back to Amazon Chronos-T5-Small if TimesFM is unavailable
    (e.g., macOS x86_64 where paxml/lingvo don't install).

    The interface is identical regardless of backend — callers get
    (point_forecast, quantiles) tuples from .forecast().
    """

    def __init__(self, model, backend: str):
        self._model = model
        self.backend = backend  # "timesfm" or "chronos"

    @classmethod
    def get(cls) -> "TimesFMModel":
        global _instance
        if _instance is not None:
            return _instance

        with _model_lock:
            if _instance is not None:
                return _instance

            # Try TimesFM first (preferred — Google's purpose-built model)
            inst = cls._try_timesfm()
            if inst is None:
                inst = cls._try_chronos()
            if inst is None:
                raise RuntimeError(
                    "No time-series model available. Install one of:\n"
                    "  pip install timesfm torch   # preferred, needs Linux + GPU\n"
                    "  pip install chronos-forecasting torch  # fallback, CPU OK"
                )

            _instance = inst
            return _instance

    @classmethod
    def _try_timesfm(cls) -> Optional["TimesFMModel"]:
        try:
            import timesfm
        except ImportError:
            logger.info("timesfm not installed — skipping")
            return None

        import os
        kwargs = {}
        checkpoint_dir = os.getenv("TIMESFM_CHECKPOINT_DIR", "").strip()
        if checkpoint_dir:
            kwargs["cache_dir"] = checkpoint_dir

        try:
            logger.info("Loading TimesFM model...")

            # Try 2.5 first, then 2.0
            model = None
            for loader_name in ["TimesFM_2p5_200M_torch", "TimesFM_2_200M_torch"]:
                loader = getattr(timesfm, loader_name, None)
                if loader is not None:
                    repo = ("google/timesfm-2.5-200m-pytorch" if "2p5" in loader_name
                            else "google/timesfm-2.0-200m-pytorch")
                    logger.info("Trying %s from %s", loader_name, repo)
                    model = loader.from_pretrained(repo, **kwargs)
                    break

            if model is None:
                logger.warning("No TimesFM loader found in timesfm package")
                return None

            # Compile with ForecastConfig if available (2.5+)
            if hasattr(timesfm, "ForecastConfig"):
                model.compile(
                    timesfm.ForecastConfig(
                        normalize_inputs=True,
                        use_continuous_quantile_head=True,
                        fix_quantile_crossing=True,
                    )
                )

            inst = cls(model, backend="timesfm")
            # Pre-warm
            inst.forecast([1.0] * 64, horizon=5)
            logger.info("TimesFM model loaded and pre-warmed (backend: %s)", loader_name)
            return inst
        except Exception as exc:
            logger.warning("TimesFM load failed: %s — trying Chronos", exc)
            return None

    @classmethod
    def _try_chronos(cls) -> Optional["TimesFMModel"]:
        try:
            import torch
            from chronos import ChronosPipeline
        except ImportError:
            logger.info("chronos-forecasting not installed — skipping")
            return None

        try:
            import torch as _torch
            logger.info("Loading Chronos-T5-Small model (fallback)...")
            pipeline = ChronosPipeline.from_pretrained(
                "amazon/chronos-t5-small",
                device_map="cpu",
                torch_dtype=_torch.float32,
            )
            inst = cls(pipeline, backend="chronos")
            inst.forecast([1.0] * 64, horizon=5)
            logger.info("Chronos model loaded and pre-warmed")
            return inst
        except Exception as exc:
            logger.warning("Chronos load failed: %s", exc)
            return None

    def forecast(
        self, series: list[float], horizon: int = 10, freq: int = 0
    ) -> tuple[list[float], dict[str, list[float]]]:
        """
        Produce point forecast + quantiles from a price series.

        Returns:
            (point_forecast, {"p10": [...], "p50": [...], "p90": [...]})
        """
        if self.backend == "timesfm":
            return self._forecast_timesfm(series, horizon, freq)
        else:
            return self._forecast_chronos(series, horizon)

    def _forecast_timesfm(self, series, horizon, freq):
        import inspect

        forecast_params = inspect.signature(self._model.forecast).parameters

        call_kwargs = {
            "inputs": [np.array(series, dtype=np.float32)],
            "horizon": horizon,
        }
        # TimesFM 1.x has `freq`, 2.0+ removed it
        if "freq" in forecast_params:
            call_kwargs["freq"] = [freq]

        result = self._model.forecast(**call_kwargs)

        point = result[0][0].tolist()
        quantile_matrix = result[1][0]

        # Quantile indices vary by version — detect shape
        n_quantiles = quantile_matrix.shape[1] if len(quantile_matrix.shape) > 1 else 0
        if n_quantiles >= 10:
            # 1.x style: 11 quantiles (0.0, 0.1, ..., 1.0)
            quantiles = {
                "p10": quantile_matrix[:, 1].tolist(),
                "p50": quantile_matrix[:, 5].tolist(),
                "p90": quantile_matrix[:, 9].tolist(),
            }
        elif n_quantiles >= 3:
            # 2.x style: fewer quantiles
            quantiles = {
                "p10": quantile_matrix[:, 0].tolist(),
                "p50": quantile_matrix[:, n_quantiles // 2].tolist(),
                "p90": quantile_matrix[:, -1].tolist(),
            }
        else:
            # Fallback: use point forecast for all
            quantiles = {
                "p10": point,
                "p50": point,
                "p90": point,
            }

        return point, quantiles

    def _forecast_chronos(self, series, horizon):
        import torch
        context = torch.tensor(series, dtype=torch.float32)
        samples = self._model.predict(context, horizon, num_samples=50)
        samples_np = samples[0].numpy()

        point = np.median(samples_np, axis=0).tolist()
        quantiles = {
            "p10": np.percentile(samples_np, 10, axis=0).tolist(),
            "p50": np.percentile(samples_np, 50, axis=0).tolist(),
            "p90": np.percentile(samples_np, 90, axis=0).tolist(),
        }
        return point, quantiles
