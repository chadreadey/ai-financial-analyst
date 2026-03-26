# Tiingo & FMP API Comprehensive Reference

> Generated 2026-03-25. Verify rate limits and pricing against live docs before major integrations.

---

## Part 1: Tiingo API Reference

### 1.1 General Overview

**Base URL:** `https://api.tiingo.com`

**Data coverage:**
- 82,468+ global securities (37,319 US + Chinese stocks; 45,149 ETFs and mutual funds)
- 2,100+ crypto tickers across 40+ exchanges
- 40+ FX pairs from tier-1 banks
- 30+ years of historical EOD data

**Authentication:** Token in `Authorization` header (preferred):
```
Authorization: Token YOUR_API_TOKEN
```
Or as query param `?token=YOUR_API_TOKEN`. Environment variable: `TIINGO_API_KEY`.

**Response formats:** JSON (default), CSV (`?format=csv`). EOD timestamps are ISO 8601 UTC; IEX intraday timestamps use `America/New_York`.

---

### 1.2 Rate Limits and Tiers

| Tier | Cost | Requests/Hour | Requests/Day | Unique Tickers/Month | Notes |
|---|---|---|---|---|---|
| Free | $0 | 50 | 1,000 | 500 | Personal use only |
| Power | ~$10/month | 5,000 | 50,000 | Unlimited | Includes News + Fundamentals |
| Commercial | Contact sales | Custom | Custom | Unlimited | Commercial license required |

⚠️ **Critical:** When the 500 unique ticker/month limit is exceeded, the API returns **HTTP 200 OK with plain text** instead of JSON. Always wrap `json.loads()` in try/except.

---

### 1.3 EOD Stock Prices

**Ticker metadata:**
```
GET https://api.tiingo.com/tiingo/daily/{ticker}
```
Returns: `ticker`, `name`, `description`, `startDate`, `endDate`, `exchangeCode`

**Historical price data:**
```
GET https://api.tiingo.com/tiingo/daily/{ticker}/prices
```

**Key parameters:**

| Parameter | Type | Description |
|---|---|---|
| `startDate` | string | `YYYY-MM-DD` |
| `endDate` | string | `YYYY-MM-DD` |
| `resampleFreq` | string | `daily`, `weekly`, `monthly`, `annually`, or intraday (`30min`, `1hour`) |
| `columns` | string | Comma-separated fields to return |
| `format` | string | `json` (default) or `csv` |

**Response fields:**

| Field | Type | Notes |
|---|---|---|
| `date` | string (ISO 8601 UTC) | e.g., `"2024-01-15T00:00:00+00:00"` |
| `open` / `high` / `low` / `close` | float | Unadjusted prices |
| `volume` | integer | Unadjusted volume |
| `adjOpen` / `adjHigh` / `adjLow` / `adjClose` | float | Split + dividend adjusted (CRSP methodology, no rounding) |
| `adjVolume` | integer | Adjusted volume |
| `divCash` | float | Cash dividend on ex-date; 0.0 otherwise |
| `splitFactor` | float | Split factor on split date; 1.0 otherwise |

**Data freshness:** EOD updates by 5:30 PM ET for equities/ETFs; corrections applied until 8:00 PM ET.

**Supported tickers bulk download:**
```
GET https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip
```
CSV with columns: `ticker`, `exchange`, `assetType` (`Stock`, `ETF`, `Mutual Fund`), `priceCurrency`, `startDate`, `endDate`.

**Ticker format notes:**
- Standard US tickers work: `AAPL`, `SPY`, `MSFT`
- ETFs and mutual funds fully supported
- ⚠️ Index symbols (`^GSPC`, `^DJI`) are **not supported** — use ETF proxies (`SPY`, `DIA`)
- No native batch endpoint — one request per ticker

---

### 1.4 Real-Time / IEX Endpoint

**REST (latest quote):**
```
GET https://api.tiingo.com/iex/{ticker}
GET https://api.tiingo.com/iex?tickers=AAPL,MSFT,GOOG
```

**REST (historical intraday):**
```
GET https://api.tiingo.com/iex/{ticker}/prices
```

