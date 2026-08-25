"""
Mutation tests for the graders.

A check that never fires is indistinguishable from one that always passes, and
the difference only shows up the day a real regression slips through. Each test
here takes a fixture that grades clean, breaks exactly one thing, and asserts
that the intended check — and no unrelated error check — reports the failure.
"""

from __future__ import annotations

import json
import re

import pytest

from evals import checks
from evals.dataset import load_agent_cases, load_synthesis_cases
from evals.seed import load_fixture

JSON_BLOCK = re.compile(r"```json\s*\n(\{.*?\})\s*\n```", re.DOTALL)


@pytest.fixture(scope="module")
def synthesis_cases():
    return {case.id: case for case in load_synthesis_cases()}


@pytest.fixture(scope="module")
def agent_cases():
    return {case.id: case for case in load_agent_cases()}


def _rewrite_json_block(text: str, mutate) -> str:
    match = JSON_BLOCK.search(text)
    assert match, "fixture has no fenced JSON block"
    data = json.loads(match.group(1))
    mutate(data)
    replacement = "```json\n" + json.dumps(data, indent=2) + "\n```"
    return text[: match.start()] + replacement + text[match.end() :]


def _result(sample, name):
    for result in sample.results:
        if result.name == name:
            return result
    raise AssertionError(f"check {name!r} did not run; ran {[r.name for r in sample.results]}")


def _assert_only_failure(sample, name):
    """The named check failed and it is the only error-severity failure."""
    assert not _result(sample, name).passed, f"{name} should have failed"
    unexpected = [r.name for r in sample.failed_errors if r.name != name]
    assert not unexpected, f"unrelated checks also failed: {unexpected}"


def grade_mutated(case, mutate):
    output = _rewrite_json_block(load_fixture(case.id), mutate)
    return checks.grade_synthesis(case, output)


# ── baseline: the fixtures grade clean ─────────────────────────────────────


def test_every_synthesis_fixture_grades_clean(synthesis_cases):
    for case in synthesis_cases.values():
        sample = checks.grade_synthesis(case, load_fixture(case.id))
        assert not sample.failed_errors, (
            f"{case.id}: {[(r.name, r.detail) for r in sample.failed_errors]}"
        )


def test_every_agent_fixture_grades_clean(agent_cases):
    for case in agent_cases.values():
        sample = checks.grade_agent(case, load_fixture(case.id))
        assert not sample.failed_errors, (
            f"{case.id}: {[(r.name, r.detail) for r in sample.failed_errors]}"
        )


# ── synthesis mutations ────────────────────────────────────────────────────


def test_missing_json_block_is_caught(synthesis_cases):
    case = synthesis_cases["syn-aligned-strong-buy"]
    prose_only = JSON_BLOCK.sub("", load_fixture(case.id))
    sample = checks.grade_synthesis(case, prose_only)
    assert not _result(sample, "structured_block_present").passed


def test_unparseable_json_skips_downstream_checks(synthesis_cases):
    """One broken block must not cascade into a dozen bogus failures."""
    case = synthesis_cases["syn-aligned-strong-buy"]
    broken = JSON_BLOCK.sub("```json\n{not valid json}\n```", load_fixture(case.id))
    sample = checks.grade_synthesis(case, broken)

    assert not _result(sample, "structured_block_present").passed
    ran = {r.name for r in sample.results}
    assert "schema_valid" not in ran
    assert "weighted_score_arithmetic" not in ran
    assert len(sample.failed_errors) == 1


def test_schema_violation_is_caught(synthesis_cases):
    case = synthesis_cases["syn-aligned-strong-buy"]
    sample = grade_mutated(case, lambda d: d.__setitem__("prior_bull_probability", 140))
    assert not _result(sample, "schema_valid").passed


def test_non_canonical_weight_is_caught(synthesis_cases):
    case = synthesis_cases["syn-aligned-strong-buy"]

    def mutate(data):
        data["signal_breakdown"]["earnings"]["weight"] = 0.30

    sample = grade_mutated(case, mutate)
    assert not _result(sample, "signal_weights_canonical").passed


