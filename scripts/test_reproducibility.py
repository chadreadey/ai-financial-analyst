"""
Signal reproducibility tester.

Runs the same ticker through the analysis pipeline N times and measures
the standard deviation of key outputs (conviction scores, signal scores,
verdicts). Helps identify which signals are deterministic (math-based)
vs noisy (LLM-based).

Usage:
    python scripts/test_reproducibility.py AAPL --runs 5
    python scripts/test_reproducibility.py AAPL --runs 5 --quant-only
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def run_quant_signals(ticker: str, runs: int) -> dict:
    """Run math-based signal computation N times. Should be perfectly deterministic."""
    from quant.signals import compute_signal_vector_from_tiingo

    api_key = os.getenv("TIINGO_API_KEY", "").strip()
    if not api_key:
        print("ERROR: TIINGO_API_KEY not set")
        return {}

    results = []
    for i in range(runs):
        print(f"  Quant run {i+1}/{runs}...", end=" ", flush=True)
        sv = compute_signal_vector_from_tiingo(ticker, api_key)
        if sv is None:
            print("FAILED (no data)")
            continue
        d = sv.to_dict()
        results.append(d)
        print(f"composite={d['composite_score']:.4f} direction={d['composite_direction']}")

    if not results:
        return {}

    # Analyze variance
    composites = [r["composite_score"] for r in results]
    signals = {}
    for sig_name in results[0]["signal_vector"]:
        scores = [r["signal_vector"][sig_name]["score"] for r in results]
        signals[sig_name] = {
            "mean": float(np.mean(scores)),
            "std": float(np.std(scores)),
            "values": scores,
        }

    return {
        "type": "quant_only",
        "runs": len(results),
        "composite": {
            "mean": float(np.mean(composites)),
            "std": float(np.std(composites)),
            "values": composites,
        },
        "signals": signals,
        "directions": Counter(r["composite_direction"] for r in results),
        "deterministic": all(c == composites[0] for c in composites),
    }


async def run_full_analysis(ticker: str, runs: int) -> dict:
    """Run full LLM analysis N times and measure output variance."""
    from orchestrator import Orchestrator, _extract_structured_block

    results = []
    for i in range(runs):
        print(f"  Full analysis run {i+1}/{runs}...", end=" ", flush=True)
        t0 = time.time()
        try:
            orch = Orchestrator()
            result = await orch.run(ticker)
            elapsed = time.time() - t0

            structured = result.structured_verdict or {}
            results.append({
                "verdict": structured.get("verdict", "UNKNOWN"),
                "conviction_score": structured.get("conviction_score"),
                "weighted_score": structured.get("weighted_score"),
                "price_target": structured.get("price_target"),
                "entry_price": structured.get("entry_price"),
                "signal_breakdown": structured.get("signal_breakdown", {}),
                "elapsed_s": round(elapsed, 1),
            })
            print(f"verdict={structured.get('verdict')} conviction={structured.get('conviction_score')} ({elapsed:.1f}s)")
        except Exception as exc:
            print(f"FAILED: {exc}")
            continue

    if not results:
        return {}

    # Analyze variance
    def _stats(values):
        clean = [v for v in values if v is not None]
        if not clean:
            return {"mean": None, "std": None, "values": values}
        return {
            "mean": round(float(np.mean(clean)), 4),
            "std": round(float(np.std(clean)), 4),
            "min": round(float(np.min(clean)), 4),
            "max": round(float(np.max(clean)), 4),
            "values": [round(v, 4) if v is not None else None for v in values],
        }

    # Per-agent signal scores
    agent_scores = {}
    for agent_name in ["dcf", "risk", "earnings", "competitive", "pattern", "macro"]:
        scores = []
        for r in results:
            sb = r.get("signal_breakdown", {})
            agent_data = sb.get(agent_name, {})
            scores.append(agent_data.get("score"))
        agent_scores[agent_name] = _stats(scores)

    return {
        "type": "full_llm",
        "runs": len(results),
        "verdicts": Counter(r["verdict"] for r in results),
        "conviction_score": _stats([r["conviction_score"] for r in results]),
        "weighted_score": _stats([r["weighted_score"] for r in results]),
        "price_target": _stats([r["price_target"] for r in results]),
        "entry_price": _stats([r["entry_price"] for r in results]),
        "agent_signal_scores": agent_scores,
        "avg_elapsed_s": round(np.mean([r["elapsed_s"] for r in results]), 1),
    }


def print_report(ticker: str, quant_result: dict, llm_result: dict):
    """Print a formatted reproducibility report."""
    print("\n" + "=" * 70)
    print(f"  REPRODUCIBILITY REPORT: {ticker}")
    print("=" * 70)

    if quant_result:
        print("\n--- QUANT SIGNALS (deterministic math) ---")
        print(f"  Runs: {quant_result['runs']}")
        c = quant_result["composite"]
        print(f"  Composite: mean={c['mean']:.4f}  std={c['std']:.6f}")
        print(f"  Deterministic: {'YES' if quant_result['deterministic'] else 'NO (BUG!)'}")
        print(f"  Directions: {dict(quant_result['directions'])}")
        print()
        for sig, data in quant_result["signals"].items():
            det = "OK" if data["std"] < 1e-10 else f"VARIANCE={data['std']:.6f}"
            print(f"    {sig:20s}  score={data['mean']:.3f}  {det}")

    if llm_result:
        print("\n--- FULL LLM ANALYSIS (non-deterministic) ---")
        print(f"  Runs: {llm_result['runs']}  Avg time: {llm_result['avg_elapsed_s']}s")
        print(f"  Verdicts: {dict(llm_result['verdicts'])}")

        for field in ["conviction_score", "weighted_score", "price_target", "entry_price"]:
            data = llm_result[field]
            if data["mean"] is not None:
                stability = "STABLE" if data["std"] < 0.10 else "UNSTABLE" if data["std"] > 0.20 else "MODERATE"
                print(f"  {field:20s}  mean={data['mean']:.4f}  std={data['std']:.4f}  range=[{data['min']:.4f}, {data['max']:.4f}]  {stability}")

        print("\n  Per-agent signal score variance:")
        for agent, data in llm_result.get("agent_signal_scores", {}).items():
            if data["mean"] is not None:
                stability = "STABLE" if data["std"] < 0.15 else "NOISY" if data["std"] > 0.30 else "MODERATE"
                print(f"    {agent:15s}  mean={data['mean']:.3f}  std={data['std']:.3f}  {stability}")

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Signal reproducibility tester")
    parser.add_argument("ticker", help="Stock ticker to test")
    parser.add_argument("--runs", type=int, default=5, help="Number of runs (default: 5)")
    parser.add_argument("--quant-only", action="store_true", help="Only test quant signals (no LLM)")
    parser.add_argument("--llm-only", action="store_true", help="Only test full LLM analysis")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    ticker = args.ticker.upper()
    print(f"\nTesting reproducibility for {ticker} ({args.runs} runs)\n")

    quant_result = {}
    llm_result = {}

    if not args.llm_only:
        print("Phase 1: Quant signal reproducibility")
        quant_result = run_quant_signals(ticker, args.runs)

    if not args.quant_only:
        print("\nPhase 2: Full LLM analysis reproducibility")
        llm_result = asyncio.run(run_full_analysis(ticker, args.runs))

    print_report(ticker, quant_result, llm_result)

    # Save raw results
    output = {
        "ticker": ticker,
        "runs": args.runs,
        "quant": quant_result if quant_result else None,
        "llm": llm_result if llm_result else None,
    }
    out_path = f"reproducibility_{ticker}_{args.runs}runs.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nRaw results saved to {out_path}")


if __name__ == "__main__":
    main()