**IEX quote response fields:**

| Field | Type | Notes |
|---|---|---|
| `ticker` | string | Symbol |
| `timestamp` | string | Quote timestamp (America/New_York) |
| `last` | float | Last trade price |
| `lastSize` | integer | Size of last trade |
| `tngoLast` | float | Tiingo-normalized last price |
| `prevClose` | float | Previous day's close |
| `open` / `high` / `low` | float | Today's OHLC |
| `mid` | float | Midpoint of bid/ask |
| `bidPrice` / `bidSize` | float / int | Current bid |
| `askPrice` / `askSize` | float / int | Current ask |

**WebSocket (real-time streaming):**
```
wss://api.tiingo.com/iex
```

---

### 1.5 Fundamentals Endpoint

*Requires paid tier (Power+). US equities, ADRs, and Chinese equities only.*

**Daily metrics (price-derived):**
```
GET https://api.tiingo.com/tiingo/fundamentals/{ticker}/daily
```
Fields: `date`, `marketCap`, `enterpriseVal`, `peRatio`, `pbRatio`, `trailingPEG1Y`

**Financial statements:**
```
GET https://api.tiingo.com/tiingo/fundamentals/{ticker}/statements
```
Parameters: `startDate`, `endDate`, `asReported` (boolean)

**Definitions catalog:**
```
GET https://api.tiingo.com/tiingo/fundamentals/definitions
```

---

### 1.6 News Endpoint

*Requires Power tier or above.*

```
GET https://api.tiingo.com/tiingo/news
```

**Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `tickers` | string (comma-sep) | Filter by ticker |
| `tags` | string (comma-sep) | Filter by Tiingo-assigned tags |
| `sources` | string (comma-sep) | Filter by source domain |
| `startDate` / `endDate` | string | `YYYY-MM-DD` date range |
| `limit` | integer | Max articles (max: 1,000) |
| `offset` | integer | Pagination offset |
| `sortBy` | string | `publishedDate` (default) or `crawlDate` |
| `onlyWithTickers` | boolean | Only articles tagged with a ticker |

**Response fields:**

| Field | Type | Notes |
|---|---|---|
| `id` | integer | Unique article ID |
| `title` | string | Headline |
| `description` | string | Short snippet |
| `url` | string | Full article link |
| `publishedDate` | string (ISO 8601 UTC) | Publication time |
| `crawlDate` | string (ISO 8601 UTC) | Tiingo index time |
| `source` | string | Source domain |
| `tags` | array of strings | Algorithm-assigned tags |
| `tickers` | array of strings | Tagged ticker symbols |

**Bulk news download:**
```
GET https://api.tiingo.com/tiingo/news/bulk_download
GET https://api.tiingo.com/tiingo/news/bulk_download/{file_id}
```

> **Flywheel opportunity:** News can be embedded into the RAG layer — wire `tickers` filter to warehouse companies for automatic coverage.

---

### 1.7 Crypto Endpoint

**Top-of-book:**
```
GET https://api.tiingo.com/tiingo/crypto/top?tickers=btcusd,ethusd
```

**Historical prices:**
```
GET https://api.tiingo.com/tiingo/crypto/prices?tickers=btcusd&startDate=2024-01-01&resampleFreq=1hour
```

**Ticker format:** Lowercase base+quote pair: `btcusd`, `ethusd`, `solusd`.

---

### 1.8 Forex Endpoint

**Historical:**
```
GET https://api.tiingo.com/tiingo/fx/{ticker}/prices
```
Example tickers: `eurusd`, `gbpusd`

**Top-of-book:**
```
GET https://api.tiingo.com/tiingo/fx/top?tickers=eurusd,gbpusd
```

**WebSocket:** `wss://api.tiingo.com/fx`

---

### 1.9 Utilities

**Ticker search:**
```
GET https://api.tiingo.com/tiingo/utilities/search?query=apple
```

**Dividends:**
```
GET https://api.tiingo.com/tiingo/daily/{ticker}/dividends
```

**Splits:**
```
GET https://api.tiingo.com/tiingo/daily/{ticker}/splits
```

