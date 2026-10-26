"""Generate static example briefs for the public showcase (makes live, paid LLM calls)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_ticker(ticker: str) -> dict:
    from config import settings
    from backend.jobs import create_job, run_analysis_job
    from backend.schemas import RunAnalysisRequest

    req = RunAnalysisRequest(ticker=ticker, provider=settings.llm_provider)
    job = create_job(ticker)
    run_analysis_job(job, req, auto_paper_trade=False)
    if job.status != "complete" or job.result is None:
        raise RuntimeError(job.error or f"job ended with status {job.status}")
    return {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "result": job.result.model_dump(mode="json"),
    }


def summarize(ticker: str, brief: dict) -> dict:
    result = brief["result"]
    sv = result.get("structured_verdict") or {}
    return {
        "ticker": ticker,
        "company_name": result.get("company_name", ticker),
        "verdict": sv.get("verdict"),
        "conviction": sv.get("conviction"),
        "price_target": sv.get("price_target"),
        "entry_price": sv.get("entry_price"),
        "has_conflicts": bool(sv.get("signal_conflicts")),
        "run_at": brief["run_at"],
    }


def build(tickers, out_dir, retries=0, analyze=run_ticker) -> int:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    entries, failed = [], {}
    for raw in tickers:
        ticker = raw.upper()
        brief = None
        for attempt in range(retries + 1):
            try:
                brief = analyze(ticker)
                break
            except Exception as exc:
                print(
                    f"[{ticker}] attempt {attempt + 1} failed: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                failed[ticker] = f"{type(exc).__name__}: {exc}"
        if brief is None:
            continue
        failed.pop(ticker, None)
        (out / f"{ticker}.json").write_text(json.dumps(brief, indent=2, default=str) + "\n")
        entry = summarize(ticker, brief)
        entries.append(entry)
        conflicts = (brief["result"].get("structured_verdict") or {}).get("signal_conflicts")
        print(
            f"[{ticker}] verdict={entry['verdict']} conviction={entry['conviction']} "
            f"signal_conflicts={json.dumps(conflicts)}"
        )

    if failed:
        print(f"Failed tickers, index.json not written: {failed}", file=sys.stderr)
        return 1
    index = {"generated_at": datetime.now(timezone.utc).isoformat(), "briefs": entries}
    (out / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    if not any(e["has_conflicts"] for e in entries):
        print("No brief shows agent disagreement; swap a ticker", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+", default=["NVDA", "JPM", "KO", "XOM"])
    ap.add_argument("--out", default="frontend/public/showcase")
    ap.add_argument("--retries", type=int, default=0)
    args = ap.parse_args()
    return build(args.tickers, args.out, args.retries)


if __name__ == "__main__":
    sys.exit(main())
