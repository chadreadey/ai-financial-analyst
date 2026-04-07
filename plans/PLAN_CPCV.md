# CPCV Implementation Plan

Combinatorial Purged Cross-Validation (Lopez de Prado, 2018) — must be in place BEFORE testing WRDS fundamentals, IBES revisions, or short signals.

## Why Before WRDS

The current 8-window walk-forward tests ONE historical path. We've already tuned against it (shorts disabled, weights adjusted, sentiment weight chosen). Adding WRDS fundamentals on top of this framework would repeat the same mistake — tuning to one path. CPCV generates hundreds of paths from the same data and computes the Probability of Backtest Overfitting (PBO).

## What CPCV Produces

1. **PBO** — fraction of combinations where the strategy underperforms OOS. PBO > 0.50 means the strategy is likely overfit.
2. **Deflated Sharpe Ratio (DSR)** — adjusts observed Sharpe for number of trials. DSR > 0 means the Sharpe is unlikely to be noise.
3. **OOS Sharpe distribution** — 252-924 unique Sharpe values from different train/test splits. Shows how robust the edge is.

## Validation Gate

After CPCV is implemented:
1. Run on gold standard config → get baseline PBO and DSR
2. When WRDS fundamentals are added → re-run CPCV
3. **Gate:** DSR should increase and PBO should not increase. If PBO rises, the new signal is adding noise.

---

## Phase 1: Core CPCV Engine (Medium)

**Depends on:** Nothing
**Deliverable:** `quant/cpcv.py` with group splitting, combination generation, purge/embargo, PBO, DSR

### Create: `quant/cpcv.py`

```python
def make_cpcv_groups(start_date, end_date, n_groups, trading_dates)
    -> list[tuple[pd.Timestamp, pd.Timestamp]]
    # Divide timeline into n_groups contiguous equal-length groups

def generate_cpcv_combinations(n_groups, n_test_groups)
    -> list[tuple[list[int], list[int]]]
    # All C(n_groups, n_test_groups) combinations
    # For n=12, k=6: 924 combinations
    # For n=10, k=5: 252 combinations

def apply_purge_embargo(
    train_boundaries, test_boundaries,
    purge_months=1, embargo_months=1, trading_dates
) -> tuple[list[Timestamp], list[Timestamp]]
    # Remove rebalance dates near boundaries (purge)
    # Remove test dates within embargo_months after last train date
    # Guard: if safe_test_dates < 2, skip combination

def compute_pbo(oos_sharpes) -> float
    # PBO = fraction of paths with OOS Sharpe <= 0
    # When IS Sharpes available (IC-on): use IS-optimal method
    # When IC-off: use OOS-negative-fraction (conservative)

def compute_deflated_sharpe(
    observed_sharpe, n_trials, oos_sharpes, n_obs, skewness, kurtosis
) -> float
    # Lopez de Prado DSR formula

@dataclass
class CPCVResult:
    n_groups: int
    n_combinations: int
    n_combinations_completed: int
    purge_months: int
    embargo_months: int
    oos_sharpes: list[float]
    is_sharpes: list[float]       # empty if IC-off
    pbo: float
    pbo_method: str               # "is_optimal" or "oos_negative_fraction"
    median_oos_sharpe: float
    mean_oos_sharpe: float
    std_oos_sharpe: float
    pct_positive_oos: float
    deflated_sharpe_ratio: float
    combination_details: list[dict]
    elapsed_seconds: float
```

### Verify
Unit test: `make_cpcv_groups("2020-01-01", "2025-12-31", 10, trading_dates)` → 10 groups of ~7.5 months each. `generate_cpcv_combinations(10, 5)` → 252 combinations.

---

## Phase 2: CPCV Runner in backtest.py (High)

**Depends on:** Phase 1
**Deliverable:** `run_cpcv()` function that uses the existing backtest engine

### Modify: `quant/backtest.py`

Add `run_cpcv(config, n_groups, n_test_groups, purge_months, embargo_months, max_combinations, n_workers, progress_cb) -> CPCVResult`

**Structure:**
1. Load universe data ONCE (same pattern as `run_walk_forward` lines 1882-1946)
2. Build trading_dates index from loaded data
3. Generate groups and combinations via `quant/cpcv.py`
4. For each combination:
   a. Compute group boundaries for train/test indices
   b. Merge test groups into rebalance date list (may be non-contiguous)
   c. Apply purge/embargo → safe_test_dates
   d. Run inner signal loop on safe_test_dates (same as walk-forward inner loop)
   e. **Non-contiguous handling:** Each test group resets capital to `initial_capital`. Pool daily returns across all test segments for Sharpe.
   f. Record OOS Sharpe for this combination
5. Compute PBO and DSR from collected Sharpes
6. Return CPCVResult

