import sys
import types
from unittest.mock import patch, MagicMock

from quant.timesfm.batch import run_batch
import quant.timesfm.model


def _stub_client_modules(mock_tiingo, mock_fmp):
    fmp_mod = types.ModuleType("fmp_client")
    fmp_mod.FMPClient = MagicMock(return_value=mock_fmp)
    tiingo_mod = types.ModuleType("tiingo_client")
    tiingo_mod.TiingoClient = MagicMock(return_value=mock_tiingo)
    return {"fmp_client": fmp_mod, "tiingo_client": tiingo_mod}


def test_run_batch_caches_signals():
    mock_model = MagicMock()
    mock_model.forecast.return_value = (
        [100 + i for i in range(10)],
        {
            "p10": [95 + i for i in range(10)],
            "p50": [100 + i for i in range(10)],
            "p90": [105 + i for i in range(10)],
        },
    )

    mock_tiingo = MagicMock()
    mock_tiingo.get_eod_history.return_value = [
        {"adjClose": float(100 + i % 10), "date": f"2024-01-{i + 1:02d}"} for i in range(100)
    ]

    mock_fmp = MagicMock()
    mock_fmp.get_income_statement_quarterly.return_value = None

    with (
        patch.dict(sys.modules, _stub_client_modules(mock_tiingo, mock_fmp)),
        patch("quant.timesfm.model.TimesFMModel.get", return_value=mock_model),
        patch("quant.timesfm.cache.put_signals") as mock_put,
    ):
        mock_put.return_value = True

        results = run_batch(["AAPL"])

        assert results["AAPL"] == "ok"
        mock_put.assert_called()
        call_args = mock_put.call_args_list[0]
        assert call_args[0][0] == "AAPL"
        assert call_args[0][1] == "price_forecast"


def test_single_failure_does_not_abort():
    mock_model = MagicMock()
    mock_model.forecast.return_value = (
        [100 + i for i in range(10)],
        {
            "p10": [95 + i for i in range(10)],
            "p50": [100 + i for i in range(10)],
            "p90": [105 + i for i in range(10)],
        },
    )

    mock_tiingo = MagicMock()

    def side_effect(ticker, **kwargs):
        if ticker == "FAIL":
            raise ValueError("Test failure")
        return [
            {"adjClose": float(100 + i % 10), "date": f"2024-01-{i + 1:02d}"} for i in range(100)
        ]

    mock_tiingo.get_eod_history.side_effect = side_effect

    mock_fmp = MagicMock()
    mock_fmp.get_income_statement_quarterly.return_value = None

    with (
        patch.dict(sys.modules, _stub_client_modules(mock_tiingo, mock_fmp)),
        patch("quant.timesfm.model.TimesFMModel.get", return_value=mock_model),
        patch("quant.timesfm.cache.put_signals") as mock_put,
    ):
        mock_put.return_value = True

        results = run_batch(["AAPL", "FAIL"])

        assert results["AAPL"] == "ok"
        assert results["FAIL"].startswith("error:")


def test_insufficient_data_skipped():
    mock_tiingo = MagicMock()
    mock_tiingo.get_eod_history.return_value = [
        {"adjClose": float(100 + i), "date": f"2024-01-{i + 1:02d}"} for i in range(10)
    ]

    mock_fmp = MagicMock()

    with (
        patch.dict(sys.modules, _stub_client_modules(mock_tiingo, mock_fmp)),
        patch("quant.timesfm.model.TimesFMModel.get", return_value=MagicMock()),
        patch("quant.timesfm.cache.put_signals"),
    ):
        results = run_batch(["SHORT"])

        assert "insufficient" in results["SHORT"]