def test_weighted_score_arithmetic_error_is_caught(synthesis_cases):
    """Scores unchanged, sum wrong — the classic LLM arithmetic slip."""
    case = synthesis_cases["syn-aligned-strong-buy"]
    sample = grade_mutated(case, lambda d: d.__setitem__("weighted_score", 0.42))

    assert not _result(sample, "weighted_score_arithmetic").passed
    assert not _result(sample, "weighted_score_matches_expected").passed
    assert _result(sample, "signal_scores_faithful").passed


def test_verdict_inconsistent_with_own_score_is_caught(synthesis_cases):
    case = synthesis_cases["syn-mixed-hold"]

    def mutate(data):
        data["verdict"] = "BUY"
        data["sizing_guidance"] = "1.0x_base_weight"

    sample = grade_mutated(case, mutate)
    assert not _result(sample, "verdict_matches_weighted_score").passed
    assert not _result(sample, "verdict_matches_expected").passed
    assert _result(sample, "sizing_matches_verdict").passed


def test_conviction_label_mismatch_is_caught(synthesis_cases):
    case = synthesis_cases["syn-aligned-strong-buy"]
    sample = grade_mutated(case, lambda d: d.__setitem__("conviction", "LOW"))
    _assert_only_failure(sample, "conviction_consistent")


def test_conviction_score_mismatch_is_caught(synthesis_cases):
    case = synthesis_cases["syn-aligned-strong-buy"]
    sample = grade_mutated(case, lambda d: d.__setitem__("conviction_score", 0.20))
    _assert_only_failure(sample, "conviction_consistent")


def test_sizing_mismatch_is_caught(synthesis_cases):
    case = synthesis_cases["syn-aligned-strong-buy"]
    sample = grade_mutated(case, lambda d: d.__setitem__("sizing_guidance", "0x_no_position"))
    _assert_only_failure(sample, "sizing_matches_verdict")


def test_probabilities_not_summing_is_caught(synthesis_cases):
    case = synthesis_cases["syn-aligned-strong-buy"]
    sample = grade_mutated(case, lambda d: d.__setitem__("prior_bear_probability", 40))
    _assert_only_failure(sample, "probabilities_sum_to_100")


def test_missing_health_dimension_is_caught(synthesis_cases):
    case = synthesis_cases["syn-aligned-strong-buy"]

    def mutate(data):
        data["health_scores"].pop("macro_environment")

    sample = grade_mutated(case, mutate)
    assert not _result(sample, "health_scores_complete").passed


def test_out_of_range_health_score_is_caught(synthesis_cases):
    case = synthesis_cases["syn-aligned-strong-buy"]

    def mutate(data):
        data["health_scores"]["overall"] = 12

    sample = grade_mutated(case, mutate)
    assert not _result(sample, "health_scores_complete").passed


def test_ignoring_a_supplied_signal_score_is_caught(synthesis_cases):
    """
    The synthesis prompt says to copy a supplied SIGNAL_SCORE verbatim. Here the
    model re-derives one from prose, which is the specific behaviour the prompt
    forbids.
    """
    case = synthesis_cases["syn-aligned-strong-buy"]

    def mutate(data):
        data["signal_breakdown"]["earnings"]["score"] = 0.4

    sample = grade_mutated(case, mutate)
    assert not _result(sample, "signal_scores_faithful").passed
    assert "earnings" in _result(sample, "signal_scores_faithful").detail


def test_entry_price_drift_is_caught(synthesis_cases):
    case = synthesis_cases["syn-aligned-strong-buy"]
    sample = grade_mutated(case, lambda d: d.__setitem__("entry_price", 260.0))
    assert not _result(sample, "entry_price_grounded").passed


def test_entry_price_within_tolerance_passes(synthesis_cases):
    case = synthesis_cases["syn-aligned-strong-buy"]
    sample = grade_mutated(case, lambda d: d.__setitem__("entry_price", 214.0))
    assert _result(sample, "entry_price_grounded").passed