---

### 1.10 Tiingo Gotchas

1. **Rate limit is HTTP 200 with plain text** — not a 429. Always wrap JSON parsing in try/except.
2. **500 unique tickers/month cap** — counts unique symbols queried per calendar month, not number of requests.
3. **No batch EOD endpoint** — one request per symbol.
4. **No index symbols** — use ETF proxies (`SPY` for S&P 500).
5. **Timezone mismatch** — EOD timestamps are UTC; IEX intraday timestamps are `America/New_York`. Convert everything to UTC at ingest.
6. **Adjusted prices use CRSP methodology** — full precision, no rounding. Handle float precision explicitly.
7. **News and Fundamentals require paid tier.**
8. **Commercial use requires commercial license** — standard plans are "internal, personal use only."

---

## Part 2: FMP API Reference

### 2.1 General Overview

**Base URLs:**
- v3 (stable/legacy): `https://financialmodelingprep.com/api/v3/`
- Stable (new): `https://financialmodelingprep.com/stable/`
- v4 (advanced): `https://financialmodelingprep.com/api/v4/`

**Authentication:** API key as query parameter on every request:
```
?apikey=YOUR_API_KEY
```
Environment variable: `FMP_API_KEY`.

**Response format:** JSON (default). Add `?datatype=csv` for CSV, `?datatype=zip` for ZIP.

**Data coverage:** 25,000+ stocks across 46+ exchanges; financial statements back to earliest SEC filing.

---

### 2.2 Rate Limits and Tiers

| Tier | Cost | Requests/Day | Requests/Min | Bandwidth (30-day) | History |
|---|---|---|---|---|---|
| Free | $0 | 250 | ~5 | 500 MB | 5 years |
| Starter | ~$22/month | Unlimited | 300 | 20 GB | 5 years |
| Premium | ~$59/month | Unlimited | 750 | 50 GB | 30+ years |
| Ultimate | ~$149/month | Unlimited | 3,000 | 150 GB | 30+ years |
| Enterprise | Custom | Unlimited | Custom | 1 TB+ | 30+ years |

⚠️ **Free tier: 250 req/day resets at midnight UTC.** For a 6-agent platform, assume ~40 calls per full analysis run — ~6 full runs/day max.

⚠️ **Bandwidth limit (500 MB/30 days)** can be hit before the request limit if pulling full price history. Always use `from`/`to` parameters.

---

### 2.3 Real-Time Quote

**Single:**
```
GET /api/v3/quote/{symbol}?apikey=KEY
```

**Batch (counts as ONE API call):**
```
GET /api/v3/quote/AAPL,MSFT,GOOG?apikey=KEY
```

**Response fields:**

| Field | Type | Notes |
|---|---|---|
| `symbol` | string | Ticker |
| `name` | string | Company name |
| `price` | float | Current price |
| `changesPercentage` | float | % change from previous close |
| `dayLow` / `dayHigh` | float | Day range |
| `yearHigh` / `yearLow` | float | 52-week range |
| `marketCap` | float | Market cap (USD) |
| `priceAvg50` / `priceAvg200` | float | Moving averages |
| `volume` / `avgVolume` | integer | Volume |
| `eps` | float | Trailing EPS |
| `pe` | float | Trailing P/E — **`0` or `null` for negative earnings** |
| `earningsAnnouncement` | string (ISO datetime) | Next earnings date |
| `sharesOutstanding` | integer | Shares outstanding |
| `timestamp` | integer | Unix epoch |

---

### 2.4 Historical Price Data

**EOD historical:**
```
GET /api/v3/historical-price-full/{symbol}?from=2020-01-01&to=2024-12-31&apikey=KEY
GET /stable/historical-price-eod/full?symbol={symbol}&from=YYYY-MM-DD&to=YYYY-MM-DD&apikey=KEY
```

**Response fields (inside `historicalStockList[].historical[]`):**

