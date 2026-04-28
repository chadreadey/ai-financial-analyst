"""
Audit Session 2: per-signal IC runner (walk-forward only, NO CPCV).

Computes Information Coefficient (rank IC) at 1M / 3M / 6M / 12M horizons
for the full fundamental signal stack on the WRDS PIT universe, plus the
three baselines (Piotroski / QMJ / HML). Produces JSON results + a markdown
summary that ranks signals by 3M IC.

Walk-forward only per user instruction:
  > "the service that we had struggled with CPCV, so we should just walk
  > forward validate each signal."

NaN propagation discipline:
  - Missing fundamental data => NaN, NEVER 0 (project_silent_zeros memory).
  - Tickers with NaN signal at a date are dropped from that signal's
    cross-section at that date (only).

Inputs:
  - WRDS PIT cache (.wrds_pit.db) for fundamentals
  - Local price cache (.price_cache/) for total returns
  - We compute the IC universe as the intersection of WRDS tickers and
    price-cache tickers — typically ~190 names.

Outputs:
  - docs/audit/session-2/ic-results.json — full numeric results
  - docs/audit/session-2/ic-summary.md   — ranked signal table + verdicts

Usage:
    python3 scripts/run_audit_ic.py                 # full universe, default window
    python3 scripts/run_audit_ic.py --limit-tickers 50
    python3 scripts/run_audit_ic.py --start 2018-01-01 --end 2024-12-31
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

# Make `quant` importable when running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from quant.wrds_store import WRDSPointInTimeStore  # noqa: E402
from quant.fundamental_provider import WRDSFundamentalProvider  # noqa: E402
from quant.factor_baselines import (  # noqa: E402
    compute_piotroski_score,
    compute_qmj_score,
    compute_hml_score,
)
from quant.earnings_signals import (  # noqa: E402
    compute_erm_score,
    compute_sue_score,
    compute_dispersion_score,
)
from quant.additional_signals import (  # noqa: E402
    compute_quality_scores,
    compute_price_momentum_scores,
    compute_insider_scores,
)
try:
    from finnhub_client import SentimentDiskCache  # noqa: E402
    _SENTIMENT_CACHE = SentimentDiskCache()
except Exception:
    _SENTIMENT_CACHE = None

logger = logging.getLogger(__name__)


# ── Configuration ───────────────────────────────────────────────────────

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICE_CACHE_DIR = os.path.join(REPO_ROOT, ".price_cache")
WRDS_DB_PATH = os.path.join(REPO_ROOT, ".wrds_pit.db")

OUT_DIR = os.path.join(REPO_ROOT, "docs", "audit", "session-2")

# Signals we score (in addition to baselines)
FUNDAMENTAL_SIGNAL_NAMES = [
    "erm",
    "sue",
    "analyst_dispersion",
    "quality_score",
    "price_momentum",
    # insider_mspr — INSUFFICIENT (no Finnhub cache present locally),
    # documented in the summary; we still emit the column header so the
    # missing slot is visible.
    "insider_mspr",
]

BASELINE_NAMES = ["piotroski", "qmj", "hml_bm"]
ALL_SIGNAL_NAMES = FUNDAMENTAL_SIGNAL_NAMES + BASELINE_NAMES

# Forward-return horizons in trading days (~21d/month)
HORIZONS = {
    "1M": 21,
    "3M": 63,
    "6M": 126,
    "12M": 252,
}


# ── Data loading ────────────────────────────────────────────────────────

def load_universe_prices(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Load OHLCV from the local price cache for tickers we have on disk."""
    data = {}
    for t in tickers:
        path = os.path.join(PRICE_CACHE_DIR, f"{t}.csv")
        if not os.path.exists(path):
            continue
        try:
            df = pd.read_csv(path, parse_dates=["date"], index_col="date")
            df.index = df.index.normalize()
            data[t] = df
        except Exception as exc:
            logger.debug("price load failed for %s: %s", t, exc)
    return data


