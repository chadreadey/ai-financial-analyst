# Plan: XGBoost Meta-Model for Signal Combination

**Goal:** Replace hand-tuned linear signal weights with a learned XGBoost ranker that discovers optimal non-linear signal combinations, validated via CPCV.

**Baseline to beat:** Linear blend (OBV×1.0 + ERM×0.40 + SUE×0.35 + Dispersion×0.25 + InstFlow×0.15), VIX 30/40 regime, Sharpe 1.04, PBO 0%.

**Key constraint:** No tuning from observed results. The model must be validated on 2020–2026 OOS via CPCV before it touches the live pipeline.

---

## Architecture

```
                    ┌──────────────────────────────────────┐
                    │     Per-Ticker Feature Vector         │
                    │                                      │
                    │  obv_trend_score      [-1, +1]       │
                    │  erm_score            [-1, +1]       │
                    │  sue_score            [-1, +1]       │
                    │  dispersion_score     [-1, +1]       │
                    │  inst_flow_score      [-1, +1]       │
                    │  atr_pct              continuous      │
                    │  volatility_regime    {0, 1, 2}      │
                    │  sentiment_score      [-1, +1] (opt) │
                    │  vix_level            continuous      │
                    │  regime_level         {0..4}         │
                    └───────────────┬──────────────────────┘
                                    │
                          ┌─────────▼──────────┐
                          │  XGBRanker          │
                          │  objective=         │
                          │    rank:pairwise    │
                          │  max_depth=3        │
                          │  n_estimators=200   │
                          │  subsample=0.7      │
                          └─────────┬──────────┘
                                    │
                          ┌─────────▼──────────┐
                          │  Ranking Score      │
                          │  (replaces          │
                          │   composite_score)  │
                          └────────────────────┘
```

**Linear blend stays as fallback.** Every backtest run reports both Sharpe numbers. If XGBoost doesn't beat linear OOS through CPCV, the linear blend remains primary.

---

## Phase 1: Feature Matrix Builder

**Purpose:** Extract per-ticker, per-date feature rows from the existing signal pipeline. This is the dataset XGBoost trains on.

**Depends on:** Nothing — uses existing signal infrastructure.

### Files to Create

- `quant/xgb_features.py` — Feature extraction from SignalVector + overlay scores
  - `build_feature_row(ticker, sv, earnings_entry, inst_entry, sentiment_entry, regime, vix) → dict`
    - Extracts: `obv_trend_score`, `erm_score`, `sue_score`, `dispersion_score`, `inst_flow_score`, `atr_pct`, `volatility_regime` (encoded 0/1/2), `sentiment_score`, `vix_level`, `regime_level` (encoded 0–4)
    - All inputs are existing objects from the backtest loop
  - `build_feature_matrix(universe_data, rebalance_dates, config, ...) → pd.DataFrame`
    - Loops over rebalance dates, calls `compute_signals_at_date` + earnings/inst/sentiment scoring
    - Computes 21-day forward returns per ticker as the label column (`fwd_21d_return`)
    - Returns DataFrame: rows = (date, ticker), columns = features + label
    - Attaches `qid` column (group ID for LambdaMART) = integer-encoded rebalance date
  - `save_feature_matrix(df, path)` / `load_feature_matrix(path)` — CSV persistence so you don't rebuild every time

### Files to Modify

- `quant/backtest.py` — No changes in Phase 1 (feature builder is standalone)

### Verification

```bash
python -c "
from quant.xgb_features import build_feature_matrix
from quant.backtest import BacktestConfig, load_universe_data
# ... load 50 tickers, 2020-2026
# fm = build_feature_matrix(...)
# assert fm.shape[0] > 1000  # ~50 tickers × ~72 months
# assert 'fwd_21d_return' in fm.columns
# assert 'qid' in fm.columns
"
```

---

## Phase 2: XGBoost Ranker Training

**Purpose:** Train XGBRanker with pairwise objective on the feature matrix, with proper time-series train/test splits.

**Depends on:** Phase 1 complete.

### Files to Create

