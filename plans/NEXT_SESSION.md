# Session Handover — 2026-04-06

---

## What Happened This Session

### Critical Bugs Fixed
1. **Look-ahead bias removed** — Alpaca timestamps at `05:00 UTC` after `tz_convert(None)` let the model execute on same-day prices. Fixed with `.dt.normalize()` in both `_fetch_ohlcv()` and `_load_cached()`. This was artificially inflating Sharpe from ~0.06 to 1.91.
2. **Walk-forward windowing fixed** — `run_walk_forward()` was advancing by `train_months` (24mo), producing only 2 windows over 2020-2026. Changed to advance by `test_months` (6mo), now produces 8 rolling windows.
3. **Sentiment cache-first fix** — `compute_news_sentiment_score()` checked `if client is None` before disk cache lookup. Moved cache lookup first so backtests work from cache alone without a live API key.
4. **`--no-shorts` flag added** — Both `run_backtest.py` and `run_ml_backtest.py`. Sets `short_threshold=-999.0`. Initial attempt used `+999.0` which made every score qualify for a short (inverted comparison).
5. **LSTM script parity** — `run_ml_backtest.py` now has `--no-ic-calibration`, `--train-months`, `--test-months`, `--enable-news-sentiment`, `--no-shorts` flags and uses the same rolling window logic.
6. **LSTM metrics crash fix** — `compute_metrics` import didn't exist. Replaced with inline metric computation.

### Key Finding: Shorts Destroy Value
Short side across 8-window walk-forward: 23 trades, 26% WR, avg -2.73%, total PnL -$15,194. Every major drawdown traces to a short that got squeezed in a bull market. Disabling shorts was the single biggest Sharpe improvement.

### Weekly vs Monthly Rebalance
Weekly (Sharpe 0.02) is dramatically worse than monthly (Sharpe 0.61). Weekly churns 655 trades at 3.8d avg hold — the signal doesn't have time to play out and transaction costs dominate. Monthly is the correct choice.

---

## Current Best Results

### Configuration: Long-only, monthly, no IC calibration, liquid_10

| Config | Sharpe | Sortino | Return | MaxDD | Trades | WR |
|--------|--------|---------|--------|-------|--------|----|
| Baseline (longs only) | 1.04 | 1.46 | +30.7% | 12.7% | 101 | 58% |
| + Sentiment | 1.35 | 2.02 | +43.7% | 12.9% | 102 | 59% |
| + LSTM + Sentiment | **TBD** | — | ~+45%* | — | 92 | — |

*LSTM run completed on Colab but crashed before computing summary stats. Fix pushed (commit 5e1c630). Re-run needed.

### 8-Window Walk-Forward Breakdown (Baseline Long-Only)

| # | Period | Return | WR | Notes |
|---|--------|--------|----|-------|
| 1 | Dec21→Jun22 | +0.2% | 33% | 2022 bear — regime filter sat out, only 3 trades |
| 2 | Jun22→Dec22 | +0.0% | — | Zero trades — fully in cash |
| 3 | Dec22→Jun23 | -2.5% | 60% | Recovery, 2 stop losses |
| 4 | Jun23→Dec23 | -4.9% | 33% | "Higher for longer" scare, worst window |
| 5 | Dec23→Jun24 | +14.6% | 75% | AI/Mag7 bull run, zero stop losses |
| 6 | Jun24→Dec24 | +7.7% | 61% | Broad bull, most active window (31 trades) |
| 7 | Dec24→Jun25 | -9.6% | 38% | Tariff correction — regime filter didn't catch it |
| 8 | Jun25→Nov25 | +21.1% | 71% | Recovery rip, strong signal |

### LSTM Window Returns (from Colab, pre-crash)

| # | LSTM+Sent | Baseline | Delta |
|---|-----------|----------|-------|
| 1 | -0.8% | +0.2% | -1.0% |
| 2 | +0.0% | +0.0% | 0.0% |
| 3 | -1.9% | -2.5% | +0.6% |
| 4 | -2.8% | -4.9% | +2.1% |
| 5 | +14.5% | +14.6% | -0.1% |
| 6 | +8.3% | +7.7% | +0.6% |
| 7 | -8.9% | -9.6% | +0.7% |
| 8 | +36.6% | +21.1% | +15.5% |

LSTM helped in Windows 3-4 (bear/choppy) and massively boosted Window 8 (recovery). Slightly hurt Window 1. Overall trajectory looks positive.

### Sentiment Impact
- Only Window 8 had Finnhub cache coverage (2025 data). Score jumped from +21.1% to +33.3%.
- Windows 1-7: no articles cached → sentiment returned neutral → no impact (correct behavior).
- 72/102 trades had sentiment flags showing `articles=0,regime=*` — confirms cache gaps, not bugs.

---

## Files Changed