def test_stop_on_wrong_side_of_entry_is_caught(synthesis_cases):
    case = synthesis_cases["syn-aligned-strong-buy"]

    def mutate(data):
        data["stop_loss"] = {"value": 225.0, "unit": "price"}

    sample = grade_mutated(case, mutate)
    _assert_only_failure(sample, "stop_loss_valid")


def test_short_stop_below_entry_is_caught(synthesis_cases):
    case = synthesis_cases["syn-deteriorating-sell"]

    def mutate(data):
        data["stop_loss"] = {"value": 19.0, "unit": "price"}

    sample = grade_mutated(case, mutate)
    _assert_only_failure(sample, "stop_loss_valid")


def test_absurdly_wide_stop_is_caught(synthesis_cases):
    case = synthesis_cases["syn-aligned-strong-buy"]

    def mutate(data):
        data["stop_loss"] = {"value": 100.0, "unit": "price"}

    sample = grade_mutated(case, mutate)
    _assert_only_failure(sample, "stop_loss_valid")


def test_price_target_contradicting_verdict_is_caught(synthesis_cases):
    case = synthesis_cases["syn-aligned-strong-buy"]
    sample = grade_mutated(case, lambda d: d.__setitem__("price_target", 190.0))
    _assert_only_failure(sample, "price_target_direction")


def test_fabricated_source_is_caught(synthesis_cases):
    """No analyst consensus was supplied for this case, so a number is invented."""
    case = synthesis_cases["syn-sparse-signal-scores"]

    def mutate(data):
        data["price_target_sources"]["analyst_consensus"] = 31.5

    sample = grade_mutated(case, mutate)
    _assert_only_failure(sample, "no_ungrounded_sources")


def test_implausible_horizon_is_caught(synthesis_cases):
    case = synthesis_cases["syn-aligned-strong-buy"]
    sample = grade_mutated(case, lambda d: d.__setitem__("primary_horizon_days", 3650))
    _assert_only_failure(sample, "horizon_plausible")


def test_prose_before_json_block_is_caught(synthesis_cases):
    case = synthesis_cases["syn-aligned-strong-buy"]
    padded = "Here is my analysis of the company. " * 12 + "\n\n" + load_fixture(case.id)
    sample = checks.grade_synthesis(case, padded)
    _assert_only_failure(sample, "json_block_first")


def test_hedging_language_is_warned_not_gated(synthesis_cases):
    case = synthesis_cases["syn-aligned-strong-buy"]
    hedged = load_fixture(case.id) + "\n\nHowever, the outlook could change.\n"
    sample = checks.grade_synthesis(case, hedged)

    result = _result(sample, "no_hedging_language")
    assert not result.passed
    assert result.severity == "warn"
    assert not sample.failed_errors, "style checks must not gate the suite"


def test_missing_brief_section_is_warned_not_gated(synthesis_cases):
    case = synthesis_cases["syn-aligned-strong-buy"]
    truncated = load_fixture(case.id).split("### Bear Case")[0]
    sample = checks.grade_synthesis(case, truncated)

    result = _result(sample, "brief_sections_present")
    assert not result.passed
    assert result.severity == "warn"
    assert not sample.failed_errors


def test_provider_error_is_caught(synthesis_cases):
    case = synthesis_cases["syn-aligned-strong-buy"]
    sample = checks.grade_synthesis(case, "", error="APIStatusError: 529 overloaded")
    assert not _result(sample, "call_succeeded").passed
    assert len(sample.failed_errors) == 1


# ── agent mutations ────────────────────────────────────────────────────────


def grade_mutated_agent(case, mutate):
    output = _rewrite_json_block(load_fixture(case.id), mutate)
    return checks.grade_agent(case, output)


def test_missing_signal_score_is_caught(agent_cases):
    case = agent_cases["agt-dcf-standard"]
    stripped = re.sub(r"^SIGNAL_SCORE:.*$", "", load_fixture(case.id), flags=re.MULTILINE)
    sample = checks.grade_agent(case, stripped)
    assert not _result(sample, "signal_score_present").passed


