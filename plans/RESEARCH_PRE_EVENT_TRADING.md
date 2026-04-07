# Pre-Event Trading Strategies: Research Report

## 1. What the Academic Literature Says

The reference materials from the Columbia GEEII course provide an essential foundation. The "Big News" case (Kashyap and Zeldes) demonstrates that macro announcement *surprises* — not the raw releases — drive asset price reactions. Their regression analysis of nonfarm payroll releases shows that the surprise component (actual minus consensus forecast) is statistically significant for bond yields across all maturities (R-squared 0.20-0.34) and for the EUR/USD exchange rate (R-squared 0.12), but notably *not* for equities (R-squared of just 0.02 for S&P 500 returns). This is a critical finding: while bonds react predictably to macro surprises, equities show ambiguous responses because strong employment data simultaneously signals higher future earnings *and* tighter monetary policy.

The Fleming-Remolona study cited in the course slides confirms the hierarchy: of the 25 largest five-minute bond price changes in a year, all were tied to macro announcements, with 10 following employment reports, 6 following CPI/PPI, and 3 following Fed funds rate announcements. Employment is the "king of announcements."

The FOMC case (Boivin, Giannoni, Himmelberg) illustrates the deeper point: what markets price is not the announcement itself but the *expected Fed reaction function*. In June 1992, with unemployment at 7.2% and a "jobless recovery," the market was pricing in potential rate cuts. Short-term rates respond to anticipated Fed policy changes, while long-term rates respond to inflation expectations — the two channels produce different implications for equities depending on the economic regime.

The GEEII lecture slides frame the core mechanism via uncovered interest rate parity and expectations theory: asset prices embed forward-looking expectations, so any *pre-event* trading profit must come from either (a) superior forecasting of the surprise, (b) exploiting a systematic behavioral bias in how markets position before announcements, or (c) harvesting a risk premium for holding through uncertainty.

---

## 2. What Works in Practice

### Pre-FOMC Announcement Drift

The most well-documented pre-event anomaly is the pre-FOMC drift discovered by Lucca and Moench (2015). From 1994-2011, the S&P 500 earned an average of 49 basis points in the 24 hours before FOMC announcements — accounting for roughly 80% of total annual equity returns. The mechanism is hypothesized to be either information leakage or a risk premium for holding through policy uncertainty.

**Post-2020 status**: The evidence is genuinely mixed. Hu et al. (2020) found the drift "essentially disappeared after 2015" in both press-conference and non-press-conference meetings, attributed to reduced monetary policy uncertainty during the forward-guidance era. However, a 2024 Applied Economics study examining data through December 2024 finds persistence, particularly during high-volatility regimes when VIX is elevated. The reconciliation is that the drift is *conditional* — it shows up when monetary policy uncertainty is high (2020 COVID response, 2022-2023 hiking cycle) and vanishes during low-uncertainty periods (2015-2019 when the Fed was highly telegraphed).

**Relevance to your system**: Your existing VIX regime filter (caution at VIX > 20, risk-off at VIX > 28) already captures the exact condition under which the pre-FOMC drift is strongest. This is a natural integration point.

### Pre-CPI and Pre-NFP Positioning

Unlike the well-documented pre-FOMC drift, evidence for systematic pre-CPI or pre-NFP equity drifts is weaker. The Kashyap-Zeldes regressions confirm this: equity R-squared to payroll surprises is only 0.02, compared to 0.20-0.34 for bonds. CPI and NFP announcements create *volatility events* rather than directional drift in equities.

What does work is **sector rotation around macro releases**: rate-sensitive sectors (REITs, utilities, homebuilders) move predictably with rate expectations, while growth/tech sectors respond to the growth signal embedded in employment data. A below-consensus CPI print that raises rate-cut odds reliably benefits rate-sensitive stocks, while an above-consensus NFP that signals a strong economy benefits cyclicals. This is more of a *conditional exposure management* strategy than a directional bet.

### Pre-Earnings Announcement Drift

The classic post-earnings announcement drift (PEAD) — discovered by Ball and Brown in 1968 — is one of the oldest and most persistent anomalies. Less discussed but relevant is the *pre-earnings* drift: stocks tend to drift upward in the 5-10 days before earnings announcements, with the drift being stronger for stocks with (a) positive analyst revision trends, (b) elevated short interest, and (c) bullish options flow (put-call ratio declining).

The pre-earnings drift is primarily explained by anticipatory buying by informed traders and hedging activity. For a systematic monthly-rebalance strategy like yours, this is relevant because it can be used as a *timing signal* — tilting toward stocks that are approaching earnings dates where sentiment and revision trends are favorable.

---

## 3. How This Maps to the Existing System

Current signal stack:

| Signal | Source | Current Weight |
|--------|--------|---------------|
| SMA Trend | Price data (Alpaca) | 25% |
| Mean Reversion Z | Price data | 20% |
| Bollinger %B | Price data | 20% |
| RSI | Price data | 15% |
| OBV Trend | Volume data | 20% |
| News Sentiment | Finnhub headlines + VADER | 10% (overlay) |
| Regime Filter | VIX + SPY 200d SMA | Gate (not scored) |

