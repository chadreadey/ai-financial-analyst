"""
Three-series eval (Phase 3 of PLAN_LEAN_QUANT_STRONG_AI).

Builds three parallel return series to attribute where the AI stack earns
its complexity:

    SPY               — passive benchmark
    Quant-only        — top-10 from the screener's candidate list at each
                        rebalance (equal-weight, ≤max_per_sector, no AI)
    AI-augmented      — Portfolio Construction agent's picks (from
                        runs/ai_picks/*.json) — 10 chosen from the top-50

The attribution number that matters is `AI Sharpe − Quant Sharpe`. If it
is positive with the AI cost accounted for, agents earn their keep;
otherwise they're expensive quant equivalents.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

from quant.metrics import (
    compute_annual_return,
    compute_max_drawdown,
    compute_sharpe,
    compute_sortino,
)

logger = logging.getLogger(__name__)


@dataclass
class Portfolio:
    """One rebalance snapshot: ticker → target weight, plus cash buffer."""

    date: pd.Timestamp
    weights: dict[str, float]
    cash_weight: float = 0.0

    def normalized(self) -> "Portfolio":
        total = sum(max(w, 0.0) for w in self.weights.values()) + max(self.cash_weight, 0.0)
        if total <= 0:
            return Portfolio(self.date, {}, 1.0)
        return Portfolio(
            self.date,
            {t: max(w, 0.0) / total for t, w in self.weights.items()},
            max(self.cash_weight, 0.0) / total,
        )


@dataclass
class SeriesResult:
    name: str
    daily_returns: pd.Series
    equity_curve: pd.Series
    metrics: dict = field(default_factory=dict)


def _compute_metrics(daily_returns: pd.Series, initial_capital: float = 100_000.0) -> dict:
    if len(daily_returns) == 0:
        return {}
    equity = (1 + daily_returns).cumprod() * initial_capital
    equity.index = daily_returns.index
    return {
        "sharpe": compute_sharpe(daily_returns),
        "sortino": compute_sortino(daily_returns),
        "annual_return_pct": compute_annual_return(equity, initial_capital),
        "max_drawdown_pct": compute_max_drawdown(equity),
        "total_return_pct": round(float(equity.iloc[-1] / initial_capital - 1) * 100, 2),
        "n_days": int(len(daily_returns)),
        "start": daily_returns.index[0].date().isoformat(),
        "end": daily_returns.index[-1].date().isoformat(),
    }


def _daily_returns_for_holding(
    portfolio: Portfolio,
    next_rebalance: Optional[pd.Timestamp],
    prices: dict[str, pd.DataFrame],
) -> pd.Series:
    """Weighted daily return series while `portfolio` is held."""
    port = portfolio.normalized()
    if not port.weights:
        return pd.Series(dtype=float)

    daily: dict[str, pd.Series] = {}
    for ticker, w in port.weights.items():
        df = prices.get(ticker)
        if df is None or len(df) == 0:
            continue
        mask = df.index > portfolio.date
        if next_rebalance is not None:
            mask &= df.index <= next_rebalance
        window = df[mask]
        if len(window) < 1:
            continue
        entry_price_slice = df[df.index <= portfolio.date]
        if entry_price_slice.empty:
            continue
        entry_close = float(entry_price_slice.iloc[-1]["close"])
        if entry_close <= 0:
            continue
        prev = pd.concat(
            [
                pd.Series({portfolio.date: entry_close}),
                window["close"].astype(float),
            ]
        )
        rets = prev.pct_change().dropna()
        daily[ticker] = rets * w

    if not daily:
        return pd.Series(dtype=float)

    combined = pd.DataFrame(daily).fillna(0.0)
    return combined.sum(axis=1)


def build_series(
    name: str,
    portfolios_by_date: dict[pd.Timestamp, Portfolio],
    prices: dict[str, pd.DataFrame],
) -> SeriesResult:
    dates = sorted(portfolios_by_date.keys())
    parts: list[pd.Series] = []
    for i, d in enumerate(dates):
        next_d = dates[i + 1] if i + 1 < len(dates) else None
        rets = _daily_returns_for_holding(portfolios_by_date[d], next_d, prices)
        parts.append(rets)
    if not parts:
        empty = pd.Series(dtype=float)
        return SeriesResult(name=name, daily_returns=empty, equity_curve=empty, metrics={})
    daily = pd.concat(parts).sort_index()
    daily = daily[~daily.index.duplicated(keep="first")]
    equity = (1 + daily).cumprod()
    metrics = _compute_metrics(daily)
    return SeriesResult(name=name, daily_returns=daily, equity_curve=equity, metrics=metrics)


def build_spy_series(
    spy_df: pd.DataFrame,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> SeriesResult:
    mask = (spy_df.index > start_date) & (spy_df.index <= end_date)
    window = spy_df[mask]
    daily = window["close"].astype(float).pct_change().dropna()
    equity = (1 + daily).cumprod()
    metrics = _compute_metrics(daily) if len(daily) else {}
    return SeriesResult(name="SPY", daily_returns=daily, equity_curve=equity, metrics=metrics)


def portfolios_from_candidate_lists(
    candidate_files: dict[str, dict],
    n_positions: int = 10,
    max_per_sector: int = 4,
) -> dict[pd.Timestamp, Portfolio]:
    """Quant-only portfolio series: top-N candidates equal-weight w/ sector cap."""
    out: dict[pd.Timestamp, Portfolio] = {}
    for date_str, payload in candidate_files.items():
        cands = payload.get("candidates", [])
        picks: list[dict] = []
        sec_counts: dict[str, int] = {}
        for c in cands:
            sec = c.get("sector", "Unknown")
            if sec_counts.get(sec, 0) >= max_per_sector:
                continue
            picks.append(c)
            sec_counts[sec] = sec_counts.get(sec, 0) + 1
            if len(picks) >= n_positions:
                break
        weights = {c["ticker"]: 1.0 / len(picks) for c in picks} if picks else {}
        cash_w = 0.0 if picks else 1.0
        out[pd.Timestamp(date_str)] = Portfolio(
            pd.Timestamp(date_str), weights=weights, cash_weight=cash_w
        )
    return out


def portfolios_from_ai_picks(ai_pick_files: dict[str, dict]) -> dict[pd.Timestamp, Portfolio]:
    out: dict[pd.Timestamp, Portfolio] = {}
    for date_str, payload in ai_pick_files.items():
        port_data = payload.get("portfolio", {})
        picks = port_data.get("picks", [])
        weights = {p["ticker"]: float(p["weight"]) for p in picks}
        cash_w = float(port_data.get("cash_weight", 0.0))
        out[pd.Timestamp(date_str)] = Portfolio(
            pd.Timestamp(date_str), weights=weights, cash_weight=cash_w
        )
    return out


def attribution(
    ai_result: SeriesResult,
    quant_result: SeriesResult,
    spy_result: SeriesResult,
) -> dict:
    def diff(a, b):
        if a is None or b is None:
            return None
        return round(a - b, 4)

    return {
        "ai_vs_quant": {
            "sharpe_delta": diff(
                ai_result.metrics.get("sharpe"), quant_result.metrics.get("sharpe")
            ),
            "sortino_delta": diff(
                ai_result.metrics.get("sortino"), quant_result.metrics.get("sortino")
            ),
            "annual_return_delta_pp": diff(
                ai_result.metrics.get("annual_return_pct"),
                quant_result.metrics.get("annual_return_pct"),
            ),
            "max_dd_delta_pp": diff(
                ai_result.metrics.get("max_drawdown_pct"),
                quant_result.metrics.get("max_drawdown_pct"),
            ),
        },
        "quant_vs_spy": {
            "sharpe_delta": diff(
                quant_result.metrics.get("sharpe"), spy_result.metrics.get("sharpe")
            ),
            "annual_return_delta_pp": diff(
                quant_result.metrics.get("annual_return_pct"),
                spy_result.metrics.get("annual_return_pct"),
            ),
        },
        "ai_vs_spy": {
            "sharpe_delta": diff(ai_result.metrics.get("sharpe"), spy_result.metrics.get("sharpe")),
            "annual_return_delta_pp": diff(
                ai_result.metrics.get("annual_return_pct"),
                spy_result.metrics.get("annual_return_pct"),
            ),
        },
    }


def format_markdown_report(
    spy: SeriesResult,
    quant: SeriesResult,
    ai: SeriesResult,
    attr: dict,
) -> str:
    def m(v):
        return "—" if v is None else str(v)

    lines = [
        "# Three-Series Eval — SPY vs Quant-only vs AI-augmented",
        "",
        f"Generated: {datetime.utcnow().isoformat(timespec='seconds')}Z",
        "",
        "## Summary Metrics",
        "",
        "| Series | Sharpe | Sortino | Ann. Return | Max DD | Total Return | Days |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in (spy, quant, ai):
        met = r.metrics
        lines.append(
            f"| {r.name} | {m(met.get('sharpe'))} | {m(met.get('sortino'))} | "
            f"{m(met.get('annual_return_pct'))}% | {m(met.get('max_drawdown_pct'))}% | "
            f"{m(met.get('total_return_pct'))}% | {m(met.get('n_days'))} |"
        )
    lines.append("")
    lines.append("## Attribution")
    lines.append("")
    ai_q = attr["ai_vs_quant"]
    lines.append(
        f"**AI vs Quant**: ΔSharpe = **{m(ai_q['sharpe_delta'])}**, "
        f"ΔSortino = {m(ai_q['sortino_delta'])}, "
        f"ΔReturn = {m(ai_q['annual_return_delta_pp'])} pp, "
        f"ΔMaxDD = {m(ai_q['max_dd_delta_pp'])} pp"
    )
    q_s = attr["quant_vs_spy"]
    lines.append(
        f"**Quant vs SPY**: ΔSharpe = {m(q_s['sharpe_delta'])}, "
        f"ΔReturn = {m(q_s['annual_return_delta_pp'])} pp"
    )
    a_s = attr["ai_vs_spy"]
    lines.append(
        f"**AI vs SPY**: ΔSharpe = {m(a_s['sharpe_delta'])}, "
        f"ΔReturn = {m(a_s['annual_return_delta_pp'])} pp"
    )
    lines.append("")
    edge = ai_q["sharpe_delta"]
    if edge is None:
        lines.append("**Verdict**: insufficient data.")
    elif edge > 0.10:
        lines.append(
            f"**Verdict**: AI clearly beats quant on risk-adjusted basis (ΔSharpe {edge})."
        )
    elif edge >= -0.10:
        lines.append(f"**Verdict**: AI ≈ quant (ΔSharpe {edge}); agents aren't earning their cost.")
    else:
        lines.append(
            f"**Verdict**: AI trails quant (ΔSharpe {edge}); drop agents or fix the prompt."
        )
    return "\n".join(lines) + "\n"
