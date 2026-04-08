"""
Canonical scoring thresholds and direction classification.

Single source of truth for BUY/SELL/HOLD boundaries and actionable gates.
All signal blend functions call reclassify() after updating composite_score.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quant.signals import SignalVector

# ── Thresholds ───────────────────────────────────────────────────────────
BUY_THRESHOLD = 0.30
SELL_THRESHOLD = -0.30
ACTIONABLE_THRESHOLD = 0.40


def classify_direction(composite_score: float) -> tuple[str, bool]:
    """Classify a composite score into direction and actionable flag.

    Returns:
        (direction, actionable) where direction is "BUY", "SELL", or "HOLD".
    """
    if composite_score >= BUY_THRESHOLD:
        direction = "BUY"
    elif composite_score <= SELL_THRESHOLD:
        direction = "SELL"
    else:
        direction = "HOLD"
    actionable = abs(composite_score) >= ACTIONABLE_THRESHOLD
    return direction, actionable


def reclassify(sv: SignalVector) -> None:
    """Update composite_direction and actionable on a SignalVector in place."""
    sv.composite_direction, sv.actionable = classify_direction(sv.composite_score)