def test_duplicate_signal_score_is_caught(agent_cases):
    case = agent_cases["agt-dcf-standard"]
    sample = checks.grade_agent(case, load_fixture(case.id) + "\nSIGNAL_SCORE: 0.90\n")
    assert not _result(sample, "signal_score_present").passed


def test_signal_score_not_required_for_risk_agent(agent_cases):
    """
    prompts/risk.md never asks for a SIGNAL_SCORE, so its absence is correct.

    If that prompt gains one, test_signal_score_required_agents_match_prompts
    fails first and points at the list to update.
    """
    case = agent_cases["agt-risk-leveraged"]
    sample = checks.grade_agent(case, load_fixture(case.id))
    ran = {r.name for r in sample.results}
    assert "signal_score_present" not in ran
    assert not sample.failed_errors


def test_out_of_range_signal_score_is_caught(agent_cases):
    case = agent_cases["agt-dcf-standard"]
    text = re.sub(
        r"^SIGNAL_SCORE:.*$", "SIGNAL_SCORE: 7.50", load_fixture(case.id), flags=re.MULTILINE
    )
    sample = checks.grade_agent(case, text)
    assert not _result(sample, "signal_score_in_range").passed


def test_non_terminal_signal_score_is_warned(agent_cases):
    case = agent_cases["agt-dcf-standard"]
    sample = checks.grade_agent(case, load_fixture(case.id) + "\n\nOne more thought.\n")
    result = _result(sample, "signal_score_terminal")
    assert not result.passed
    assert result.severity == "warn"


def test_missing_earnings_block_is_caught(agent_cases):
    case = agent_cases["agt-earnings-complete"]
    sample = checks.grade_agent(case, JSON_BLOCK.sub("", load_fixture(case.id)))
    assert not _result(sample, "earnings_structured_present").passed


def test_earnings_score_not_matching_breakdown_is_caught(agent_cases):
    """prompts/earnings.md: SIGNAL_SCORE = mean(verdict_breakdown.values())."""
    case = agent_cases["agt-earnings-complete"]

    def mutate(data):
        data["verdict_breakdown"]["trajectory"] = -0.9

    sample = grade_mutated_agent(case, mutate)
    assert not _result(sample, "earnings_score_equals_breakdown_mean").passed


def test_invalid_red_flag_severity_is_caught(agent_cases):
    case = agent_cases["agt-earnings-complete"]

    def mutate(data):
        data["red_flags"][0]["severity"] = "CRITICAL"

    sample = grade_mutated_agent(case, mutate)
    assert not _result(sample, "red_flag_severities_valid").passed


def test_fabricated_value_for_withheld_input_is_caught(agent_cases):
    """
    The M-Score inputs were withheld from this case, so any number here was
    invented. This is the fabrication probe that matters most in this domain.
    """
    case = agent_cases["agt-earnings-withheld-inputs"]

    def mutate(data):
        data["accounting_quality"]["mscore"] = -2.14

    sample = grade_mutated_agent(case, mutate)
    result = _result(sample, "withheld_fields_are_null")
    assert not result.passed
    assert "mscore" in result.detail


def test_fabricated_consensus_revision_is_caught(agent_cases):
    case = agent_cases["agt-earnings-withheld-inputs"]

    def mutate(data):
        data["earnings_trajectory"]["consensus_eps_revision_3m"] = 0.031

    sample = grade_mutated_agent(case, mutate)
    assert not _result(sample, "withheld_fields_are_null").passed


def test_forbidden_value_is_caught(agent_cases):
    case = agent_cases["agt-dcf-standard"].model_copy(update={"forbidden_values": ["$999.99"]})
    sample = checks.grade_agent(case, load_fixture(case.id) + "\nTarget: $999.99\n")
    assert not _result(sample, "no_forbidden_values").passed


