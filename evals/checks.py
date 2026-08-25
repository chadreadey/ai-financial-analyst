"""
Deterministic graders.

Every check in this module is a pure function of (case, model output) with no
LLM in the loop, so results are reproducible and free to compute. That matters
more than it sounds: an eval whose grader is itself an LLM inherits that LLM's
variance, and you end up debugging the grader instead of the system.

Checks return :class:`CheckResult`. Returning ``None`` means *not applicable*
(recorded as a skip, excluded from pass rates) — used when an earlier check
already established the output is unusable, so that one unparseable JSON block
produces one failure rather than fifteen.

Severity splits the suite into what gates a merge and what is merely tracked:

``error``
    The artifact is wrong or unusable downstream. Gates CI.
``warn``
    The artifact is usable but off-contract (style, prompt-adherence). Tracked
    over time, does not gate.
"""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Sequence

from pydantic import ValidationError

from evals import contracts
from evals.contracts import (
    BANNED_HEDGES,
    ENTRY_PRICE_DRIFT_TOLERANCE,
    HEALTH_DIMENSIONS,
    MAX_STOP_DISTANCE_PCT,
    REQUIRED_BRIEF_SECTIONS,
    SIGNAL_WEIGHTS,
    SIZING_FOR_VERDICT,
    EarningsStructured,
    SynthesisVerdict,
)
from evals.dataset import AgentCase, SynthesisCase

Severity = str

#: Tolerance for float comparisons the model is expected to compute by hand.
#: Loose enough to absorb rounding to 2dp on six weighted terms, tight enough
#: that a genuinely different arithmetic path fails.
ARITHMETIC_TOLERANCE = 0.02


@functools.lru_cache(maxsize=1)
def _production_extractors() -> tuple[Callable, Callable]:
    """
    Import the extractors the request path actually uses.

    Deliberately not re-implemented here: an eval that parses model output with
    its own forgiving parser measures the parser, not the pipeline.
    """
    from orchestrator import _extract_earnings_structured, _extract_structured_block

    return _extract_structured_block, _extract_earnings_structured


def extract_structured(text: str) -> tuple[Optional[dict], str]:
    extract, _ = _production_extractors()
    return extract(text)


def extract_earnings_structured(text: str) -> Optional[dict]:
    _, extract = _production_extractors()
    return extract(text)


_FENCED_JSON = re.compile(r"```(?:json)?\s*\n(\{.*?\})\s*\n```", re.DOTALL)


def extract_pattern_vector(text: str) -> Optional[dict]:
    """
    Parse the signal vector block specified by ``prompts/pattern.md``.

    Unlike the other extractors this one has no request-path counterpart to
    borrow, because nothing in ``orchestrator.py`` parses the Pattern agent's
    JSON — the synthesis reads its prose. The contract is still worth grading:
    the prompt spends 25 lines pinning down a schema, and drift off it is
    currently invisible.
    """
    for match in _FENCED_JSON.finditer(text or ""):
        raw = match.group(1).strip()
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
            except (json.JSONDecodeError, ValueError):
                continue
        if isinstance(data, dict) and ("composite_score" in data or "signal_vector" in data):
            return data
    return None


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    severity: Severity = "error"
    #: Optional continuous companion metric (e.g. absolute arithmetic error),
    #: aggregated as a mean in reports. Pass/fail remains the gate.
    metric: Optional[float] = None


@dataclass
class Sample:
    """One graded model response."""

    case_id: str
    output: str
    latency_ms: float = 0.0
    error: Optional[str] = None
    structured: Optional[dict] = None
    prose: str = ""
    results: List[CheckResult] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    @property
    def failed_errors(self) -> List[CheckResult]:
        return [r for r in self.results if not r.passed and r.severity == "error"]


def _passed(
    name: str,
    detail: str = "",
    metric: Optional[float] = None,
    severity: Severity = "error",
) -> CheckResult:
    # Severity travels with passing results too, so a check that only ever
    # passes still reports the right gating category.
    return CheckResult(name=name, passed=True, detail=detail, severity=severity, metric=metric)


def _failed(
    name: str,
    detail: str,
    severity: Severity = "error",
    metric: Optional[float] = None,
) -> CheckResult:
    return CheckResult(name=name, passed=False, detail=detail, severity=severity, metric=metric)


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace("%", "").replace("$", "").replace(",", "").strip())
        except ValueError:
            return None
    return None


