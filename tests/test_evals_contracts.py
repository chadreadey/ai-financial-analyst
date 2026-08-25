"""
Drift tests between the prompts, ``evals.contracts``, and ``orchestrator``.

Three copies of the same decision rules exist in this repo: the prose in
``prompts/*.md`` that the model reads, the constants in ``evals.contracts``
that the graders read, and the override logic in ``orchestrator.py`` that the
request path applies. Editing one without the others is the most likely way for
the eval suite to start silently measuring the wrong thing, so these tests parse
the prompts and compare all three.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

import orchestrator
from evals import contracts

SYNTHESIS_PROMPT = Path("prompts/synthesis.md")
PATTERN_PROMPT = Path("prompts/pattern.md")


def _score_sweep() -> list[float]:
    """Every 0.01 step across the score range, including exact boundaries."""
    steps = [float(Decimal(n) / 100) for n in range(-100, 101)]
    return steps + [0.2999, 0.3001, 0.5999, 0.6001, -0.2999, -0.3001, -0.5999, -0.6001]


# ── prompts/synthesis.md ───────────────────────────────────────────────────


def test_signal_weights_match_synthesis_prompt():
    """The Step 2 weight table is the source of truth for SIGNAL_WEIGHTS."""
    text = SYNTHESIS_PROMPT.read_text(encoding="utf-8")
    section = text.split("Apply these reliability weights", 1)[1].split(
        "Compute `weighted_score", 1
    )[0]
    parsed = {
        name.strip().lower(): float(value)
        for name, value in re.findall(r"^- (\w+):\s*(\d\.\d+)", section, re.MULTILINE)
    }
    assert parsed == contracts.SIGNAL_WEIGHTS, (
        "prompts/synthesis.md Step 2 weights disagree with evals.contracts."
        f" prompt={parsed} contracts={contracts.SIGNAL_WEIGHTS}"
    )


def test_signal_weights_partition_one():
    total = sum(contracts.SIGNAL_WEIGHTS.values())
    assert abs(total - 1.0) < contracts.WEIGHT_SUM_TOLERANCE


def test_decision_table_matches_prompt():
    """Parse the Step 3 markdown table and check every band boundary."""
    text = SYNTHESIS_PROMPT.read_text(encoding="utf-8")
    rows = re.findall(
        r"^\|\s*([^|]+?)\s*\|\s*(STRONG BUY|BUY|HOLD|SELL|STRONG SELL)\s*\|",
        text,
        re.MULTILINE,
    )
    assert rows, "Step 3 decision table not found in prompts/synthesis.md"

    bands = {verdict: bound.strip() for bound, verdict in rows}
    assert set(bands) == set(contracts.VERDICTS)
    assert bands["STRONG BUY"].startswith("≥ +0.60")
    assert bands["STRONG SELL"].startswith("≤ -0.60")

    assert contracts.verdict_for_score(0.60) == "STRONG BUY"
    assert contracts.verdict_for_score(0.59) == "BUY"
    assert contracts.verdict_for_score(0.30) == "BUY"
    assert contracts.verdict_for_score(0.29) == "HOLD"
    assert contracts.verdict_for_score(-0.29) == "HOLD"
    assert contracts.verdict_for_score(-0.30) == "SELL"
    assert contracts.verdict_for_score(-0.59) == "SELL"
    assert contracts.verdict_for_score(-0.60) == "STRONG SELL"


def test_macro_multiplier_matches_prompt():
    text = SYNTHESIS_PROMPT.read_text(encoding="utf-8")
    assert "macro_score ≤ -0.5" in text
    assert "multiply the final weighted_score by 0.7" in text
    assert contracts.ADVERSE_MACRO_THRESHOLD == -0.5
    assert contracts.ADVERSE_MACRO_MULTIPLIER == 0.7


# ── orchestrator override vs contracts ─────────────────────────────────────


@pytest.mark.parametrize("score", _score_sweep())
def test_orchestrator_verdict_matches_contract(score):
    assert orchestrator._verdict_from_weighted_score(score) == contracts.verdict_for_score(score)


@pytest.mark.parametrize("score", [abs(s) for s in _score_sweep()])
def test_orchestrator_conviction_matches_contract(score):
    assert orchestrator._conviction_label(score) == contracts.conviction_for_score(score)


def test_sizing_defined_for_every_verdict():
    assert set(contracts.SIZING_FOR_VERDICT) == set(contracts.VERDICTS)
    assert set(contracts.SIZING_FOR_VERDICT.values()) <= set(contracts.SIZING_VALUES)


# ── weighted score arithmetic ──────────────────────────────────────────────


def test_weighted_score_is_plain_weighted_sum():
    signals = {
        "dcf": 0.5,
        "risk": 0.4,
        "earnings": 0.9,
        "competitive": 0.8,
        "pattern": 0.8,
        "macro": 0.5,
    }
    expected = sum(v * contracts.SIGNAL_WEIGHTS[k] for k, v in signals.items())
    assert contracts.weighted_score_for_signals(signals) == pytest.approx(expected)


def test_adverse_macro_scales_the_total():
    base = {"dcf": 1.0, "risk": 1.0, "earnings": 1.0, "competitive": 1.0, "pattern": 1.0}
    benign = contracts.weighted_score_for_signals({**base, "macro": 0.0})
    adverse = contracts.weighted_score_for_signals({**base, "macro": -0.6})

    raw_adverse = sum(v * contracts.SIGNAL_WEIGHTS[k] for k, v in {**base, "macro": -0.6}.items())
    assert adverse == pytest.approx(raw_adverse * contracts.ADVERSE_MACRO_MULTIPLIER)
    assert adverse < benign


def test_macro_at_threshold_triggers_multiplier():
    base = {"dcf": 1.0, "risk": 1.0, "earnings": 1.0, "competitive": 1.0, "pattern": 1.0}
    at = contracts.weighted_score_for_signals({**base, "macro": -0.5})
    just_above = contracts.weighted_score_for_signals({**base, "macro": -0.49})
    # -0.5 satisfies "≤ -0.5" so it is damped, while -0.49 is not; the damped
    # score is therefore lower despite the more favourable macro reading.
    assert at < just_above


def test_missing_signal_weight_is_not_redistributed():
    """
    A missing agent shrinks the score rather than renormalising.

    ``prompts/synthesis.md`` gives no renormalisation rule, so with the macro
    agent disabled the weights cover 0.88 and every verdict is biased toward
    HOLD. Documented in docs/EVALS.md as a known gap.
    """
    full = {k: 1.0 for k in contracts.SIGNAL_WEIGHTS}
    without_macro = {k: v for k, v in full.items() if k != "macro"}
    assert contracts.weighted_score_for_signals(full) == pytest.approx(1.0)
    assert contracts.weighted_score_for_signals(without_macro) == pytest.approx(0.88)


# ── prompts/pattern.md ─────────────────────────────────────────────────────


def test_pattern_weights_match_prompt():
    text = PATTERN_PROMPT.read_text(encoding="utf-8")
    section = text.split("## Composite Score", 1)[1].split("`composite_score", 1)[0]
    found = [float(v) for v in re.findall(r"^- [^:]+: (\d\.\d+)", section, re.MULTILINE)]
    assert sorted(found) == sorted(contracts.PATTERN_WEIGHTS.values())
    assert sum(contracts.PATTERN_WEIGHTS.values()) == pytest.approx(1.0)


def test_pattern_actionable_threshold_matches_prompt():
    text = PATTERN_PROMPT.read_text(encoding="utf-8")
    assert "|composite_score| ≥ 0.40 is actionable" in text
    assert contracts.PATTERN_ACTIONABLE_THRESHOLD == 0.40


@pytest.mark.parametrize(
    "pct_b,expected",
    [(0.0, 1.0), (0.5, 0.0), (1.0, -1.0), (0.63, -0.26), (1.4, -1.0), (-0.2, 1.0)],
)
def test_bollinger_formula(pct_b, expected):
    assert contracts.bollinger_score(pct_b) == pytest.approx(expected)


@pytest.mark.parametrize(
    "rsi,expected", [(30, 0.4), (50, 0.0), (70, -0.4), (58.4, -0.168), (0, 1.0), (100, -1.0)]
)
def test_rsi_formula(rsi, expected):
    assert contracts.rsi_score(rsi) == pytest.approx(expected)


# ── SIGNAL_SCORE parsing ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("analysis\n\nSIGNAL_SCORE: 0.75", [0.75]),
        ("analysis\n\nSIGNAL_SCORE: -0.40", [-0.40]),
        ("analysis\n\nSIGNAL_SCORE: +0.5", [0.5]),
        ("analysis\n\n**SIGNAL_SCORE**: 0.20", [0.20]),
        ("  SIGNAL_SCORE:  0.10  ", [0.10]),
        ("a\nSIGNAL_SCORE: 0.1\nb\nSIGNAL_SCORE: 0.2", [0.1, 0.2]),
        ("no score here", []),
        ("inline mention of SIGNAL_SCORE: 0.5 mid-sentence", []),
        ("", []),
    ],
)
def test_parse_signal_scores(text, expected):
    assert contracts.parse_signal_scores(text) == pytest.approx(expected)


def test_signal_score_required_agents_match_prompts():
    """Only the prompts that actually demand a SIGNAL_SCORE are listed."""
    for agent in ("dcf", "earnings", "competitive", "risk", "pattern", "macro"):
        prompt = Path(f"prompts/{agent}.md")
        if not prompt.exists():
            continue
        demands = "SIGNAL_SCORE: X.XX" in prompt.read_text(encoding="utf-8")
        listed = agent in contracts.SIGNAL_SCORE_REQUIRED_AGENTS
        assert demands == listed, (
            f"prompts/{agent}.md {'demands' if demands else 'does not demand'} a "
            f"SIGNAL_SCORE but contracts {'lists' if listed else 'omits'} it"
        )


def test_signal_scores_from_reports_takes_the_terminal_value():
    reports = [
        {"signal": "dcf", "text": "draft SIGNAL_SCORE: 0.10\nrevised\nSIGNAL_SCORE: 0.50"},
        {"signal": "risk", "text": "prose only"},
        {"signal": "not_a_signal", "text": "SIGNAL_SCORE: 0.90"},
    ]
    assert contracts.signal_scores_from_reports(reports) == {"dcf": 0.50}
