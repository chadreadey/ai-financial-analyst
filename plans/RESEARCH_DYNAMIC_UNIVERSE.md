# Dynamic Universe + Sector Classification

## Best Option: FMP (Already Have API Key)

### S&P 500 Constituents
`GET https://financialmodelingprep.com/api/v3/sp500_constituent?apikey=KEY`

Returns: symbol, name, **sector**, subSector, headQuarter, dateFirstAdded, CIK. Sector is GICS-aligned. One call gets everything — no per-ticker enrichment needed.

### Historical Constituents (Survivorship Bias Fix)
`GET https://financialmodelingprep.com/api/v3/historical/sp500_constituent?apikey=KEY`

Returns changelog: dateAdded, addedSecurity, removedTicker, removedSecurity, reason. Reconstruct point-in-time membership by replaying additions/removals backward from today.

### ETF Holdings (Top N by Weight)
`GET https://financialmodelingprep.com/stable/etf/holdings?symbol=SPY&apikey=KEY`

Returns: asset, sharesNumber, **weightPercentage**. Sort by weight descending for top 50.

### Per-Ticker Profile
`GET /api/v3/profile/{symbol}` — returns sector, industry, marketCap, description. Free tier.

**Free tier: 250 calls/day.** These are low-frequency (cache the list daily), so not a constraint.

## Free Alternative: Wikipedia
```python
import pandas as pd
tables = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
sp500 = tables[0]  # Symbol, Security, GICS Sector, GICS Sub-Industry
changes = tables[1]  # Historical adds/removes with dates back to 1996
```

## What Doesn't Work
- **Alpaca**: No sector/industry in asset metadata
- **Finnhub**: `finnhubIndustry` is their own taxonomy, not GICS
- **pandas_datareader**: S&P 500 function deprecated as of 2024

## Recommended Architecture
1. **Primary**: FMP `sp500_constituent` — cache to SQLite with sector attached
2. **Historical**: Wikipedia changes table for backtest survivorship-bias fix
3. **Top-N by weight**: FMP ETF holdings for SPY, or sort by marketCap
4. **Refresh frequency**: Daily or weekly (index changes are rare)
