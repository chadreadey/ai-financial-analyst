"""
Convexity sleeve (Phase 5 scaffolding).

Paper-only options-sleeve infrastructure per PLAN_LEVERED_CORE_AND_INTEL_FLOW
§1.3 and MEMO_2026_07_13_LEAN_QUANT_STRONG_AI Phase 5. Defined-risk
structures only, hard caps, sleeve-level circuit breakers. No live money
until >= 1 quarter of tracked-idea outperformance per the source-accuracy
tracker.
"""

from sleeve.idea_card import DeskAction, IdeaCard
from sleeve.paper_sleeve import (
    PaperSleeve,
    Position,
    SleeveConfig,
    SleeveHalted,
)

__all__ = [
    "DeskAction",
    "IdeaCard",
    "PaperSleeve",
    "Position",
    "SleeveConfig",
    "SleeveHalted",
]