| Field | Type | Notes |
|---|---|---|
| `date` | string (`YYYY-MM-DD`) | Trading date |
| `open` / `high` / `low` / `close` | float | Split-adjusted prices |
| `adjClose` | float | Split + dividend adjusted close |
| `volume` / `unadjustedVolume` | integer | |
| `vwap` | float | Volume-weighted average price |
| `changePercent` | float | Day over day % change |

**Intraday:**
```
GET /api/v3/historical-chart/{interval}/{symbol}?apikey=KEY
```
Intervals: `1min`, `5min`, `15min`, `30min`, `1hour`, `4hour`

**Batch EOD by date (all tickers, one call):**
```
GET /api/v4/batch-request-end-of-day-prices?date=YYYY-MM-DD&apikey=KEY
```

---

### 2.5 Company Profile

```
GET /api/v3/profile/{symbol}?apikey=KEY
GET /stable/profile/{symbol}?apikey=KEY
```

**Key fields:** `symbol`, `companyName`, `price`, `mktCap`, `beta`, `volAvg`, `range` (52-week), `currency`, `cik`, `isin`, `exchange`, `industry`, `sector`, `website`, `description`, `ceo`, `country`, `fullTimeEmployees`, `ipoDate`, `isEtf`, `isActivelyTrading`, `image`

---

### 2.6 Financial Statements

All follow the same pattern. Default `period=annual`; add `?period=quarter` for quarterly.

**Income Statement:**
```
GET /api/v3/income-statement/{symbol}?period=annual&limit=10&apikey=KEY
```
Key fields: `revenue`, `costOfRevenue`, `grossProfit`, `grossProfitRatio`, `operatingIncome`, `operatingIncomeRatio`, `ebitda`, `ebitdaratio`, `netIncome`, `netIncomeRatio`, `eps`, `epsdiluted`

**Balance Sheet:**
```
GET /api/v3/balance-sheet-statement/{symbol}?period=quarter&limit=20&apikey=KEY
```
Key fields: `cashAndCashEquivalents`, `totalCurrentAssets`, `totalAssets`, `shortTermDebt`, `longTermDebt`, `totalDebt`, `netDebt`, `totalStockholdersEquity`

**Cash Flow:**
```
GET /api/v3/cash-flow-statement/{symbol}?period=annual&apikey=KEY
```
Key fields: `operatingCashFlow`, `capitalExpenditure`, `freeCashFlow`, `dividendsPaid`, `commonStockRepurchased`

**Financial reports (raw 10-K/10-Q):**
```
GET /api/v4/financial-reports-json?symbol=AAPL&year=2023&period=FY&apikey=KEY
```

---

### 2.7 Key Metrics and Ratios

**Key Metrics (periodic):**
```
GET /api/v3/key-metrics/{symbol}?period=annual&limit=10&apikey=KEY
```

**Key Metrics TTM (trailing twelve months):**
```
GET /api/v3/key-metrics-ttm/{symbol}?apikey=KEY
GET /stable/key-metrics-ttm?symbol={symbol}&apikey=KEY
```
Key fields: `revenuePerShare`, `freeCashFlowPerShare`, `bookValuePerShare`, `marketCap`, `enterpriseValue`, `peRatio`, `priceToSalesRatio`, `pbRatio`, `evToSales`, `enterpriseValueOverEBITDA`, `evToFreeCashFlow`, `debtToEquity`, `debtToAssets`, `currentRatio`, `roic`, `roe`, `roa`, `dividendYield`

**Key Metrics TTM Bulk:**
```
GET /stable/key-metrics-ttm/bulk?apikey=KEY
```

**Financial Ratios TTM:**
```
GET /api/v3/ratios-ttm/{symbol}?apikey=KEY
```
Key fields: `grossProfitMargin`, `operatingProfitMargin`, `netProfitMargin`, `returnOnEquity`, `returnOnAssets`, `debtEquityRatio`, `currentRatio`, `priceEarningsRatio`, `priceToBookRatio`, `priceToSalesRatio`, `enterpriseValueMultiple`

---

### 2.8 Analyst Estimates and Price Targets