# ── pattern vector mutations ───────────────────────────────────────────────


def test_pattern_composite_arithmetic_error_is_caught(agent_cases):
    case = agent_cases["agt-pattern-technicals"]
    sample = grade_mutated_agent(case, lambda d: d.__setitem__("composite_score", 0.85))

    assert not _result(sample, "pattern_composite_arithmetic").passed
    # 0.85 clears the 0.40 bar while `actionable` still says false.
    assert not _result(sample, "pattern_actionable_consistent").passed


def test_pattern_actionable_threshold_is_caught(agent_cases):
    case = agent_cases["agt-pattern-technicals"]
    sample = grade_mutated_agent(case, lambda d: d.__setitem__("actionable", True))
    _assert_only_failure(sample, "pattern_actionable_consistent")


def test_pattern_direction_contradicting_composite_is_caught(agent_cases):
    case = agent_cases["agt-pattern-technicals"]
    sample = grade_mutated_agent(case, lambda d: d.__setitem__("composite_direction", "SELL"))
    _assert_only_failure(sample, "pattern_direction_consistent")


def test_pattern_directional_atr_is_caught(agent_cases):
    """prompts/pattern.md fixes the ATR score at 0.0; it sizes, it does not point."""
    case = agent_cases["agt-pattern-technicals"]

    def mutate(data):
        data["signal_vector"]["atr_regime"]["score"] = -0.5

    sample = grade_mutated_agent(case, mutate)
    _assert_only_failure(sample, "pattern_atr_non_directional")


def test_pattern_bollinger_formula_violation_is_caught(agent_cases):
    case = agent_cases["agt-pattern-technicals"]

    def mutate(data):
        data["signal_vector"]["bollinger_pctb"]["score"] = 0.6

    sample = grade_mutated_agent(case, mutate)
    assert not _result(sample, "pattern_bollinger_formula").passed


def test_pattern_rsi_formula_violation_is_caught(agent_cases):
    case = agent_cases["agt-pattern-technicals"]

    def mutate(data):
        data["signal_vector"]["rsi"]["score"] = 0.95

    sample = grade_mutated_agent(case, mutate)
    assert not _result(sample, "pattern_rsi_formula").passed


def test_pattern_rsi_divergence_bonus_is_allowed(agent_cases):
    """A ±0.3 divergence adjustment is legal and must not be flagged."""
    case = agent_cases["agt-pattern-technicals"]

    def mutate(data):
        data["signal_vector"]["rsi"]["score"] = -0.168 + 0.3

    sample = grade_mutated_agent(case, mutate)
    assert _result(sample, "pattern_rsi_formula").passed


def test_pattern_missing_sma_gate_flag_is_caught(agent_cases):
    case = agent_cases["agt-pattern-technicals"]

    def mutate(data):
        data["signal_vector"]["sma_trend"]["score"] = -1.0

    sample = grade_mutated_agent(case, mutate)
    assert not _result(sample, "pattern_sma_gate_flag").passed


def test_pattern_missing_vector_key_is_caught(agent_cases):
    case = agent_cases["agt-pattern-technicals"]

    def mutate(data):
        data["signal_vector"].pop("obv_trend")

    sample = grade_mutated_agent(case, mutate)
    assert not _result(sample, "pattern_vector_present").passed


# ── grader robustness ──────────────────────────────────────────────────────


def test_a_raising_grader_does_not_abort_the_run(synthesis_cases, monkeypatch):
    case = synthesis_cases["syn-aligned-strong-buy"]

    def exploding(_case, _sample):
        raise ZeroDivisionError("boom")

    exploding.__name__ = "exploding_check"
    monkeypatch.setattr(checks, "SYNTHESIS_CHECKS", [*checks.SYNTHESIS_CHECKS, exploding])
    sample = checks.grade_synthesis(case, load_fixture(case.id))

    result = _result(sample, "exploding_check")
    assert not result.passed
    assert "ZeroDivisionError" in result.detail
    assert len(sample.results) > 10, "other checks still ran"
