"""
Aggregation, rendering, and pass/fail gating for eval runs.

The headline number is ``case_pass_rate``: the fraction of cases where every
``error``-severity check passed. Per-check rates sit underneath it, because
"87% of cases pass" is only actionable once you can see that the 13% are all
failing the same arithmetic check.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from evals.checks import Sample


@dataclass
class CheckStat:
    name: str
    severity: str
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    metrics: List[float] = field(default_factory=list)

    @property
    def evaluated(self) -> int:
        return self.passed + self.failed

    @property
    def pass_rate(self) -> Optional[float]:
        return self.passed / self.evaluated if self.evaluated else None

    @property
    def mean_metric(self) -> Optional[float]:
        return statistics.fmean(self.metrics) if self.metrics else None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "severity": self.severity,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "pass_rate": self.pass_rate,
            "mean_metric": self.mean_metric,
        }


@dataclass
class EvalReport:
    suite: str
    mode: str
    model: str
    samples: List[Sample]
    cassette_hits: int = 0
    cassette_misses: int = 0

    @property
    def check_stats(self) -> List[CheckStat]:
        stats: Dict[str, CheckStat] = {}
        for sample in self.samples:
            for result in sample.results:
                stat = stats.setdefault(
                    result.name, CheckStat(name=result.name, severity=result.severity)
                )
                # A check can be raised to `error` by any sample that treats it
                # as one; keep the strictest severity seen.
                if result.severity == "error":
                    stat.severity = "error"
                if result.passed:
                    stat.passed += 1
                else:
                    stat.failed += 1
                if result.metric is not None:
                    stat.metrics.append(result.metric)
        return sorted(stats.values(), key=lambda s: (s.severity != "error", s.name))

    @property
    def case_pass_rate(self) -> float:
        if not self.samples:
            return 0.0
        clean = sum(1 for s in self.samples if not s.failed_errors)
        return clean / len(self.samples)

    @property
    def mean_latency_ms(self) -> Optional[float]:
        """Mean wall time per call, or ``None`` in replay mode where it is noise."""
        values = [s.latency_ms for s in self.samples if s.latency_ms]
        if not values:
            return None
        mean = statistics.fmean(values)
        return mean if mean >= 1.0 else None

    def failures(self) -> List[tuple[str, str, str]]:
        """``(case_id, check_name, detail)`` for every error-severity failure."""
        return [
            (sample.case_id, result.name, result.detail)
            for sample in self.samples
            for result in sample.failed_errors
        ]

    def to_dict(self) -> dict:
        return {
            "suite": self.suite,
            "mode": self.mode,
            "model": self.model,
            "n_samples": len(self.samples),
            "case_pass_rate": self.case_pass_rate,
            "mean_latency_ms": self.mean_latency_ms,
            "cassette_hits": self.cassette_hits,
            "cassette_misses": self.cassette_misses,
            "checks": [s.to_dict() for s in self.check_stats],
            "failures": [
                {"case_id": c, "check": n, "detail": d} for c, n, d in self.failures()
            ],
        }

    def to_markdown(self) -> str:
        lines = [
            f"## Eval: `{self.suite}`",
            "",
            f"- model: `{self.model}` (mode: `{self.mode}`)",
            f"- samples: {len(self.samples)}",
            f"- **case pass rate: {self.case_pass_rate:.1%}**",
        ]
        if self.mean_latency_ms:
            lines.append(f"- mean latency: {self.mean_latency_ms:.0f} ms")
        lines += ["", "| check | severity | pass | fail | rate | mean metric |", "|---|---|---|---|---|---|"]
        for stat in self.check_stats:
            rate = f"{stat.pass_rate:.0%}" if stat.pass_rate is not None else "n/a"
            metric = f"{stat.mean_metric:.4g}" if stat.mean_metric is not None else ""
            lines.append(
                f"| `{stat.name}` | {stat.severity} | {stat.passed} | {stat.failed} "
                f"| {rate} | {metric} |"
            )

        failures = self.failures()
        if failures:
            lines += ["", "### Failures", ""]
            for case_id, check, detail in failures[:40]:
                lines.append(f"- `{case_id}` — **{check}**: {detail}")
            if len(failures) > 40:
                lines.append(f"- ...and {len(failures) - 40} more")
        return "\n".join(lines) + "\n"

    def to_console(self) -> str:
        lines = [
            "",
            f"  suite={self.suite}  model={self.model}  mode={self.mode}",
            f"  samples={len(self.samples)}  case_pass_rate={self.case_pass_rate:.1%}",
            "",
        ]
        width = max((len(s.name) for s in self.check_stats), default=10)
        for stat in self.check_stats:
            rate = f"{stat.pass_rate:.0%}" if stat.pass_rate is not None else " n/a"
            mark = "PASS" if not stat.failed else "FAIL"
            flag = "" if stat.severity == "error" else "  (warn)"
            lines.append(
                f"  [{mark}] {stat.name.ljust(width)}  {rate.rjust(4)}  "
                f"({stat.passed}/{stat.evaluated}){flag}"
            )
        failures = self.failures()
        if failures:
            lines += ["", "  Failures:"]
            for case_id, check, detail in failures[:20]:
                lines.append(f"    - {case_id} :: {check}: {detail}")
            if len(failures) > 20:
                lines.append(f"    ...and {len(failures) - 20} more")
        return "\n".join(lines) + "\n"


@dataclass
class Gate:
    """Merge criteria applied to a report."""

    min_case_pass_rate: float = 1.0
    #: Per-check minimum pass rates; unlisted error checks must be perfect.
    min_check_pass_rate: Dict[str, float] = field(default_factory=dict)

    def evaluate(self, report: EvalReport) -> tuple[bool, List[str]]:
        violations: List[str] = []
        if report.case_pass_rate < self.min_case_pass_rate:
            violations.append(
                f"case pass rate {report.case_pass_rate:.1%} < required "
                f"{self.min_case_pass_rate:.1%}"
            )
        for stat in report.check_stats:
            if stat.severity != "error" or stat.pass_rate is None:
                continue
            required = self.min_check_pass_rate.get(stat.name, 1.0)
            if stat.pass_rate < required:
                violations.append(
                    f"{stat.name} pass rate {stat.pass_rate:.1%} < required {required:.1%}"
                )
        return (not violations), violations


def compare_to_baseline(
    report: EvalReport, baseline: dict, tolerance: float = 0.0
) -> List[str]:
    """Return human-readable regressions relative to a stored baseline report."""
    regressions: List[str] = []
    base_rate = baseline.get("case_pass_rate")
    if base_rate is not None and report.case_pass_rate < base_rate - tolerance:
        regressions.append(
            f"case pass rate fell {base_rate:.1%} -> {report.case_pass_rate:.1%}"
        )
    base_checks = {c["name"]: c for c in baseline.get("checks", [])}
    for stat in report.check_stats:
        prior = base_checks.get(stat.name)
        if not prior or prior.get("pass_rate") is None or stat.pass_rate is None:
            continue
        if stat.pass_rate < prior["pass_rate"] - tolerance:
            regressions.append(
                f"{stat.name} fell {prior['pass_rate']:.1%} -> {stat.pass_rate:.1%}"
            )
    return regressions


def write_json(report: EvalReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")


def write_markdown(report: EvalReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.to_markdown(), encoding="utf-8")
