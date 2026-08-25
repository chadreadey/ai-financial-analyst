"""
Portfolio Construction Agent (Phase 2 of PLAN_LEAN_QUANT_STRONG_AI).

Consumes the screener's top-N candidate list (from `quant.screener`) plus
optional per-ticker analyst notes and returns a portfolio: which tickers
to hold, with what target weights.

This agent is the *decision layer* in the lean-quant / strong-AI split:
the quant screener does the ranking, agents do the selection. Success is
measured as AI-augmented Sharpe minus quant-only Sharpe (Phase 3).

Design decisions:
- Structured JSON response with a lightweight schema — no free-form prose
  is scoreable in the phase-3 eval.
- Live LLM path uses the same LLMProvider abstraction as the other agents.
- Deterministic fallback (`select_deterministic`) mirrors the LLM prompt's
  intent so historical replay and testing are cheap.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from llm import LLMProvider, get_provider

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are the Portfolio Construction agent for a lean-quant, strong-AI equity
strategy. A screener has already narrowed the investable universe to a
top-N candidate list using IC-validated fundamental signals (QMJ, SUE, ERM).
Your job is to pick the FINAL portfolio from that list.

Constraints:
- Hold N_POSITIONS names (default 10), long-only, equal-weight unless a
  strong reason to deviate.
- Respect sector diversification: no more than MAX_PER_SECTOR positions
  from a single GICS sector.
- Never invent tickers not in the candidate list.
- If fewer than N_POSITIONS candidates meet a minimum quality bar, hold
  cash for the remainder (report `n_positions` < N and non-zero `cash_weight`).

Return ONLY a JSON object with this schema:
{
  "picks": [
    {"ticker": "AAPL", "weight": 0.10, "rationale": "<1-sentence why>"},
    ...
  ],
  "cash_weight": 0.0,
  "reasoning": "<2-4 sentences on portfolio construction logic>",
  "risk_notes": "<any concentration or macro risks>"
}
Weights sum (picks + cash_weight) must equal 1.0 within 0.01.
"""


@dataclass
class Pick:
    ticker: str
    weight: float
    rationale: str = ""


@dataclass
class Portfolio:
    picks: list[Pick]
    cash_weight: float = 0.0
    reasoning: str = ""
    risk_notes: str = ""
    raw: Optional[dict[str, Any]] = None
    source: str = "heuristic"  # 'heuristic', 'llm', 'fallback'

    def to_dict(self) -> dict:
        return {
            "picks": [
                {"ticker": p.ticker, "weight": round(p.weight, 6), "rationale": p.rationale}
                for p in self.picks
            ],
            "cash_weight": round(self.cash_weight, 6),
            "reasoning": self.reasoning,
            "risk_notes": self.risk_notes,
            "source": self.source,
        }


def _normalize_weights(picks: list[Pick], cash_weight: float = 0.0) -> tuple[list[Pick], float]:
    total = sum(max(p.weight, 0.0) for p in picks) + max(cash_weight, 0.0)
    if total <= 0:
        n = len(picks)
        if n == 0:
            return [], 1.0
        w = (1.0 - max(cash_weight, 0.0)) / n
        return [Pick(p.ticker, w, p.rationale) for p in picks], max(cash_weight, 0.0)
    picks = [Pick(p.ticker, max(p.weight, 0.0) / total, p.rationale) for p in picks]
    return picks, max(cash_weight, 0.0) / total


def select_deterministic(
    candidates: list[dict],
    n_positions: int = 10,
    max_per_sector: int = 4,
    min_composite: float = 0.0,
) -> Portfolio:
    """
    Heuristic PC agent: picks top-N by composite, respects sector cap.

    Used for historical replay (no LLM cost) and as an LLM-call fallback.
    """
    picks: list[Pick] = []
    sector_counts: dict[str, int] = {}
    for cand in candidates:
        composite = float(cand.get("composite", 0.0))
        if composite < min_composite:
            continue
        sector = cand.get("sector", "Unknown")
        if sector_counts.get(sector, 0) >= max_per_sector:
            continue
        picks.append(
            Pick(
                ticker=cand["ticker"],
                weight=1.0 / n_positions,
                rationale=f"screener composite {composite:.3f} (sector {sector})",
            )
        )
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        if len(picks) >= n_positions:
            break

    cash_weight = 0.0
    if len(picks) < n_positions:
        cash_weight = (n_positions - len(picks)) / n_positions

    picks, cash_weight = _normalize_weights(picks, cash_weight)
    return Portfolio(
        picks=picks,
        cash_weight=cash_weight,
        reasoning=(
            f"Deterministic top-{len(picks)} pick by screener composite with "
            f"max_per_sector={max_per_sector} enforced. Cash held for unfilled slots."
        ),
        risk_notes=(
            f"Sector concentrations: {dict(sector_counts)}. No qualitative overlay applied."
            if sector_counts
            else "No positions taken — all candidates below min_composite floor."
        ),
        source="heuristic",
    )


