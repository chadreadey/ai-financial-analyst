# API & Data Burn Rate

Last updated: 2026-04-07

## Current Monthly Costs (Academic/Free Tier)

### Data APIs

| Provider | Plan | Rate Limit | Monthly Cost | What We Use It For |
|----------|------|-----------|-------------|-------------------|
| **Alpaca** | Free | 200 req/min | **$0** | Primary price data (OHLCV), 2016+ history |
| **Tiingo** | Free/Power | 50 req/hr (free), fundamentals DOW 30 only | **$0** | Backup prices, fundamentals for DOW 30 tickers |
| **FMP** | Free | 250 calls/day | **$0** | S&P 500 constituents, sector data, analyst estimates, balance sheets |
| **Finnhub** | Free | 60 req/min | **$0** | News sentiment (1yr rolling), insider sentiment (10yr), earnings calendar |
| **FRED** | Free | Unlimited | **$0** | VIX, macro data (CPI, yields, etc.) |
| **WRDS** | Academic | Unlimited (bulk SQL) | **$0** | Compustat quarterly, IBES analyst estimates, CRSP link tables |
| **Yahoo Finance** | Unofficial | Rate limited | **$0** | VIX data, fallback quotes |

**Total data cost: $0/mo**

### LLM APIs

| Provider | Model | Usage Pattern | Monthly Cost (50 stocks) | Monthly Cost (200 stocks) |
|----------|-------|--------------|-------------------------|--------------------------|
| **Anthropic** | Claude Sonnet 4.6 | 6 agents + synthesis per stock | **~$19** | **~$76** |
| **Anthropic** | Claude Batch API | Same, 24hr async | **~$9.50** | **~$38** |
| **OpenAI** | GPT-4o-mini | Not currently used | — | — |

**Current LLM spend: ~$19/mo** (50 stocks, real-time Claude)

### Development Tools

| Tool | Cost | Notes |
|------|------|-------|
| **Claude Code** (this tool) | Per Anthropic plan | Development/research |
| **Google Colab Pro** | ~$10/mo | LSTM training, GPU compute |

---

## Current Total: ~$29/mo

---

## What Changes When We Go Commercial

### Tier 1: Replace WRDS (required at commercial threshold)

| WRDS Dataset | Replacement | Cost | Notes |
|-------------|------------|------|-------|
| Compustat Quarterly (`comp.fundq`) | FMP Pro | **$79/mo** ($948/yr) | Balance sheets, income statements. Unlimited calls. |
| | *or* S&P Capital IQ | **$15-25K/yr** | Institutional grade, exact `rdq` equivalent |
| IBES Estimates (`ibes.detu_epsus`) | **No direct retail replacement** | — | FMP `/analyst-estimates` lacks `anndats` (per-analyst revision dates) |
| | Estimize | **$299/mo** ($3,588/yr) | Crowdsourced estimates, not identical to IBES |
| | Visible Alpha | **$20K+/yr** | Institutional only |
| | Refinitiv IBES Direct | **$20K+/yr** | Same data, commercial license |
| CRSP Link Table | Manual ticker mapping | **$0** | Already have Tiingo/Alpaca for prices |

**Minimum WRDS replacement: $79/mo** (FMP Pro, loses IBES)
**Full WRDS replacement: ~$25K/yr** (Capital IQ + Refinitiv)

### Tier 2: Upgrade Free APIs for Production

| Current (Free) | Upgrade To | Cost | Why |
|----------------|-----------|------|-----|
| FMP Free (250/day) | FMP Starter | **$29/mo** | 80 req/min, enough for 200 tickers |
| FMP Free | FMP Pro | **$79/mo** | Unlimited, analyst estimates, DCF |
| Finnhub Free (60/min) | Finnhub Premium | **$50/mo** | Higher limits, no throttling |
| Tiingo Free | Tiingo Power | **$30/mo** | Full fundamentals (not just DOW 30), news archive |
| Alpaca Free | Alpaca Unlimited | **$9/mo** | Real-time data, no delay |

**Production-ready data stack: ~$170/mo** (FMP Pro + Finnhub Premium + Tiingo Power + Alpaca)

### Tier 3: Scale LLM Costs

| Scale | Real-time Claude | Batch Claude | Hybrid (DeepSeek + Claude) |
|-------|-----------------|-------------|---------------------------|
| 50 stocks/mo | $19 | $9.50 | $4.64 |
| 100 stocks/mo | $38 | $19 | $9.28 |
| 200 stocks/mo | $76 | $38 | $18.55 |
| 500 stocks/mo | $189 | $95 | $46.38 |

---

## Scaling Scenarios

### Scenario A: Research Mode (current)
- 10-50 tickers, monthly rebalance
- Free data APIs + WRDS academic
- Claude real-time for analysis
- **Total: ~$29/mo**

### Scenario B: Pre-Commercial (next milestone)
- 50-100 tickers, monthly rebalance
- Free data APIs + WRDS academic
- Batch Claude for cost efficiency
- **Total: ~$20/mo**

### Scenario C: Launch (replace WRDS, production APIs)
- 100-200 tickers, monthly rebalance
- FMP Pro + Finnhub Premium + Tiingo Power + Alpaca Unlimited
- Hybrid LLM (DeepSeek specialists + Claude synthesis)
- **Total: ~$190/mo** ($2,280/yr)

### Scenario D: Scale (full S&P 500)
- 500 tickers, weekly screening + monthly deep analysis
- Same data stack as Scenario C
- Batch Claude for all 500
- **Total: ~$265/mo** ($3,180/yr)

### Scenario E: Institutional (full IBES replacement)
- 500 tickers with real analyst revision data
- Capital IQ or Refinitiv IBES
- **Total: ~$2,300/mo** ($27,600/yr)

---

## Cost Jump Summary

| Transition | Monthly Δ | What You Gain |
|-----------|----------|---------------|
| Current → Batch Claude | -$9.50 | Same quality, half price |
| Current → Replace WRDS (FMP Pro only) | +$79 | Lose IBES, keep fundamentals |
| Current → Production data stack | +$170 | Higher rate limits, full coverage |
| Current → Full commercial (no WRDS, no free tiers) | +$260 | Production-ready, 200 tickers |
| Production → Institutional IBES | +$2,000 | Real analyst revision data back |

---

## Critical Dependencies on Free/Academic Data

| Dependency | Risk If Lost | Mitigation |
|-----------|-------------|-----------|
| **WRDS IBES** | Lose point-in-time analyst revision signal | FMP consensus is a degraded substitute. Estimize ($299/mo) is partial. True replacement is Refinitiv ($20K+/yr). |
| **WRDS Compustat `rdq`** | Lose exact report date for point-in-time | FMP `filingDate` is close but not identical. Can derive with ~45 day lag assumption. |
| **Finnhub Free** | Lose news sentiment signal (Sharpe 1.04→1.35) | Tiingo Power ($30/mo) has 15yr news archive. EODHD ($20/mo) has scored sentiment. |
| **FMP Free** | Lose S&P 500 constituents, sector data | Wikipedia scrape (already implemented as fallback). $29/mo Starter is cheap insurance. |
| **Alpaca Free** | Lose primary price data | Tiingo free tier as backup (already implemented). |

---

## Notes
- All costs are as of April 2026 and subject to change
- WRDS academic license prohibits commercial use — all WRDS-derived signals must be replaceable
- The two hardest things to replace commercially: IBES `anndats` and Compustat `rdq`
- FMP Pro at $79/mo is the pragmatic first upgrade — covers fundamentals + estimates + news
