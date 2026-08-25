"""
Machine-readable encoding of the decision contracts stated in ``prompts/``.

The synthesis prompt (``prompts/synthesis.md``) does not ask the model for an
opinion — it asks it to execute a specified arithmetic procedure: score each
signal, multiply by a fixed weight, sum, apply a macro regime multiplier, and
map the result through a threshold table. Because the procedure is fully
specified, the correct answer for any set of input signal scores is computable,
which is what makes the synthesis stage gradeable without human labels.

This module is the single source of truth for those rules. ``orchestrator.py``
re-implements the verdict/conviction half of the same table when it overrides
the model's output; ``tests/test_evals_contracts.py`` asserts the two agree so
that editing the prompt without editing the code (or vice versa) fails CI.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Mapping, Optional

from pydantic import BaseModel, Field

# ── Signal weights (prompts/synthesis.md, Step 2) ──────────────────────────

SIGNAL_WEIGHTS: Dict[str, float] = {
    "earnings": 0.22,
    "pattern": 0.18,
    "risk": 0.17,
    "dcf": 0.17,
    "competitive": 0.14,
    "macro": 0.12,
}

SIGNAL_NAMES: tuple[str, ...] = tuple(SIGNAL_WEIGHTS)

#: Weights are specified as a complete partition of 1.0. When the macro agent is
#: disabled (``settings.enable_macro_agent``) the remaining weights sum to 0.88,
#: and the prompt gives the model no renormalisation rule. See docs/EVALS.md.
WEIGHT_SUM_TOLERANCE = 1e-6

# ── Macro regime adjustment (prompts/synthesis.md, Step 2) ─────────────────

ADVERSE_MACRO_THRESHOLD = -0.5
ADVERSE_MACRO_MULTIPLIER = 0.7

# ── Decision table (prompts/synthesis.md, Step 3) ──────────────────────────

STRONG_BUY_THRESHOLD = 0.60
BUY_THRESHOLD = 0.30
SELL_THRESHOLD = -0.30
STRONG_SELL_THRESHOLD = -0.60

HIGH_CONVICTION_THRESHOLD = 0.60
MEDIUM_CONVICTION_THRESHOLD = 0.30

VERDICTS = ("STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL")
CONVICTIONS = ("HIGH", "MEDIUM", "LOW")
SIZING_VALUES = (
    "1.5x_base_weight",
    "1.0x_base_weight",
    "0.5x_base_weight",
    "0x_no_position",
)

SIZING_FOR_VERDICT: Dict[str, str] = {
    "STRONG BUY": "1.5x_base_weight",
    "BUY": "1.0x_base_weight",
    "HOLD": "0x_no_position",
    "SELL": "1.0x_base_weight",
    "STRONG SELL": "1.5x_base_weight",
}

HEALTH_DIMENSIONS = (
    "valuation",
    "risk_profile",
    "earnings_quality",
    "competitive_position",
    "quantitative_signals",
    "macro_environment",
    "overall",
)

HEALTH_SCORE_MIN = 1
HEALTH_SCORE_MAX = 10

#: The synthesis prompt bans hedging ("No hedging language. No 'however' or
#: 'that said'."). Matched case-insensitively on word boundaries.
BANNED_HEDGES = (
    "however",
    "that said",
    "on the other hand",
)

REQUIRED_BRIEF_SECTIONS = (
    "Verdict & Price Target",
    "Bull Case",
    "Bear Case",
    "Key Catalyst",
    "Signal Conflicts",
)

# ── Risk parameters (prompts/synthesis.md, Step 5) ─────────────────────────

#: ``orchestrator.py`` rejects an LLM stop that sits on the wrong side of entry
#: or further than this fraction away, then substitutes a computed stop.
MAX_STOP_DISTANCE_PCT = 0.25
ATR_STOP_MULTIPLE = 2.0
FALLBACK_STOP_PCT = 0.08

#: ``orchestrator.py`` overwrites ``entry_price`` with the live quote whenever
#: the model's value drifts by more than this.
ENTRY_PRICE_DRIFT_TOLERANCE = 0.05

# ── Per-agent SIGNAL_SCORE contract (prompts/{dcf,earnings,...}.md) ────────

SIGNAL_SCORE_PATTERN = re.compile(
    r"^[ \t]*(?:\*\*)?SIGNAL_SCORE(?:\*\*)?[ \t]*:[ \t]*([+-]?\d*\.?\d+)[ \t]*$",
    re.MULTILINE,
)

SIGNAL_SCORE_MIN = -1.0
SIGNAL_SCORE_MAX = 1.0

#: Only these prompts instruct the agent to emit a terminal SIGNAL_SCORE.
#: ``risk``, ``pattern`` and ``macro`` do not, so the synthesis has to infer
#: those three scores from prose — 0.47 of the decision weight with no
#: mechanical anchor. See docs/EVALS.md.
SIGNAL_SCORE_REQUIRED_AGENTS = ("dcf", "earnings", "competitive")

EARNINGS_BREAKDOWN_KEYS = ("trajectory", "margins", "quality", "outlook")
EARNINGS_RED_FLAG_SEVERITIES = ("LOW", "MED", "HIGH")

# ── Pattern signal vector (prompts/pattern.md) ─────────────────────────────

#: ``prompts/pattern.md`` calls a composite at or above this magnitude
#: "actionable" and anything below it noise.
PATTERN_ACTIONABLE_THRESHOLD = 0.40

PATTERN_VECTOR_KEYS = (
    "sma_trend",
    "mean_reversion_z",
    "bollinger_pctb",
    "rsi",
    "obv_trend",
    "atr_regime",
)

PATTERN_DIRECTIONS = ("BUY", "SELL", "HOLD", "NEUTRAL")

#: Composite weights from ``prompts/pattern.md``. ``atr_regime`` is explicitly
#: a sizing input rather than a directional one and carries no weight.
PATTERN_WEIGHTS: Dict[str, float] = {
    "sma_trend": 0.25,
    "mean_reversion_z": 0.20,
    "bollinger_pctb": 0.20,
    "rsi": 0.15,
    "obv_trend": 0.20,
}

#: ``prompts/pattern.md``: the ATR signal "is NOT a directional signal — score
#: is always 0.0".
PATTERN_ATR_SCORE = 0.0

#: ``prompts/pattern.md``: a bearish SMA gate must raise this flag so that long
#: entries are suppressed downstream.
SMA_GATE_BEARISH_FLAG = "sma_gate_bearish"
SMA_GATE_BEARISH_THRESHOLD = -0.5

#: RSI score is ``(50 - rsi) / 50``, with an optional ±0.3 divergence
#: adjustment, so a compliant score can sit this far from the base formula.
RSI_DIVERGENCE_BONUS = 0.3


def pattern_composite(scores: Mapping[str, Optional[float]]) -> float:
    """Compute ``Σ(signal_score × weight)`` over the weighted pattern signals."""
    total = 0.0
    for name, weight in PATTERN_WEIGHTS.items():
        score = scores.get(name)
        if score is not None:
            total += float(score) * weight
    return round(total, 6)


def bollinger_score(pct_b: float) -> float:
    """``(0.5 - %B) × 2``, clamped to [-1, +1]."""
    return max(-1.0, min(1.0, (0.5 - pct_b) * 2))


def rsi_score(rsi: float) -> float:
    """``(50 - RSI) / 50``, clamped to [-1, +1], before any divergence bonus."""
    return max(-1.0, min(1.0, (50.0 - rsi) / 50.0))


# ── Derived decisions ──────────────────────────────────────────────────────


def verdict_for_score(weighted_score: float) -> str:
    """Map a weighted score to a verdict using the Step 3 threshold table."""
    if weighted_score >= STRONG_BUY_THRESHOLD:
        return "STRONG BUY"
    if weighted_score >= BUY_THRESHOLD:
        return "BUY"
    if weighted_score <= STRONG_SELL_THRESHOLD:
        return "STRONG SELL"
    if weighted_score <= SELL_THRESHOLD:
        return "SELL"
    return "HOLD"


def conviction_for_score(conviction_score: float) -> str:
    """Map ``abs(weighted_score)`` to a conviction label."""
    if conviction_score >= HIGH_CONVICTION_THRESHOLD:
        return "HIGH"
    if conviction_score >= MEDIUM_CONVICTION_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def weighted_score_for_signals(signals: Mapping[str, Optional[float]]) -> float:
    """
    Compute ``Σ(signal_score × weight)`` with the Step 2 macro regime adjustment.

    Signals absent from ``signals`` (or set to ``None``) contribute nothing;
    their weight is *not* redistributed, mirroring the prompt, which offers no
    renormalisation rule for a missing agent.
    """
    total = 0.0
    for name, weight in SIGNAL_WEIGHTS.items():
        score = signals.get(name)
        if score is None:
            continue
        total += float(score) * weight

    macro = signals.get("macro")
    if macro is not None and float(macro) <= ADVERSE_MACRO_THRESHOLD:
        total *= ADVERSE_MACRO_MULTIPLIER

    return round(total, 6)


class ExpectedDecision(BaseModel):
    """The decision the synthesis prompt's own procedure implies."""

    weighted_score: float
    conviction_score: float
    verdict: str
    conviction: str
    sizing_guidance: str

    @classmethod
    def from_signals(cls, signals: Mapping[str, Optional[float]]) -> "ExpectedDecision":
        weighted = weighted_score_for_signals(signals)
        conviction_score = round(abs(weighted), 6)
        verdict = verdict_for_score(weighted)
        return cls(
            weighted_score=weighted,
            conviction_score=conviction_score,
            verdict=verdict,
            conviction=conviction_for_score(conviction_score),
            sizing_guidance=SIZING_FOR_VERDICT[verdict],
        )


