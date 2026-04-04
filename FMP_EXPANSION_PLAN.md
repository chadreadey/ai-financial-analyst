# FMP Expansion Plan — 7 New Data Sources

> Generated 2026-03-26. All phases follow existing codebase patterns verified by source inspection.

---

## Codebase Findings

**`fmp_client.py`** — `FMPClient` wraps `requests.Session`, uses a two-lock pattern in `FMPCache`: first lock checks cache, blocking HTTP fires outside the lock, second lock writes result. All 5 existing methods follow this exact pattern. Warning threshold at 200 calls, error at 250.

**`market_enrichment.py`** — All enrichment tasks are `_task_*` functions returning `Dict[str, Any]` with keys `section_entries` (list of `(key, text)` tuples), `sources`, `warnings`, `filter_stats`. `build_enrichment_context` submits all tasks to a `ThreadPoolExecutor`, iterates results in `_ENRICHMENT_TASK_ORDER`. Current order: `("market_data", "tavily", "peers", "estimates", "price", "macro", "rag")`.

**`peer_enrichment.py`** — `discover_peers()` uses Tavily web search to extract ticker symbols from free-text, then validates each against FMP/Yahoo. `_validate_ticker()` already accepts `fmp_cache` and calls `fmp_cache.get_quote()` as primary validator.

**Agent `enrichment_sections` tuples (current):**
- `EarningsAgent`: `("market_data", "external_company", "analyst_estimates", "peer_comparison", "filing_mda", "rag_research")`
- `CompetitiveAgent`: `("sector_briefing", "external_sector", "external_company", "external_industry", "peer_comparison", "filing_business", "segment_data", "rag_research")`
- `RiskAgent`: `("market_data", "external_risks", "macro_data", "price_history", "filing_risk_factors", "filing_mda", "rag_research")`
- `DCFAgent`: `("market_data", "external_company", "analyst_estimates", "price_history", "macro_data", "peer_comparison", "filing_mda", "segment_data", "rag_research")`

---

## FMP API Budget — Before and After

### Current Baseline (~15 calls/run)

| Call | Endpoint | Count |
|---|---|---|
| `get_quote(ticker)` | `/api/v3/quote/{symbol}` | ~6 (subject + peers) |
| `get_key_metrics(ticker)` | `/api/v3/key-metrics-ttm/{symbol}` | ~6 (subject + peers) |
| `get_analyst_estimates(ticker)` | `/api/v3/analyst-estimates/{symbol}` | 1 |
| `get_price_target(ticker)` | `/api/v4/price-target-summary` | 1 |
| `get_earnings_surprises(ticker)` | `/api/v3/earnings-surprises/{symbol}` | 1 |
| **Baseline total** | | **~15** |

### Post-All-Phases Budget

| Phase | New Endpoint | Marginal Calls | Running Total |
|---|---|---|---|
| Baseline | (existing) | — | ~15 |
| 1a | Earnings Surprises section | 0 (cache hit) | ~15 |
| 1b | Analyst Grades Summary | +1 | ~16 |
| 2 | FMP News | +1 | ~17 |
| 3a | DCF Cross-Check | +1 | ~18 |
| 3b | Institutional Holdings | +1 | ~19 |
| 4 | Stock Screener | +1 | ~20 |
| 5 | FMP SEC Filings (default off) | +1 (if enabled) | ~21 |
| **Full run total** | | | **~21 calls** |

**Budget verdict:** 21 calls/run is well within the 250/day free tier (~11 full runs/day). The 200-call warning in `FMPClient._get()` is per-run, not per-day — no changes needed.

---

## Phase 1: Earnings Surprises + Analyst Grades Summary

**Depends on:** Nothing
**Effort:** Low | **Impact:** High

### Phase 1a — Earnings Surprises as Dedicated Section Key

`get_earnings_surprises()` already exists on `FMPClient` and `FMPCache` and is fetched inside `_task_estimates`. This phase promotes it to its own enrichment key so `EarningsAgent` subscribes to it independently without receiving the full estimates blob.

#### `market_enrichment.py`

1. Add `_fmp_earnings_surprises_section(ticker, fmp_cache) -> tuple[str, list[str]]` — renders last 8 quarters of beat/miss with magnitude under header `=== Earnings Surprises (FMP) ===`. Pure formatting, no new HTTP call.

