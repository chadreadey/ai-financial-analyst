import json
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_evidence import to_payload  # noqa: E402

EVAL = ROOT / "docs" / "eval" / "three_series_llm"


def test_payload_from_repo_files():
    latest = json.loads((EVAL / "latest.json").read_text())
    returns = pd.read_csv(EVAL / "daily_returns.csv", index_col=0)
    p = to_payload(latest, returns)
    assert p["series"]["SPY"]["sharpe"] == 0.74
    assert p["series"]["Quant-only"]["sharpe"] == 1.15
    assert p["series"]["AI-augmented"]["sharpe"] == 1.01
    assert set(p["series"]["SPY"]) == {
        "sharpe",
        "sortino",
        "ann_return_pct",
        "max_dd_pct",
        "total_return_pct",
        "days",
    }
    curve = p["curve"]
    for k in ("SPY", "Quant-only", "AI-augmented"):
        assert abs(curve[0][k] - 1.0) < 0.05
    dates = [c["date"] for c in curve]
    assert dates == sorted(dates)
    assert 300 <= len(curve) <= 400
    for c in curve:
        assert not any(math.isnan(v) for k, v in c.items() if k != "date")


def test_nan_first_row_treated_as_zero():
    df = pd.DataFrame(
        {"SPY": [None, 0.01, 0.02], "Quant-only": [0.1, 0.0, 0.0], "AI-augmented": [0.0, 0.0, 0.0]},
        index=["2024-01-01", "2024-01-02", "2024-01-03"],
    )
    latest = {"config": {}, "series": {}, "attribution": {}}
    p = to_payload(latest, df)
    last = p["curve"][-1]
    assert abs(last["SPY"] - 1.01 * 1.02) < 1e-9
    assert abs(last["Quant-only"] - 1.1) < 1e-9
