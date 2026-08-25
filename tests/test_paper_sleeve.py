"""Tests for the paper convexity sleeve (Phase 5 scaffolding)."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from sleeve.idea_card import (
    Catalyst,
    DeskAction,
    Direction,
    EntryExit,
    IdeaCard,
    Instrument,
    LifecycleAction,
)
from sleeve.paper_sleeve import PaperSleeve, SleeveConfig, SleeveHalted


def _mk_idea(instrument: Instrument = Instrument.CALL_SPREAD, id_: str = "idea-1") -> IdeaCard:
    return IdeaCard(
        id=id_,
        source="test_desk",
        published_at=datetime(2024, 1, 15, 10, 0, 0),
        tickers=["AAPL"],
        direction=Direction.LONG,
        instrument=instrument,
        thesis="Post-earnings drift setup with defined-risk upside.",
        catalysts=[Catalyst(event="AAPL Q1 earnings", expected_date=date(2024, 2, 1))],
        time_horizon="1m",
        conviction_language="watchlist — modest size",
        entry_exit=EntryExit(strikes=[180.0, 190.0], expiry=date(2024, 2, 16)),
    )


class TestIdeaCardValidation:
    def test_valid_card_serializes(self):
        card = _mk_idea()
        d = card.to_dict()
        assert d["source"] == "test_desk"
        assert d["instrument"] == "call_spread"

    def test_naked_options_rejected(self):
        with pytest.raises(ValidationError):
            _mk_idea(instrument=Instrument.NAKED_OPTION)

    def test_thesis_length_capped(self):
        long_thesis = "x" * 1500
        with pytest.raises(ValidationError):
            IdeaCard(
                id="i",
                source="s",
                published_at=datetime(2024, 1, 15),
                tickers=["AAPL"],
                direction=Direction.LONG,
                instrument=Instrument.CALL_SPREAD,
                thesis=long_thesis,
            )


class TestDeskAction:
    def test_lifecycle_serializes(self):
        da = DeskAction(
            idea_id="idea-1",
            action=LifecycleAction.OPEN,
            at=datetime(2024, 1, 16),
            notes="entered per plan",
        )
        d = da.to_dict()
        assert d["action"] == "open"
        assert d["notes"] == "entered per plan"


class TestPaperSleeveOpen:
    def test_open_succeeds_within_caps(self):
        s = PaperSleeve(nav=100_000.0)
        idea = _mk_idea()
        pos = s.open_position(idea, max_loss=500.0, max_profit=1500.0, entry_debit=500.0)
        assert pos.is_open
        assert len(s.positions) == 1
        expected_cash = 100_000 * s.config.max_sleeve_capital_pct - 500.0
        assert s.sleeve_cash == pytest.approx(expected_cash)

    def test_open_rejects_disallowed_instrument(self):
        s = PaperSleeve(
            nav=100_000.0, config=SleeveConfig(allowed_instruments=(Instrument.PUT_SPREAD,))
        )
        idea = _mk_idea(instrument=Instrument.CALL_SPREAD)
        with pytest.raises(ValueError, match="not in allowed set"):
            s.open_position(idea, max_loss=500.0, max_profit=1500.0, entry_debit=500.0)

    def test_open_rejects_excess_loss(self):
        s = PaperSleeve(nav=100_000.0)
        idea = _mk_idea()
        with pytest.raises(ValueError, match="exceeds per-trade cap"):
            s.open_position(idea, max_loss=1500.0, max_profit=3000.0, entry_debit=1500.0)

    def test_open_rejects_zero_or_negative_max_loss(self):
        s = PaperSleeve(nav=100_000.0)
        idea = _mk_idea()
        with pytest.raises(ValueError, match="defined-risk"):
            s.open_position(idea, max_loss=0.0, max_profit=1500.0, entry_debit=100.0)


class TestPaperSleeveClose:
    def test_close_updates_pnl_and_cash(self):
        s = PaperSleeve(nav=100_000.0)
        idea = _mk_idea()
        pos = s.open_position(idea, max_loss=500.0, max_profit=1500.0, entry_debit=500.0)
        closed = s.close_position(pos.id, pnl_realized=800.0, reason="target")
        assert not closed.is_open
        assert s.sleeve_cash == pytest.approx(5_000 + 800)
        assert s.realized_pnl() == 800.0

    def test_double_close_raises(self):
        s = PaperSleeve()
        idea = _mk_idea()
        pos = s.open_position(idea, max_loss=500.0, max_profit=1500.0, entry_debit=500.0)
        s.close_position(pos.id, pnl_realized=100.0)
        with pytest.raises(ValueError):
            s.close_position(pos.id, pnl_realized=50.0)


class TestSleeveDrawdownHalt:
    def test_halt_triggers_at_10pct_dd(self):
        s = PaperSleeve(nav=100_000.0)
        idea = _mk_idea()
        pos = s.open_position(idea, max_loss=1000.0, max_profit=2000.0, entry_debit=1000.0)
        assert not s.halted
        s.mark_to_market(pos.id, pnl_unrealized=-1000.0)
        assert s.halted

    def test_open_rejected_after_halt(self):
        s = PaperSleeve(nav=100_000.0)
        idea1 = _mk_idea(id_="idea-1")
        p1 = s.open_position(idea1, max_loss=1000.0, max_profit=2000.0, entry_debit=1000.0)
        s.mark_to_market(p1.id, pnl_unrealized=-1000.0)
        idea2 = _mk_idea(id_="idea-2")
        with pytest.raises(SleeveHalted):
            s.open_position(idea2, max_loss=500.0, max_profit=1500.0, entry_debit=500.0)

    def test_manual_halt_reset(self):
        s = PaperSleeve(nav=100_000.0)
        idea = _mk_idea()
        pos = s.open_position(idea, max_loss=1000.0, max_profit=2000.0, entry_debit=1000.0)
        s.mark_to_market(pos.id, pnl_unrealized=-1000.0)
        assert s.halted
        s.reset_halt(reason="post-mortem complete; positions closed manually")
        assert not s.halted


class TestCreditSpreadAccounting:
    """
    Credit-spread P&L convention lock-in (P0 fix from PR #15 review).

    Convention: pnl_realized is TOTAL trade P&L (final cash − initial cash),
    NOT incremental cash at close. Cash flow at open uses -entry_debit;
    at close uses +entry_debit + pnl_realized.
    """

    def test_credit_spread_expires_worthless(self):
        s = PaperSleeve(nav=100_000.0)
        idea = _mk_idea(instrument=Instrument.PUT_SPREAD)
        pos = s.open_position(idea, max_loss=800.0, max_profit=200.0, entry_debit=-200.0)
        assert s.sleeve_cash == pytest.approx(5_200)
        s.close_position(pos.id, pnl_realized=200.0, reason="expired_worthless")
        assert s.sleeve_cash == pytest.approx(5_200)

    def test_credit_spread_max_loss(self):
        s = PaperSleeve(nav=100_000.0)
        idea = _mk_idea(instrument=Instrument.PUT_SPREAD)
        pos = s.open_position(idea, max_loss=800.0, max_profit=200.0, entry_debit=-200.0)
        assert s.sleeve_cash == pytest.approx(5_200)
        s.close_position(pos.id, pnl_realized=-800.0, reason="max_loss")
        assert s.sleeve_cash == pytest.approx(4_200)

    def test_debit_gt_max_loss_rejected(self):
        s = PaperSleeve(nav=100_000.0)
        idea = _mk_idea()
        with pytest.raises(ValueError, match="contradicts the defined-risk claim"):
            s.open_position(idea, max_loss=300.0, max_profit=700.0, entry_debit=500.0)

    def test_negative_max_profit_rejected(self):
        s = PaperSleeve(nav=100_000.0)
        idea = _mk_idea()
        with pytest.raises(ValueError, match="max_profit must be non-negative"):
            s.open_position(idea, max_loss=500.0, max_profit=-100.0, entry_debit=500.0)


class TestPersistence:
    def test_to_json_roundtrippable_shape(self):
        s = PaperSleeve(nav=100_000.0)
        idea = _mk_idea()
        s.open_position(idea, max_loss=500.0, max_profit=1500.0, entry_debit=500.0)
        import json

        payload = json.loads(s.to_json())
        assert "config" in payload
        assert payload["positions"][0]["max_loss"] == 500.0
        assert "idea-1" in payload["ideas"]
