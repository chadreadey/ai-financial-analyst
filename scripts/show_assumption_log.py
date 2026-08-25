#!/usr/bin/env python3
"""
Show / tail the stochastic assumption log.

The assumption logger (:mod:`quant.assumption_audit`) streams one JSON object
per line to a JSONL file. This is the primary way to *read* those logs from the
terminal: it groups records by status and severity, prints the violations, and
lists the "information gaps" (checks that could not be evaluated).

Where the log lives (in precedence order):
  1. ``--path`` argument, if given
  2. ``ASSUMPTION_AUDIT_JSONL`` environment variable
  3. ``config.settings.assumption_audit_log_path`` (default ``logs/assumptions.jsonl``)
  4. the batch auditor's output ``docs/audit/session-4-statistical-rigor/assumption_log.jsonl``

Examples:
    python3 scripts/show_assumption_log.py                      # default location
    python3 scripts/show_assumption_log.py --status violated    # only violations
    python3 scripts/show_assumption_log.py --severity high      # high+critical
    python3 scripts/show_assumption_log.py --tail 20            # last 20 records
    python3 scripts/show_assumption_log.py --target sharpe      # filter by target
    python3 scripts/show_assumption_log.py --path /tmp/x.jsonl  # explicit file
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import Optional

_SEV_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_DEFAULT_ARTIFACT = "docs/audit/session-4-statistical-rigor/assumption_log.jsonl"


def resolve_log_path(explicit: Optional[str]) -> Optional[str]:
    if explicit:
        return explicit
    env = os.getenv("ASSUMPTION_AUDIT_JSONL")
    if env and os.path.exists(env):
        return env
    try:
        from config import settings

        p = getattr(settings, "assumption_audit_log_path", None)
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    if os.path.exists(_DEFAULT_ARTIFACT):
        return _DEFAULT_ARTIFACT
    # Last resort: newest assumption_log.jsonl anywhere under docs/audit.
    candidates = sorted(
        glob.glob("docs/audit/**/assumption_log.jsonl", recursive=True),
        key=os.path.getmtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def load_records(path: str) -> list[dict]:
    recs = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return recs


def _ctx_str(rec: dict) -> str:
    ctx = rec.get("context", {}) or {}
    keys = ("artifact", "module", "run", "ticker", "signal", "horizon")
    parts = [f"{k}={ctx[k]}" for k in keys if k in ctx]
    return ", ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--path", default=None, help="Explicit JSONL path.")
    ap.add_argument(
        "--status",
        default=None,
        choices=["pass", "violated", "skipped_insufficient_information", "skipped", "error"],
        help="Filter by status ('skipped' matches the skipped status).",
    )
    ap.add_argument(
        "--severity",
        default=None,
        choices=["low", "medium", "high", "critical"],
        help="Show records at this severity or higher.",
    )
    ap.add_argument("--assumption", default=None, help="Filter by assumption id substring.")
    ap.add_argument("--target", default=None, help="Filter by target substring.")
    ap.add_argument("--tail", type=int, default=0, help="Only the last N (post-filter) records.")
    ap.add_argument("--json", action="store_true", help="Emit filtered records as JSON.")
    args = ap.parse_args()

    path = resolve_log_path(args.path)
    if not path:
        print(
            "No assumption log found. Generate one with:\n"
            "  python3 scripts/run_statistical_rigor_audit.py\n"
            "or point --path / ASSUMPTION_AUDIT_JSONL at a JSONL file.",
            file=sys.stderr,
        )
        return 2
    if not os.path.exists(path):
        print(f"Log file does not exist: {path}", file=sys.stderr)
        return 2

    recs = load_records(path)

    # Filters.
    def keep(r: dict) -> bool:
        st = r.get("status", "")
        if args.status:
            want = args.status
            if want == "skipped":
                if not st.startswith("skipped"):
                    return False
            elif st != want:
                return False
        if args.severity:
            if _SEV_RANK.get(r.get("severity", "low"), 0) < _SEV_RANK[args.severity]:
                return False
        if args.assumption and args.assumption not in r.get("assumption", ""):
            return False
        if args.target and args.target not in r.get("target", ""):
            return False
        return True

    filtered = [r for r in recs if keep(r)]
    if args.tail and args.tail > 0:
        filtered = filtered[-args.tail :]

    if args.json:
        print(json.dumps(filtered, indent=2))
        return 0

    # Summary over the *filtered* set.
    counts = {"pass": 0, "violated": 0, "skipped": 0, "error": 0}
    for r in filtered:
        st = r.get("status", "")
        if st.startswith("skipped"):
            counts["skipped"] += 1
        elif st in counts:
            counts[st] += 1
    print("=" * 72)
    print("  ASSUMPTION LOG")
    print("=" * 72)
    print(f"  file      : {path}")
    print(f"  records   : {len(filtered)} shown ({len(recs)} total)")
    print(
        f"  pass={counts['pass']}  VIOLATED={counts['violated']}  "
        f"skipped={counts['skipped']}  error={counts['error']}"
    )

    viols = [r for r in filtered if r.get("status") == "violated"]
    if viols:
        print("\n  Violations (worst severity first):")
        viols.sort(key=lambda r: _SEV_RANK.get(r.get("severity", "low"), 0), reverse=True)
        for r in viols:
            ctx = _ctx_str(r)
            ctx = f"  [{ctx}]" if ctx else ""
            print(
                f"  [{r.get('severity', '?').upper():>8}] "
                f"{r.get('assumption', '?')}:{r.get('target', '?')}{ctx}"
            )
            print(f"             {r.get('message', '')}")

    skipped = [r for r in filtered if str(r.get("status", "")).startswith("skipped")]
    if skipped and not args.status:
        seen = set()
        uniq = []
        for r in skipped:
            key = (r.get("assumption"), r.get("message"))
            if key not in seen:
                seen.add(key)
                uniq.append(r)
        print(f"\n  Information gaps ({len(skipped)} skipped, {len(uniq)} distinct):")
        for r in uniq[:40]:
            print(f"    - {r.get('assumption', '?')}: {r.get('message', '')}")

    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