def _stop_loss_value(structured: dict) -> Optional[float]:
    raw = structured.get("stop_loss")
    if isinstance(raw, dict):
        return _as_float(raw.get("value"))
    return _as_float(raw)


# ══════════════════════════════════════════════════════════════════════════
# Synthesis checks
# ══════════════════════════════════════════════════════════════════════════

SynthesisCheck = Callable[[SynthesisCase, Sample], Optional[CheckResult]]

SYNTHESIS_CHECKS: List[SynthesisCheck] = []


def synthesis_check(fn: SynthesisCheck) -> SynthesisCheck:
    SYNTHESIS_CHECKS.append(fn)
    return fn


@synthesis_check
def check_call_succeeded(case: SynthesisCase, sample: Sample) -> CheckResult:
    if sample.error:
        return _failed("call_succeeded", f"provider error: {sample.error}")
    if not sample.output.strip():
        return _failed("call_succeeded", "empty response")
    return _passed("call_succeeded")


@synthesis_check
def check_structured_block_present(case: SynthesisCase, sample: Sample) -> Optional[CheckResult]:
    if sample.error:
        return None
    if sample.structured is None:
        return _failed(
            "structured_block_present",
            "no fenced JSON block could be parsed; downstream verdict, price "
            "target and history persistence are all skipped when this happens",
        )
    return _passed("structured_block_present")


@synthesis_check
def check_schema_valid(case: SynthesisCase, sample: Sample) -> Optional[CheckResult]:
    if not sample.structured:
        return None
    try:
        SynthesisVerdict.model_validate(sample.structured)
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]
        )
        return _failed("schema_valid", errors)
    return _passed("schema_valid")


@synthesis_check
def check_signal_weights_canonical(case: SynthesisCase, sample: Sample) -> Optional[CheckResult]:
    if not sample.structured:
        return None
    breakdown = sample.structured.get("signal_breakdown")
    if not isinstance(breakdown, dict) or not breakdown:
        return _failed("signal_weights_canonical", "signal_breakdown missing or empty")

    wrong: List[str] = []
    for name, entry in breakdown.items():
        expected = SIGNAL_WEIGHTS.get(str(name).lower())
        if expected is None:
            wrong.append(f"{name}: not a known signal")
            continue
        actual = _as_float(entry.get("weight")) if isinstance(entry, dict) else None
        if actual is None or abs(actual - expected) > 1e-6:
            wrong.append(f"{name}: {actual} != {expected}")
    if wrong:
        return _failed("signal_weights_canonical", "; ".join(wrong))
    return _passed("signal_weights_canonical")


@synthesis_check
def check_weighted_score_arithmetic(case: SynthesisCase, sample: Sample) -> Optional[CheckResult]:
    """Recompute the sum from the model's *own* scores and weights."""
    if not sample.structured:
        return None
    breakdown = sample.structured.get("signal_breakdown")
    reported = _as_float(sample.structured.get("weighted_score"))
    if not isinstance(breakdown, dict) or reported is None:
        return _failed("weighted_score_arithmetic", "weighted_score or breakdown missing")

    signals = {
        str(name).lower(): _as_float(entry.get("score"))
        for name, entry in breakdown.items()
        if isinstance(entry, dict)
    }
    recomputed = contracts.weighted_score_for_signals(signals)
    delta = abs(recomputed - reported)
    if delta > ARITHMETIC_TOLERANCE:
        return _failed(
            "weighted_score_arithmetic",
            f"reported {reported:.4f}, recomputed {recomputed:.4f} (delta {delta:.4f})",
            metric=delta,
        )
    return _passed("weighted_score_arithmetic", metric=delta)


@synthesis_check
def check_verdict_matches_weighted_score(
    case: SynthesisCase, sample: Sample
) -> Optional[CheckResult]:
    if not sample.structured:
        return None
    weighted = _as_float(sample.structured.get("weighted_score"))
    verdict = str(sample.structured.get("verdict") or "").upper().strip()
    if weighted is None:
        return _failed("verdict_matches_weighted_score", "weighted_score missing")
    expected = contracts.verdict_for_score(weighted)
    if verdict != expected:
        return _failed(
            "verdict_matches_weighted_score",
            f"weighted_score {weighted:.4f} implies {expected}, model said {verdict!r}",
        )
    return _passed("verdict_matches_weighted_score")