Additional data already available: SEC insider data (MSPR), FRED macro series, Finnhub earnings calendar.

**What can be built on top of this without new infrastructure:**

1. **FOMC proximity adjustment** — FRED access and VIX regime filter already exist. The FOMC schedule is fixed and known a year in advance (8 meetings). When the next FOMC is within 3 trading days AND VIX > 20, apply a bullish tilt to composite scores, effectively harvesting the pre-FOMC risk premium.

2. **Earnings calendar overlay** — Finnhub already provides earnings calendars. Before each monthly rebalance, check which candidate stocks have earnings in the next 5-10 days. Stocks with upcoming earnings + positive news sentiment trend + positive analyst revisions represent a confluence signal.

3. **Macro surprise momentum** — Use FRED to track recent CPI/NFP/ISM surprises (actual vs. consensus). A streak of above-consensus macro data suggests the Fed reaction function is tilting hawkish, which should increase the weight on the regime filter and reduce exposure to rate-sensitive names.

---

## 4. Concrete Signal Designs

### Signal A: FOMC Proximity Risk Premium (Recommended First Build)

**Data sources**: FOMC schedule (hardcoded or from Finnhub economic calendar), VIX level (already available via regime filter), Fed funds futures implied probability (optional, from CME via FRED).

**Calculation**:
```python
fomc_days_away = trading_days_until_next_fomc(as_of_date)
vix_level = current_vix  # from regime filter

if fomc_days_away <= 3 and vix_level > 20:
    fomc_boost = +0.15  # add to composite score
elif fomc_days_away <= 3 and vix_level <= 20:
    fomc_boost = +0.05  # small boost, drift weaker in calm markets
else:
    fomc_boost = 0.0
```

**Holding period**: Operates within existing monthly rebalance. Influences *which* rebalance dates produce stronger buy signals. No intra-month trading required.

**Expected impact**: Based on the Lucca-Moench data, FOMC weeks during high-VIX periods have averaged 50-100bps excess returns. With 8 FOMC meetings per year, roughly 2-3 will coincide with monthly rebalances in elevated-VIX environments. The signal is sparse but high-conviction.

**Backtest discipline**: The FOMC schedule is known in advance and does not change, so there is no look-ahead bias. VIX is observable in real-time. This is one of the cleanest event signals to backtest.

### Signal B: Pre-Earnings Sentiment Confluence

**Data sources**: Finnhub earnings calendar (already integrated), Finnhub news sentiment (already integrated), analyst estimate revisions (available via FMP free tier or Finnhub).

**Calculation**:
```python
for each stock in candidate_universe:
    days_to_earnings = trading_days_until_next_earnings(ticker, as_of_date)
    
    if 3 <= days_to_earnings <= 15:
        # Stock is in the pre-earnings window
        sentiment_trend = 30d_news_sentiment - 60d_news_sentiment
        revision_direction = sign(mean_analyst_eps_revision_last_30d)
        insider_signal = mspr_score  # already available from SEC data
        
        pre_earnings_score = (
            0.4 * normalize(sentiment_trend) +
            0.3 * revision_direction +
            0.3 * normalize(insider_signal)
        )
        # Clip to [-0.15, +0.15] and add to composite
```

**Holding period**: Captured within monthly rebalance. Stocks in the pre-earnings window with positive confluence get a scoring boost at selection time.

**Expected impact**: PEAD literature suggests 1-3% excess returns in the post-announcement period for top-decile surprise stocks. The pre-earnings drift is smaller (0.5-1%) but combines with existing sentiment signal to reduce false positives. The key value is the *confluence* — when news sentiment, insider buying, and analyst revisions all agree, the probability of a positive earnings surprise is significantly elevated.

### Signal C: Macro Surprise Regime Adjustment

**Data sources**: FRED economic data (already integrated) — specifically a DIY Citigroup Economic Surprise Index using CPI, NFP, ISM, retail sales surprises vs. consensus.

**Calculation**:
```python
recent_surprises = [
    (actual_CPI - consensus_CPI) / std_CPI_surprise,
    (actual_NFP - consensus_NFP) / std_NFP_surprise,
    (actual_ISM - consensus_ISM) / std_ISM_surprise,
]
macro_surprise_z = mean(recent_surprises)

if macro_surprise_z > 1.0:
    # Economy running hot -> Fed likely tighter -> favor cyclicals
    sector_tilt = "pro_cyclical"
    regime_caution = True
elif macro_surprise_z < -1.0:
    # Economy weakening -> Fed likely easier -> favor rate-sensitive
    sector_tilt = "defensive"
else:
    sector_tilt = "neutral"
```

**Holding period**: Monthly. Modifies sector tilts within stock selection, not timing.

**Expected impact**: Less about direct alpha, more about risk management. During macro surprise streaks, the regime filter will be better calibrated. The Kashyap-Zeldes data shows bond yields respond with R-squared 0.20-0.34 to payroll surprises — that predictability in the rate environment translates to predictable sector rotation in equities.

---

## 5. Data Requirements and Sources