# ── Response contracts ─────────────────────────────────────────────────────


class SignalEntry(BaseModel):
    score: float = Field(ge=SIGNAL_SCORE_MIN, le=SIGNAL_SCORE_MAX)
    weight: float = Field(ge=0.0, le=1.0)


class StopLoss(BaseModel):
    value: float
    unit: str = "price"


class HealthScores(BaseModel):
    valuation: int = Field(ge=HEALTH_SCORE_MIN, le=HEALTH_SCORE_MAX)
    risk_profile: int = Field(ge=HEALTH_SCORE_MIN, le=HEALTH_SCORE_MAX)
    earnings_quality: int = Field(ge=HEALTH_SCORE_MIN, le=HEALTH_SCORE_MAX)
    competitive_position: int = Field(ge=HEALTH_SCORE_MIN, le=HEALTH_SCORE_MAX)
    quantitative_signals: int = Field(ge=HEALTH_SCORE_MIN, le=HEALTH_SCORE_MAX)
    macro_environment: int = Field(ge=HEALTH_SCORE_MIN, le=HEALTH_SCORE_MAX)
    overall: int = Field(ge=HEALTH_SCORE_MIN, le=HEALTH_SCORE_MAX)


class SynthesisVerdict(BaseModel):
    """
    Strict form of the JSON block described in ``prompts/synthesis.md`` Step 6.

    Production deliberately parses this leniently (``_extract_structured_block``
    tolerates trailing commas and returns a bare ``dict``), so this model is not
    wired into the request path. It exists to make "did the model honour the
    schema it was given" a measurable pass/fail rather than a downstream
    ``KeyError``.
    """

    verdict: str
    conviction: str
    conviction_score: float = Field(ge=0.0, le=1.0)
    time_horizon: str
    primary_horizon_days: int = Field(gt=0)
    signal_breakdown: Dict[str, SignalEntry]
    weighted_score: float = Field(ge=-1.0, le=1.0)
    prior_bull_probability: int = Field(ge=0, le=100)
    prior_bear_probability: int = Field(ge=0, le=100)
    entry_price: Optional[float] = None
    price_target: Optional[float] = None
    price_target_sources: Dict[str, Optional[float]] = Field(default_factory=dict)
    stop_loss: Optional[StopLoss] = None
    sizing_guidance: str
    review_triggers: list[str] = Field(default_factory=list)
    signal_conflicts: list[str] = Field(default_factory=list)
    health_scores: HealthScores

    model_config = {"extra": "allow"}