2. Add `_task_earnings_surprises(ticker, fmp_cache) -> Dict[str, Any]`:
```python
# guard: if not fmp_cache or not env_flag("ENABLE_FMP"): return empty
# section_entries: [("earnings_surprises", text)]
```

3. Update `_ENRICHMENT_TASK_ORDER` — insert `"earnings_surprises"` after `"estimates"`.

4. In `build_enrichment_context` — submit conditionally alongside other FMP tasks.

#### `config.py`
```python
max_earnings_surprises_section_chars: int = 1200
```

#### `agents/earnings.py`
Add `"earnings_surprises"` to `enrichment_sections` after `"analyst_estimates"`.

**API cost:** 0 new calls (cache hit).
**New env vars:** None (gated by existing `ENABLE_FMP`).
**Verification:** `python main.py AAPL --inspect-context` — confirm `=== Earnings Surprises (FMP) ===` is a distinct section separate from estimates.

---

### Phase 1b — Analyst Grades Summary

#### `fmp_client.py`

Add to `FMPClient`:
```python
def get_grades_summary(self, symbol: str) -> dict:
    # GET /stable/grades-summary?symbol={symbol}
    # Fields: strongBuy, buy, hold, sell, strongSell, consensus
```

Add to `FMPCache`:
```python
_grades_cache: Dict[str, dict] = {}

def get_grades_summary(self, symbol: str) -> dict:
    # Two-lock pattern identical to get_price_target()
```

#### `market_enrichment.py`

1. Add `_fmp_grades_section(ticker, fmp_cache) -> tuple[str, list[str]]` — renders buy/hold/sell distribution + consensus under `=== Analyst Grades (FMP) ===`.

2. Add `_task_analyst_grades(ticker, fmp_cache) -> Dict[str, Any]` — gated by `fmp_cache and env_flag("ENABLE_FMP")`.

3. Insert `"analyst_grades"` into `_ENRICHMENT_TASK_ORDER` after `"earnings_surprises"`.

4. Submit conditionally in `build_enrichment_context`.

#### `config.py`
```python
max_analyst_grades_section_chars: int = 800
```

#### `agents/dcf.py`
Add `"analyst_grades"` to `enrichment_sections` after `"analyst_estimates"`.

**API cost:** +1 call/run.
**New env vars:** None (gated by `ENABLE_FMP`).
**Verification:** Confirm `=== Analyst Grades (FMP) ===` in DCF agent context.

---

## Phase 2: FMP News Feed

**Depends on:** Phase 1 (pattern established)
**Effort:** Low | **Impact:** High

#### `fmp_client.py`

Add to `FMPClient`:
```python
def get_stock_news(self, symbol: str, limit: int = 10) -> list[dict]:
    # GET /api/v4/stock_news?tickers={symbol}&limit={limit}
    # Fields: title, text, url, publishedDate, site
```

Add to `FMPCache`:
```python
_news_cache: Dict[str, list] = {}

def get_stock_news(self, symbol: str, limit: int = 10) -> list[dict]:
    # Cache key: f"{sym}:{limit}"
    # Two-lock pattern identical to get_earnings_surprises()
```

#### `config.py`
```python
enable_fmp_news: bool = True
max_fmp_news_section_chars: int = 2000
fmp_news_limit: int = 10
```

#### `market_enrichment.py`

1. Add `_fmp_news_section(ticker, fmp_cache) -> tuple[str, list[str]]` — renders most recent articles as numbered list: `{n}. {title} ({publishedDate})\n   {url}\n   {150-char snippet}` under `=== Recent News (FMP) ===`.

2. Add `_task_fmp_news(ticker, fmp_cache) -> Dict[str, Any]` — gated by `fmp_cache and settings.enable_fmp_news`.

3. Insert `"fmp_news"` into `_ENRICHMENT_TASK_ORDER` immediately after `"tavily"` (high recency signal, appears early in context).

4. In `build_enrichment_context`:
```python
if fmp_cache and settings.enable_fmp_news:
    futures["fmp_news"] = pool.submit(_task_fmp_news, ticker, fmp_cache)
```

#### Agent updates

`agents/earnings.py` — add `"fmp_news"` after `"external_company"`.

`agents/competitive.py` — add `"fmp_news"` after `"external_company"`.

**API cost:** +1 call/run.
**New env vars:** `ENABLE_FMP_NEWS=true`
**Verification:** Confirm `=== Recent News (FMP) ===` in Earnings and Competitive agent contexts.