| Data Need | Free Source | Integration Effort |
|-----------|------------|-------------------|
| FOMC meeting dates | Fed website (static, 8/year) | Trivial — hardcode annually |
| Earnings calendar | Finnhub (already integrated) | Low — API call already available |
| Analyst EPS revisions | FMP free tier (250 calls/day) | Medium — new API method |
| Economic calendar (CPI, NFP dates) | Finnhub economic calendar API | Low — same client |
| Consensus economic forecasts | Trading Economics API (limited free) or FRED surveys | Medium |
| VIX data | Already in regime filter | Zero |
| Insider trading (MSPR) | Already from SEC | Zero |

**Key point**: Signal A (FOMC proximity) requires zero new data sources. Signal B requires only the Finnhub earnings calendar already in use. Signal C requires the most new data (economic consensus forecasts) but a DIY surprise index can be constructed from FRED data already pulled.

---

## 6. Risks and Pitfalls

### Look-Ahead Bias in Event Strategy Backtesting

This is the single greatest danger. Event dates are known *ex ante*, but the specific data released at those events is not. Common mistakes:

- **Using finalized earnings dates that were later revised.** Companies sometimes reschedule earnings. Backtests must use the *originally announced* date, not the final date. Finnhub's historical calendar should capture this, but verify.
- **Confusing announcement date with reporting date.** Economic data is released at 8:30 AM ET; daily OHLCV bars capture the reaction. Ensure signals use the *pre-announcement* close, not the *post-announcement* close.
- **Using revised macro data.** FRED provides both initial releases and revised figures. NFP, GDP, and CPI are all revised after initial release. Backtests must use the *first-release* vintage, which FRED supports via its ALFRED (Archival FRED) database.

### Survivorship Bias

The current 10-stock large-cap universe is relatively safe from survivorship bias (large caps rarely delist), but backtesting with today's S&P 500 constituents projected backwards will exclude companies that were in the index during the backtest period but have since been removed or acquired. This matters more as the universe expands to 200-500 stocks.

### Overfitting Sparse Events

FOMC meetings occur 8 times per year. Over a 6-year OOS window (2020-2026), that is only 48 observations. The pre-FOMC drift signal applied to monthly rebalance further reduces usable observations to roughly 8-12 (months where rebalance falls near FOMC). This sample is too small for standalone statistical significance. The signal should be treated as a *tilt* (5-15% weight), not a primary driver.

### Transaction Costs and Capacity

The existing 10bps round-trip cost assumption is appropriate. Pre-event signals do not change rebalance frequency (still monthly) or increase turnover. The only risk is if FOMC or earnings proximity signals cause more aggressive position sizing, which could increase turnover at the margin.

### Regime Dependence

The pre-FOMC drift is *strongly* regime-dependent — it works during high uncertainty and disappears during low uncertainty. The VIX regime filter already captures this. But adding this signal may show poor standalone Sharpe because it only fires in specific environments. Evaluate on *conditional* metrics (Sharpe during VIX > 20 periods only).

---

## 7. Recommended Priority

**Build Signal A (FOMC Proximity Risk Premium) first.**

1. **Zero new data infrastructure.** FOMC dates are static. VIX is already in the regime filter. Implementation is a 20-line function.

2. **Cleanest backtest.** No look-ahead bias risk (FOMC dates known a year ahead). No survivorship bias. No data revision concerns.

3. **Strongest academic backing.** Lucca-Moench is published in the Journal of Finance. The 2024 Applied Economics update confirms persistence during high-VIX periods. The VIX regime filter is already built to detect exactly the environment where this signal works.

4. **Compatible with monthly rebalance.** The signal simply says: "If my rebalance date falls within 3 days of an FOMC meeting and VIX is elevated, be more aggressive on the long side."

5. **Incremental Sharpe improvement.** Even a modest conditional improvement of 20-30bps annualized during FOMC weeks could push Sharpe from 1.35 toward 1.40-1.45, given that FOMC weeks tend to be high-volatility weeks where current signals may underperform.

**Second priority**: Signal B (pre-earnings confluence), because Finnhub data is already integrated and the signal leverages existing news sentiment infrastructure.

**Third priority**: Signal C (macro surprise regime adjustment), because it requires the most new data plumbing and the alpha is more about risk management than return generation.

---

## Sources

- Lucca and Moench, "The Pre-FOMC Announcement Drift" (NY Fed Staff Report, Journal of Finance 2015)
- Hu et al., "The disappearing pre-FOMC announcement drift" (Finance Research Letters, 2020)
- "The pre-FOMC announcement drift: short-lived or long-lasting?" (Applied Economics, 2024)
- Ball and Brown, "An Empirical Evaluation of Accounting Income Numbers" (Journal of Accounting Research, 1968)
- Bernard and Thomas, "Post-Earnings-Announcement Drift" (Journal of Accounting Research, 1989)
- Kashyap and Zeldes, "Big News" (Columbia Business School case study, GEEII course)
- Boivin, Giannoni, Himmelberg, "FOMC Case" (Columbia Business School case study)
- Fleming and Remolona, "What Moves Bond Prices?" (Journal of Portfolio Management, 1999)