**Analyst consensus estimates:**
```
GET /api/v3/analyst-estimates/{symbol}?period=annual&limit=10&apikey=KEY
GET /stable/financial-estimates?symbol={symbol}&period=quarter&apikey=KEY
```
Fields per period: `date`, `estimatedRevenueLow/High/Avg`, `estimatedEbitdaAvg`, `estimatedNetIncomeLow/High/Avg`, `estimatedEpsAvg/High/Low`, `numberAnalystEstimatedRevenue`, `numberAnalystsEstimatedEps`

**Price target summary:**
```
GET /stable/price-target-summary?symbol={symbol}&apikey=KEY
```

**Price target consensus:**
```
GET /stable/price-target-consensus?symbol={symbol}&apikey=KEY
```
Fields: `symbol`, `targetHigh`, `targetLow`, `targetConsensus`, `targetMedian`

**Analyst grades summary:**
```
GET /stable/grades-summary?symbol={symbol}&apikey=KEY
```
Fields: `symbol`, `strongBuy`, `buy`, `hold`, `sell`, `strongSell`

---

### 2.9 Earnings

**Earnings surprises:**
```
GET /api/v3/earnings-surprises/{symbol}?apikey=KEY
```
Fields: `date`, `symbol`, `actualEarningResult`, `estimatedEarning`

**Earnings history:**
```
GET /stable/earnings/{symbol}?apikey=KEY
```
Fields: `date`, `eps`, `epsEstimated`, `time` (BMO/AMC), `revenue`, `revenueEstimated`, `fiscalDateEnding`

**Earnings calendar (upcoming):**
```
GET /stable/earnings-calendar?from=YYYY-MM-DD&to=YYYY-MM-DD&apikey=KEY
```

---

### 2.10 Stock Peers

```
GET /api/v4/stock_peers?symbol=AAPL&apikey=KEY
```
Returns: `symbol`, `peersList` (array of peer ticker strings). Selected by sector, exchange, and market cap similarity.

⚠️ May be restricted to paid tiers — test before relying on it.

---

### 2.11 News

**Stock-specific news:**
```
GET /api/v3/stock_news?tickers=AAPL,MSFT&limit=50&from=YYYY-MM-DD&to=YYYY-MM-DD&apikey=KEY
GET /stable/news/stock?symbols={symbol}&limit=50&apikey=KEY
```

**General market news:**
```
GET /stable/news/general?limit=20&apikey=KEY
```

**Search news:**
```
GET /stable/news/search?query=earnings+beat&apikey=KEY
```

**Response fields:** `publishedDate`, `title`, `image`, `site`, `text` (snippet), `url`, `symbol`

---

### 2.12 Screener

```
GET /api/v3/stock-screener?sector=Technology&marketCapMoreThan=1000000000&exchange=NASDAQ&limit=100&apikey=KEY
```

**Key parameters:** `marketCapMoreThan/LowerThan`, `priceMoreThan/LowerThan`, `betaMoreThan/LowerThan`, `isEtf`, `isActivelyTrading`, `sector`, `industry`, `country`, `exchange`, `limit`

**Sectors:** `Technology`, `Healthcare`, `Financial Services`, `Energy`, `Consumer Cyclical`, `Consumer Defensive`, `Industrials`, `Basic Materials`, `Real Estate`, `Utilities`, `Communication Services`

---

### 2.13 Index and Macro Data

**Index prices (FMP supports `^` symbols via URL encoding):**
```
GET /api/v3/historical-price-full/%5EGSPC?apikey=KEY
```

**S&P 500 constituents:**
```
GET /api/v3/sp500_constituent?apikey=KEY
```

**Macroeconomic indicators:**
```
GET /api/v4/economic?name=GDP&apikey=KEY
```
Available: `GDP`, `realGDP`, `federalFunds`, `CPI`, `inflationRate`, `retailSales`, `unemploymentRate`, `totalNonfarmPayroll`, `initialClaims`, `30YearFixedRateMortgageAverage`, `smoothedUSRecessionProbabilities`, and more.

---

### 2.14 ETF and Institutional Holdings

**ETF holdings:**
```
GET /api/v3/etf-holder/{symbol}?apikey=KEY
```

