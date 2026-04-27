"""
Test invariants of the IC-weighted earnings sub-blend.

Source: docs/audit/session-2/ic-summary.md
Spec: re-weight ERM / SUE / analyst_dispersion using IC findings with
      50% shrinkage toward equal weight.

Invariants:
  1. Weights sum to 1.0 (within float tolerance)
  2. ERM weight > SUE weight (since ERM has higher mean IC at every horizon)
  3. Dispersion weight ≤ 0.10 (effectively dropped per audit verdict —
     wrong-sign IC at every horizon, |3M t|<1.0)
"""

from __future__ import annotations

import math

import pytest

from quant.earnings_signals import EARNINGS_BLEND_WEIGHTS


def test_weights_sum_to_one():
    """Sum of all sub-signal weights must equal 1.0 (within fp tolerance)."""
    total = sum(EARNINGS_BLEND_WEIGHTS.values())
    assert math.isclose(total, 1.0, abs_tol=1e-6), (
        f"earnings sub-blend weights must sum to 1.0, got {total}"
    )


def test_erm_weight_exceeds_sue_weight():
    """ERM dominates SUE — its mean IC is ~2x larger across 1M/3M/6M."""
    w_erm = EARNINGS_BLEND_WEIGHTS["erm"]
    w_sue = EARNINGS_BLEND_WEIGHTS["sue"]
    assert w_erm > w_sue, (
        f"ERM weight ({w_erm}) must exceed SUE weight ({w_sue}) — "
        "ERM has higher mean IC at every horizon."
    )


def test_dispersion_weight_effectively_dropped():
    """
    Analyst dispersion is below the |t|>=1.0 threshold and has wrong-sign
    IC at every horizon — so it must be effectively dropped (≤ 0.10) but
    NOT deleted, so the code path stays live for divergence-as-signal
    follow-ups in Session 3.
    """
    w_disp = EARNINGS_BLEND_WEIGHTS["analyst_dispersion"]
    assert w_disp <= 0.10, (
        f"analyst_dispersion weight ({w_disp}) must be <= 0.10 "
        "(wrong-sign at every horizon, |3M t|<1.0)."
    )
    # And we keep it nonzero (per user direction: don't delete the path).
    assert w_disp > 0.0, (
        "analyst_dispersion weight must remain > 0 — code path is kept "
        "live so the signal can be recomputed and so divergence between "
        "dispersion and ERM/SUE remains observable."
    )


def test_only_three_signals_in_blend():
    """The blend covers exactly the three earnings sub-signals."""
    assert set(EARNINGS_BLEND_WEIGHTS) == {"erm", "sue", "analyst_dispersion"}


def test_all_weights_nonnegative():
    """No sub-signal should carry negative weight (signed IC penalty is
    handled by zeroing/floor at the math step, not by negative weights)."""
    for k, v in EARNINGS_BLEND_WEIGHTS.items():
        assert v >= 0.0, f"weight for {k} is negative: {v}"
