"""
Combinatorial Purged Cross-Validation (CPCV).

Implementation of Lopez de Prado's CPCV framework from
"Advances in Financial Machine Learning" (2018).

Generates multiple train/test paths from the same data to compute:
  - Probability of Backtest Overfitting (PBO)
  - Deflated Sharpe Ratio (DSR)
  - OOS Sharpe distribution across all combinatorial paths

Usage:
    groups = make_cpcv_groups("2020-01-01", "2026-01-01", n_groups=10, trading_dates=dates)
    combos = generate_cpcv_combinations(n_groups=10, n_test_groups=5)
    for train_idx, test_idx in combos:
        train_dates, test_dates = apply_purge_embargo(
            groups, train_idx, test_idx, purge_months=1, embargo_months=1, trading_dates=dates
        )
        # run backtest on test_dates, record Sharpe
    pbo = compute_pbo(oos_sharpes)
    dsr = compute_deflated_sharpe(...)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from itertools import combinations
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def make_cpcv_groups(
    start_date: str,
    end_date: str,
    n_groups: int,
    trading_dates: pd.DatetimeIndex,
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """
    Divide [start_date, end_date] into n_groups contiguous equal-length groups.

    Groups are defined by calendar interval, then snapped to trading days.
    Returns list of (group_start, group_end) tuples.
    """
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)

    # Generate n_groups+1 boundary points evenly spaced
    boundaries = pd.date_range(start, end, periods=n_groups + 1)

    # Snap each boundary to nearest trading day
    snapped = []
    for b in boundaries:
        mask = trading_dates <= b
        if mask.any():
            snapped.append(trading_dates[mask][-1])
        else:
            snapped.append(trading_dates[0])

    groups = []
    for i in range(n_groups):
        g_start = snapped[i]
        g_end = snapped[i + 1]
        groups.append((g_start, g_end))

    return groups


def generate_cpcv_combinations(
    n_groups: int,
    n_test_groups: int = 0,
) -> list[tuple[list[int], list[int]]]:
    """
    Generate all C(n_groups, n_test_groups) train/test combinations.

    Args:
        n_groups: Total number of time groups
        n_test_groups: Number of groups assigned to test. Defaults to n_groups // 2.

    Returns:
        List of (train_indices, test_indices) tuples.
        For n=12, k=6: 924 combinations.
        For n=10, k=5: 252 combinations.
    """
    if n_test_groups <= 0:
        n_test_groups = n_groups // 2

    all_indices = list(range(n_groups))
    result = []
    for test_combo in combinations(all_indices, n_test_groups):
        test_idx = list(test_combo)
        train_idx = [i for i in all_indices if i not in test_combo]
        result.append((train_idx, test_idx))

    return result


def apply_purge_embargo(
    groups: list[tuple[pd.Timestamp, pd.Timestamp]],
    train_indices: list[int],
    test_indices: list[int],
    rebalance_dates: list[pd.Timestamp],
    purge_months: int = 1,
    embargo_months: int = 1,
) -> tuple[list[pd.Timestamp], list[pd.Timestamp]]:
    """
    Filter rebalance dates with purge and embargo for one CPCV combination.

    Purge: Remove rebalance dates within purge_months of any train/test
    boundary to prevent label leakage (forward returns from train period
    overlapping into test period).

    Embargo: Remove test dates within embargo_months after the end of
    any training group to prevent serial correlation leakage.

    Args:
        groups: Output of make_cpcv_groups
        train_indices: Group indices assigned to training
        test_indices: Group indices assigned to testing
        rebalance_dates: All candidate rebalance dates
        purge_months: Months to purge around boundaries
        embargo_months: Months to embargo after training ends

    Returns:
        (safe_train_dates, safe_test_dates) — filtered rebalance date lists.
        Either may be empty if purge/embargo removes all dates.
    """
    purge_delta = pd.DateOffset(months=purge_months)
    embargo_delta = pd.DateOffset(months=embargo_months)

    train_groups = [groups[i] for i in train_indices]
    test_groups = [groups[i] for i in test_indices]

    # Collect all train/test boundary dates where a train group
    # is adjacent to a test group
    boundary_dates = set()
    train_set = set(train_indices)
    test_set = set(test_indices)
    for i in range(len(groups) - 1):
        # A boundary exists where group i and group i+1 are in different sets
        if (i in train_set and (i + 1) in test_set) or \
           (i in test_set and (i + 1) in train_set):
            boundary_dates.add(groups[i][1])  # end of group i = start of group i+1

    # Build purge zones: +/- purge_months around each boundary
    def in_purge_zone(date: pd.Timestamp) -> bool:
        for bd in boundary_dates:
            if (bd - purge_delta) <= date <= (bd + purge_delta):
                return True
        return False

    # Build embargo zones: embargo_months after each train group end
    # that borders a test group
    embargo_ends = []
    for i in train_indices:
        g_end = groups[i][1]
        # Check if the next group is a test group
        if (i + 1) in test_set:
            embargo_ends.append(g_end + embargo_delta)

    def in_embargo_zone(date: pd.Timestamp) -> bool:
        for i in train_indices:
            g_end = groups[i][1]
            if (i + 1) in test_set:
                if g_end < date <= (g_end + embargo_delta):
                    return True
        return False

    # Assign rebalance dates to train or test based on group membership
    train_dates_raw = []
    test_dates_raw = []
    for d in rebalance_dates:
        for i in train_indices:
            g_start, g_end = groups[i]
            if g_start <= d <= g_end:
                train_dates_raw.append(d)
                break
        for i in test_indices:
            g_start, g_end = groups[i]
            if g_start <= d <= g_end:
                test_dates_raw.append(d)
                break

    # Apply purge to both train and test
    safe_train = [d for d in train_dates_raw if not in_purge_zone(d)]
    safe_test = [d for d in test_dates_raw if not in_purge_zone(d) and not in_embargo_zone(d)]

    return sorted(safe_train), sorted(safe_test)


def compute_pbo(
    oos_sharpes: list[float],
    is_sharpes: Optional[list[float]] = None,
) -> tuple[float, str]:
    """
    Compute Probability of Backtest Overfitting.

    Two methods:
    1. IS-optimal (when is_sharpes available): For each combination, check if
       the IS-optimal strategy (highest train Sharpe) has OOS Sharpe <= 0.
       PBO = fraction where this holds.
    2. OOS-negative-fraction (when IC is off, no IS evaluation):
       PBO = fraction of all OOS paths with Sharpe <= 0.
       This is a conservative approximation.

    Returns (pbo, method_name).
    """
    if not oos_sharpes:
        return 1.0, "no_data"

    if is_sharpes and len(is_sharpes) == len(oos_sharpes):
        # IS-optimal method: rank by IS performance, check if best IS
        # strategies also perform well OOS
        pairs = list(zip(is_sharpes, oos_sharpes))
        # Sort by IS Sharpe descending
        pairs.sort(key=lambda x: x[0], reverse=True)
        # The IS-optimal strategy is pairs[0]
        # But PBO is actually: across all possible "best IS" selections,
        # what fraction have OOS <= 0?
        # Simplified: use the logit approach from Lopez de Prado
        # For practical purposes, compute the rank correlation:
        n = len(pairs)
        n_overfit = sum(1 for is_s, oos_s in pairs[:n // 2] if oos_s <= 0)
        pbo = n_overfit / max(n // 2, 1)
        return pbo, "is_optimal"
    else:
        # Conservative: fraction of OOS paths with non-positive Sharpe
        n_negative = sum(1 for s in oos_sharpes if s <= 0)
        pbo = n_negative / len(oos_sharpes)
        return pbo, "oos_negative_fraction"


def _expected_max_sharpe(n_trials: int, std_sharpe: float) -> float:
    """
    Expected maximum Sharpe under the null hypothesis (all strategies
    have true Sharpe = 0). From Bailey & Lopez de Prado (2014).

    E[max(SR)] ≈ std * ((1 - γ) * Φ^{-1}(1 - 1/N) + γ * Φ^{-1}(1 - 1/(N*e)))

    Simplified approximation: E[max] ≈ std * sqrt(2 * log(N))
    """
    if n_trials <= 1 or std_sharpe <= 0:
        return 0.0
    return std_sharpe * math.sqrt(2.0 * math.log(n_trials))


def compute_deflated_sharpe(
    observed_sharpe: float,
    n_trials: int,
    n_obs: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
    std_sharpe: float = 1.0,
) -> float:
    """
    Deflated Sharpe Ratio (Lopez de Prado, 2014).

    Tests whether the observed Sharpe is statistically significant
    after adjusting for the number of trials (strategies tested).

    DSR = (SR_observed - E[max(SR)]) / SE(SR)

    where SE(SR) accounts for non-normal return distribution
    (skewness and kurtosis).

    Args:
        observed_sharpe: Best observed OOS Sharpe
        n_trials: Number of strategy configurations tested
        n_obs: Number of return observations
        skewness: Return distribution skewness (0 = normal)
        kurtosis: Return distribution kurtosis (3 = normal)
        std_sharpe: Standard deviation of Sharpe across trials

    Returns:
        DSR value. > 0 indicates Sharpe is unlikely due to chance.
    """
    if n_obs <= 1 or n_trials <= 0:
        return 0.0

    # Expected max Sharpe under null
    e_max_sr = _expected_max_sharpe(n_trials, std_sharpe)

    # Standard error of the Sharpe ratio (Lo, 2002) with
    # non-normality correction (Bailey & Lopez de Prado)
    se_sr = math.sqrt(
        (1.0
         - skewness * observed_sharpe
         + ((kurtosis - 1.0) / 4.0) * observed_sharpe ** 2)
        / (n_obs - 1.0)
    )

    if se_sr <= 0:
        return 0.0

    dsr = (observed_sharpe - e_max_sr) / se_sr
    return round(dsr, 4)


def compute_sharpe_from_returns(
    daily_returns: pd.Series,
    annual_factor: float = 252.0,
) -> Optional[float]:
    """Compute annualized Sharpe from a daily return series."""
    if daily_returns is None or len(daily_returns) < 2:
        return None
    mean_ret = daily_returns.mean()
    std_ret = daily_returns.std()
    if std_ret == 0 or np.isnan(std_ret):
        return None
    return round(float(mean_ret / std_ret * math.sqrt(annual_factor)), 2)


@dataclass
class CPCVResult:
    """Results of a CPCV validation run."""

    n_groups: int = 0
    n_test_groups: int = 0
    n_combinations: int = 0
    n_combinations_completed: int = 0
    n_combinations_skipped: int = 0
    purge_months: int = 1
    embargo_months: int = 1

    # Per-combination Sharpe distributions
    oos_sharpes: list[float] = field(default_factory=list)
    is_sharpes: list[float] = field(default_factory=list)

    # Aggregate statistics
    pbo: float = 1.0
    pbo_method: str = "no_data"
    median_oos_sharpe: float = 0.0
    mean_oos_sharpe: float = 0.0
    std_oos_sharpe: float = 0.0
    pct_positive_oos: float = 0.0
    deflated_sharpe_ratio: float = 0.0

    # Detail
    combination_details: list[dict] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    error: Optional[str] = None

    def compute_summary_stats(self) -> None:
        """Compute aggregate stats from oos_sharpes. Call after all combos are run."""
        if not self.oos_sharpes:
            return

        arr = np.array(self.oos_sharpes)
        self.median_oos_sharpe = round(float(np.median(arr)), 4)
        self.mean_oos_sharpe = round(float(np.mean(arr)), 4)
        self.std_oos_sharpe = round(float(np.std(arr)), 4)
        self.pct_positive_oos = round(float(np.mean(arr > 0) * 100), 1)

        self.pbo, self.pbo_method = compute_pbo(
            self.oos_sharpes,
            self.is_sharpes if self.is_sharpes else None,
        )

        # DSR: use the median OOS Sharpe as the "observed" Sharpe
        # (more robust than max, which is what you'd claim)
        # n_obs: approximate monthly observations across test groups
        n_obs = max(len(self.oos_sharpes), 10)
        self.deflated_sharpe_ratio = compute_deflated_sharpe(
            observed_sharpe=self.median_oos_sharpe,
            n_trials=self.n_combinations,
            n_obs=n_obs,
            skewness=float(pd.Series(arr).skew()) if len(arr) > 2 else 0.0,
            kurtosis=float(pd.Series(arr).kurtosis() + 3) if len(arr) > 2 else 3.0,
            std_sharpe=self.std_oos_sharpe if self.std_oos_sharpe > 0 else 1.0,
        )

    def to_dict(self) -> dict:
        return {
            "n_groups": self.n_groups,
            "n_test_groups": self.n_test_groups,
            "n_combinations": self.n_combinations,
            "n_combinations_completed": self.n_combinations_completed,
            "n_combinations_skipped": self.n_combinations_skipped,
            "purge_months": self.purge_months,
            "embargo_months": self.embargo_months,
            "pbo": self.pbo,
            "pbo_method": self.pbo_method,
            "median_oos_sharpe": self.median_oos_sharpe,
            "mean_oos_sharpe": self.mean_oos_sharpe,
            "std_oos_sharpe": self.std_oos_sharpe,
            "pct_positive_oos": self.pct_positive_oos,
            "deflated_sharpe_ratio": self.deflated_sharpe_ratio,
            "oos_sharpes": self.oos_sharpes,
            "is_sharpes": self.is_sharpes,
            "combination_details": self.combination_details,
            "elapsed_seconds": self.elapsed_seconds,
            "error": self.error,
        }

    def print_summary(self) -> str:
        """Return formatted summary string."""
        lines = [
            "",
            "=" * 70,
            "  CPCV VALIDATION RESULTS",
            "=" * 70,
            "",
            f"  Groups: {self.n_groups} | Test groups: {self.n_test_groups}",
            f"  Combinations: {self.n_combinations_completed}/{self.n_combinations}"
            f" ({self.n_combinations_skipped} skipped)",
            f"  Purge: {self.purge_months} month | Embargo: {self.embargo_months} month",
            "",
            f"  PBO:                   {self.pbo:8.2%}  ({self.pbo_method})",
            f"  Deflated Sharpe Ratio: {self.deflated_sharpe_ratio:8.4f}",
            "",
            f"  Median OOS Sharpe:     {self.median_oos_sharpe:8.4f}",
            f"  Mean OOS Sharpe:       {self.mean_oos_sharpe:8.4f}",
            f"  Std OOS Sharpe:        {self.std_oos_sharpe:8.4f}",
            f"  Pct Positive:          {self.pct_positive_oos:7.1f}%",
        ]

        # ASCII histogram of OOS Sharpe distribution
        if self.oos_sharpes:
            lines.append("")
            lines.append("  OOS Sharpe Distribution:")
            arr = np.array(self.oos_sharpes)
            bins = [(-999, -0.5), (-0.5, 0.0), (0.0, 0.5), (0.5, 1.0),
                    (1.0, 1.5), (1.5, 2.0), (2.0, 999)]
            labels = ["< -0.5", "-0.5–0.0", " 0.0–0.5", " 0.5–1.0",
                      " 1.0–1.5", " 1.5–2.0", "  2.0+  "]
            max_bar = 40
            counts = [int(np.sum((arr > lo) & (arr <= hi))) for lo, hi in bins]
            max_count = max(counts) if max(counts) > 0 else 1
            for label, count in zip(labels, counts):
                bar_len = int(count / max_count * max_bar)
                pct = count / len(arr) * 100
                lines.append(f"  {label} {'█' * bar_len} {pct:4.0f}% ({count})")

        lines.append("")
        lines.append(f"  Elapsed: {self.elapsed_seconds:.1f}s")
        lines.append("=" * 70)

        return "\n".join(lines)