@synthesis_check
def check_conviction_consistent(case: SynthesisCase, sample: Sample) -> Optional[CheckResult]:
    if not sample.structured:
        return None
    weighted = _as_float(sample.structured.get("weighted_score"))
    score = _as_float(sample.structured.get("conviction_score"))
    label = str(sample.structured.get("conviction") or "").upper().strip()
    if weighted is None or score is None:
        return _failed("conviction_consistent", "weighted_score or conviction_score missing")

    problems = []
    if abs(abs(weighted) - score) > ARITHMETIC_TOLERANCE:
        problems.append(f"conviction_score {score:.4f} != abs(weighted_score) {abs(weighted):.4f}")
    expected_label = contracts.conviction_for_score(score)
    if label != expected_label:
        problems.append(f"conviction {label!r} should be {expected_label!r}")
    if problems:
        return _failed("conviction_consistent", "; ".join(problems))
    return _passed("conviction_consistent")


@synthesis_check
def check_sizing_matches_verdict(case: SynthesisCase, sample: Sample) -> Optional[CheckResult]:
    if not sample.structured:
        return None
    verdict = str(sample.structured.get("verdict") or "").upper().strip()
    sizing = str(sample.structured.get("sizing_guidance") or "").strip()
    expected = SIZING_FOR_VERDICT.get(verdict)
    if expected is None:
        return _failed("sizing_matches_verdict", f"unknown verdict {verdict!r}")
    if sizing != expected:
        return _failed(
            "sizing_matches_verdict",
            f"{verdict} implies {expected}, model said {sizing!r}",
        )
    return _passed("sizing_matches_verdict")


@synthesis_check
def check_probabilities_sum_to_100(case: SynthesisCase, sample: Sample) -> Optional[CheckResult]:
    if not sample.structured:
        return None
    bull = _as_float(sample.structured.get("prior_bull_probability"))
    bear = _as_float(sample.structured.get("prior_bear_probability"))
    if bull is None or bear is None:
        return _failed("probabilities_sum_to_100", "bull/bear probability missing")
    total = bull + bear
    if abs(total - 100.0) > 0.5:
        return _failed(
            "probabilities_sum_to_100",
            f"{bull} + {bear} = {total}",
            metric=abs(total - 100.0),
        )
    return _passed("probabilities_sum_to_100", metric=abs(total - 100.0))


@synthesis_check
def check_health_scores_complete(case: SynthesisCase, sample: Sample) -> Optional[CheckResult]:
    if not sample.structured:
        return None
    health = sample.structured.get("health_scores")
    if not isinstance(health, dict):
        return _failed("health_scores_complete", "health_scores missing")
    missing = [d for d in HEALTH_DIMENSIONS if d not in health]
    out_of_range = [
        f"{k}={v}"
        for k, v in health.items()
        if (_as_float(v) is None)
        or not (contracts.HEALTH_SCORE_MIN <= _as_float(v) <= contracts.HEALTH_SCORE_MAX)
    ]
    problems = []
    if missing:
        problems.append(f"missing {missing}")
    if out_of_range:
        problems.append(f"out of 1-10 range: {out_of_range}")
    if problems:
        return _failed("health_scores_complete", "; ".join(problems))
    return _passed("health_scores_complete")


@synthesis_check
def check_signal_scores_faithful(case: SynthesisCase, sample: Sample) -> Optional[CheckResult]:
    """
    The prompt says to copy a supplied ``SIGNAL_SCORE`` verbatim rather than
    re-derive it from the prose. This is the sharpest instruction-following
    probe in the suite: the right answer is printed in the input.
    """
    if not sample.structured:
        return None
    expected_scores = case.signal_scores()
    if not expected_scores:
        return None
    breakdown = sample.structured.get("signal_breakdown")
    if not isinstance(breakdown, dict):
        return _failed("signal_scores_faithful", "signal_breakdown missing")

    drifted: List[str] = []
    worst = 0.0
    for name, expected in expected_scores.items():
        entry = breakdown.get(name)
        actual = _as_float(entry.get("score")) if isinstance(entry, dict) else None
        if actual is None:
            drifted.append(f"{name}: absent (expected {expected})")
            continue
        delta = abs(actual - expected)
        worst = max(worst, delta)
        if delta > 1e-6:
            drifted.append(f"{name}: {actual} != supplied {expected}")
    if drifted:
        return _failed("signal_scores_faithful", "; ".join(drifted), metric=worst)
    return _passed("signal_scores_faithful", metric=worst)