def _extract_json(text: str) -> Optional[dict]:
    """Extract the first well-formed JSON object from a model response."""
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _parse_llm_response(raw: dict, candidates: list[dict]) -> Portfolio:
    valid_tickers = {c["ticker"] for c in candidates}
    picks: list[Pick] = []
    for entry in raw.get("picks", []):
        if not isinstance(entry, dict):
            continue
        ticker = entry.get("ticker")
        if ticker not in valid_tickers:
            logger.warning("LLM invented ticker %s — dropping", ticker)
            continue
        try:
            weight = float(entry.get("weight", 0.0))
        except (TypeError, ValueError):
            weight = 0.0
        picks.append(Pick(ticker=ticker, weight=weight, rationale=entry.get("rationale", "")))

    try:
        cash_weight = float(raw.get("cash_weight", 0.0))
    except (TypeError, ValueError):
        cash_weight = 0.0

    picks, cash_weight = _normalize_weights(picks, cash_weight)
    return Portfolio(
        picks=picks,
        cash_weight=cash_weight,
        reasoning=str(raw.get("reasoning", "")),
        risk_notes=str(raw.get("risk_notes", "")),
        raw=raw,
        source="llm",
    )


@dataclass
class PortfolioConstructionAgent:
    """LLM-backed PC agent for production/live paths."""

    provider: Optional[LLMProvider] = None
    model: Optional[str] = None
    max_tokens: int = 4000
    n_positions: int = 10
    max_per_sector: int = 4
    min_composite: float = 0.0

    def __post_init__(self):
        if self.provider is None:
            self.provider = get_provider()
        if self.model is None:
            self.model = self.provider.default_model

    def _system_prompt(self) -> str:
        return SYSTEM_PROMPT.replace("N_POSITIONS", str(self.n_positions)).replace(
            "MAX_PER_SECTOR", str(self.max_per_sector)
        )

    def _build_user_prompt(
        self,
        candidates: list[dict],
        analyst_notes: Optional[dict[str, str]] = None,
    ) -> str:
        analyst_notes = analyst_notes or {}
        lines = [
            f"Rebalance candidates ({len(candidates)} names, screener-ranked):",
            "",
        ]
        for c in candidates:
            contribs = c.get("contributions", {})
            contrib_str = ", ".join(f"{k.split('_')[0]}={v:+.2f}" for k, v in contribs.items())
            lines.append(
                f"- {c['ticker']} [{c.get('sector', '?')}] composite={c.get('composite', 0):.3f} "
                f"({contrib_str})"
            )
            note = analyst_notes.get(c["ticker"])
            if note:
                trimmed = note.strip().replace("\n", " ")[:400]
                lines.append(f"    analyst: {trimmed}")
        lines.append("")
        lines.append(
            f"Choose your final {self.n_positions}-position portfolio. Respond with the JSON only."
        )
        return "\n".join(lines)

    async def select(
        self,
        candidates: list[dict],
        analyst_notes: Optional[dict[str, str]] = None,
    ) -> Portfolio:
        if not candidates:
            return Portfolio(picks=[], cash_weight=1.0, source="fallback")

        system = self._system_prompt()
        user = self._build_user_prompt(candidates, analyst_notes)

        try:
            raw_text = await self.provider.generate(
                system=system,
                user=user,
                model=self.model,
                max_tokens=self.max_tokens,
            )
        except Exception as exc:
            logger.warning("PC agent LLM call failed (%s) — falling back to heuristic", exc)
            portfolio = select_deterministic(
                candidates,
                n_positions=self.n_positions,
                max_per_sector=self.max_per_sector,
                min_composite=self.min_composite,
            )
            portfolio.source = "fallback"
            return portfolio

        parsed = _extract_json(raw_text)
        if parsed is None:
            logger.warning("PC agent returned non-JSON — falling back to heuristic")
            portfolio = select_deterministic(
                candidates,
                n_positions=self.n_positions,
                max_per_sector=self.max_per_sector,
                min_composite=self.min_composite,
            )
            portfolio.source = "fallback"
            return portfolio

        return _parse_llm_response(parsed, candidates)
