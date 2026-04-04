from __future__ import annotations

import logging
import threading
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_model_lock = threading.Lock()
_instance: Optional["TimesFMModel"] = None


class TimesFMModel:
    def __init__(self, model):
        self._model = model

    @classmethod
    def get(cls) -> "TimesFMModel":
        global _instance
        if _instance is not None:
            return _instance

        with _model_lock:
            if _instance is not None:
                return _instance

            try:
                import timesfm
            except ImportError:
                raise RuntimeError(
                    "timesfm package not installed. Run: pip install 'timesfm[torch]'"
                )

            import os
            checkpoint_dir = os.getenv("TIMESFM_CHECKPOINT_DIR", "").strip() or None
            kwargs = {}
            if checkpoint_dir:
                kwargs["cache_dir"] = checkpoint_dir

            logger.info("Loading TimesFM 2.5 200M model...")
            model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
                "google/timesfm-2.5-200m-pytorch", **kwargs
            )
            model.compile(
                timesfm.ForecastConfig(
                    normalize_inputs=True,
                    use_continuous_quantile_head=True,
                    fix_quantile_crossing=True,
                )
            )

            inst = cls(model)
            inst.forecast([1.0] * 64, horizon=5)
            logger.info("TimesFM model loaded and pre-warmed")
            _instance = inst
            return _instance

    def forecast(
        self, series: list[float], horizon: int = 10, freq: int = 0
    ) -> tuple[list[float], dict[str, list[float]]]:
        result = self._model.forecast(
            inputs=[np.array(series, dtype=np.float32)],
            freq=[freq],
            horizon=horizon,
        )
        point = result[0][0].tolist()
        quantile_matrix = result[1][0]
        quantiles = {
            "p10": quantile_matrix[:, 1].tolist(),
            "p50": quantile_matrix[:, 5].tolist(),
            "p90": quantile_matrix[:, 9].tolist(),
        }
        return point, quantiles
