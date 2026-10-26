"""Build frontend/public/evidence/three_series.json from the three-series eval outputs."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "docs" / "eval" / "three_series_llm"
OUT = ROOT / "frontend" / "public" / "evidence" / "three_series.json"

SERIES_NAMES = ["SPY", "Quant-only", "AI-augmented"]
_FIELD_MAP = {
    "sharpe": "sharpe",
    "sortino": "sortino",
    "ann_return_pct": "annual_return_pct",
    "max_dd_pct": "max_drawdown_pct",
    "total_return_pct": "total_return_pct",
    "days": "n_days",
}


def _curve(returns: pd.DataFrame) -> list[dict]:
    df = returns.copy()
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()[SERIES_NAMES].fillna(0.0)
    growth = (1.0 + df).cumprod()
    iso = df.index.isocalendar()
    keys = iso["year"].astype(str) + "-" + iso["week"].astype(str).str.zfill(2)
    weekly = growth.groupby(keys.to_numpy()).tail(1)
    return [
        {"date": d.strftime("%Y-%m-%d"), **{n: round(float(row[n]), 4) for n in SERIES_NAMES}}
        for d, row in weekly.iterrows()
    ]


def to_payload(latest: dict, returns: pd.DataFrame) -> dict:
    series = {
        name: {out: stats.get(src) for out, src in _FIELD_MAP.items()}
        for name, stats in latest.get("series", {}).items()
    }
    return {
        "generated_at": latest.get("generated_at"),
        "config": latest.get("config", {}),
        "series": series,
        "attribution": latest.get("attribution", {}),
        "curve": _curve(returns),
    }


def main() -> None:
    latest = json.loads((EVAL_DIR / "latest.json").read_text())
    returns = pd.read_csv(EVAL_DIR / "daily_returns.csv", index_col=0)
    payload = to_payload(latest, returns)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote {OUT} ({len(payload['curve'])} weekly points)")


if __name__ == "__main__":
    main()