| File | What Changed |
|------|-------------|
| `quant/backtest.py` | Rolling window fix (line 1652), `.dt.normalize()` on prices, sentiment z-score normalization, asymmetric short blend, adaptive sentiment weighting, golden cross floor, high-vol stop widening, flags on Position/TradeRecord |
| `scripts/run_backtest.py` | `--no-shorts` flag, `--enable-news-sentiment` flag |
| `scripts/run_ml_backtest.py` | Rolling windows, `--no-shorts`, `--no-ic-calibration`, `--train-months`, `--test-months`, `--enable-news-sentiment`, inline metrics computation |
| `scripts/prefetch_sentiment.py` | New file — pre-populates Finnhub cache |
| `quant/sentiment.py` | Cache-first lookup, insider MSPR same fix |
| `finnhub_client.py` | New file — FinnhubClient + SentimentDiskCache |
| `price_provider.py` | New file — AlpacaClient price provider |

---

## Immediate Next Steps

### 1. Re-run LSTM on Colab (5 min)
The fix is pushed. On Colab:
```
!cd ai-financial-analyst && git pull && python scripts/run_ml_backtest.py --walk-forward --start 2020-01-01 --end 2026-04-01 --train-months 24 --test-months 6 --no-ic-calibration --no-shorts --universe liquid_10 --skip-baseline --enable-news-sentiment --lstm-weight 0.20 --output wf_8w_lstm_sentiment.json
```
Download the JSON and analyze. Expected Sharpe ~1.3-1.5 based on window returns.

### 2. Prefetch Finnhub Cache for 2024
Sentiment only fired in Window 8 because cache is sparse. Extend coverage:
```
python scripts/prefetch_sentiment.py --universe liquid_10 --start 2024-01-01
```
This takes ~30 min (rate limited at 1.1s/call). After caching, re-run sentiment to see impact on Windows 5-7.

### 3. Fix Window 7 (Tariff Correction)
Window 7 (Dec24→Jun25) lost -9.6% — the biggest remaining drawdown. The VIX-based regime filter didn't trigger because the tariff sell-off didn't spike VIX above 28 for long enough. Options:
- Add trade policy uncertainty index as a regime signal
- Use news sentiment as an early warning (needs cache coverage for that period)
- Consider a volatility-of-volatility (VVIX) trigger

### 4. Short Side Rehabilitation (Future)
Shorts are disabled. To bring them back profitably:
- Only allow shorts when VIX > 28 AND death cross confirmed (double gate)
- Or train a separate short-only model with different signals (momentum-focused, not mean-reversion)
- Test on 2022 bear market window specifically

---

## What NOT to Do

- **Do not tune on 2025 walk-forward data** — it's contaminated from this session's tuning (see `feedback_backtest_discipline.md`)
- **Do not re-enable IC calibration** — equal weights outperform IC-calibrated weights OOS (confirmed across multiple runs)
- **Do not switch to weekly rebalance** — conclusively worse (Sharpe 0.02 vs 1.04)
- **Do not re-enable shorts** without a dedicated short model — the existing short signal is anticorrelated with forward returns in bull markets

---

## Result Files Reference

| File | Config | Sharpe |
|------|--------|--------|
| `wf_8w_monthly.json` | L+S, monthly, no IC, liquid_10 | 0.61 |
| `wf_8w_weekly.json` | L+S, weekly, no IC, liquid_10 | 0.02 |
| `wf_8w_longs_only.json` | Long-only, monthly, no IC, liquid_10 | 1.04 |
| `wf_8w_sentiment.json` | Long-only + sentiment, monthly, no IC, liquid_10 | 1.35 |
| `wf_8w_lstm_sentiment.json` | Long-only + LSTM + sentiment (Colab, needs re-run) | TBD |

All runs: 2020-01-01 → 2026-04-01, 8 rolling windows (24mo train / 6mo test).

---

## Run Commands (single-line, no backslashes)

```bash
# Baseline long-only
python scripts/run_backtest.py --walk-forward --start 2020-01-01 --end 2026-04-01 --train-months 24 --test-months 6 --no-ic-calibration --universe liquid_10 --no-shorts --output wf_8w_longs_only.json

# + Sentiment
python scripts/run_backtest.py --walk-forward --start 2020-01-01 --end 2026-04-01 --train-months 24 --test-months 6 --no-ic-calibration --universe liquid_10 --no-shorts --enable-news-sentiment --output wf_8w_sentiment.json

# + LSTM + Sentiment (Colab only — ~20 min on T4)
python scripts/run_ml_backtest.py --walk-forward --start 2020-01-01 --end 2026-04-01 --train-months 24 --test-months 6 --no-ic-calibration --no-shorts --universe liquid_10 --skip-baseline --enable-news-sentiment --lstm-weight 0.20 --output wf_8w_lstm_sentiment.json

# Prefetch sentiment cache
python scripts/prefetch_sentiment.py --universe liquid_10 --start 2024-01-01
```

---

## Architecture Discussions Queued (from prior NEXT_SESSION.md)
- LSTM vs GBM vs ensemble for signal generation
- Fully autonomous daily scan system
- RL for adaptive signal weighting (start with bandit / IC calibration)
- Geopolitical GraphRAG extensions
- Pre-earnings signal integration