@synthesis_check
def check_verdict_matches_expected(case: SynthesisCase, sample: Sample) -> Optional[CheckResult]:
    """End-to-end: does the verdict match what the spec implies for this input?"""
    if not sample.structured or not case.has_complete_signal_scores():
        return None
    expected = case.expected_decision()
    actual = str(sample.structured.get("verdict") or "").upper().strip()
    if actual != expected.verdict:
        return _failed(
            "verdict_matches_expected",
            f"expected {expected.verdict} (weighted_score {expected.weighted_score:.4f}), "
            f"got {actual!r}",
        )
    return _passed("verdict_matches_expected")


@synthesis_check
def check_weighted_score_matches_expected(
    case: SynthesisCase, sample: Sample
) -> Optional[CheckResult]:
    if not sample.structured or not case.has_complete_signal_scores():
        return None
    expected = case.expected_decision().weighted_score
    actual = _as_float(sample.structured.get("weighted_score"))
    if actual is None:
        return _failed("weighted_score_matches_expected", "weighted_score missing")
    delta = abs(actual - expected)
    if delta > ARITHMETIC_TOLERANCE:
        return _failed(
            "weighted_score_matches_expected",
            f"expected {expected:.4f}, got {actual:.4f} (delta {delta:.4f})",
            metric=delta,
        )
    return _passed("weighted_score_matches_expected", metric=delta)


@synthesis_check
def check_entry_price_grounded(case: SynthesisCase, sample: Sample) -> Optional[CheckResult]:
    if not sample.structured or not case.current_price:
        return None
    entry = _as_float(sample.structured.get("entry_price"))
    if entry is None:
        return _failed("entry_price_grounded", "entry_price missing")
    drift = abs(entry - case.current_price) / case.current_price
    if drift > ENTRY_PRICE_DRIFT_TOLERANCE:
        return _failed(
            "entry_price_grounded",
            f"entry_price {entry} drifts {drift:.1%} from supplied price {case.current_price}",
            metric=drift,
        )
    return _passed("entry_price_grounded", metric=drift)


@synthesis_check
def check_stop_loss_valid(case: SynthesisCase, sample: Sample) -> Optional[CheckResult]:
    if not sample.structured:
        return None
    entry = _as_float(sample.structured.get("entry_price")) or case.current_price
    stop = _stop_loss_value(sample.structured)
    if entry is None or entry <= 0:
        return None
    if stop is None:
        return _failed("stop_loss_valid", "stop_loss missing")

    is_short = "SELL" in str(sample.structured.get("verdict") or "").upper()
    if is_short and stop <= entry:
        return _failed("stop_loss_valid", f"short stop {stop} must sit above entry {entry}")
    if not is_short and stop >= entry:
        return _failed("stop_loss_valid", f"long stop {stop} must sit below entry {entry}")
    distance = abs(stop - entry) / entry
    if distance > MAX_STOP_DISTANCE_PCT:
        return _failed(
            "stop_loss_valid",
            f"stop is {distance:.1%} from entry, beyond the {MAX_STOP_DISTANCE_PCT:.0%} "
            "sanity bound",
            metric=distance,
        )
    return _passed("stop_loss_valid", metric=distance)


@synthesis_check
def check_price_target_direction(case: SynthesisCase, sample: Sample) -> Optional[CheckResult]:
    if not sample.structured:
        return None
    entry = _as_float(sample.structured.get("entry_price")) or case.current_price
    target = _as_float(sample.structured.get("price_target"))
    verdict = str(sample.structured.get("verdict") or "").upper()
    if entry is None or target is None or verdict == "HOLD":
        return None
    if "BUY" in verdict and target <= entry:
        return _failed(
            "price_target_direction",
            f"{verdict} with price_target {target} at or below entry {entry}",
        )
    if "SELL" in verdict and target >= entry:
        return _failed(
            "price_target_direction",
            f"{verdict} with price_target {target} at or above entry {entry}",
        )
    return _passed("price_target_direction")