class EarningsVerdictBreakdown(BaseModel):
    trajectory: Optional[float] = Field(default=None, ge=-1.0, le=1.0)
    margins: Optional[float] = Field(default=None, ge=-1.0, le=1.0)
    quality: Optional[float] = Field(default=None, ge=-1.0, le=1.0)
    outlook: Optional[float] = Field(default=None, ge=-1.0, le=1.0)


class EarningsRedFlag(BaseModel):
    flag: str
    severity: str


class EarningsStructured(BaseModel):
    """Strict form of the D-mode block in ``prompts/earnings.md``."""

    accounting_quality: Dict[str, Any] = Field(default_factory=dict)
    earnings_trajectory: Dict[str, Any] = Field(default_factory=dict)
    red_flags: list[EarningsRedFlag] = Field(default_factory=list)
    verdict_breakdown: EarningsVerdictBreakdown

    model_config = {"extra": "allow"}


# ── Parsing helpers ────────────────────────────────────────────────────────


def parse_signal_scores(text: str) -> list[float]:
    """Return every ``SIGNAL_SCORE: X.XX`` value found in an agent's output."""
    return [float(m) for m in SIGNAL_SCORE_PATTERN.findall(text or "")]


def signal_scores_from_reports(reports: Iterable[Mapping[str, str]]) -> Dict[str, float]:
    """
    Map ``{signal_name: score}`` from fixture agent reports.

    Each report is a mapping with a ``signal`` key (one of :data:`SIGNAL_NAMES`)
    and a ``text`` body. Reports whose body carries no terminal SIGNAL_SCORE are
    omitted, which is the same thing the synthesis prompt tells the model to do:
    fall back to reading the prose.
    """
    scores: Dict[str, float] = {}
    for report in reports:
        name = str(report.get("signal", "")).strip().lower()
        if name not in SIGNAL_WEIGHTS:
            continue
        found = parse_signal_scores(str(report.get("text", "")))
        if found:
            scores[name] = found[-1]
    return scores