---

## Phase 3: DCF Cross-Check + Institutional Holdings

**Depends on:** Phase 1
**Effort:** Medium | **Impact:** Medium–High

### Phase 3a — DCF Cross-Check

#### `fmp_client.py`

Add to `FMPClient`:
```python
def get_dcf_valuation(self, symbol: str) -> dict:
    # GET /api/v3/discounted-cash-flow/{symbol}
    # Fields: symbol, date, dcf, "Stock Price"
```

Add to `FMPCache`:
```python
_dcf_cache: Dict[str, dict] = {}

def get_dcf_valuation(self, symbol: str) -> dict:
    # Two-lock pattern identical to get_price_target()
```

#### `config.py`
```python
enable_fmp_dcf: bool = True
max_fmp_dcf_section_chars: int = 600
```

#### `market_enrichment.py`

1. Add `_fmp_dcf_section(ticker, fmp_cache) -> tuple[str, list[str]]` — renders FMP DCF estimate, current price, implied upside/downside %, data date under `=== FMP DCF Model (Cross-Check) ===`.

2. Add `_task_fmp_dcf(ticker, fmp_cache) -> Dict[str, Any]` — gated by `fmp_cache and settings.enable_fmp_dcf`.

3. Insert `"fmp_dcf"` into `_ENRICHMENT_TASK_ORDER` after `"analyst_grades"`.

#### `agents/dcf.py`
Add `"fmp_dcf"` to `enrichment_sections` after `"analyst_grades"`.

**API cost:** +1 call/run.
**New env vars:** `ENABLE_FMP_DCF=true`
**Verification:** Confirm `=== FMP DCF Model (Cross-Check) ===` in DCF agent context with a dollar figure.

---

### Phase 3b — Institutional Holdings (13-F)

#### `fmp_client.py`

Add to `FMPClient`:
```python
def get_institutional_holders(self, symbol: str, limit: int = 10) -> list[dict]:
    # GET /api/v4/institutional-ownership/institutional-holders/symbol-ownership
    # params: symbol, limit, includeCurrentQuarter=True
    # Fields: investorName, shares, dateReported, change, changeInShares
```

Add to `FMPCache`:
```python
_inst_holders_cache: Dict[str, list] = {}

def get_institutional_holders(self, symbol: str, limit: int = 10) -> list[dict]:
    # Cache key: f"{sym}:{limit}"
    # Two-lock pattern
```

#### `config.py`
```python
enable_fmp_institutional: bool = True
max_fmp_institutional_section_chars: int = 1500
fmp_institutional_limit: int = 10
```

#### `market_enrichment.py`

1. Add `_fmp_institutional_section(ticker, fmp_cache) -> tuple[str, list[str]]` — renders top holders table `{rank}. {investorName}: {shares:,} shares ({changeInShares:+,} vs. prior quarter)` under `=== Institutional Holdings (FMP / 13-F) ===`.

2. Add `_task_fmp_institutional(ticker, fmp_cache) -> Dict[str, Any]` — gated by `fmp_cache and settings.enable_fmp_institutional`.

3. Insert `"fmp_institutional"` into `_ENRICHMENT_TASK_ORDER` after `"fmp_dcf"`.

#### Agent updates

`agents/risk.py` — add `"fmp_institutional"` after `"macro_data"`.

`agents/competitive.py` — add `"fmp_institutional"` after `"fmp_news"`.

**API cost:** +1 call/run.
**New env vars:** `ENABLE_FMP_INSTITUTIONAL=true`
**Verification:** Confirm `=== Institutional Holdings (FMP / 13-F) ===` in Risk and Competitive agent contexts with known large holders (e.g., Vanguard for AAPL).

---

## Phase 4: FMP Stock Screener for Peer Discovery

**Depends on:** Nothing (self-contained in `peer_enrichment.py`)
**Effort:** Medium | **Impact:** Medium

The current `discover_peers()` uses Tavily web search to extract tickers from free-text then validates each. The FMP screener returns structured, pre-validated peers by sector + market cap range in a single call.

#### `fmp_client.py`