- `quant/xgb_ranker.py` — Training, prediction, and model persistence
  - `XGBMetaModel` class:
    - `__init__(params=None)` — defaults to conservative hyperparams:
      ```
      objective = "rank:pairwise"
      max_depth = 3
      n_estimators = 200
      learning_rate = 0.05
      subsample = 0.7
      colsample_bytree = 0.8
      min_child_weight = 10
      reg_alpha = 1.0
      reg_lambda = 1.0
      ```
    - `fit(X_train, y_train, qid_train)` — wraps `xgb.XGBRanker.fit()`
    - `predict(X) → np.ndarray` — returns ranking scores (higher = better)
    - `feature_importance() → dict[str, float]` — gain-based importance
    - `save(path)` / `load(path)` — JSON model persistence via `save_model()`
  - `train_with_temporal_split(feature_matrix, train_end_date, val_months=6) → XGBMetaModel, dict`
    - Splits by date: everything before `train_end_date` = train, next `val_months` = validation
    - Returns fitted model + validation metrics (nDCG@10, Spearman IC, top-decile return)
    - **No lookahead:** validation period is always after training period

### Dependencies to Add

- `requirements.txt`: `xgboost>=2.0`

### Config to Add

- `quant/backtest.py` `BacktestConfig`:
  ```python
  enable_xgb_ranker: bool = False
  xgb_model_path: str = ""       # path to saved model (empty = train from scratch)
  xgb_train_months: int = 48     # months of history to train on
  xgb_retrain_freq: int = 12     # retrain every N rebalance periods
  ```

### Verification

```bash
python -c "
from quant.xgb_ranker import XGBMetaModel, train_with_temporal_split
from quant.xgb_features import load_feature_matrix
fm = load_feature_matrix('.xgb_features.csv')
model, metrics = train_with_temporal_split(fm, '2024-01-01', val_months=6)
print(f'Val nDCG@10: {metrics[\"ndcg_10\"]:.4f}')
print(f'Val IC: {metrics[\"spearman_ic\"]:.4f}')
print(model.feature_importance())
"
```

---

## Phase 3: CPCV Validation

**Purpose:** Run the XGBoost ranker through CPCV to measure PBO and OOS Sharpe distribution. This is the go/no-go gate.

**Depends on:** Phase 1 + Phase 2 complete.

### Files to Create

- `quant/xgb_cpcv.py` — CPCV harness for the XGBoost ranker
  - `run_xgb_cpcv(feature_matrix, universe_data, config, n_groups=12, n_test_groups=6) → CPCVResult`
    - For each CPCV combination:
      1. Train XGBMetaModel on train dates from the feature matrix
      2. Predict ranking scores on test dates
      3. Build portfolio (top-decile long, bottom-decile short) using XGB ranks instead of linear composite
      4. Compute OOS Sharpe for this combination
    - Uses existing `apply_purge_embargo()` from `cpcv.py`
    - Returns `CPCVResult` with XGB-specific metadata (feature importance per fold, nDCG per fold)
  - `compare_xgb_vs_linear(xgb_cpcv_result, linear_cpcv_result) → str`
    - Side-by-side comparison: PBO, median OOS Sharpe, Sharpe distribution overlap
    - Renders as formatted text report

### Files to Modify

- None — this is a standalone validation script. It imports from `cpcv.py` but doesn't modify it.

### Verification

Run CPCV with 12 groups / 6 test (924 combinations). Gate criteria:
- XGB PBO ≤ linear PBO
- XGB median OOS Sharpe ≥ linear median OOS Sharpe
- Feature importance: no single feature > 60% (would indicate overfitting to one signal)

```bash
python -m quant.xgb_cpcv --start 2020-01-01 --end 2026-01-01 --groups 12
```

---

## Phase 4: Backtest Integration

**Purpose:** Wire XGBoost ranking into the main backtest loop as an alternative to linear blending. Both modes run side-by-side.

**Depends on:** Phase 3 passes the CPCV gate.

### Files to Modify

- **`quant/backtest.py`** — Add XGBoost ranking path in the rebalance loop
  - After all individual signals are computed (line ~1834, after institutional flow blend):
    ```python
    if config.enable_xgb_ranker:
        # Build feature row for each ticker from current signals + overlays
        # Predict ranking score via XGBMetaModel
        # Override sv.composite_score with XGB ranking score (normalized to [-1, +1])
        # Reclassify all SignalVectors
    ```
  - The XGB path **replaces** the linear blend weights but **keeps** all the individual signal computations unchanged. It consumes the same inputs (OBV score, ERM score, etc.) and produces a composite_score.
  - Linear blend remains the default path when `enable_xgb_ranker=False`.
  - When XGB is enabled, add `xgb_rank` to each SignalVector's flags for audit trail.

- **`quant/backtest.py` `BacktestConfig`** — Add fields (from Phase 2 config section)

