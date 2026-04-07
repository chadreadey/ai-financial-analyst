# Critical Gap Analysis: Your System vs. Current Research (2024-2026)

## System Under Review
- 6 deterministic technical signals (SMA, RSI, Bollinger, Mean Reversion, OBV, ATR)
- News sentiment overlay (Finnhub VADER + insider MSPR)
- VIX + SPY SMA regime filter with golden/death cross
- Monthly rebalance, long-only, 10-stock concentrated portfolio
- Custom LSTM as experimental 7th signal (degraded Sharpe, shelved)
- 6 LLM equity research agents (DCF, Risk, Earnings, Competitive, Pattern, Macro)
- Gold standard: Sharpe 1.35 on 8-window walk-forward OOS 2020-2026

---

## CRITICAL GAPS (things that would meaningfully improve the system)

### 1. You're using VADER when FinBERT exists and is dramatically better

**Gap severity: HIGH**

FinBERT achieves 88.2% accuracy on financial text vs. 62-74% for VADER/SVM/LSTM (Huang et al., 2024, Contemporary Accounting Research). Your entire sentiment pipeline is built on VADER, which is a general-purpose lexicon that doesn't understand financial language. "Revenues missed expectations" is negative in finance but VADER may score it neutral. Fine-tuned LLaMA-2 on financial sentiment shows even stronger correlation with cumulative abnormal returns than FinBERT.

**What to do:** Replace VADER with FinBERT (or FinBERT-tone) in `quant/sentiment.py`. FinBERT is a ~110M parameter model that runs in <1 second per headline on CPU. It's a drop-in replacement for VADER's `polarity_scores()` — same input (headline text), same output concept (sentiment score), dramatically better accuracy on financial text. The Loughran-McDonald dictionary (free, downloaded in minutes) is an intermediate step if you don't want to run a model.

### 2. You have zero cross-sectional/fundamental factors

**Gap severity: HIGH**

Your 6 signals are ALL technical (price/volume-derived). Current research (Springer 2025 SHAP study) shows that fundamental factors — return on assets, sales-to-price, earnings volatility — are the top-ranked cross-sectional predictors, consistently outranking derived technicals like RSI and Bollinger. You have FMP data that provides these fundamentals, but none of it feeds into the quant composite.

**What to do:** Add 2-3 fundamental signals to the composite: (1) earnings revision momentum (FMP analyst estimates, already in `fmp_client.py`), (2) ROA or ROE (from FMP quarterly financials, already fetched), (3) sales-to-price. These are deterministic, free to compute from data you already cache, and have documented ICs of 0.04-0.10 (higher than any of your technical signals).

### 3. Your signal combination is fixed equal-weight — IC-weighted rolling is strictly better

**Gap severity: MEDIUM-HIGH**

You tested IC calibration and it underperformed — but the research says IC-weighted rolling (30-60 day lookback) with shrinkage consistently beats equal weight across studies. Your IC calibration implementation used `ic_shrinkage=0.90` (90% toward equal weight), which is essentially equal weight with a tiny IC tilt. Try `ic_shrinkage=0.50-0.70` or use LASSO for signal selection (which would aggressively zero out redundant signals).

Alternatively, a Ridge meta-learner stacked on the 7 signal outputs (trained on rolling OOS predictions) is the state-of-the-art approach and is explicitly recommended by the 2025 ensemble literature.

### 4. Your walk-forward validation is standard but not rigorous by ML standards

**Gap severity: MEDIUM**

Your 8-window rolling walk-forward is better than most retail backtests. But it tests only ONE historical path and is subject to overfitting that specific sequence. Combinatorial Purged Cross-Validation (CPCV, Lopez de Prado) generates multiple simulated paths and computes the Probability of Backtest Overfitting (PBO). A 2024 study found CPCV achieves significantly lower PBO and higher Deflated Sharpe Ratio than standard walk-forward.

Your LSTM walk-forward also lacks purged gaps — with 20-day forward return labels, you need at least a 20-day embargo between train and test sets to prevent serial-correlation leakage.

**What to do:** Implement CPCV as a secondary validation layer alongside your rolling WF. Also add a 20-day purge/embargo period to the LSTM walk-forward in `run_ml_backtest.py`.

### 5. Your regime detection is primitive compared to available methods

**Gap severity: MEDIUM**

VIX threshold + SPY SMA is a reasonable starting point, but it missed the 2025 tariff correction (Window 7, -9.6%). The literature offers clear upgrades:

- **Turbulence Index** (Mahalanobis distance of current sector return vector vs. historical covariance) — a single numpy computation that adds meaningful regime precision. This would have caught the tariff correction because sector returns decorrelated (tech crashed, defensives held).
- **Statistical Jump Model** (2024, arxiv 2402.05272) — HMM with jump penalties to reduce false positives in regime transitions.
- **Adaptive Hierarchical HMM** — meta-regime layer that shifts based on macro environment.

The turbulence index is the highest ROI upgrade: ~20 lines of code, no new data, and it captures exactly the type of rotation event that your VIX filter missed.

### 6. The 52-week high ratio signal is a documented free lunch you're not using

**Gap severity: MEDIUM**

George & Hwang's 52-week high ratio (price / 52-week high) generates ~2x the returns of standard 12-1 month momentum with less crash exposure. It's been replicated through 2024 and is trivial to compute from your existing price data. This is a single line: `price / df['close'].rolling(252).max()`.

---

## MODERATE GAPS (worth investigating but not urgent)

### 7. No options-implied features