Add to `FMPClient`:
```python
def screen_stocks(
    self,
    sector: str = "",
    market_cap_more_than: int = 0,
    market_cap_lower_than: int = 0,
    limit: int = 20,
) -> list[dict]:
    # GET /api/v3/stock-screener
    # params: sector, marketCapMoreThan, marketCapLowerThan, limit, exchange=NYSE,NASDAQ
    # Fields: symbol, companyName, marketCap, sector, industry, beta, price
```

Add to `FMPCache`:
```python
_screener_cache: Dict[str, list] = {}

def screen_stocks(self, sector, market_cap_more_than, market_cap_lower_than, limit=20) -> list[dict]:
    # Cache key: f"{sector}:{market_cap_more_than}:{market_cap_lower_than}:{limit}"
    # Two-lock pattern — only method where cache key is not a single symbol
```

#### `config.py`
```python
enable_fmp_screener: bool = True
fmp_screener_limit: int = 25
```

#### `peer_enrichment.py`

Modify `discover_peers()` — add FMP screener code path **before** the Tavily search block:

```python
# After sector/subject_cap is resolved, BEFORE the Tavily block:
if fmp_cache and env_flag("ENABLE_FMP") and settings.enable_fmp_screener and sector:
    cap_low  = int(subject_cap * 0.1) if subject_cap > 0 else 0
    cap_high = int(subject_cap * 10)  if subject_cap > 0 else 0
    screener_results = fmp_cache.screen_stocks(
        sector=sector,
        market_cap_more_than=cap_low,
        market_cap_lower_than=cap_high,
        limit=settings.fmp_screener_limit,
    )
    for row in screener_results:
        sym = row.get("symbol", "").upper()
        if sym and sym != ticker and sym not in raw_candidates:
            raw_candidates.append(sym)
```

Screener results feed into the same `raw_candidates` list. Existing `_validate_ticker()` scoring and `_fetch_peer_metrics()` run unchanged.

**API cost:** +1 screener call/run. Validation quote calls reuse `_quote_cache` where already populated. Worst case: up to `fmp_screener_limit` new `get_quote()` calls if cache is cold.
**New env vars:** `ENABLE_FMP_SCREENER=true`
**Verification:** Run with `ENABLE_TAVILY=false` to force screener-only path. Confirm `peer_comparison` section still appears. Check logs for `"FMP screener added N peer candidates"`.

---

## Phase 5: FMP SEC Filings Supplement / EDGAR Fallback

**Depends on:** Nothing
**Effort:** Medium–High | **Impact:** Low (EDGAR already works)
**Default:** OFF — deploy only if EDGAR proves unreliable

#### `fmp_client.py`

Add to `FMPClient`:
```python
def get_financial_report_json(self, symbol: str, year: int, period: str = "FY") -> dict:
    # GET /api/v4/financial-reports-json?symbol={symbol}&year={year}&period={period}
    # period: "FY", "Q1", "Q2", "Q3", "Q4"
```

Add to `FMPCache`:
```python
_financial_report_cache: Dict[str, dict] = {}

def get_financial_report_json(self, symbol: str, year: int, period: str = "FY") -> dict:
    # Cache key: f"{sym}:{year}:{period}"
    # Two-lock pattern
```

#### `config.py`
```python
enable_fmp_sec_filings: bool = False   # OFF by default — EDGAR is primary
max_fmp_sec_section_chars: int = 3000
fmp_sec_report_year: int = 0           # 0 = auto-detect most recent fiscal year
```

#### `market_enrichment.py`

1. Add `_fmp_sec_filing_section(ticker, fmp_cache, year=None) -> tuple[str, list[str]]` — renders compact balance sheet + income summary from structured JSON under `=== SEC Filing Data (FMP) ===`. If `year=0`, derive as `datetime.now().year - 1`.

2. Add `_task_fmp_sec(ticker, fmp_cache) -> Dict[str, Any]` — gated by `fmp_cache and settings.enable_fmp_sec_filings`.

3. Append `"fmp_sec_filing"` to end of `_ENRICHMENT_TASK_ORDER` (lowest priority — EDGAR filing text is richer).

4. Submit conditionally in `build_enrichment_context`.

**Note:** Do NOT add `"fmp_sec_filing"` to any agent's `enrichment_sections` by default. Make available in `section_map` only; add agent subscriptions as a follow-up when enabled in production.

**API cost:** +1 call/run (only when `enable_fmp_sec_filings=True`).
**New env vars:** `ENABLE_FMP_SEC_FILINGS=false`
**Verification:** Set `ENABLE_EDGARTOOLS=false ENABLE_FMP_SEC_FILINGS=true` and run. Confirm `=== SEC Filing Data (FMP) ===` appears without duplicating EDGAR content in agent contexts.