- **`quant/backtest.py` `run_backtest()`** — Add model loading/training logic:
  - If `xgb_model_path` is set → load pre-trained model
  - Else → train from scratch using first `xgb_train_months` of data
  - Retrain every `xgb_retrain_freq` periods (rolling window)

- **`quant/signals.py` `SignalVector`** — Add field:
  ```python
  xgb_rank_score: float = 0.0  # populated when XGB ranker is active
  ```

### Integration Risks

1. **SignalVector mutation order** — XGB must run AFTER all individual signals are computed but BEFORE regime filtering and portfolio construction. The current blend chain is: IC weights → LSTM → sentiment → fundamentals → earnings → inst_flow → FOMC → regime. XGB replaces the entire blend chain (IC weights through inst_flow) but still respects FOMC proximity and regime filtering.

2. **Retraining during backtest** — Each retrain call builds a feature matrix from past data. This must not include any future data. The `build_feature_matrix()` function must be called with `end_date=reb_date` to prevent lookahead.

3. **Score normalization** — XGBRanker outputs raw ranking scores (unbounded). These must be cross-sectionally normalized to [-1, +1] (via rank percentile → linear map) before being assigned to `composite_score`, since downstream portfolio construction and scoring thresholds depend on this range.

### Verification

```bash
# Run both modes on same universe, compare
python run_backtest.py --tickers SP50 --start 2020-01-01 --end 2026-01-01 \
  --enable-xgb-ranker --cpcv
python run_backtest.py --tickers SP50 --start 2020-01-01 --end 2026-01-01 \
  --cpcv
# Compare Sharpe, PBO, alpha side by side
```

---

## Phase 5: Feature Importance Monitoring

**Purpose:** Track which signals the model relies on over time. Catch drift and ensure no single signal dominates.

**Depends on:** Phase 4 complete.

### Files to Create

- `quant/xgb_monitoring.py` — Feature importance tracking
  - `log_feature_importance(model, reb_date, path=".xgb_importance_log.csv")`
    - Appends one row per rebalance with gain-based importance for each feature
  - `detect_importance_drift(log_path, window=6) → list[str]`
    - Alerts if any feature's importance changed by >20pp over `window` periods
    - Alerts if any feature > 50% importance (single-signal overfitting)
  - `print_importance_report(log_path) → str`
    - Time-series chart of feature importance (ASCII sparklines)

### Files to Modify

- `quant/backtest.py` — Call `log_feature_importance()` after each retrain

### Verification

After a full backtest run, inspect `.xgb_importance_log.csv`:
- No feature > 50% in any period
- Importance distribution is relatively stable across time

---

## Implementation Order (Effort vs Impact)

| Priority | Phase | Effort | Impact | Notes |
|----------|-------|--------|--------|-------|
| 1 | Phase 1: Feature Matrix | Medium | Foundation | Must exist before anything else. Can be verified independently. |
| 2 | Phase 2: XGBoost Ranker | Low | Core | Small file, mostly wraps xgboost API. Conservative defaults. |
| 3 | Phase 3: CPCV Validation | Medium | **Go/no-go gate** | If XGB fails CPCV, stop here. No wasted integration work. |
| 4 | Phase 4: Backtest Integration | Medium | High | Only do this if Phase 3 passes. Most integration risk here. |
| 5 | Phase 5: Monitoring | Low | Safety | Prevents silent degradation post-integration. |

**Critical path:** Phase 1 → Phase 2 → Phase 3 (gate) → Phase 4 → Phase 5

If Phase 3 fails, the feature matrix and ranker are still useful diagnostics — they tell you which signals have non-linear interactions worth exploring with simpler methods (e.g., conditional weighting).

---

## Hyperparameter Discipline

The following hyperparameters are **fixed at conservative defaults** and must NOT be tuned from observed backtest results:

- `max_depth=3` — shallow trees prevent overfitting on ~6K rows
- `min_child_weight=10` — ensures each leaf has meaningful sample size
- `subsample=0.7` — row subsampling for regularization
- `reg_alpha=1.0, reg_lambda=1.0` — L1/L2 regularization

The only tunable is `n_estimators`, and it should be set via early stopping on the temporal validation split (Phase 2), not from OOS results.

---

## What This Does NOT Do

- Does not add new signals — it combines existing ones better
- Does not replace regime filtering — XGB outputs composite_score, regime gates still apply
- Does not require GPU — XGBoost CPU training on ~6K rows takes < 5 seconds
- Does not make the pipeline non-deterministic — XGBoost with `seed=42` is fully reproducible