IV skew and put-call ratio are documented sentiment proxies with predictive power for short-term reversals (ScienceDirect 2024). You don't have options data. CBOE or Polygon could provide this, but it's a new data source and adds complexity. Lower priority than the fundamental factor gap.

### 8. LSTM architecture is outdated

Your 2-layer LSTM with 64 hidden units is a 2018-era architecture. Current state-of-the-art for 20-day equity prediction is Temporal Fusion Transformer (TFT) or hybrid CEEMDAN-Informer-LSTM. However, the research also shows that adding more historical data can HURT LSTM performance (Springer Financial Innovation 2025) — your 24-month training window may be suboptimal. Try 36-48 months with a rolling (not expanding) window.

That said, no LSTM variant is likely to dramatically change your Sharpe. The marginal value of time-series ML for daily-frequency equity prediction remains low (IC 0.01-0.03).

### 9. No ensemble diversity monitoring

Your signals are likely correlated (SMA trend and mean reversion are both price-derived; RSI and Bollinger both measure overbought/oversold). Lopez de Prado's "10 Reasons ML Funds Fail" cites correlated models as a primary failure mode — they fail simultaneously. Adding one fundamentally uncorrelated signal (macro, fundamental, or cross-asset) is more valuable than adding a fourth momentum variant.

### 10. No concept drift monitoring

You have no mechanism to detect when your signals stop working. ADWIN (Adaptive Windowing) or Page-Hinkley test are lightweight monitors recommended by the 2024 MDPI concept drift survey. Track rolling 30-day directional accuracy vs. 1-year baseline; trigger retraining or regime review if degradation exceeds 15%.

---

## WHERE YOUR SYSTEM STANDS OUT (double down here)

### A. Deterministic reproducibility is rare and valuable

Temperature=0, scoring rubrics, no stochastic elements — your system produces byte-identical results across runs. The multi-agent LLM literature (TradingAgents, MarketSenseAI) does NOT achieve this. Your reproducibility discipline is a genuine competitive advantage for audit trails, investor communication, and iterative improvement. **Double down: maintain this as a hard constraint for any new signal.**

### B. Monthly rebalance frequency is validated and optimal

Current research confirms monthly dominates weekly for factor-based strategies (directly aligns with your weekly Sharpe 0.02 finding). You arrived at this empirically, and the literature backs it. Don't second-guess it.

### C. The two-stage pipeline architecture is ahead of most academic work

Your planned quant screen → LLM deep analysis → blended scoring pipeline is architecturally similar to MarketSenseAI 2.0 (which reported 125.9% returns on S&P 100). Most academic LLM trading papers use a single model, not a multi-agent pipeline with separate screening. Your phased deployment with shadow mode validation is more rigorous than any published LLM trading paper's validation approach.

### D. The regime filter prevented catastrophic loss in 2022

Windows 1-2 (2022 bear market) lost only 0.2% while SPY fell ~25%. The VIX + SMA regime filter's capital preservation is the primary driver of your strong Sharpe. Most academic factor backtests don't include regime filters and show much worse drawdowns.

### E. FOMC proximity signal has clean academic backing

Lucca-Moench is one of the most well-documented anomalies in finance. You've implemented it correctly (VIX-conditional, hardcoded dates with no look-ahead bias). The marginal Sharpe impact was small at monthly frequency, but this is the type of clean, defensible signal that impresses investors.

---

## PRIORITY RANKING (effort vs impact)

| Priority | Gap | Effort | Expected Impact |
|---|---|---|---|
| 1 | Replace VADER with FinBERT | 4-6 hrs | High — 88% vs 62% accuracy on financial text |
| 2 | Add fundamental signals (ROA, earnings revisions) | 4-6 hrs | High — documented IC 0.04-0.10 |
| 3 | Add 52-week high ratio signal | 1 hr | Medium — 2x momentum with less crash risk |
| 4 | Add turbulence index to regime filter | 2-3 hrs | Medium — catches sector rotation events VIX misses |
| 5 | CPCV validation layer | 4-6 hrs | Medium — reduces probability of backtest overfitting |
| 6 | Retune IC shrinkage / try LASSO | 2-3 hrs | Medium — current 0.90 is too conservative |
| 7 | LSTM purge/embargo periods | 1-2 hrs | Low-Medium — prevents serial correlation leakage |
| 8 | Concept drift monitor (ADWIN) | 2-3 hrs | Low — insurance, not alpha |

---

## Sources

- Blitz (2024), "Factor premiums do not decay" (CFA Institute)
- Swade, Hanauer, Lohre, Blitz (2024), "Factor Zoo (.zip)" (SSRN 4605976)
- Neuhierl, Randl, Reschenhofer (2024), "Timing the Factor Zoo" (AEA conference)
- Huang et al. (2024), "FinBERT: A Large Language Model for Extracting Information from Financial Text" (Contemporary Accounting Research)
- MarketSenseAI 2.0 (2025), arxiv 2502.00415
- TradingAgents (2024), arxiv 2412.20138
- Springer (2025), "Significance of predictors: revisiting stock return predictions"
- Lopez de Prado, "Advances in Financial Machine Learning" (2018); "10 Reasons ML Funds Fail" (GARP)
- Schwarz (2025), "The Actual Retail Price of Equity Trades" (Journal of Finance)
- George & Hwang, "The 52-Week High and Momentum Investing" (replicated through 2024)
- AH-HMM (2025), MDPI Journal of Risk and Financial Management
- Statistical Jump Model (2024), arxiv 2402.05272
- CPCV (2024), QuantBeckman study
- CEEMDAN-Informer-LSTM (2025), ScienceDirect
- Springer Financial Innovation (2025), "LSTM memory inconsistencies in stock markets"