---

## Integration Risks

### Risk 1 — `_ENRICHMENT_TASK_ORDER` ordering affects trimming
Sections at the end of the list are trimmed first when `enrichment_max_chars` is hit. Place high-signal sections (news, estimates, surprises) early; low-priority sections (sec filing, rag) late. The order proposed follows this priority.

### Risk 2 — Agent context budget expansion
DCF agent gains 3 new sections across all phases (`analyst_grades`, `fmp_dcf`, `fmp_news` optional). If `max_context_dcf_chars` is non-zero, verify agent context is not being truncated after additions by checking `--inspect-context` output.

### Risk 3 — Screener validation amplifies quote cache misses
If `fmp_screener_limit=25` and cache is cold, up to 25 `get_quote()` calls fire during peer validation. Set `fmp_screener_limit` ≤ 20 on free tier. Bounded by the screener limit setting.

### Risk 4 — Pre-existing `os.getenv()` violation in `_task_macro`
`_task_macro` in `market_enrichment.py` uses `os.getenv("ENABLE_WAREHOUSE")` directly — a pre-existing violation. Do NOT replicate this. All new feature flags must use `settings.enable_*` for task-level guards and `env_flag("ENABLE_*")` for inline guards inside helper functions.

---

## Implementation Order

| Priority | Phase | Effort | Impact | Seq |
|---|---|---|---|---|
| 1 | 1a — Earnings Surprises section | Low | High | 1st |
| 2 | 1b — Analyst Grades Summary | Low | High | 2nd |
| 3 | 2 — FMP News Feed | Low | High | 3rd |
| 4 | 3a — DCF Cross-Check | Low | Medium | 4th |
| 5 | 3b — Institutional Holdings | Medium | Medium | 5th |
| 6 | 4 — Stock Screener peer discovery | Medium | Medium | 6th |
| 7 | 5 — FMP SEC Filings supplement | High | Low | 7th (defer) |

Phases 1a, 1b, and 2 can be implemented in a single sitting. Phases 3a + 3b as a second sitting. Phase 4 independent. Phase 5 deferred until EDGAR proves unreliable in production.

---

## Final State After All Phases

### `_ENRICHMENT_TASK_ORDER`
```python
_ENRICHMENT_TASK_ORDER = (
    "market_data",
    "tavily",
    "fmp_news",
    "peers",
    "estimates",
    "earnings_surprises",
    "analyst_grades",
    "fmp_dcf",
    "fmp_institutional",
    "price",
    "macro",
    "rag",
    "fmp_sec_filing",
)
```

### New `config.py` fields
```python
# Phase 1a
max_earnings_surprises_section_chars: int = 1200

# Phase 1b
max_analyst_grades_section_chars: int = 800

# Phase 2
enable_fmp_news: bool = True
max_fmp_news_section_chars: int = 2000
fmp_news_limit: int = 10

# Phase 3a
enable_fmp_dcf: bool = True
max_fmp_dcf_section_chars: int = 600

# Phase 3b
enable_fmp_institutional: bool = True
max_fmp_institutional_section_chars: int = 1500
fmp_institutional_limit: int = 10

# Phase 4
enable_fmp_screener: bool = True
fmp_screener_limit: int = 25

# Phase 5
enable_fmp_sec_filings: bool = False
max_fmp_sec_section_chars: int = 3000
fmp_sec_report_year: int = 0
```

### New FMP endpoints

| Phase | Method | Endpoint |
|---|---|---|
| 1b | `get_grades_summary(symbol)` | `GET /stable/grades-summary?symbol=` |
| 2 | `get_stock_news(symbol, limit)` | `GET /api/v4/stock_news?tickers=&limit=` |
| 3a | `get_dcf_valuation(symbol)` | `GET /api/v3/discounted-cash-flow/{symbol}` |
| 3b | `get_institutional_holders(symbol, limit)` | `GET /api/v4/institutional-ownership/institutional-holders/symbol-ownership` |
| 4 | `screen_stocks(sector, cap_low, cap_high, limit)` | `GET /api/v3/stock-screener` |
| 5 | `get_financial_report_json(symbol, year, period)` | `GET /api/v4/financial-reports-json` |