**Critical: inner loop duplication risk.** Both `run_walk_forward` and `run_cpcv` duplicate the signal→overlay→portfolio loop. Add `# SYNC WITH run_walk_forward` comment. Future refactor: extract `_run_period()` helper.

### Verify
Run with `n_groups=6, max_combinations=5` on liquid_10 2020-2026. Confirm 5 OOS Sharpes returned, PBO computed, elapsed < 5 minutes.

---

## Phase 3: CLI Integration (Small)

**Depends on:** Phase 2
**Deliverable:** `--cpcv` flag on `run_backtest.py`

### Modify: `scripts/run_backtest.py`

New arguments:
```
--cpcv                   Run CPCV validation
--n-groups 12            Number of time groups (default: 10 for 2020+, 12 for 2013+)
--n-test-groups 0        Test groups per combo (0 = n_groups // 2)
--purge-months 1         Purge window at train/test boundaries
--embargo-months 1       Embargo after training period
--cpcv-max-combos 0      0 = all combinations; N = random sample N (seed=42)
--cpcv-workers 1         Parallel workers
```

Add `print_cpcv_summary(result)`:
```
  CPCV VALIDATION RESULTS
  252 combinations (10 groups, 5 test)
  Purge: 1 month | Embargo: 1 month

  PBO:                    0.23 (oos_negative_fraction)
  Deflated Sharpe Ratio:  0.81
  Median OOS Sharpe:      1.14
  Mean OOS Sharpe:        0.98
  Std OOS Sharpe:         0.43
  Pct Positive:          77.0%

  OOS Sharpe Distribution:
  [-0.5, 0.0)  ████████  23%
  [ 0.0, 0.5)  ██████████████  15%
  [ 0.5, 1.0)  ████████████████████  28%
  [ 1.0, 1.5)  ██████████████████  22%
  [ 1.5, 2.0+) ██████████  12%
```

Output JSON has `"cpcv"` key alongside existing backtest output.

### Verify
```bash
python scripts/run_backtest.py --universe liquid_10 --start 2020-01-01 --cpcv --n-groups 6 --cpcv-max-combos 20 --no-ic-calibration --no-shorts
```
Expect: 20 combinations, PBO printed, output JSON with `cpcv.oos_sharpe_distribution`.

---

## Phase 4: Parallelization (Medium, Optional)

**Depends on:** Phase 2
**Deliverable:** Multi-core CPCV for full 924-combination runs

C(12,6) = 924 combinations × ~50s each = ~13 hours single-core. With 8 workers: ~1.5 hours.

### Approach
- `concurrent.futures.ProcessPoolExecutor`
- Serialize `universe_data` to temp parquet before spawning
- Module-level `_run_one_cpcv_combination(args_tuple)` for pickling
- Each worker re-reads parquet + VIX CSV (no shared state)
- `pool.imap_unordered` for progress tracking

### Verify
Run full C(10,5)=252 with `--cpcv-workers 4`. Compare results to single-core sample — Sharpe distribution should be statistically identical.

---

## Parameter Recommendations

| Date Range | N Groups | N Test | Combinations | Est. Time (1 core) | Est. Time (8 cores) |
|-----------|----------|--------|-------------|--------------------|--------------------|
| 2020-2026 (75mo) | 10 | 5 | 252 | ~3.5 hrs | ~30 min |
| 2013-2026 (156mo, WRDS) | 12 | 6 | 924 | ~13 hrs | ~1.5 hrs |
| Quick validation | 6 | 3 | 20 | ~20 min | ~5 min |

- **Purge = 1 month** — covers 21-day holding period label leakage
- **Embargo = 1 month** — conservative; serial correlation in monthly signals minimal beyond 1 month
- **Sampling:** Use `--cpcv-max-combos 50` for fast iteration, full run for final validation

---

## Risk Log

| Risk | Mitigation |
|------|-----------|
| Inner loop diverges from `run_walk_forward` | `# SYNC` comment; future refactor to shared `_run_period()` helper |
| Non-contiguous test groups inflate Sharpe | Reset capital per test group; pool daily returns for single Sharpe |
| Short test groups lose all dates to purge/embargo | Guard: skip combination if `safe_test_dates < 2`; count in `n_combinations_completed` |
| PBO meaningless without IS Sharpes (IC off) | Use `oos_negative_fraction` method; annotate `pbo_method` in results |
| 924 combos impractical single-core | Phase 4 parallelization; `max_combinations` sampling for development |

---

## Execution Order

```
Phase 1 (cpcv.py)        ← START HERE
    ↓
Phase 2 (run_cpcv)
    ↓
Phase 3 (CLI)            ← VALIDATION GATE: run on gold standard before WRDS
    ↓
Phase 4 (parallel)       ← needed for full runs with WRDS 2013-2026
    ↓
WRDS Integration Plan    ← proceeds only if PBO < 0.40
```
