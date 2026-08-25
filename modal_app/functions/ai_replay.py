"""LLM-mode AI-augmented pick replay, fanned out on Modal.

One container call per rebalance date: each call runs the Portfolio
Construction agent's live LLM path against that date's candidate list
(from runs/candidates/) and returns the selected portfolio. The local
entrypoint collects results and writes:

    runs/ai_picks_llm/YYYY-MM-DD.json
    runs/ai_picks_llm/_manifest.json

Afterwards, compare against the heuristic series with:

    python3 scripts/run_three_series_eval.py --ai-picks-dir runs/ai_picks_llm

BIAS WARNING: this is a *contaminated* replay. The LLM's training data
includes the historical period being replayed, so it may "know" which
candidates won. Treat the result as an upper bound on AI value, not a
measurement. See README "Backtest bias disclosure".

Usage:
    modal run modal_app/functions/ai_replay.py                    # all dates
    modal run modal_app/functions/ai_replay.py --limit-dates 2    # smoke test
    modal run modal_app/functions/ai_replay.py --model claude-sonnet-5
"""

from __future__ import annotations

import json
import os

import modal

from modal_app.app import app, image, secrets

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

replay_image = image.add_local_python_source(
    # Full transitive local-import closure of agents.portfolio_construction
    # (agents/__init__ imports every agent class).
    "agents",
    "llm",
    "config",
    "modal_app",
    "context_budget",
    "models",
    "prompt_loader",
    "utils",
    copy=False,
)

DEFAULT_MODEL = "claude-opus-5"


@app.function(
    image=replay_image,
    secrets=secrets,
    timeout=600,
    retries=modal.Retries(max_retries=2, initial_delay=5.0),
)
def pc_select_llm(payload: dict) -> dict:
    """Run the LLM PC agent on one rebalance date's candidate list."""
    import asyncio

    from agents.portfolio_construction import PortfolioConstructionAgent

    agent = PortfolioConstructionAgent(
        model=payload["model"],
        n_positions=payload["n_positions"],
        max_per_sector=payload["max_per_sector"],
        min_composite=payload["min_composite"],
    )
    portfolio = asyncio.run(agent.select(payload["candidates"]))

    # The agent silently falls back to the heuristic on LLM failure, which
    # would fake ΔSharpe = 0. Fail loudly instead so Modal retries.
    if portfolio.source != "llm":
        raise RuntimeError(
            f"{payload['date']}: PC agent returned source={portfolio.source!r}, not 'llm'"
        )

    return {
        "rebalance_date": payload["date"],
        "n_candidates": len(payload["candidates"]),
        "portfolio": portfolio.to_dict(),
        "config": {
            "mode": "llm",
            "model": payload["model"],
            "n_positions": payload["n_positions"],
            "max_per_sector": payload["max_per_sector"],
            "min_composite": payload["min_composite"],
        },
    }


@app.local_entrypoint()
def main(
    model: str = DEFAULT_MODEL,
    limit_dates: int = 0,
    candidate_dir: str = "",
    out_dir: str = "",
    n_positions: int = 10,
    max_per_sector: int = 4,
    min_composite: float = 0.0,
):
    from datetime import datetime, timezone

    candidate_dir = candidate_dir or os.path.join(REPO_ROOT, "runs", "candidates")
    out_dir = out_dir or os.path.join(REPO_ROOT, "runs", "ai_picks_llm")
    os.makedirs(out_dir, exist_ok=True)

    dates = sorted(
        f[:-5] for f in os.listdir(candidate_dir) if f.endswith(".json") and not f.startswith("_")
    )
    if limit_dates:
        dates = dates[:limit_dates]

    payloads = []
    for d in dates:
        with open(os.path.join(candidate_dir, f"{d}.json")) as fh:
            candidates = json.load(fh).get("candidates", [])
        payloads.append(
            {
                "date": d,
                "candidates": candidates,
                "model": model,
                "n_positions": n_positions,
                "max_per_sector": max_per_sector,
                "min_composite": min_composite,
            }
        )

    print(f"Dispatching {len(payloads)} rebalance dates to Modal (model={model})")

    ok, failed = [], []
    for payload, result in zip(payloads, pc_select_llm.map(payloads, return_exceptions=True)):
        d = payload["date"]
        if isinstance(result, Exception):
            failed.append(d)
            print(f"  FAILED {d}: {result}")
            continue
        with open(os.path.join(out_dir, f"{d}.json"), "w") as fh:
            json.dump(result, fh, indent=2)
        ok.append(d)
        picks = ", ".join(p["ticker"] for p in result["portfolio"]["picks"])
        print(f"  {d}: {picks} cash={result['portfolio']['cash_weight']:.2f}")

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "llm",
        "model": model,
        "n_positions": n_positions,
        "max_per_sector": max_per_sector,
        "min_composite": min_composite,
        "dates": ok,
        "failed_dates": failed,
        "bias_note": (
            "Contaminated replay: LLM training data covers the replay period. "
            "Interpret as an upper bound on AI value."
        ),
    }
    with open(os.path.join(out_dir, "_manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)

    print(f"\nWrote {len(ok)} pick files to {out_dir} ({len(failed)} failed)")
    if failed:
        print(f"Failed dates: {failed}")