**Institutional (13-F) holders:**
```
GET /api/v3/institutional-holder/{symbol}?apikey=KEY
```

---

### 2.15 DCF Valuation

```
GET /api/v3/discounted-cash-flow/{symbol}?apikey=KEY
GET /api/v3/historical-discounted-cash-flow/{symbol}?period=quarter&apikey=KEY
```

---

### 2.16 FMP Gotchas

1. **`pe == 0` or `null` for negative/zero earnings** — never treat `pe == 0` as valid data. Check for both `null` and `0` and emit N/A.
2. **Free tier 250 req/day resets at midnight UTC** — not your local timezone. Build UTC-aware retry logic.
3. **Bandwidth cap (500 MB/30 days)** — always pass `from`/`to` date params on historical endpoints.
4. **v3 vs. stable endpoint migration** — FMP is migrating to `/stable/`. Field names can differ between versions. New integrations should target `/stable/` where documented.
5. **Batch quote = one API call** — always batch aggressively on paid tiers.
6. **`stock_peers` may be paid-tier only** — test before relying on it in free-tier workflows.
7. **Two different PE field names** — `pe` (quote endpoint) vs. `peRatio` (key-metrics) vs. `priceEarningsRatio` (ratios-ttm). Use `ratios-ttm.priceEarningsRatio` for consistency in screening.
8. **FMP returns HTTP 429 for rate limit** — proper status code, parse `Retry-After` header.
9. **Index symbols use URL-encoded `^`** — `%5EGSPC` for S&P 500, `%5EDJI` for Dow.
10. **Short-interest data and Russell 2000 constituents not available** at any tier.

---

## Part 3: Which API for Which Data

| Data Type | Use | Reason |
|---|---|---|
| EOD stock prices (US) | Tiingo preferred | CRSP methodology, higher precision |
| Adjusted close (total return) | Either | Both provide `adjClose`; Tiingo has no rounding |
| Real-time/intraday quotes | Tiingo IEX | Real-time via IEX feed; FMP intraday ~15min delayed on lower tiers |
| P/E ratio (trailing) | FMP `key-metrics-ttm` | Available on free tier; Tiingo fundamentals requires paid |
| Market cap | FMP `/profile/` or `/quote/` | Free tier; Tiingo fundamentals requires paid |
| Income statement | FMP | Broader coverage, deeper history, free for US |
| Balance sheet | FMP | Same |
| Cash flow statement | FMP | Same |
| Analyst EPS/revenue estimates | FMP | Tiingo has no analyst consensus endpoint |
| Price targets | FMP | Tiingo has no price target endpoint |
| Earnings surprises | FMP | Tiingo has no earnings surprise endpoint |
| Peer list | FMP `/api/v4/stock_peers` | Tiingo has no peer endpoint |
| Company profile (sector/industry) | FMP | More comprehensive; Tiingo metadata is minimal |
| Financial ratios TTM | FMP `ratios-ttm` | Well-structured; not available in Tiingo free tier |
| News | Tiingo (paid) or FMP (free) | Tiingo news is higher quality; FMP accessible on free tier |
| Crypto prices | Tiingo | 2,100+ tickers, 40+ exchanges; FMP crypto coverage is thinner |
| Forex historical | Tiingo | 40+ pairs from tier-1 banks; WebSocket real-time |
| Index prices (^GSPC, ^VIX) | FMP | Tiingo does not support index symbols |
| Stock screener | FMP | Tiingo has no screener |
| Macroeconomic indicators | FMP | Tiingo has no macro endpoint |
| ETF price history | Tiingo | 45,149 ETFs/MFs covered |
| ETF holdings breakdown | FMP | Tiingo has no holdings endpoint |
| Institutional holdings (13-F) | FMP | Tiingo has no 13-F data |
| DCF valuation | FMP | Built-in DCF endpoint; Tiingo has no equivalent |
| SEC filings / as-reported data | FMP | Direct 10-K/10-Q JSON/XLSX download |
| Batch price download (all tickers, one date) | FMP `/api/v4/batch-request-end-of-day-prices` | Single call; no Tiingo equivalent |

---