@synthesis_check
def check_no_ungrounded_sources(case: SynthesisCase, sample: Sample) -> Optional[CheckResult]:
    """
    Fields with no supporting input must stay null.

    ``prompts/synthesis.md`` Step 4 says to triangulate from available inputs
    and state when only one exists; a populated ``analyst_consensus`` for a case
    that supplied none is a fabricated number reaching a trade sheet.
    """
    if not sample.structured or not case.ungrounded_fields:
        return None
    sources = sample.structured.get("price_target_sources")
    fabricated = []
    for field_name in case.ungrounded_fields:
        value = sources.get(field_name) if isinstance(sources, dict) else None
        if value is None:
            value = sample.structured.get(field_name)
        if _as_float(value) is not None:
            fabricated.append(f"{field_name}={value}")
    if fabricated:
        return _failed(
            "no_ungrounded_sources",
            "fabricated from absent data: " + ", ".join(fabricated),
        )
    return _passed("no_ungrounded_sources")


@synthesis_check
def check_json_block_first(case: SynthesisCase, sample: Sample) -> Optional[CheckResult]:
    """
    Step 6 requires the JSON block before any prose.

    Not cosmetic: ``_extract_structured_block`` takes the *first* fenced block,
    so a model that leads with prose containing an illustrative snippet gets the
    wrong object parsed into the trade sheet.
    """
    if sample.error or not sample.output.strip():
        return None
    fence = sample.output.find("```")
    if fence == -1:
        return None
    preamble = sample.output[:fence].strip()
    if len(preamble) > 200:
        return _failed(
            "json_block_first",
            f"{len(preamble)} chars of prose precede the JSON block",
            metric=float(len(preamble)),
        )
    return _passed("json_block_first", metric=float(len(preamble)))


@synthesis_check
def check_brief_sections_present(case: SynthesisCase, sample: Sample) -> Optional[CheckResult]:
    if sample.error:
        return None
    body = sample.prose or sample.output
    missing = [s for s in REQUIRED_BRIEF_SECTIONS if s.lower() not in body.lower()]
    if missing:
        return _failed("brief_sections_present", f"missing sections: {missing}", severity="warn")
    return _passed("brief_sections_present", severity="warn")


@synthesis_check
def check_no_hedging_language(case: SynthesisCase, sample: Sample) -> Optional[CheckResult]:
    if sample.error:
        return None
    body = sample.prose or sample.output
    found = [
        hedge
        for hedge in BANNED_HEDGES
        if re.search(rf"\b{re.escape(hedge)}\b", body, re.IGNORECASE)
    ]
    if found:
        return _failed(
            "no_hedging_language",
            f"prompt bans hedging, found: {found}",
            severity="warn",
            metric=float(len(found)),
        )
    return _passed("no_hedging_language", metric=0.0, severity="warn")


@synthesis_check
def check_horizon_plausible(case: SynthesisCase, sample: Sample) -> Optional[CheckResult]:
    if not sample.structured:
        return None
    days = _as_float(sample.structured.get("primary_horizon_days"))
    if days is None:
        return _failed("horizon_plausible", "primary_horizon_days missing")
    if not (1 <= days <= 400):
        return _failed(
            "horizon_plausible",
            f"{days} days is outside the 1-400 range the signal half-life table implies",
        )
    return _passed("horizon_plausible")


# ══════════════════════════════════════════════════════════════════════════
# Phase 1 agent checks
# ══════════════════════════════════════════════════════════════════════════

AgentCheck = Callable[[AgentCase, Sample], Optional[CheckResult]]

AGENT_CHECKS: List[AgentCheck] = []


def agent_check(fn: AgentCheck) -> AgentCheck:
    AGENT_CHECKS.append(fn)
    return fn


@agent_check
def check_agent_call_succeeded(case: AgentCase, sample: Sample) -> CheckResult:
    if sample.error:
        return _failed("call_succeeded", f"provider error: {sample.error}")
    if not sample.output.strip():
        return _failed("call_succeeded", "empty response")
    return _passed("call_succeeded")


@agent_check
def check_signal_score_present(case: AgentCase, sample: Sample) -> Optional[CheckResult]:
    if sample.error or case.agent not in contracts.SIGNAL_SCORE_REQUIRED_AGENTS:
        return None
    scores = contracts.parse_signal_scores(sample.output)
    if not scores:
        return _failed(
            "signal_score_present",
            "no 'SIGNAL_SCORE: X.XX' line; the synthesis prompt then falls back "
            "to re-reading prose, silently changing how the signal is weighted",
        )
    if len(scores) > 1:
        return _failed(
            "signal_score_present",
            f"prompt requires exactly one SIGNAL_SCORE line, found {len(scores)}: {scores}",
        )
    return _passed("signal_score_present")


