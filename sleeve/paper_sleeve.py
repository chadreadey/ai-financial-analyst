"""
Paper convexity sleeve — position book with hard caps and circuit breakers.

Enforces the §1.3 policy from PLAN_LEVERED_CORE_AND_INTEL_FLOW:

- Defined-risk structures only. `open_position` rejects naked_option via
  the IdeaCard schema and additionally requires a positive `max_loss`.
- Sleeve size starts at ≤5% NAV; step-up rule tracked externally.
- Max loss per trade ≤ 1% of NAV.
- Sleeve halts at −10% sleeve drawdown → all opens rejected until reset.
- Every position links back to an IdeaCard.id (idea provenance).
- Separate accounting: own P&L, own DD.

Paper-only: no broker integration here; a production layer wraps this book.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sleeve.idea_card import IdeaCard, Instrument

logger = logging.getLogger(__name__)


class SleeveHalted(RuntimeError):
    """Raised when a `open_position` is attempted while the sleeve is halted."""


@dataclass
class SleeveConfig:
    initial_nav: float = 100_000.0
    max_sleeve_capital_pct: float = 0.05
    max_loss_per_trade_pct: float = 0.01
    sleeve_halt_drawdown_pct: float = 0.10
    allowed_instruments: tuple = (
        Instrument.CALL_SPREAD,
        Instrument.PUT_SPREAD,
        Instrument.IRON_CONDOR,
        Instrument.BUTTERFLY,
    )


@dataclass
class Position:
    id: str
    idea_id: str
    instrument: Instrument
    tickers: list[str]
    entry_at: datetime
    max_loss: float
    max_profit: float
    entry_debit: float
    pnl_realized: float = 0.0
    pnl_unrealized: float = 0.0
    closed_at: Optional[datetime] = None
    close_reason: str = ""

    @property
    def is_open(self) -> bool:
        return self.closed_at is None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "idea_id": self.idea_id,
            "instrument": self.instrument.value,
            "tickers": self.tickers,
            "entry_at": self.entry_at.isoformat(),
            "max_loss": self.max_loss,
            "max_profit": self.max_profit,
            "entry_debit": self.entry_debit,
            "pnl_realized": self.pnl_realized,
            "pnl_unrealized": self.pnl_unrealized,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "close_reason": self.close_reason,
        }


@dataclass
class PaperSleeve:
    config: SleeveConfig = field(default_factory=SleeveConfig)
    nav: float = 100_000.0
    sleeve_cash: float = 0.0
    positions: list[Position] = field(default_factory=list)
    ideas: dict[str, IdeaCard] = field(default_factory=dict)
    halted: bool = False
    halt_reason: Optional[str] = None
    peak_sleeve_equity: float = 0.0
    _next_position_id: int = 1

    def __post_init__(self):
        if self.sleeve_cash == 0.0:
            self.sleeve_cash = self.nav * self.config.max_sleeve_capital_pct
        if self.peak_sleeve_equity == 0.0:
            self.peak_sleeve_equity = self.sleeve_cash

    def _check_open(self, idea: IdeaCard, max_loss: float) -> None:
        if self.halted:
            raise SleeveHalted(f"Sleeve halted: {self.halt_reason}")
        if max_loss <= 0:
            raise ValueError("max_loss must be positive (defined-risk requirement)")
        loss_cap = self.nav * self.config.max_loss_per_trade_pct
        if max_loss > loss_cap:
            raise ValueError(
                f"max_loss {max_loss:.2f} exceeds per-trade cap "
                f"{loss_cap:.2f} ({self.config.max_loss_per_trade_pct * 100}% NAV)"
            )
        if idea.instrument not in self.config.allowed_instruments:
            raise ValueError(
                f"Instrument {idea.instrument.value} not in allowed set "
                f"{[i.value for i in self.config.allowed_instruments]}"
            )

    def register_idea(self, idea: IdeaCard) -> None:
        self.ideas[idea.id] = idea

    def open_position(
        self,
        idea: IdeaCard,
        max_loss: float,
        max_profit: float,
        entry_debit: float,
        entry_at: Optional[datetime] = None,
    ) -> Position:
        self._check_open(idea, max_loss)
        self.register_idea(idea)
        pos = Position(
            id=f"pos_{self._next_position_id}",
            idea_id=idea.id,
            instrument=idea.instrument,
            tickers=list(idea.tickers),
            entry_at=entry_at or datetime.utcnow(),
            max_loss=max_loss,
            max_profit=max_profit,
            entry_debit=entry_debit,
        )
        self._next_position_id += 1
        self.positions.append(pos)
        self.sleeve_cash -= entry_debit
        self._recompute_peak()
        return pos

    def mark_to_market(self, position_id: str, pnl_unrealized: float) -> None:
        pos = self._get(position_id)
        pos.pnl_unrealized = pnl_unrealized
        self._check_sleeve_drawdown()

    def close_position(
        self,
        position_id: str,
        pnl_realized: float,
        reason: str = "target",
        closed_at: Optional[datetime] = None,
    ) -> Position:
        pos = self._get(position_id)
        if not pos.is_open:
            raise ValueError(f"Position {position_id} already closed")
        pos.pnl_realized = pnl_realized
        pos.pnl_unrealized = 0.0
        pos.closed_at = closed_at or datetime.utcnow()
        pos.close_reason = reason
        self.sleeve_cash += pos.entry_debit + pnl_realized
        self._check_sleeve_drawdown()
        return pos

    def sleeve_equity(self) -> float:
        return self.sleeve_cash + sum(p.pnl_unrealized for p in self.positions if p.is_open)

    def realized_pnl(self) -> float:
        return sum(p.pnl_realized for p in self.positions if not p.is_open)

    def unrealized_pnl(self) -> float:
        return sum(p.pnl_unrealized for p in self.positions if p.is_open)

    def sleeve_drawdown_pct(self) -> float:
        if self.peak_sleeve_equity <= 0:
            return 0.0
        cur = self.sleeve_equity()
        if cur >= self.peak_sleeve_equity:
            return 0.0
        return (self.peak_sleeve_equity - cur) / self.peak_sleeve_equity

    def _recompute_peak(self) -> None:
        eq = self.sleeve_equity()
        if eq > self.peak_sleeve_equity:
            self.peak_sleeve_equity = eq

    def _check_sleeve_drawdown(self) -> None:
        self._recompute_peak()
        dd = self.sleeve_drawdown_pct()
        if dd >= self.config.sleeve_halt_drawdown_pct and not self.halted:
            self.halted = True
            self.halt_reason = (
                f"Sleeve drawdown {dd * 100:.1f}% ≥ halt threshold "
                f"{self.config.sleeve_halt_drawdown_pct * 100:.1f}%"
            )
            logger.warning("SLEEVE HALTED: %s", self.halt_reason)

    def reset_halt(self, reason: str) -> None:
        """Manual override — caller records rationale."""
        self.halted = False
        self.halt_reason = None
        logger.info("Sleeve halt reset: %s", reason)

    def _get(self, position_id: str) -> Position:
        for p in self.positions:
            if p.id == position_id:
                return p
        raise KeyError(f"Position {position_id} not found")

    def to_json(self) -> str:
        return json.dumps(
            {
                "config": {
                    "initial_nav": self.config.initial_nav,
                    "max_sleeve_capital_pct": self.config.max_sleeve_capital_pct,
                    "max_loss_per_trade_pct": self.config.max_loss_per_trade_pct,
                    "sleeve_halt_drawdown_pct": self.config.sleeve_halt_drawdown_pct,
                    "allowed_instruments": [i.value for i in self.config.allowed_instruments],
                },
                "nav": self.nav,
                "sleeve_cash": self.sleeve_cash,
                "peak_sleeve_equity": self.peak_sleeve_equity,
                "halted": self.halted,
                "halt_reason": self.halt_reason,
                "positions": [p.to_dict() for p in self.positions],
                "ideas": {k: v.to_dict() for k, v in self.ideas.items()},
                "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
            },
            indent=2,
            default=str,
        )