## Part 4: Integration Gotchas and Tips

### Authentication
- **Tiingo:** Use `Authorization: Token KEY` header. Never log raw request URLs — they will contain your token if using query param auth.
- **FMP:** Key is always in the query string. Guard against exposure in proxy/CDN access logs.

### Rate Limit Handling
- **Tiingo:** 500 unique tickers/month is the binding constraint on free tier, not req/hr. Upgrade to Power or cache aggressively.
- **Tiingo rate limit = HTTP 200 plain text** — detect by checking `Content-Type` or try/except on `json.loads()`.
- **FMP free tier = 250 req/day** — roughly 6 full analysis runs/day. Upgrade or cache heavily.
- **FMP paid tiers = per-minute cap** — implement token-bucket throttling.

### Caching TTLs (recommended)
| Data | TTL |
|---|---|
| EOD prices | 6 hours (or refresh once after 6 PM ET) |
| Intraday quotes | 1–5 min (Tiingo IEX) / 15 min (FMP) |
| Financial statements | 24 hours |
| Key metrics TTM | 4 hours |
| News | 15–30 min |
| Analyst estimates / price targets | 4 hours |

### Data Pipeline Tips
1. **Normalize timestamps at ingest.** Convert all Tiingo and FMP timestamps to UTC immediately.
2. **Use FMP batch quote** for multi-ticker live prices on paid tiers — one API call regardless of symbol count.
3. **Validate tickers against `supported_tickers.zip`** before querying Tiingo.
4. **PE is nullable/zero for unprofitable companies** — fall back to EV/EBITDA or P/S.
5. **Always use `adjClose`** for return calculations. Raw `close` is split-only-adjusted (FMP) or fully unadjusted (Tiingo).
6. **FMP historical-price-full returns full history by default** — always pass `from`/`to` to limit payload.
7. **FMP `earningsAnnouncement`** in the quote response can be stale — cross-check with the earnings calendar endpoint.
8. **Tiingo news `crawlDate` vs `publishedDate`:** Use `publishedDate` for display; use `crawlDate` to poll for new articles since last check.

### Field Name Mapping (same concept, different names)
| Concept | Tiingo | FMP quote | FMP key-metrics | FMP ratios-ttm |
|---|---|---|---|---|
| P/E ratio | `peRatio` (fundamentals) | `pe` | `peRatio` | `priceEarningsRatio` |
| Market cap | `marketCap` (fundamentals) | `marketCap` | `marketCap` | — |
| EV/EBITDA | — | — | `enterpriseValueOverEBITDA` | `enterpriseValueMultiple` |
| Adjusted close | `adjClose` | — | — | — |
| Market cap (profile) | — | `marketCap` | — | — |

---

## Untapped Opportunities for This Platform

Given the current architecture, these endpoints are **not yet wired in** but are high-value:

| Endpoint | API | Value |
|---|---|---|
| `/tiingo/news?tickers=...` | Tiingo (paid) | Real-time news per ticker → feed into Tavily replacement or supplement |
| `/stable/news/stock` | FMP (free) | News feed available now, no extra cost |
| `/api/v4/economic?name=GDP` | FMP | Replace or supplement FRED for macro indicators |
| `/api/v4/stock_peers` | FMP | Structured peer list to improve peer discovery accuracy |
| `/api/v3/key-metrics-ttm/bulk` | FMP | Pull all TTM metrics in one call for warehouse screening |
| `/api/v4/batch-request-end-of-day-prices` | FMP | Nightly batch price update for entire warehouse in one call |
| `wss://api.tiingo.com/iex` | Tiingo | WebSocket for real-time price updates (post-Streamlit migration) |
| `/api/v3/earnings-surprises` | FMP | Historical beat/miss data → feeds Earnings Agent context |
| `/stable/earnings-calendar` | FMP | Forward-looking earnings dates → scheduling/alerting |
| `/api/v3/discounted-cash-flow` | FMP | FMP's own DCF as a cross-check against your DCF agent |
| `/tiingo/crypto/prices` | Tiingo | Crypto coverage if you ever expand beyond equities |