def get_wrds_universe() -> list[str]:
    """All distinct tickers in the WRDS PIT cache."""
    conn = sqlite3.connect(WRDS_DB_PATH)
    rows = conn.execute(
        "SELECT DISTINCT ticker FROM compustat_quarterly ORDER BY ticker"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


# ── Forward returns ─────────────────────────────────────────────────────

def compute_forward_returns_panel(
    universe_data: dict[str, pd.DataFrame],
    as_of: pd.Timestamp,
    horizon_days: int,
) -> pd.Series:
    """Forward N-day total return per ticker from `as_of`. Drops missing."""
    out = {}
    for t, df in universe_data.items():
        future = df[df.index > as_of]
        current = df[df.index <= as_of]
        if len(current) < 1 or len(future) < horizon_days:
            continue
        p_now = float(current.iloc[-1]["close"])
        p_fwd = float(future.iloc[horizon_days - 1]["close"])
        if p_now > 0 and not math.isnan(p_now) and not math.isnan(p_fwd):
            out[t] = (p_fwd / p_now) - 1
    return pd.Series(out, dtype=float)


# ── Signal scoring panel ────────────────────────────────────────────────

def compute_signal_panel(
    universe_data: dict[str, pd.DataFrame],
    as_of: pd.Timestamp,
    wrds_store: WRDSPointInTimeStore,
    provider: WRDSFundamentalProvider,
) -> Optional[pd.DataFrame]:
    """
    Compute a per-ticker score for every signal at a single rebalance date.

    Returns DataFrame indexed by ticker with one column per signal in
    ALL_SIGNAL_NAMES. Missing => NaN.
    """
    as_of_d = as_of.date() if hasattr(as_of, "date") else as_of
    tickers = list(universe_data.keys())

    # ── Vectorized cross-sectional precompute ─────────────────────────
    momentum_scores = compute_price_momentum_scores(universe_data, as_of)
    quality_scores = compute_quality_scores(tickers, provider, as_of_d)
    # insider MSPR — disk cache only, no API calls (prefetched 2026-04-27)
    insider_scores = compute_insider_scores(
        tickers, as_of, finnhub_client=None, sentiment_cache=_SENTIMENT_CACHE,
    )

    rows = {}
    for t in tickers:
        row = {sig: float("nan") for sig in ALL_SIGNAL_NAMES}

        # Fundamentals (per-ticker)
        try:
            erm_s, erm_meta = compute_erm_score(t, provider, as_of_date=as_of_d)
            if "error" not in erm_meta:
                row["erm"] = float(erm_s)
        except Exception:
            pass

        try:
            sue_s, sue_meta = compute_sue_score(t, provider, as_of_date=as_of_d)
            if "error" not in sue_meta:
                row["sue"] = float(sue_s)
        except Exception:
            pass

        try:
            disp_s, disp_meta = compute_dispersion_score(t, provider, as_of_date=as_of_d)
            if "error" not in disp_meta:
                row["analyst_dispersion"] = float(disp_s)
        except Exception:
            pass

        if t in quality_scores:
            row["quality_score"] = float(quality_scores[t])
        if t in momentum_scores:
            row["price_momentum"] = float(momentum_scores[t])
        if t in insider_scores:
            row["insider_mspr"] = float(insider_scores[t])

        # Baselines
        try:
            p = compute_piotroski_score(t, as_of_d, wrds_store)
            if p is not None:
                row["piotroski"] = float(p)
        except Exception:
            pass

        try:
            q = compute_qmj_score(t, as_of_d, wrds_store)
            if q is not None:
                row["qmj"] = float(q)
        except Exception:
            pass

        # HML needs a price (point-in-time close on as_of)
        try:
            df = universe_data[t]
            avail = df[df.index <= as_of]
            price = float(avail.iloc[-1]["close"]) if len(avail) else None
            if price and price > 0:
                h = compute_hml_score(t, as_of_d, wrds_store, price=price)
                if h is not None:
                    row["hml_bm"] = float(h)
        except Exception:
            pass

        rows[t] = row

    if not rows:
        return None
    return pd.DataFrame.from_dict(rows, orient="index")


# ── IC computation ──────────────────────────────────────────────────────

@dataclass
class SignalIcStats:
    signal: str
    horizon: str
    n_dates: int
    mean_ic: float
    std_ic: float
    t_stat: float
    pct_positive: float

    # Long-short decile spread (annualized return)
    ls_ann_return: float
    ls_yearly_hit_rate: float
    ls_max_drawdown: float

    @property
    def verdict(self) -> str:
        if self.n_dates < 10:
            return "INSUFFICIENT"
        if abs(self.t_stat) >= 2:
            return "SIGNIFICANT" if self.mean_ic > 0 else "SIG_WRONG_SIGN"
        if abs(self.t_stat) >= 1.5:
            return "marginal"
        return "NO_SIGNAL"

    def to_dict(self):
        return {
            "signal": self.signal,
            "horizon": self.horizon,
            "n_dates": self.n_dates,
            "mean_ic": round(self.mean_ic, 4),
            "std_ic": round(self.std_ic, 4),
            "t_stat": round(self.t_stat, 3),
            "pct_positive": round(self.pct_positive, 1),
            "ls_ann_return": round(self.ls_ann_return, 4),
            "ls_yearly_hit_rate": round(self.ls_yearly_hit_rate, 3),
            "ls_max_drawdown": round(self.ls_max_drawdown, 4),
            "verdict": self.verdict,
        }


def _max_drawdown(cum_curve: np.ndarray) -> float:
    """Max peak-to-trough drawdown on a cumulative-wealth curve (>0)."""
    if len(cum_curve) == 0:
        return 0.0
    peak = np.maximum.accumulate(cum_curve)
    dd = (cum_curve - peak) / peak
    return float(dd.min())


def compute_ic_walkforward(
    panel_per_date: list[tuple[pd.Timestamp, pd.DataFrame]],
    fwd_returns_per_date: list[tuple[pd.Timestamp, pd.Series]],
    horizon_label: str,
    horizon_days: int,
) -> list[SignalIcStats]:
    """
    Walk-forward IC + long-short decile statistics for each signal.

    `panel_per_date[i]` and `fwd_returns_per_date[i]` MUST share the same date.

    Long-short statistics are computed on **non-overlapping** windows so
    compounding stays honest. We sample one rebalance every `horizon_days // 21`
    months (e.g. every 3 months for the 3M horizon, every 12 for 12M). For the
    1M horizon this is every rebalance, which is already non-overlapping.
    """
    # How many monthly rebalances make up one horizon-non-overlap window
    months_per_horizon = max(1, round(horizon_days / 21))

    stats_per_signal = {sig: {
        "ics": [],            # IC computed at every rebalance (overlap is fine for IC)
        "ls_returns": [],     # LS return at non-overlapping samples
        "ls_dates": [],       # corresponding dates
    } for sig in ALL_SIGNAL_NAMES}

    for i, ((date_p, panel), (date_r, fwd)) in enumerate(
        zip(panel_per_date, fwd_returns_per_date)
    ):
        assert date_p == date_r
        common = panel.index.intersection(fwd.index)
        if len(common) < 10:
            continue
        # Non-overlapping flag for LS sampling
        is_ls_sample = (i % months_per_horizon == 0)

        for sig in ALL_SIGNAL_NAMES:
            if sig not in panel.columns:
                continue
            scores = panel.loc[common, sig].astype(float)
            r = fwd.loc[common].astype(float)
            mask = scores.notna() & r.notna()
            scores = scores[mask]
            r = r[mask]
            if len(scores) < 10 or scores.std() < 1e-8:
                continue

            rho, _ = stats.spearmanr(scores, r)
            if not np.isnan(rho):
                stats_per_signal[sig]["ics"].append(float(rho))

            # Long-short decile spread on non-overlapping samples only
            if is_ls_sample and len(scores) >= 20:
                top_threshold = scores.quantile(0.9)
                bot_threshold = scores.quantile(0.1)
                top = r[scores >= top_threshold]
                bot = r[scores <= bot_threshold]
                if len(top) >= 1 and len(bot) >= 1:
                    ls = float(top.mean() - bot.mean())
                    stats_per_signal[sig]["ls_returns"].append(ls)
                    stats_per_signal[sig]["ls_dates"].append(date_p)

    # ── Aggregate to SignalIcStats ──────────────────────────────────
    results: list[SignalIcStats] = []
    for sig in ALL_SIGNAL_NAMES:
        d = stats_per_signal[sig]
        ics = np.array(d["ics"], dtype=float)
        n = int(len(ics))

        if n < 1:
            results.append(SignalIcStats(
                signal=sig, horizon=horizon_label,
                n_dates=0, mean_ic=float("nan"), std_ic=float("nan"),
                t_stat=0.0, pct_positive=0.0,
                ls_ann_return=float("nan"),
                ls_yearly_hit_rate=float("nan"),
                ls_max_drawdown=float("nan"),
            ))
            continue

        mean_ic = float(np.mean(ics))
        std_ic = float(np.std(ics, ddof=1)) if n > 1 else 0.0
        t_stat = mean_ic / (std_ic / math.sqrt(n)) if std_ic > 1e-8 else 0.0
        pct_pos = float(np.mean(ics > 0)) * 100.0

        # Long-short stats on non-overlapping windows
        ls_arr = np.array(d["ls_returns"], dtype=float) if d["ls_returns"] else np.array([])
        ls_dates = d["ls_dates"]
        if len(ls_arr) > 0:
            mean_ls = float(np.mean(ls_arr))
            # Annualize: each LS observation is a horizon-period return.
            # ann = (1 + mean_ls) ** (12 / months_per_horizon) - 1
            periods_per_year = 12.0 / months_per_horizon
            ls_ann = (1 + mean_ls) ** periods_per_year - 1
            # Yearly hit rate (over years that have at least one observation)
            df_ls = pd.DataFrame({"date": ls_dates, "ls": ls_arr})
            df_ls["year"] = pd.to_datetime(df_ls["date"]).dt.year
            yearly = df_ls.groupby("year")["ls"].mean()
            hit_rate = float((yearly > 0).mean()) if len(yearly) > 0 else float("nan")
            # Max DD on cumulative wealth — non-overlapping LS so this
            # compounds honestly
            cum = np.cumprod(1 + ls_arr)
            mdd = _max_drawdown(cum)
        else:
            ls_ann = float("nan")
            hit_rate = float("nan")
            mdd = float("nan")

        results.append(SignalIcStats(
            signal=sig, horizon=horizon_label,
            n_dates=n, mean_ic=mean_ic, std_ic=std_ic,
            t_stat=float(t_stat), pct_positive=pct_pos,
            ls_ann_return=ls_ann, ls_yearly_hit_rate=hit_rate,
            ls_max_drawdown=mdd,
        ))

    return results


# ── Top-level runner ────────────────────────────────────────────────────

def generate_monthly_rebalance_dates(
    start: pd.Timestamp, end: pd.Timestamp, trading_dates: pd.DatetimeIndex,
) -> list[pd.Timestamp]:
    """Last trading day of each month between start and end."""
    candidates = pd.date_range(start, end, freq="BME")
    out = []
    for c in candidates:
        mask = trading_dates <= c
        if mask.any():
            out.append(trading_dates[mask][-1])
    # Dedup + sort
    out = sorted(set(out))
    return out


def run(
    start: str,
    end: str,
    limit_tickers: Optional[int],
    out_dir: str,
) -> dict:
    """Main IC audit run. Returns a result dict (also persisted to disk)."""
    t0 = time.time()
    os.makedirs(out_dir, exist_ok=True)

    # ── Universe ───────────────────────────────────────────────────
    wrds_tickers = set(get_wrds_universe())
    price_tickers = {f.replace(".csv", "")
                     for f in os.listdir(PRICE_CACHE_DIR) if f.endswith(".csv")}
    universe = sorted(wrds_tickers & price_tickers)
    print(f"[universe] WRDS={len(wrds_tickers)}  price-cache={len(price_tickers)}  "
          f"intersection={len(universe)}")

    if limit_tickers is not None:
        universe = universe[:limit_tickers]
        print(f"[universe] --limit-tickers={limit_tickers} -> {len(universe)} tickers")

    universe_data = load_universe_prices(universe)
    print(f"[load] loaded {len(universe_data)} ticker price series")

    # ── Trading date axis from union of all loaded series ──────────
    all_idx = pd.DatetimeIndex(sorted(set().union(*[df.index for df in universe_data.values()])))
    rebalance_dates = generate_monthly_rebalance_dates(
        pd.Timestamp(start), pd.Timestamp(end), all_idx,
    )
    # Keep ample buffer from the right edge so the longest horizon has
    # sufficient forward data (12M = 252 trading days).
    cutoff = all_idx[-1] - pd.tseries.offsets.BDay(max(HORIZONS.values()))
    rebalance_dates = [d for d in rebalance_dates if d <= cutoff]
    print(f"[dates] {len(rebalance_dates)} monthly rebalance dates "
          f"({rebalance_dates[0].date() if rebalance_dates else 'n/a'} -> "
          f"{rebalance_dates[-1].date() if rebalance_dates else 'n/a'})")

    # ── Stores ─────────────────────────────────────────────────────
    store = WRDSPointInTimeStore()
    provider = WRDSFundamentalProvider(store)

    # ── Score panels and forward returns at every rebalance ────────
    panel_per_date: list[tuple[pd.Timestamp, pd.DataFrame]] = []
    fwd_per_horizon: dict[str, list[tuple[pd.Timestamp, pd.Series]]] = {
        h: [] for h in HORIZONS
    }

    for i, d in enumerate(rebalance_dates):
        if i % 12 == 0:
            print(f"[rebalance] {i+1}/{len(rebalance_dates)} {d.date()}")
        panel = compute_signal_panel(universe_data, d, store, provider)
        if panel is None or panel.empty:
            continue
        panel_per_date.append((d, panel))
        for label, hd in HORIZONS.items():
            fwd = compute_forward_returns_panel(universe_data, d, hd)
            fwd_per_horizon[label].append((d, fwd))

    print(f"[score] {len(panel_per_date)} valid rebalance dates")

    # ── IC per horizon ─────────────────────────────────────────────
    full_results = {}
    for label, hd in HORIZONS.items():
        # align panels to fwd lists (same length, same dates)
        fwd_list = fwd_per_horizon[label]
        # Some rebalance dates may have produced empty fwd series — that's OK
        stats_list = compute_ic_walkforward(
            panel_per_date, fwd_list, label, hd,
        )
        full_results[label] = [s.to_dict() for s in stats_list]
        print(f"[ic-{label}] computed for {len(stats_list)} signals")

    # ── Coverage diagnostics ───────────────────────────────────────
    coverage = {}
    for sig in ALL_SIGNAL_NAMES:
        n_dates_total = len(panel_per_date)
        if n_dates_total == 0:
            coverage[sig] = {"avg_tickers_per_date": 0, "pct_dates_with_data": 0}
            continue
        per_date_counts = []
        for _, panel in panel_per_date:
            if sig in panel.columns:
                per_date_counts.append(int(panel[sig].notna().sum()))
            else:
                per_date_counts.append(0)
        coverage[sig] = {
            "avg_tickers_per_date": round(float(np.mean(per_date_counts)), 1),
            "pct_dates_with_data": round(
                float(np.mean(np.array(per_date_counts) > 0)) * 100, 1
            ),
            "max_tickers": int(max(per_date_counts)) if per_date_counts else 0,
        }

    runtime_s = time.time() - t0
    out = {
        "meta": {
            "start": start,
            "end": end,
            "universe_size": len(universe_data),
            "n_rebalance_dates": len(panel_per_date),
            "horizons": HORIZONS,
            "runtime_seconds": round(runtime_s, 1),
            "walk_forward_only": True,
            "cpcv_used": False,
            "wrds_tickers_total": len(wrds_tickers),
            "price_cache_tickers_total": len(price_tickers),
            "intersection_universe_total": len(wrds_tickers & price_tickers),
            "limit_tickers": limit_tickers,
        },
        "coverage": coverage,
        "ic": full_results,
    }

    # ── Persist results ───────────────────────────────────────────
    json_path = os.path.join(out_dir, "ic-results.json")
    with open(json_path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"[write] results -> {json_path}")

    md_path = os.path.join(out_dir, "ic-summary.md")
    with open(md_path, "w") as f:
        f.write(render_summary_md(out))
    print(f"[write] summary -> {md_path}")

    return out


# ── Markdown renderer ───────────────────────────────────────────────────

def render_summary_md(results: dict) -> str:
    meta = results["meta"]
    cov = results["coverage"]
    ic = results["ic"]

    lines = []
    lines.append("# Audit Session 2 — Per-Signal IC Summary")
    lines.append("")
    lines.append(
        f"**Generated**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}  "
    )
    lines.append(
        f"**Window**: {meta['start']} → {meta['end']}  "
        f"**Universe**: {meta['universe_size']} tickers (WRDS ∩ price-cache)  "
    )
    lines.append(
        f"**Rebalance dates**: {meta['n_rebalance_dates']}  "
        f"**Walk-forward only** (no CPCV).  "
        f"**Runtime**: {meta['runtime_seconds']}s"
    )
    lines.append("")

    # Universe note
    lines.append("## Universe Coverage")
    lines.append(
        f"- WRDS PIT cache: {meta['wrds_tickers_total']} tickers"
    )
    lines.append(
        f"- Local price cache: {meta['price_cache_tickers_total']} tickers"
    )
    lines.append(
        f"- Intersection (used for IC): {meta['intersection_universe_total']} tickers"
    )
    if meta.get("limit_tickers"):
        lines.append(
            f"- `--limit-tickers={meta['limit_tickers']}` applied for this run"
        )
    lines.append("")
    lines.append(
        "Tickers in WRDS but missing from the local price cache are "
        "EXCLUDED from the IC universe rather than faked. Per the "
        "`project_silent_zeros` discipline, missing data => NaN, never 0."
    )
    lines.append("")

    # Per-signal coverage
    lines.append("## Per-Signal Coverage")
    lines.append("")
    lines.append("| Signal | Avg tickers/date | Max | % dates with data |")
    lines.append("|---|---:|---:|---:|")
    for sig in ALL_SIGNAL_NAMES:
        c = cov.get(sig, {})
        lines.append(
            f"| `{sig}` | {c.get('avg_tickers_per_date', 0)} | "
            f"{c.get('max_tickers', 0)} | {c.get('pct_dates_with_data', 0)}% |"
        )
    lines.append("")

    # IC tables — one per horizon
    horizon_order = ["1M", "3M", "6M", "12M"]
    for h in horizon_order:
        lines.append(f"## IC at {h} horizon")
        lines.append("")
        lines.append(
            "| Signal | N | Mean IC | Std | t-stat | %pos | LS ann. | "
            "LS hit-rate | LS MaxDD | Verdict |"
        )
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")

        rows = ic.get(h, [])
        # Sort by mean_ic descending (NaN last)
        def _key(r):
            v = r.get("mean_ic")
            if v is None or (isinstance(v, float) and math.isnan(v)):
                return -1e9
            return v
        rows_sorted = sorted(rows, key=_key, reverse=True)
        for r in rows_sorted:
            mic = r.get("mean_ic")
            sic = r.get("std_ic")
            ts = r.get("t_stat")
            pp = r.get("pct_positive")
            ls = r.get("ls_ann_return")
            hr = r.get("ls_yearly_hit_rate")
            mdd = r.get("ls_max_drawdown")

            def fmt(v, pct=False):
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    return "n/a"
                if pct:
                    return f"{v:.1f}%" if not isinstance(v, float) else f"{v*100:.1f}%"
                return f"{v:+.4f}" if isinstance(v, float) else str(v)

            verdict = r.get("verdict", "")
            lines.append(
                f"| `{r['signal']}` | {r['n_dates']} | "
                f"{(f'{mic:+.4f}' if isinstance(mic, (int, float)) and not math.isnan(mic) else 'n/a')} | "
                f"{(f'{sic:.4f}' if isinstance(sic, (int, float)) and not math.isnan(sic) else 'n/a')} | "
                f"{(f'{ts:+.2f}' if isinstance(ts, (int, float)) and not math.isnan(ts) else 'n/a')} | "
                f"{(f'{pp:.0f}%' if isinstance(pp, (int, float)) and not math.isnan(pp) else 'n/a')} | "
                f"{(f'{ls*100:+.1f}%' if isinstance(ls, (int, float)) and not math.isnan(ls) else 'n/a')} | "
                f"{(f'{hr*100:.0f}%' if isinstance(hr, (int, float)) and not math.isnan(hr) else 'n/a')} | "
                f"{(f'{mdd*100:.1f}%' if isinstance(mdd, (int, float)) and not math.isnan(mdd) else 'n/a')} | "
                f"{verdict} |"
            )
        lines.append("")

    # Decision summary
    lines.append("## 3M Decision Summary")
    lines.append("")
    h3 = ic.get("3M", [])
    pio = next((r for r in h3 if r["signal"] == "piotroski"), None)
    pio_ic = pio.get("mean_ic") if pio else None
    if pio_ic is not None and not (isinstance(pio_ic, float) and math.isnan(pio_ic)):
        lines.append(f"**Piotroski floor IC at 3M**: {pio_ic:+.4f}")
        lines.append("")
        lines.append("| Signal | 3M Mean IC | Beats Piotroski? |")
        lines.append("|---|---:|---|")
        sorted_h3 = sorted(
            [r for r in h3 if not (isinstance(r.get("mean_ic"), float)
                                   and math.isnan(r["mean_ic"]))],
            key=lambda r: r["mean_ic"], reverse=True,
        )
        for r in sorted_h3:
            sig = r["signal"]
            if sig in BASELINE_NAMES:
                continue
            mic = r["mean_ic"]
            beats = "**YES**" if mic > pio_ic else "no"
            lines.append(f"| `{sig}` | {mic:+.4f} | {beats} |")
    else:
        lines.append("Piotroski IC unavailable at 3M — see coverage section.")
    lines.append("")

    # Methodology
    lines.append("## Methodology")
    lines.append("")
    lines.append("- **Walk-forward only**, NO CPCV (per user direction).")
    lines.append("- Monthly rebalance dates (last trading day of each month).")
    lines.append("- IC = Spearman rank correlation between signal and forward return.")
    lines.append("- IC is computed at every monthly rebalance (overlap is fine for IC averaging).")
    lines.append("- Long-short = top-decile mean minus bottom-decile mean.")
    lines.append("- LS sampled on **non-overlapping** windows (every horizon-many months).")
    lines.append("- Annualized LS = `(1 + mean_ls) ** (12/horizon_months) - 1` (no overlap-compounding).")
    lines.append("- Yearly hit rate = fraction of calendar years with positive mean LS.")
    lines.append("- t-stat = `mean_ic / (std_ic / sqrt(N))` over rebalance-period ICs.")
    lines.append("- Verdict thresholds: |t|≥2 SIGNIFICANT; |t|≥1.5 marginal; else NO_SIGNAL; N<10 INSUFFICIENT.")
    lines.append("")
    lines.append("## Audit Notes")
    lines.append("")
    lines.append(
        "- `insider_mspr` is INSUFFICIENT: requires Finnhub MSPR cache "
        "which is not on disk locally. Code path is wired through "
        "`compute_insider_scores` and would activate when the cache lands. "
        "Computed coverage above will read 0%."
    )
    lines.append(
        "- The runner uses the **WRDS ∩ price-cache** intersection. To "
        "expand coverage to the full 495 WRDS universe, prefetch prices "
        "(`scripts/prefetch_*.py`) for the missing tickers. Until then, "
        "tickers without price data are EXCLUDED rather than faked."
    )
    lines.append(
        "- Piotroski with <9 valid sub-tests is scaled up linearly to the "
        "[0, 9] range. Documented simplification in `quant/factor_baselines.py`."
    )
    lines.append(
        "- QMJ payout pillar is proxied by ROA (we have no dividend data "
        "in the WRDS PIT store). Documented simplification."
    )

    return "\n".join(lines)


# ── CLI entry ───────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--start", default="2015-01-01")
    p.add_argument("--end", default="2024-12-31")
    p.add_argument("--limit-tickers", type=int, default=None,
                   help="Limit universe size for testing")
    p.add_argument("--out-dir", default=OUT_DIR)
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    run(
        start=args.start,
        end=args.end,
        limit_tickers=args.limit_tickers,
        out_dir=args.out_dir,
    )


if __name__ == "__main__":
    main()
