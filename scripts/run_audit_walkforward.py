"""
Audit Session 2 — Walk-forward comparison of earnings sub-blend weights.

Runs run_walk_forward() (NEVER run_cpcv) with two named earnings sub-blend
configs and writes a comparison report.

Question being answered:
  Does the IC-derived earnings reweight (v2) produce better aggregate
  strategy alpha than the prior hand-tuned weights (v0)?

  v0 (hand-tuned):  ERM 0.40 / SUE 0.35 / Dispersion 0.25
  v2 (IC-derived):  ERM 0.4846 / SUE 0.4654 / Dispersion 0.0500

The v2 weights are the committed defaults in quant/earnings_signals.py. The
harness does NOT mutate that file — it threads v0 overrides through new
BacktestConfig fields (earnings_erm_weight / earnings_sue_weight /
earnings_dispersion_weight) which the run_walk_forward call site forwards
as kwargs to compute_earnings_signal_scores().

Walk-forward only per user direction:
    "the service that we had struggled with CPCV, so we should just walk
     forward validate each signal."

Universe:
  WRDS PIT cache (.wrds_pit.db) ∩ local price cache (.price_cache/).

Outputs:
  docs/audit/session-2/walkforward-results.json   raw metrics for both runs
  docs/audit/session-2/walkforward-comparison.md  markdown report

Usage:
    python3 scripts/run_audit_walkforward.py --config v0
    python3 scripts/run_audit_walkforward.py --config v2
    python3 scripts/run_audit_walkforward.py --config both
    python3 scripts/run_audit_walkforward.py --config both --bonus
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Make `quant` importable when running from repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# Load .env so PRICE_PROVIDER, FINNHUB_API_KEY, etc. are configured before
# any quant module reads them at import time.
from dotenv import load_dotenv  # noqa: E402
load_dotenv(_REPO_ROOT / ".env")

import pandas as pd  # noqa: E402

from quant.backtest import BacktestConfig, run_walk_forward  # noqa: E402
from quant import cross_sectional as cs  # noqa: E402
from quant.earnings_signals import EARNINGS_BLEND_WEIGHTS  # noqa: E402

logger = logging.getLogger(__name__)


# ── Universe loaders ─────────────────────────────────────────────────────

PRICE_CACHE_DIR = _REPO_ROOT / ".price_cache"
WRDS_DB_PATH = _REPO_ROOT / ".wrds_pit.db"
OUT_DIR = _REPO_ROOT / "docs" / "audit" / "session-2"


def get_wrds_universe() -> list[str]:
    """All distinct tickers in the WRDS PIT cache."""
    conn = sqlite3.connect(str(WRDS_DB_PATH))
    rows = conn.execute(
        "SELECT DISTINCT ticker FROM compustat_quarterly ORDER BY ticker"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_price_cache_tickers() -> set[str]:
    """All ticker symbols with a CSV in the local price cache."""
    if not PRICE_CACHE_DIR.exists():
        return set()
    return {p.stem for p in PRICE_CACHE_DIR.iterdir() if p.suffix == ".csv"}


def get_audit_universe() -> list[str]:
    """495-ticker universe = WRDS PIT ∩ price-cache (matches run_audit_ic.py)."""
    wrds = set(get_wrds_universe())
    cache = get_price_cache_tickers()
    inter = sorted(wrds & cache)
    return inter


# ── Earnings sub-blend configs ───────────────────────────────────────────

# Per task spec — DO NOT modify the committed EARNINGS_BLEND_WEIGHTS constant.
# Pass these through BacktestConfig.earnings_*_weight overrides instead.
EARNINGS_WEIGHT_CONFIGS: dict[str, dict[str, float]] = {
    "v0": {
        "erm_weight": 0.40,
        "sue_weight": 0.35,
        "dispersion_weight": 0.25,
    },
    "v2": {
        "erm_weight": float(EARNINGS_BLEND_WEIGHTS["erm"]),         # 0.4846
        "sue_weight": float(EARNINGS_BLEND_WEIGHTS["sue"]),         # 0.4654
        "dispersion_weight": float(EARNINGS_BLEND_WEIGHTS["analyst_dispersion"]),  # 0.05
    },
}


# ── Session 3 composite-level reweight configs ──────────────────────────
#
# v3-* configs override the entire DEFAULT_COMPOSITE_WEIGHTS dict (post the
# 2026-04-28 production change that zeroed insider_score). These test
# "does an aggressive composite-level reweight produce better aggregate
# alpha than the current production weights?" + investigate the bull-year
# drag observed in the v0/v2/v2-no-insider results.
#
# All v3 configs use the v2 (IC-derived) earnings sub-blend for the
# earnings_rank_score component.
COMPOSITE_WEIGHT_CONFIGS: dict[str, dict[str, float]] = {
    # v3-IC-tilted: aggressively up-weight the IC-measured signals
    # (earnings_rank, quality_score) and down-weight unmeasured ones
    # (sentiment, regression, arima). Insider stays at 0.
    "v3-ic-tilted": {
        "obv_trend": 0.15,
        "earnings_rank_score": 0.40,        # boosted — ERM/SUE both significant
        "institutional_flow_score": 0.10,   # no measured IC; retained at moderate
        "sentiment_score": 0.025,           # no measured IC; reduced
        "sector_momentum_score": 0.0,       # already 0
        "quality_score": 0.25,              # boosted — significant at 1M
        "price_momentum_score": 0.05,       # near-zero IC; reduced
        "insider_score": 0.0,               # wrong-sign IC (RISK-2)
        "event_timing_score": 0.0,          # already 0
        "price_regression_score": 0.025,    # no IC; very sparse
        "arima_forecast_score": 0.0,        # no IC; very sparse
    },
    # v3-no-noise: zero out the unmeasured signals (sentiment, regression,
    # arima) and redistribute their weight proportionally to the others.
    # Tests the "noise signals are dragging in bull years" hypothesis.
    "v3-no-noise": {
        "obv_trend": 0.214,                 # 0.1667 / 0.778
        "earnings_rank_score": 0.286,       # 0.2222 / 0.778
        "institutional_flow_score": 0.143,  # 0.1111 / 0.778
        "sentiment_score": 0.0,             # ZEROED
        "sector_momentum_score": 0.0,
        "quality_score": 0.214,             # 0.1667 / 0.778
        "price_momentum_score": 0.143,      # 0.1111 / 0.778
        "insider_score": 0.0,
        "event_timing_score": 0.0,
        "price_regression_score": 0.0,      # ZEROED
        "arima_forecast_score": 0.0,        # ZEROED
    },
    # v3-fundamental-stack: most extreme — only signals with measured
    # significant IC plus institutional. Tests "is the bull-year drag
    # inherent to fundamental signals or caused by the noise pad?"
    "v3-fundamental-stack": {
        "obv_trend": 0.20,
        "earnings_rank_score": 0.40,
        "institutional_flow_score": 0.10,
        "sentiment_score": 0.0,
        "sector_momentum_score": 0.0,
        "quality_score": 0.30,
        "price_momentum_score": 0.0,        # ZEROED — near-zero IC
        "insider_score": 0.0,
        "event_timing_score": 0.0,
        "price_regression_score": 0.0,
        "arima_forecast_score": 0.0,
    },
    # v4-shortveto-only: v3-fundamental-stack weights, short-veto enabled,
    # QMJ disabled. Isolates the short-veto's contribution. If this beats
    # v3-fundamental-stack, the short-veto pulls weight on its own.
    "v4-shortveto-only": {
        "obv_trend": 0.20,
        "earnings_rank_score": 0.40,
        "institutional_flow_score": 0.10,
        "sentiment_score": 0.0,
        "sector_momentum_score": 0.0,
        "quality_score": 0.30,
        "price_momentum_score": 0.0,
        "insider_score": 0.0,
        "event_timing_score": 0.0,
        "price_regression_score": 0.0,
        "arima_forecast_score": 0.0,
        "qmj_score": 0.0,                 # NOT enabled
    },
    # v4-qmj-only: v3-fundamental-stack base, QMJ replaces quality_score
    # entirely (QMJ subsumes quality at corr ρ=+0.31), short-veto disabled.
    # Isolates QMJ's contribution. If this beats v3-fundamental-stack, the
    # QMJ-as-composite-signal change pulls weight on its own.
    "v4-qmj-only": {
        "obv_trend": 0.20,
        "earnings_rank_score": 0.40,
        "institutional_flow_score": 0.10,
        "sentiment_score": 0.0,
        "sector_momentum_score": 0.0,
        "quality_score": 0.0,             # ZEROED — QMJ subsumes
        "price_momentum_score": 0.0,
        "insider_score": 0.0,
        "event_timing_score": 0.0,
        "price_regression_score": 0.0,
        "arima_forecast_score": 0.0,
        "qmj_score": 0.30,                # takes the 0.30 quality weight
    },
    # v4-gold: v3-fundamental-stack base + QMJ at 25% (highest measured
    # IC: 12M IC +0.042 t=4.57; 12M L/S return +11.9% with -9.5% MaxDD
    # and 90% hit-rate) + short-side fundamental veto enabled (vetoes
    # NVDA-2022-style strong-fundamentals shorts that drag the strategy
    # in bull years). Quality reduced 30→20% because QMJ overlaps
    # (corr ρ ≈ +0.31). Earnings_rank reduced 40→30% to make room.
    # All technical / unmeasured signals (sentiment, regression, ARIMA,
    # momentum) = 0. OBV kept at 15% (only-surviving cross-sectional
    # technical). Institutional flow kept at 10% (no measured IC but
    # believed to work; cheap to keep).
    #
    # Auto-enabled when this config (or any composite-config containing
    # `qmj_score > 0`) is selected: enable_qmj_signal=True AND
    # enable_short_fundamental_veto=True. See `build_config` /
    # `run_with_composite_weights` below for the wiring.
    "v4-gold": {
        "obv_trend": 0.15,
        "earnings_rank_score": 0.30,
        "institutional_flow_score": 0.10,
        "sentiment_score": 0.0,
        "sector_momentum_score": 0.0,
        "quality_score": 0.20,
        "price_momentum_score": 0.0,
        "insider_score": 0.0,
        "event_timing_score": 0.0,
        "price_regression_score": 0.0,
        "arima_forecast_score": 0.0,
        "qmj_score": 0.25,
    },
}


def progress(msg: str) -> None:
    print(f"  [{datetime.now().strftime('%H:%M:%S')}] {msg}")


# ── BacktestConfig builder ───────────────────────────────────────────────

def build_config(
    tickers: list[str],
    start_date: str,
    end_date: str,
    earnings_weights: dict[str, float],
    *,
    train_months: int = 24,
    test_months: int = 6,
    zero_insider: bool = False,
    max_short_positions: int = 10,
    max_long_positions: int = 10,
    max_per_sector: int = 3,
) -> BacktestConfig:
    """
    Build a BacktestConfig for the audit walk-forward.

    Mirrors the canonical run_phase0.py config (monthly rebalance, earnings +
    news sentiment overlays enabled, regime filter on, IC calibration on)
    but threads earnings sub-blend weight overrides through.

    NOTE: CPCV is NEVER invoked by this harness; only run_walk_forward.
    """
    # Build the config first so we can also set the (currently global) composite
    # weights override before the per-rebalance loop runs.
    cfg = BacktestConfig(
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        rebalance_freq="monthly",
        long_threshold=0.20,
        short_threshold=-0.40,
        enable_regime_filter=True,
        enable_ic_calibration=True,
        max_long_positions=max_long_positions,
        max_short_positions=max_short_positions,
        max_per_sector=max_per_sector,
        train_months=train_months,
        test_months=test_months,
        # Phase 0 orthogonal signals: earnings + sentiment
        enable_earnings_signals=True,
        earnings_signal_weight=0.30,
        enable_news_sentiment=True,
        news_sentiment_weight=0.10,
        # Per-component sub-blend weight overrides (the variable under test)
        earnings_erm_weight=earnings_weights["erm_weight"],
        earnings_sue_weight=earnings_weights["sue_weight"],
        earnings_dispersion_weight=earnings_weights["dispersion_weight"],
        # We do NOT enable institutional flow / xgb / etc. — keep the
        # comparison surface narrow so the only moving piece is the earnings
        # sub-blend (and optionally the insider weight in the bonus run).
    )
    return cfg


# ── Run wrapper ─────────────────────────────────────────────────────────

def _load_spy_series() -> pd.Series:
    """Load SPY closing prices from the local price cache for benchmarking."""
    spy_path = PRICE_CACHE_DIR / "SPY.csv"
    if not spy_path.exists():
        return pd.Series(dtype=float)
    df = pd.read_csv(spy_path, parse_dates=["date"], index_col="date")
    df.index = df.index.normalize()
    if "close" not in df.columns:
        return pd.Series(dtype=float)
    return df["close"].sort_index()


def _yearly_breakdown(
    equity_curve: list[dict],
    benchmark_curve: list[dict],
    spy_series: Optional[pd.Series] = None,
) -> list[dict]:
    """
    Compute year-by-year strategy and benchmark returns.

    Strategy returns are derived from `equity_curve`. Benchmark returns are
    taken from `benchmark_curve` when populated; otherwise they fall back to
    `spy_series` (loaded from the local price cache). `run_walk_forward` does
    not populate `benchmark_curve` at the aggregate level (only `run_backtest`
    does), so the SPY fallback is the normal case here.

    Returns list of dicts: {year, strategy_return_pct, benchmark_return_pct,
                            strategy_beats_benchmark}.
    """
    if not equity_curve:
        return []

    def _to_series(curve: list[dict]) -> pd.Series:
        if not curve:
            return pd.Series(dtype=float)
        df = pd.DataFrame(curve)
        val_col = "equity" if "equity" in df.columns else ("value" if "value" in df.columns else None)
        if val_col is None:
            return pd.Series(dtype=float)
        df["date"] = pd.to_datetime(df["date"])
        s = pd.Series(df[val_col].values, index=df["date"]).sort_index()
        return s

    strat = _to_series(equity_curve)
    bench_curve_series = _to_series(benchmark_curve)
    if spy_series is None:
        spy_series = _load_spy_series()

    if strat.empty:
        return []

    out = []
    for year in sorted(strat.index.year.unique()):
        s_yr = strat[strat.index.year == year]
        if len(s_yr) < 2:
            continue
        s_ret = float(s_yr.iloc[-1] / s_yr.iloc[0] - 1) * 100

        b_ret: Optional[float] = None
        if not bench_curve_series.empty:
            b_yr = bench_curve_series[bench_curve_series.index.year == year]
            if len(b_yr) >= 2:
                b_ret = float(b_yr.iloc[-1] / b_yr.iloc[0] - 1) * 100
        if b_ret is None and not spy_series.empty:
            spy_yr = spy_series[spy_series.index.year == year]
            if len(spy_yr) >= 2:
                b_ret = float(spy_yr.iloc[-1] / spy_yr.iloc[0] - 1) * 100

        out.append({
            "year": int(year),
            "strategy_return_pct": round(s_ret, 2),
            "benchmark_return_pct": round(b_ret, 2) if b_ret is not None else None,
            "strategy_beats_benchmark": (b_ret is not None and s_ret > b_ret),
        })
    return out


def run_one_config(
    name: str,
    cfg: BacktestConfig,
    label_suffix: str = "",
) -> dict:
    """
    Execute run_walk_forward(cfg) and return a summary metrics dict suitable
    for JSON serialization.
    """
    label = f"{name}{label_suffix}"
    print()
    print("=" * 70)
    print(f"  WALK-FORWARD RUN — config={label}")
    print("=" * 70)
    print(f"  start={cfg.start_date}  end={cfg.end_date}")
    print(f"  tickers={len(cfg.tickers)}")
    print(f"  rebalance={cfg.rebalance_freq} train={cfg.train_months}m test={cfg.test_months}m")
    print(f"  earnings: enable={cfg.enable_earnings_signals} weight={cfg.earnings_signal_weight}")
    print(f"  earnings sub-blend: erm={cfg.earnings_erm_weight} "
          f"sue={cfg.earnings_sue_weight} disp={cfg.earnings_dispersion_weight}")

    t0 = time.time()
    result = run_walk_forward(cfg, progress_cb=progress)
    elapsed = time.time() - t0

    print()
    print(f"  Status: {result.status}")
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"  Total return:  {result.total_return_pct:+.2f}%")
    print(f"  Annual return: {result.annual_return_pct:+.2f}%")
    print(f"  Sharpe:        {result.sharpe}")
    print(f"  Sortino:       {result.sortino}")
    print(f"  Max drawdown:  {result.max_drawdown_pct:.2f}%")
    print(f"  Win rate:      {result.win_rate_pct:.1f}%")
    print(f"  Total trades:  {result.total_trades}")
    print(f"  Avg holding:   {result.avg_holding_days:.1f} days")
    print(f"  Benchmark:     {result.benchmark_return_pct:+.2f}%")
    print(f"  Alpha vs SPY:  {result.alpha_pct:+.2f}%")

    # Year-by-year breakdown
    yearly = _yearly_breakdown(result.equity_curve, result.benchmark_curve)
    if yearly:
        print(f"\n  Year-by-year:")
        for y in yearly:
            mk = "+" if y["strategy_beats_benchmark"] else " "
            print(f"   {mk} {y['year']}: strat={y['strategy_return_pct']:+6.2f}%  "
                  f"bench={y['benchmark_return_pct'] if y['benchmark_return_pct'] is not None else 'NA'}")

    # Walk-forward window summary
    if result.walk_forward:
        print(f"\n  Windows: {len(result.walk_forward)}")

    summary = {
        "name": name,
        "label_suffix": label_suffix,
        "status": result.status,
        "error": result.error,
        "elapsed_seconds": round(elapsed, 1),
        "config": {
            "start_date": cfg.start_date,
            "end_date": cfg.end_date,
            "rebalance_freq": cfg.rebalance_freq,
            "train_months": cfg.train_months,
            "test_months": cfg.test_months,
            "n_tickers": len(cfg.tickers),
            "long_threshold": cfg.long_threshold,
            "short_threshold": cfg.short_threshold,
            "max_long_positions": cfg.max_long_positions,
            "max_short_positions": cfg.max_short_positions,
            "earnings_signal_weight": cfg.earnings_signal_weight,
            "earnings_erm_weight": cfg.earnings_erm_weight,
            "earnings_sue_weight": cfg.earnings_sue_weight,
            "earnings_dispersion_weight": cfg.earnings_dispersion_weight,
            "news_sentiment_weight": cfg.news_sentiment_weight,
            "enable_earnings_signals": cfg.enable_earnings_signals,
            "enable_news_sentiment": cfg.enable_news_sentiment,
            "enable_regime_filter": cfg.enable_regime_filter,
            "enable_ic_calibration": cfg.enable_ic_calibration,
        },
        "metrics": {
            "total_return_pct": result.total_return_pct,
            "annual_return_pct": result.annual_return_pct,
            "sharpe": result.sharpe,
            "sortino": result.sortino,
            "calmar": result.calmar,
            "max_drawdown_pct": result.max_drawdown_pct,
            "win_rate_pct": result.win_rate_pct,
            "total_trades": result.total_trades,
            "avg_holding_days": result.avg_holding_days,
            "benchmark_return_pct": result.benchmark_return_pct,
            "benchmark_sharpe": result.benchmark_sharpe,
            "alpha_pct": result.alpha_pct,
        },
        "yearly": yearly,
        "n_windows": len(result.walk_forward),
    }
    return summary


# ── Bonus run: zero insider weight in DEFAULT_COMPOSITE_WEIGHTS ──────────

def run_bonus_zero_insider(cfg: BacktestConfig) -> dict:
    """
    Run with insider_score weight zeroed in DEFAULT_COMPOSITE_WEIGHTS,
    redistributing the 10% proportionally to other non-zero weights.

    Mutates the module-level DEFAULT_COMPOSITE_WEIGHTS *in process*, runs the
    backtest, then restores the original mapping.
    """
    orig = dict(cs.DEFAULT_COMPOSITE_WEIGHTS)

    # Build new weights: zero out insider_score, redistribute its 10% pro-rata
    # across the other strictly positive-weight signals.
    insider_w = orig.get("insider_score", 0.0)
    new = dict(orig)
    new["insider_score"] = 0.0
    if insider_w > 0:
        donors = {k: v for k, v in new.items() if k != "insider_score" and v > 0.0}
        donors_total = sum(donors.values())
        if donors_total > 0:
            for k in donors:
                new[k] = round(new[k] + insider_w * (donors[k] / donors_total), 6)

    print()
    print(f"  [bonus] DEFAULT_COMPOSITE_WEIGHTS reweighted (insider zeroed):")
    for k, v in new.items():
        if v > 0 or orig[k] > 0:
            mark = "*" if abs(v - orig[k]) > 1e-9 else " "
            print(f"     {mark} {k:30s}  {orig[k]:.4f}  ->  {v:.4f}")

    cs.DEFAULT_COMPOSITE_WEIGHTS = new
    try:
        out = run_one_config("v2", cfg, label_suffix="-no-insider")
        out["name"] = "v2-no-insider"
        out["composite_weights_used"] = new
    finally:
        cs.DEFAULT_COMPOSITE_WEIGHTS = orig

    return out


def run_with_composite_weights(
    name: str,
    weights: dict[str, float],
    cfg: BacktestConfig,
) -> dict:
    """
    Run with a custom DEFAULT_COMPOSITE_WEIGHTS override.

    Mutates the module-level dict in process, runs, then restores. Used by
    Session 3 v3-* composite reweight configs.

    Auto-enables QMJ + short-veto for any config with `qmj_score > 0`
    (e.g. v4-gold). This keeps the harness CLI surface unchanged: just
    pass `--composite-config v4-gold` and the right flags get set.
    """
    orig = dict(cs.DEFAULT_COMPOSITE_WEIGHTS)
    new = dict(orig)
    # Apply overrides; any key present in weights replaces the production value
    for k, v in weights.items():
        new[k] = float(v)

    # Per-config flag overrides for v4-* isolation tests. If a config name
    # is keyed here, these flags take precedence over the qmj_score-based
    # auto-enable. Lets us isolate "short-veto only" vs "QMJ only" cleanly.
    # Configs not listed here fall back to:
    #   - enable_qmj_signal: qmj_score > 0
    #   - enable_short_fundamental_veto: same as enable_qmj_signal OR v4-* name
    COMPOSITE_FLAG_OVERRIDES = {
        "v4-shortveto-only": {"enable_qmj_signal": False, "enable_short_fundamental_veto": True},
        "v4-qmj-only":       {"enable_qmj_signal": True,  "enable_short_fundamental_veto": False},
        "v4-gold":           {"enable_qmj_signal": True,  "enable_short_fundamental_veto": True},
    }

    if name in COMPOSITE_FLAG_OVERRIDES:
        flags = COMPOSITE_FLAG_OVERRIDES[name]
        auto_qmj = flags["enable_qmj_signal"]
        auto_short_veto = flags["enable_short_fundamental_veto"]
    else:
        # Fallback: qmj_score weight implies enabling QMJ; v4-* prefix implies short-veto.
        auto_qmj = float(new.get("qmj_score", 0.0)) > 0.0
        auto_short_veto = auto_qmj or name.startswith("v4-")

    cfg.enable_qmj_signal = bool(auto_qmj)
    cfg.enable_short_fundamental_veto = bool(auto_short_veto)

    print()
    print(f"  [composite] DEFAULT_COMPOSITE_WEIGHTS overridden for {name}:")
    for k in sorted(set(orig) | set(new)):
        if new.get(k, 0.0) > 0 or orig.get(k, 0.0) > 0:
            mark = "*" if abs(new.get(k, 0.0) - orig.get(k, 0.0)) > 1e-9 else " "
            print(f"     {mark} {k:30s}  {orig.get(k, 0.0):.4f}  ->  {new.get(k, 0.0):.4f}")
    if auto_qmj:
        print(f"     [auto] enable_qmj_signal=True (qmj_score weight={new.get('qmj_score', 0.0):.4f})")
    if auto_short_veto:
        print(f"     [auto] enable_short_fundamental_veto=True (min_strong_signals={cfg.short_veto_min_strong_signals})")

    cs.DEFAULT_COMPOSITE_WEIGHTS = new
    try:
        out = run_one_config(name, cfg)
        out["composite_weights_used"] = new
        out["auto_enabled"] = {
            "enable_qmj_signal": bool(getattr(cfg, "enable_qmj_signal", False)),
            "enable_short_fundamental_veto": bool(
                getattr(cfg, "enable_short_fundamental_veto", False)
            ),
        }
    finally:
        cs.DEFAULT_COMPOSITE_WEIGHTS = orig
    return out


# ── Markdown report ──────────────────────────────────────────────────────

def _fmt(v, fmt: str = "{:+.2f}") -> str:
    if v is None:
        return "—"
    try:
        return fmt.format(v)
    except Exception:
        return str(v)


def write_markdown_report(
    runs: list[dict],
    universe_size: int,
    universe_strategy: str,
    out_path: Path,
) -> None:
    """Compose docs/audit/session-2/walkforward-comparison.md."""
    if not runs:
        out_path.write_text("# Walk-Forward Comparison\n\nNo runs completed.\n")
        return

    # Look up by name
    by_name = {r["name"]: r for r in runs}
    v0 = by_name.get("v0")
    v2 = by_name.get("v2")
    bonus = by_name.get("v2-no-insider")

    lines: list[str] = []
    lines.append("# Audit Session 2 — Walk-Forward Comparison")
    lines.append("")
    lines.append(f"**Generated**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    if runs:
        cfg = runs[0]["config"]
        lines.append(
            f"**Window**: {cfg['start_date']} → {cfg['end_date']}  "
            f"**Universe**: {universe_size} tickers ({universe_strategy})  "
            f"**Rebalance**: {cfg['rebalance_freq']}  "
            f"(walk-forward train={cfg['train_months']}m / test={cfg['test_months']}m)  "
            "**Walk-forward only** (no CPCV)."
        )
    lines.append("")
    lines.append("## Question")
    lines.append("")
    lines.append("Does the IC-derived earnings reweight (v2) produce better aggregate "
                 "strategy alpha than the prior hand-tuned weights (v0)?")
    lines.append("")
    lines.append("## Earnings sub-blend configs under test")
    lines.append("")
    lines.append("| Config | ERM | SUE | Dispersion | Source |")
    lines.append("|---|---:|---:|---:|---|")
    lines.append("| v0 (hand-tuned) | 0.4000 | 0.3500 | 0.2500 | Pre-audit defaults |")
    lines.append(
        f"| v2 (IC-derived) | {EARNINGS_BLEND_WEIGHTS['erm']:.4f} | "
        f"{EARNINGS_BLEND_WEIGHTS['sue']:.4f} | "
        f"{EARNINGS_BLEND_WEIGHTS['analyst_dispersion']:.4f} | "
        "Audit ic-summary.md (495-universe, 1M/3M/6M IC means + 50% shrinkage + 0.95/0.05 dispersion floor) |"
    )
    lines.append("")

    # ── Summary table ───────────────────────────────────────────────────
    def _row(label: str, key: str, fmt: str = "{:+.2f}", invert_delta: bool = False) -> str:
        v0v = (v0 or {}).get("metrics", {}).get(key) if v0 else None
        v2v = (v2 or {}).get("metrics", {}).get(key) if v2 else None
        delta = None
        if v0v is not None and v2v is not None:
            try:
                delta = v2v - v0v
                if invert_delta:
                    delta = -delta
            except Exception:
                delta = None
        return f"| {label} | {_fmt(v0v, fmt)} | {_fmt(v2v, fmt)} | {_fmt(delta, '{:+.2f}')} |"

    lines.append("## Aggregate metrics")
    lines.append("")
    lines.append("| Metric | v0 (hand-tuned) | v2 (IC-weighted) | Δ (v2 − v0) |")
    lines.append("|---|---:|---:|---:|")
    lines.append(_row("Total return %",      "total_return_pct"))
    lines.append(_row("Annualized return %", "annual_return_pct"))
    lines.append(_row("Sharpe ratio",        "sharpe", "{:+.3f}"))
    lines.append(_row("Sortino ratio",       "sortino", "{:+.3f}"))
    lines.append(_row("Max drawdown %",      "max_drawdown_pct"))
    lines.append(_row("Win rate %",          "win_rate_pct"))
    lines.append(_row("Total trades",        "total_trades", "{:.0f}"))
    lines.append(_row("Avg holding days",    "avg_holding_days", "{:.1f}"))
    lines.append(_row("Benchmark return %",  "benchmark_return_pct"))
    lines.append(_row("Alpha vs benchmark %", "alpha_pct"))
    lines.append("")

    # Yearly hit-rate
    def _hit_rate(run: Optional[dict]) -> Optional[float]:
        if run is None or not run.get("yearly"):
            return None
        years = run["yearly"]
        n = len(years)
        if n == 0:
            return None
        wins = sum(1 for y in years if (y.get("benchmark_return_pct") is not None
                                         and y["strategy_return_pct"] > y["benchmark_return_pct"]))
        return round(wins / n * 100, 1)

    hr0 = _hit_rate(v0)
    hr2 = _hit_rate(v2)
    delta_hr = (hr2 - hr0) if (hr0 is not None and hr2 is not None) else None
    lines.append(f"| Year-by-year hit rate (vs SPY) | {_fmt(hr0, '{:.1f}%')} | {_fmt(hr2, '{:.1f}%')} | {_fmt(delta_hr, '{:+.1f}pp')} |")
    lines.append("")

    # ── Bonus row ────────────────────────────────────────────────────────
    if bonus is not None:
        lines.append("### Bonus: v2 with insider_mspr zeroed in DEFAULT_COMPOSITE_WEIGHTS")
        lines.append("")
        lines.append("| Metric | v2 (IC-weighted) | v2-no-insider | Δ (no-insider − v2) |")
        lines.append("|---|---:|---:|---:|")
        for label, key, fmt in [
            ("Total return %",      "total_return_pct",      "{:+.2f}"),
            ("Annualized return %", "annual_return_pct",     "{:+.2f}"),
            ("Sharpe ratio",        "sharpe",                "{:+.3f}"),
            ("Sortino ratio",       "sortino",               "{:+.3f}"),
            ("Max drawdown %",      "max_drawdown_pct",      "{:+.2f}"),
            ("Win rate %",          "win_rate_pct",          "{:+.2f}"),
            ("Alpha vs benchmark %", "alpha_pct",            "{:+.2f}"),
        ]:
            v2v = (v2 or {}).get("metrics", {}).get(key)
            bv = bonus["metrics"].get(key)
            d = (bv - v2v) if (v2v is not None and bv is not None) else None
            lines.append(f"| {label} | {_fmt(v2v, fmt)} | {_fmt(bv, fmt)} | {_fmt(d, '{:+.2f}')} |")
        lines.append("")

    # ── Year-by-year breakdown ───────────────────────────────────────────
    lines.append("## Year-by-year strategy returns")
    lines.append("")
    years_seen: set[int] = set()
    for r in (v0, v2, bonus):
        if r:
            for y in r.get("yearly", []):
                years_seen.add(y["year"])
    years_sorted = sorted(years_seen)

    def _year_get(run: Optional[dict], year: int):
        if run is None:
            return None
        for y in run.get("yearly", []):
            if y["year"] == year:
                return y
        return None

    headers = ["Year", "v0", "v2"]
    if bonus is not None:
        headers.append("v2-no-insider")
    headers.append("SPY")
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|---" * len(headers) + "|")

    for year in years_sorted:
        y0 = _year_get(v0, year)
        y2 = _year_get(v2, year)
        yb = _year_get(bonus, year) if bonus else None
        spy = None
        for src in (y2, y0, yb):
            if src and src.get("benchmark_return_pct") is not None:
                spy = src["benchmark_return_pct"]; break
        row = [str(year)]
        row.append(_fmt(y0["strategy_return_pct"] if y0 else None, "{:+.2f}%"))
        row.append(_fmt(y2["strategy_return_pct"] if y2 else None, "{:+.2f}%"))
        if bonus is not None:
            row.append(_fmt(yb["strategy_return_pct"] if yb else None, "{:+.2f}%"))
        row.append(_fmt(spy, "{:+.2f}%"))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # ── Interpretation ──────────────────────────────────────────────────
    lines.append("## Interpretation")
    lines.append("")
    if v0 and v2:
        delta_sharpe = ((v2["metrics"]["sharpe"] or 0) - (v0["metrics"]["sharpe"] or 0))
        delta_alpha = (v2["metrics"]["alpha_pct"] - v0["metrics"]["alpha_pct"])
        delta_dd = (v2["metrics"]["max_drawdown_pct"] - v0["metrics"]["max_drawdown_pct"])
        v2_beats_v0 = (delta_sharpe > 0 and delta_alpha > 0)
        v2_beats_spy = v2["metrics"]["alpha_pct"] > 0
        v0_beats_spy = v0["metrics"]["alpha_pct"] > 0

        lines.append(f"- **v2 vs v0**: Sharpe Δ {delta_sharpe:+.3f}, Alpha Δ {delta_alpha:+.2f}pp, "
                     f"MaxDD Δ {delta_dd:+.2f}pp. "
                     + ("**v2 strictly beats v0**" if v2_beats_v0 else
                        "**v2 does NOT strictly beat v0**") + ".")
        lines.append(f"- **v2 vs SPY**: Alpha {v2['metrics']['alpha_pct']:+.2f}%. "
                     + ("Positive alpha." if v2_beats_spy else "Negative alpha — strategy underperforms buy-and-hold."))
        lines.append(f"- **v0 vs SPY**: Alpha {v0['metrics']['alpha_pct']:+.2f}%. "
                     + ("Positive alpha." if v0_beats_spy else "Negative alpha — strategy underperforms buy-and-hold."))
        # Economic significance heuristic — Δ Sharpe < 0.05 is noise on a 10-year sample.
        if abs(delta_sharpe) < 0.05 and abs(delta_alpha) < 1.0:
            lines.append("- **Economic significance**: Δ Sharpe and Δ Alpha both small. "
                         "The IC-level signal advantage is largely **invisible at the composite level** — "
                         "consistent with the fact that earnings is a 30%-weight overlay on a 10-signal "
                         "composite and the dispersion contribution that v0 contained was already weak (NO_SIGNAL "
                         "at 1M, marginal at 6M).")
        else:
            lines.append("- **Economic significance**: Δ Sharpe ≥ 0.05 or Δ Alpha ≥ 1pp suggests the reweight "
                         "is meaningful at the composite level.")
    if bonus is not None and v2:
        d_sharpe = (bonus["metrics"]["sharpe"] or 0) - (v2["metrics"]["sharpe"] or 0)
        d_alpha = bonus["metrics"]["alpha_pct"] - v2["metrics"]["alpha_pct"]
        lines.append(f"- **Bonus (v2-no-insider)**: Sharpe Δ {d_sharpe:+.3f}, Alpha Δ {d_alpha:+.2f}pp vs v2. "
                     + ("Removing insider_mspr **helps**." if (d_sharpe > 0 or d_alpha > 0)
                        else "Removing insider_mspr does NOT help on this universe."))

    lines.append("")
    lines.append("## Methodology notes")
    lines.append("")
    lines.append("- **Walk-forward only** via `run_walk_forward()`. `run_cpcv()` is never called.")
    lines.append("- Universe: WRDS PIT cache ∩ local price cache (matches `scripts/run_audit_ic.py:get_audit_universe`).")
    lines.append("- Earnings sub-blend weights are passed via new `BacktestConfig.earnings_*_weight` "
                 "fields, threaded through to `compute_earnings_signal_scores()` at the run_walk_forward "
                 "call site (quant/backtest.py). The committed `EARNINGS_BLEND_WEIGHTS` constant is unchanged.")
    lines.append("- Bonus run zeroes `insider_score` in `DEFAULT_COMPOSITE_WEIGHTS` (in-process mutation, "
                 "restored after the run) and redistributes its 10% proportionally to the other "
                 "non-zero composite weights.")
    lines.append("")

    out_path.write_text("\n".join(lines) + "\n")


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Session 2 — Walk-forward earnings weight comparison")
    parser.add_argument(
        "--config", choices=["v0", "v2", "both"], default="both",
        help="Which earnings sub-blend config(s) to run (default: both)",
    )
    parser.add_argument("--start", default="2015-01-01", help="Backtest window start")
    parser.add_argument("--end", default="2024-12-31", help="Backtest window end")
    parser.add_argument("--train-months", type=int, default=24)
    parser.add_argument("--test-months", type=int, default=6)
    parser.add_argument(
        "--limit-tickers", type=int, default=0,
        help="Cap universe size (top-N alphabetical) for runtime control. 0 = no cap.",
    )
    parser.add_argument(
        "--bonus", action="store_true",
        help="If both v0 and v2 succeed, also run v2 with insider_mspr zeroed in DEFAULT_COMPOSITE_WEIGHTS.",
    )
    parser.add_argument(
        "--composite-config", choices=list(COMPOSITE_WEIGHT_CONFIGS.keys()), default="",
        help="Run a single Session 3 v3-* composite-reweight config with v2 earnings weights "
             "(overrides --config and --bonus when set). Each config writes its own output files.",
    )
    parser.add_argument(
        "--max-short-positions", type=int, default=0,
        help="Override BacktestConfig.max_short_positions. Default 0 matches "
             "production (long-only since 2026-04-28). Set to 10 to test "
             "long/short variants.",
    )
    parser.add_argument(
        "--max-long-positions", type=int, default=10,
        help="Override BacktestConfig.max_long_positions (default 10).",
    )
    parser.add_argument(
        "--max-per-sector", type=int, default=3,
        help="Override BacktestConfig.max_per_sector (default 3).",
    )
    parser.add_argument("--output-md", default="", help="Override markdown output path")
    parser.add_argument("--output-json", default="", help="Override JSON output path")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = Path(args.output_json) if args.output_json else (OUT_DIR / "walkforward-results.json")
    md_path = Path(args.output_md) if args.output_md else (OUT_DIR / "walkforward-comparison.md")

    # Build universe
    full_universe = get_audit_universe()
    universe_strategy = "WRDS ∩ price-cache"
    if args.limit_tickers and args.limit_tickers < len(full_universe):
        tickers = full_universe[: args.limit_tickers]
        universe_strategy = f"WRDS ∩ price-cache, top-{args.limit_tickers} alphabetical (sample reduction)"
    else:
        tickers = full_universe

    print()
    print("*" * 70)
    print("  AUDIT SESSION 2 — WALK-FORWARD EARNINGS WEIGHT COMPARISON")
    print("*" * 70)
    print(f"  Universe: {len(tickers)} tickers ({universe_strategy})")
    print(f"  Window:   {args.start} → {args.end}")
    print(f"  Configs:  {args.config}{' + composite=' + args.composite_config if args.composite_config else ''}")
    print(f"  WF:       train={args.train_months}m / test={args.test_months}m")
    print(f"  Bonus:    {'YES' if args.bonus else 'no'}")
    print("*" * 70)

    # ── Session 3 single-config composite-override mode ─────────────────
    if args.composite_config:
        cc_name = args.composite_config
        cc_weights = COMPOSITE_WEIGHT_CONFIGS[cc_name]
        # Use v2 earnings sub-blend (current production)
        weights = EARNINGS_WEIGHT_CONFIGS["v2"]
        cfg = build_config(
            tickers=tickers,
            start_date=args.start,
            end_date=args.end,
            earnings_weights=weights,
            train_months=args.train_months,
            test_months=args.test_months,
            max_short_positions=args.max_short_positions,
            max_long_positions=args.max_long_positions,
            max_per_sector=args.max_per_sector,
        )
        try:
            summary = run_with_composite_weights(cc_name, cc_weights, cfg)
        except Exception as exc:
            logger.exception("Composite config %s FAILED", cc_name)
            summary = {
                "name": cc_name, "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "config": {"start_date": cfg.start_date, "end_date": cfg.end_date,
                           "n_tickers": len(cfg.tickers)},
                "metrics": {}, "yearly": [], "n_windows": 0,
            }
        payload = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "universe_size": len(tickers),
            "universe_strategy": universe_strategy,
            "window": {"start": args.start, "end": args.end},
            "composite_config": cc_name,
            "composite_weights": cc_weights,
            "earnings_weights": weights,
            "runs": [summary],
        }
        json_path.write_text(json.dumps(payload, indent=2, default=str))
        # Skip the markdown report for single-config runs — synthesizer will
        # combine the JSON outputs from all v3-* runs into one report.
        print()
        print(f"  Single-config run done. JSON: {json_path}")
        return

    runs: list[dict] = []

    configs_to_run: list[str] = []
    if args.config in ("v0", "both"):
        configs_to_run.append("v0")
    if args.config in ("v2", "both"):
        configs_to_run.append("v2")

    cfg_for_bonus: Optional[BacktestConfig] = None

    for cfg_name in configs_to_run:
        weights = EARNINGS_WEIGHT_CONFIGS[cfg_name]
        cfg = build_config(
            tickers=tickers,
            start_date=args.start,
            end_date=args.end,
            earnings_weights=weights,
            train_months=args.train_months,
            test_months=args.test_months,
            max_short_positions=args.max_short_positions,
            max_long_positions=args.max_long_positions,
            max_per_sector=args.max_per_sector,
        )
        if cfg_name == "v2":
            cfg_for_bonus = cfg
        try:
            summary = run_one_config(cfg_name, cfg)
            runs.append(summary)
        except Exception as exc:
            logger.exception("Config %s FAILED", cfg_name)
            runs.append({
                "name": cfg_name,
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "config": {
                    "start_date": cfg.start_date,
                    "end_date": cfg.end_date,
                    "n_tickers": len(cfg.tickers),
                    "earnings_erm_weight": cfg.earnings_erm_weight,
                    "earnings_sue_weight": cfg.earnings_sue_weight,
                    "earnings_dispersion_weight": cfg.earnings_dispersion_weight,
                },
                "metrics": {},
                "yearly": [],
                "n_windows": 0,
            })

    # Bonus only if both v0 and v2 ran cleanly.
    if args.bonus and cfg_for_bonus is not None:
        clean = {r["name"] for r in runs if r.get("status") not in ("error", None) and r.get("metrics")}
        if {"v0", "v2"}.issubset(clean):
            try:
                bonus_summary = run_bonus_zero_insider(cfg_for_bonus)
                runs.append(bonus_summary)
            except Exception as exc:
                logger.exception("Bonus run FAILED")
                runs.append({
                    "name": "v2-no-insider",
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "metrics": {},
                    "yearly": [],
                    "n_windows": 0,
                })
        else:
            print()
            print("  [bonus] skipped — v0 and v2 must both finish cleanly first.")

    # ── Persist results ─────────────────────────────────────────────────
    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "universe_size": len(tickers),
        "universe_strategy": universe_strategy,
        "wrds_universe_size": len(get_wrds_universe()),
        "price_cache_tickers_total": len(get_price_cache_tickers()),
        "window": {"start": args.start, "end": args.end},
        "earnings_weight_configs": EARNINGS_WEIGHT_CONFIGS,
        "runs": runs,
    }
    json_path.write_text(json.dumps(payload, indent=2, default=str))
    write_markdown_report(runs, len(tickers), universe_strategy, md_path)

    print()
    print(f"  JSON results: {json_path}")
    print(f"  Markdown:     {md_path}")
    print()


if __name__ == "__main__":
    main()
