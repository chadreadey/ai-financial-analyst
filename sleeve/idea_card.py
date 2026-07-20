"""
IdeaCard + DeskAction schemas (Phase 5 scaffolding).

Faithful to PLAN_LEVERED_CORE_AND_INTEL_FLOW §2.3:

    IdeaCard: source, published_at, tickers, direction, instrument,
              thesis (≤3 sentences, extracted not summarized),
              catalysts[{event, expected_date}], time_horizon,
              conviction_language (verbatim), entry_exit.

    DeskAction: open/adjust/close lifecycle keyed to prior IdeaCard.

Schema-only in this phase: no LLM extraction pipeline yet, no intel.db
writer. Callers construct these directly; the paper-sleeve book consumes
them. Production wiring (Gmail → n8n → extractor) lands later.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


class Instrument(str, Enum):
    EQUITY = "equity"
    CALL_SPREAD = "call_spread"
    PUT_SPREAD = "put_spread"
    IRON_CONDOR = "iron_condor"
    BUTTERFLY = "butterfly"
    NAKED_OPTION = "naked_option"  # rejected by validation; kept for detection


class LifecycleAction(str, Enum):
    OPEN = "open"
    ADJUST = "adjust"
    CLOSE = "close"


class Catalyst(BaseModel):
    event: str
    expected_date: Optional[date] = None


class EntryExit(BaseModel):
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    strikes: Optional[list[float]] = None
    expiry: Optional[date] = None


class IdeaCard(BaseModel):
    id: str
    source: str
    published_at: datetime
    tickers: list[str]
    direction: Direction
    instrument: Instrument
    thesis: str = Field(..., max_length=1000)
    catalysts: list[Catalyst] = Field(default_factory=list)
    time_horizon: Optional[str] = None
    conviction_language: Optional[str] = None
    entry_exit: Optional[EntryExit] = None

    @model_validator(mode="after")
    def _no_naked_options(self):
        if self.instrument == Instrument.NAKED_OPTION:
            raise ValueError(
                "Naked options are prohibited by the sleeve policy — use a defined-risk "
                "structure (call_spread/put_spread/iron_condor/butterfly)."
            )
        return self

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")


class DeskAction(BaseModel):
    idea_id: str
    action: LifecycleAction
    at: datetime
    notes: str = ""

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")
