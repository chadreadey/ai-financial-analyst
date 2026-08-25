"""
Command line entry point for the eval harness.

    python -m evals run     --suite all                  # offline replay, gates on exit code
    python -m evals run     --suite synthesis -v         # show every failure detail
    python -m evals record  --suite synthesis            # live calls, writes cassettes
    python -m evals baseline --suite all                 # freeze current results as the baseline

``run`` exits non-zero when the gate in ``evals/gates.json`` is violated or when
results regress against ``evals/baselines/<suite>.json``, which is what makes it
usable as a CI step.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

from evals.dataset import load_agent_cases, load_synthesis_cases
from evals.replay import CassetteMiss, open_cassette
from evals.report import (
    EvalReport,
    Gate,
    compare_to_baseline,
    write_json,
    write_markdown,
)
from evals.runner import RunConfig, build_provider, run_agent_suite, run_synthesis_suite

SUITES = ("synthesis", "agents")
GATES_FILE = Path(__file__).parent / "gates.json"
BASELINE_DIR = Path(__file__).parent / "baselines"


def _load_gate(suite: str) -> Gate:
    if not GATES_FILE.exists():
        return Gate()
    raw = json.loads(GATES_FILE.read_text(encoding="utf-8")).get(suite, {})
    return Gate(
        min_case_pass_rate=raw.get("min_case_pass_rate", 1.0),
        min_check_pass_rate=raw.get("min_check_pass_rate", {}),
    )


async def _run_suite(suite: str, config: RunConfig, provider_name: Optional[str]) -> EvalReport:
    cassette = open_cassette(suite)
    provider = build_provider(config, cassette, live_provider_name=provider_name)
    try:
        if suite == "synthesis":
            report = await run_synthesis_suite(load_synthesis_cases(), provider, config)
        else:
            report = await run_agent_suite(load_agent_cases(), provider, config)
    finally:
        if config.mode != "replay":
            cassette.save()
    return report


def _resolve_suites(name: str) -> tuple[str, ...]:
    return SUITES if name == "all" else (name,)


def _emit(report: EvalReport, args: argparse.Namespace) -> None:
    print(report.to_console())
    if args.json_out:
        write_json(report, Path(args.json_out.replace("{suite}", report.suite)))
    if args.markdown_out:
        write_markdown(report, Path(args.markdown_out.replace("{suite}", report.suite)))


def _cmd_run(args: argparse.Namespace) -> int:
    failed = False
    for suite in _resolve_suites(args.suite):
        config = RunConfig(
            suite=suite,
            mode=args.mode,
            model=args.model,
            concurrency=args.concurrency,
            repeats=args.repeats,
            case_filter=args.filter,
        )
        try:
            report = asyncio.run(_run_suite(suite, config, args.provider))
        except CassetteMiss as exc:
            print(f"\n  {suite}: cassette miss\n  {exc}\n", file=sys.stderr)
            failed = True
            continue

        _emit(report, args)

        gate = _load_gate(suite)
        if args.min_pass_rate is not None:
            gate.min_case_pass_rate = args.min_pass_rate
        ok, violations = gate.evaluate(report)
        for violation in violations:
            print(f"  GATE: {suite}: {violation}", file=sys.stderr)

        baseline_path = BASELINE_DIR / f"{suite}.json"
        if baseline_path.exists():
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            for regression in compare_to_baseline(report, baseline, args.tolerance):
                print(f"  REGRESSION: {suite}: {regression}", file=sys.stderr)
                ok = False

        failed = failed or not ok
    return 1 if failed else 0


def _cmd_record(args: argparse.Namespace) -> int:
    for suite in _resolve_suites(args.suite):
        config = RunConfig(
            suite=suite,
            mode=args.mode,
            model=args.model,
            concurrency=args.concurrency,
            repeats=args.repeats,
            case_filter=args.filter,
        )
        report = asyncio.run(_run_suite(suite, config, args.provider))
        _emit(report, args)
        print(
            f"  recorded {report.cassette_misses} new response(s) into "
            f"evals/cassettes/{suite}.json"
        )
    return 0


def _cmd_baseline(args: argparse.Namespace) -> int:
    for suite in _resolve_suites(args.suite):
        config = RunConfig(suite=suite, mode=args.mode, model=args.model)
        report = asyncio.run(_run_suite(suite, config, args.provider))
        path = BASELINE_DIR / f"{suite}.json"
        write_json(report, path)
        print(f"  wrote baseline {path} (case pass rate {report.case_pass_rate:.1%})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evals", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser, default_mode: str) -> None:
        p.add_argument("--suite", choices=(*SUITES, "all"), default="all")
        p.add_argument("--mode", choices=("replay", "record", "auto"), default=default_mode)
        p.add_argument("--provider", default=None, help="anthropic | openai (live modes)")
        p.add_argument("--model", default=None)
        p.add_argument("--concurrency", type=int, default=4)
        p.add_argument("--repeats", type=int, default=1)
        p.add_argument("--filter", default=None, help="substring match on case id or tag")
        p.add_argument("--json-out", default=None, help="path, may contain {suite}")
        p.add_argument("--markdown-out", default=None, help="path, may contain {suite}")

    run = sub.add_parser("run", help="grade a suite (offline by default)")
    add_common(run, "replay")
    run.add_argument("--min-pass-rate", type=float, default=None)
    run.add_argument(
        "--tolerance",
        type=float,
        default=0.0,
        help="allowed drop vs baseline before a regression is reported",
    )
    run.set_defaults(func=_cmd_run)

    record = sub.add_parser("record", help="call the live model and refresh cassettes")
    add_common(record, "auto")
    record.set_defaults(func=_cmd_record)

    baseline = sub.add_parser("baseline", help="freeze the current results as the baseline")
    add_common(baseline, "replay")
    baseline.set_defaults(func=_cmd_baseline)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