@agent_check
def check_signal_score_in_range(case: AgentCase, sample: Sample) -> Optional[CheckResult]:
    scores = contracts.parse_signal_scores(sample.output)
    if not scores:
        return None
    value = scores[-1]
    if not (contracts.SIGNAL_SCORE_MIN <= value <= contracts.SIGNAL_SCORE_MAX):
        return _failed("signal_score_in_range", f"{value} outside [-1.0, +1.0]")
    return _passed("signal_score_in_range", metric=value)


@agent_check
def check_signal_score_terminal(case: AgentCase, sample: Sample) -> Optional[CheckResult]:
    """The prompts say the SIGNAL_SCORE line is the last line of the output."""
    if sample.error or not contracts.parse_signal_scores(sample.output):
        return None
    lines = [line for line in sample.output.strip().splitlines() if line.strip()]
    if not lines:
        return None
    if not contracts.SIGNAL_SCORE_PATTERN.match(lines[-1]):
        return _failed(
            "signal_score_terminal",
            f"last line is {lines[-1][:80]!r}, not the SIGNAL_SCORE line",
            severity="warn",
        )
    return _passed("signal_score_terminal", severity="warn")


@agent_check
def check_earnings_structured_present(case: AgentCase, sample: Sample) -> Optional[CheckResult]:
    if case.agent != "earnings" or sample.error:
        return None
    if sample.structured is None:
        return _failed(
            "earnings_structured_present",
            "no parseable D-mode JSON; AnalysisResult.earnings_structured is "
            "then null and the synthesis loses the accounting-quality fields",
        )
    return _passed("earnings_structured_present")


@agent_check
def check_earnings_schema_valid(case: AgentCase, sample: Sample) -> Optional[CheckResult]:
    if case.agent != "earnings" or not sample.structured:
        return None
    try:
        EarningsStructured.model_validate(sample.structured)
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]
        )
        return _failed("earnings_schema_valid", errors)
    return _passed("earnings_schema_valid")


@agent_check
def check_earnings_score_equals_breakdown_mean(
    case: AgentCase, sample: Sample
) -> Optional[CheckResult]:
    """``prompts/earnings.md``: SIGNAL_SCORE = mean(verdict_breakdown.values())."""
    if case.agent != "earnings" or not sample.structured:
        return None
    scores = contracts.parse_signal_scores(sample.output)
    breakdown = sample.structured.get("verdict_breakdown")
    if not scores or not isinstance(breakdown, dict):
        return None
    values = [
        _as_float(breakdown.get(k))
        for k in contracts.EARNINGS_BREAKDOWN_KEYS
        if _as_float(breakdown.get(k)) is not None
    ]
    if not values:
        return None
    expected = sum(values) / len(values)
    delta = abs(expected - scores[-1])
    if delta > ARITHMETIC_TOLERANCE:
        return _failed(
            "earnings_score_equals_breakdown_mean",
            f"SIGNAL_SCORE {scores[-1]} != mean(verdict_breakdown) {expected:.4f}",
            metric=delta,
        )
    return _passed("earnings_score_equals_breakdown_mean", metric=delta)


@agent_check
def check_withheld_fields_are_null(case: AgentCase, sample: Sample) -> Optional[CheckResult]:
    """
    Fabrication probe.

    Cases withhold the inputs for specific structured fields; the prompt says
    "set any unavailable field to null. Do NOT fabricate values." A number here
    is a hallucinated financial statistic, which is the failure mode that
    matters most in this domain.
    """
    if not case.null_fields or not sample.structured:
        return None
    fabricated: List[str] = []
    for dotted in case.null_fields:
        value: Any = sample.structured
        for part in dotted.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value is not None:
            fabricated.append(f"{dotted}={value!r}")
    if fabricated:
        return _failed(
            "withheld_fields_are_null",
            "fabricated values for withheld inputs: " + ", ".join(fabricated),
        )
    return _passed("withheld_fields_are_null")


@agent_check
def check_no_forbidden_values(case: AgentCase, sample: Sample) -> Optional[CheckResult]:
    if not case.forbidden_values or sample.error:
        return None
    found = [v for v in case.forbidden_values if v in sample.output]
    if found:
        return _failed(
            "no_forbidden_values",
            f"output contains values absent from its input: {found}",
        )
    return _passed("no_forbidden_values")


@agent_check
def check_pattern_vector_present(case: AgentCase, sample: Sample) -> Optional[CheckResult]:
    if case.agent != "pattern" or sample.error:
        return None
    if sample.structured is None:
        return _failed(
            "pattern_vector_present",
            "no parseable signal vector block",
        )
    missing = [
        k
        for k in contracts.PATTERN_VECTOR_KEYS
        if k not in (sample.structured.get("signal_vector") or {})
    ]
    if missing:
        return _failed("pattern_vector_present", f"signal_vector missing {missing}")
    return _passed("pattern_vector_present")


@agent_check
def check_pattern_actionable_consistent(case: AgentCase, sample: Sample) -> Optional[CheckResult]:
    """``prompts/pattern.md``: ``|composite_score| >= 0.40`` is actionable."""
    if case.agent != "pattern" or not sample.structured:
        return None
    composite = _as_float(sample.structured.get("composite_score"))
    actionable = sample.structured.get("actionable")
    if composite is None or not isinstance(actionable, bool):
        return _failed("pattern_actionable_consistent", "composite_score or actionable missing")
    expected = abs(composite) >= contracts.PATTERN_ACTIONABLE_THRESHOLD
    if actionable != expected:
        return _failed(
            "pattern_actionable_consistent",
            f"composite {composite} implies actionable={expected}, got {actionable}",
        )
    return _passed("pattern_actionable_consistent")


@agent_check
def check_pattern_direction_consistent(case: AgentCase, sample: Sample) -> Optional[CheckResult]:
    if case.agent != "pattern" or not sample.structured:
        return None
    composite = _as_float(sample.structured.get("composite_score"))
    direction = str(sample.structured.get("composite_direction") or "").upper().strip()
    if composite is None or not direction:
        return _failed("pattern_direction_consistent", "composite_score or direction missing")
    if direction not in contracts.PATTERN_DIRECTIONS:
        return _failed("pattern_direction_consistent", f"unknown direction {direction!r}")
    if composite > 0 and direction == "SELL":
        return _failed(
            "pattern_direction_consistent",
            f"composite {composite} is positive but direction is SELL",
        )
    if composite < 0 and direction == "BUY":
        return _failed(
            "pattern_direction_consistent",
            f"composite {composite} is negative but direction is BUY",
        )
    return _passed("pattern_direction_consistent")


def _pattern_signal(structured: dict, name: str) -> dict:
    entry = (structured.get("signal_vector") or {}).get(name)
    return entry if isinstance(entry, dict) else {}


@agent_check
def check_pattern_composite_arithmetic(case: AgentCase, sample: Sample) -> Optional[CheckResult]:
    """Recompute the composite from the model's own per-signal scores."""
    if case.agent != "pattern" or not sample.structured:
        return None
    reported = _as_float(sample.structured.get("composite_score"))
    vector = sample.structured.get("signal_vector")
    if reported is None or not isinstance(vector, dict):
        return _failed("pattern_composite_arithmetic", "composite or vector missing")
    scores = {
        name: _as_float(_pattern_signal(sample.structured, name).get("score"))
        for name in contracts.PATTERN_WEIGHTS
    }
    recomputed = contracts.pattern_composite(scores)
    delta = abs(recomputed - reported)
    if delta > ARITHMETIC_TOLERANCE:
        return _failed(
            "pattern_composite_arithmetic",
            f"reported {reported}, recomputed {recomputed:.4f} (delta {delta:.4f})",
            metric=delta,
        )
    return _passed("pattern_composite_arithmetic", metric=delta)


@agent_check
def check_pattern_atr_non_directional(case: AgentCase, sample: Sample) -> Optional[CheckResult]:
    if case.agent != "pattern" or not sample.structured:
        return None
    score = _as_float(_pattern_signal(sample.structured, "atr_regime").get("score"))
    if score is None:
        return None
    if abs(score - contracts.PATTERN_ATR_SCORE) > 1e-6:
        return _failed(
            "pattern_atr_non_directional",
            f"atr_regime scored {score}; the prompt fixes it at 0.0 because it "
            "sizes positions rather than pointing a direction",
        )
    return _passed("pattern_atr_non_directional")


@agent_check
def check_pattern_bollinger_formula(case: AgentCase, sample: Sample) -> Optional[CheckResult]:
    if case.agent != "pattern" or not sample.structured:
        return None
    entry = _pattern_signal(sample.structured, "bollinger_pctb")
    pct_b = _as_float(entry.get("pct_b"))
    score = _as_float(entry.get("score"))
    if pct_b is None or score is None:
        return None
    expected = contracts.bollinger_score(pct_b)
    delta = abs(expected - score)
    if delta > ARITHMETIC_TOLERANCE:
        return _failed(
            "pattern_bollinger_formula",
            f"%B {pct_b} implies score {expected:.4f}, got {score}",
            metric=delta,
        )
    return _passed("pattern_bollinger_formula", metric=delta)


@agent_check
def check_pattern_rsi_formula(case: AgentCase, sample: Sample) -> Optional[CheckResult]:
    if case.agent != "pattern" or not sample.structured:
        return None
    entry = _pattern_signal(sample.structured, "rsi")
    rsi = _as_float(entry.get("rsi_value"))
    score = _as_float(entry.get("score"))
    if rsi is None or score is None:
        return None
    expected = contracts.rsi_score(rsi)
    delta = abs(expected - score)
    # The prompt allows a ±0.3 divergence adjustment on top of the base formula.
    if delta > contracts.RSI_DIVERGENCE_BONUS + ARITHMETIC_TOLERANCE:
        return _failed(
            "pattern_rsi_formula",
            f"RSI {rsi} implies {expected:.4f} (±0.3 for divergence), got {score}",
            metric=delta,
        )
    return _passed("pattern_rsi_formula", metric=delta)


@agent_check
def check_pattern_sma_gate_flag(case: AgentCase, sample: Sample) -> Optional[CheckResult]:
    """A bearish SMA gate must be flagged so long entries get suppressed."""
    if case.agent != "pattern" or not sample.structured:
        return None
    score = _as_float(_pattern_signal(sample.structured, "sma_trend").get("score"))
    if score is None:
        return None
    flags = sample.structured.get("flags")
    flags = flags if isinstance(flags, list) else []
    bearish = score <= contracts.SMA_GATE_BEARISH_THRESHOLD
    flagged = contracts.SMA_GATE_BEARISH_FLAG in flags
    if bearish and not flagged:
        return _failed(
            "pattern_sma_gate_flag",
            f"sma_trend {score} is a bearish gate but {contracts.SMA_GATE_BEARISH_FLAG!r} "
            f"is absent from flags {flags}",
        )
    if flagged and not bearish:
        return _failed(
            "pattern_sma_gate_flag",
            f"{contracts.SMA_GATE_BEARISH_FLAG!r} raised with sma_trend {score}",
        )
    return _passed("pattern_sma_gate_flag")


@agent_check
def check_red_flag_severities_valid(case: AgentCase, sample: Sample) -> Optional[CheckResult]:
    if case.agent != "earnings" or not sample.structured:
        return None
    flags = sample.structured.get("red_flags")
    if not isinstance(flags, list):
        return None
    bad = [
        str(f.get("severity"))
        for f in flags
        if isinstance(f, dict)
        and str(f.get("severity")) not in contracts.EARNINGS_RED_FLAG_SEVERITIES
    ]
    if bad:
        return _failed(
            "red_flag_severities_valid",
            f"severities must be LOW/MED/HIGH, got {bad}",
        )
    return _passed("red_flag_severities_valid")


# ══════════════════════════════════════════════════════════════════════════
# Grading entry points
# ══════════════════════════════════════════════════════════════════════════


def _run(checks: Sequence[Callable], case: Any, sample: Sample) -> Sample:
    for check in checks:
        try:
            result = check(case, sample)
        except Exception as exc:  # a broken grader must not abort the run
            result = _failed(
                getattr(check, "__name__", "unknown_check"),
                f"grader raised {type(exc).__name__}: {exc}",
            )
        if result is not None:
            sample.results.append(result)
    return sample


def grade_synthesis(case: SynthesisCase, output: str, **kwargs: Any) -> Sample:
    structured, prose = extract_structured(output)
    sample = Sample(
        case_id=case.id,
        output=output,
        structured=structured,
        prose=prose,
        tags=list(case.tags),
        **kwargs,
    )
    return _run(SYNTHESIS_CHECKS, case, sample)


def grade_agent(case: AgentCase, output: str, **kwargs: Any) -> Sample:
    if case.agent == "earnings":
        structured = extract_earnings_structured(output)
    elif case.agent == "pattern":
        structured = extract_pattern_vector(output)
    else:
        structured = None
    sample = Sample(
        case_id=case.id,
        output=output,
        structured=structured,
        tags=list(case.tags),
        **kwargs,
    )
    return _run(AGENT_CHECKS, case, sample)
