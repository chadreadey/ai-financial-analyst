# MARKET_DATA_PLAN.md

## Tiingo + FMP Migration Plan: Replacing Yahoo Finance as Primary Market Data Source

**Document version:** 2026-03-25
**Platform:** AI Financial Analyst (Streamlit Cloud, 6-agent equity research)
**Problem:** Yahoo Finance crumb/auth failures from datacenter IPs generate 17+ Sentry errors per run and cause enrichment sections to return empty.

---

## Inventory of All Yahoo Finance Touch Points

| File | Yahoo usage | Phase that replaces it |
|---|---|---|
| `yahoo_cache.py` | `YahooLookupCache.get_info()` — all `.info` dict fetches | Phase 6 (demote to fallback) |
| `market_enrichment.py` | `_yahoo_section()` — price, cap, P/E, 52W range, beta | Phase 1 (Tiingo) + Phase 2 (FMP) |
| `market_enrichment.py` | `_analyst_estimates_section()` — price targets, EPS estimates, revenue estimates, earnings trend, growth estimates | Phase 2 (FMP) |
| `market_enrichment.py` | `_price_history_section()` — 2yr daily/weekly OHLCV, technicals | Phase 3 (Tiingo) |
| `market_enrichment.py` | `_macro_section()` — `^GSPC`, `^VIX`, sector ETF YTD via `yf.Ticker().history()` | Phase 4 (Tiingo) |
| `peer_enrichment.py` | `_validate_ticker()` — confirms ticker is real equity with marketCap | Phase 5 (FMP) |
| `peer_enrichment.py` | `discover_peers()` — `recommendedSymbols` from Yahoo info | Phase 5 (FMP) |
| `peer_enrichment.py` | `_fetch_peer_metrics()` — all PEER_METRICS dict from Yahoo info | Phase 5 (FMP) |
| `peer_enrichment.py` | `build_peer_comparison()` — subject info via `yf.Ticker().info` | Phase 5 (FMP) |
| `agents/pattern.py` | `_compute_risk_metrics()` — 2yr daily history for Sharpe, drawdown, VaR | Phase 3 (covered by Tiingo price history client) |

---

## Shared Architectural Principles

**ENV flag pattern:** Every new provider gets an `ENABLE_*` flag in `config.py` (`Settings` class). Read flags at call sites via `env_flag("ENABLE_TIINGO")` from `utils.py:9` — **NOT** raw `os.getenv()`. `env_flag()` normalizes `"true"`, `"1"`, `"yes"`, `"on"` to `True`; raw `os.getenv()` returns the string `"true"` which requires explicit comparison and is easy to get wrong. Use `os.getenv()` only for string values (API keys). Do not use `settings.*` for runtime-toggled flags — `settings` is frozen at import time before `_set_runtime_env()` mutates `os.environ`.

**Cache interface contract:** `YahooLookupCache` is passed as `cache` throughout both `market_enrichment.py` and `peer_enrichment.py`. New provider clients are independent objects — they do not replace the cache parameter signature. The cache eventually wraps Yahoo as fallback only (Phase 6).

**Fail-safe pattern:** All enrichment functions return `("", [])` on exception. Every new provider function must be wrapped in `try/except` with `logger.debug(..., exc_info=True)`. All `_task_*` wrappers already catch exceptions at `market_enrichment.py:566-587` and return empty dicts.

**`_task_*` dict contract:** Every `_task_*` function must return exactly these five keys in **both** the success path and the `except` branch: `section_entries`, `sources`, `warnings`, `filter_stats`, and (for the market task only) `sector`/`industry`. Missing any of the first three raises `KeyError` at `market_enrichment.py:762-772` and aborts `build_enrichment_context()` entirely.

**`_ENRICHMENT_TASK_ORDER`:** Any new task key added to `futures` in `build_enrichment_context()` must also be added to `_ENRICHMENT_TASK_ORDER` at `market_enrichment.py:25`. Keys not in this tuple are silently dropped from the final LLM context string.

**HTTP client session management:** Instantiate one `requests.Session` per client instance in `__init__`, mount the `Authorization` header at session level, and reuse it across all method calls. Do **not** create per-call sessions — that defeats TCP keep-alive and TLS reuse, adding latency per call. Every `.get()` call must specify `timeout=(5, 15)` (connect, read seconds). A missing timeout will hang the thread indefinitely inside the `ThreadPoolExecutor`.

**No inner thread pools inside task functions:** `_task_*` functions already run inside an outer `ThreadPoolExecutor`. New task implementations must not create their own inner pools. (Note: `_task_tavily` at `market_enrichment.py:246` already creates a nested pool — this is a pre-existing pattern, do not replicate it in new tasks.)

**Thread-safe cache locking:** New caches (`FMPCache`, `TiingoCache`) must replicate the two-lock pattern from `yahoo_cache.py:28-62`: acquire `self._lock`, check cache, release; perform HTTP call outside the lock; reacquire, write, return copy. Never hold the lock during network I/O.

**Adjusted close:** All price history computations (returns, SMA, volatility, Sharpe, drawdown) must use split- and dividend-adjusted close. For Tiingo, this means `adjClose` — not `close`. Using `close` produces wrong returns for any ticker with dividends or splits in the history window.

**Context budget:** Every section text must pass through `trim_text(section_text, settings.max_*_chars)` before returning — see `market_enrichment.py:83`, `149`, `392`, `562` for existing examples.

**Dependencies:** No new libraries required. All clients are pure REST over `requests` (already in deps).

---

## Phase 1: Tiingo Client + Live Quote Section

**Goal:** Replace `_yahoo_section()` primary path with Tiingo live quote for price, 52W range, and volume.

### Files to Create

**`tiingo_client.py`**

Interface sketch:
```
class TiingoClient:
    def __init__(self, api_key: str) -> None
    def get_quote(self, symbol: str) -> dict
        # GET /tiingo/daily/{sym}/prices — returns list, take [0]
        # Fields: close, prevClose, low52Week, high52Week, volume
    def get_meta(self, symbol: str) -> dict
        # GET /tiingo/daily/{sym} — description, sector, startDate
    def get_eod_history(self, symbol: str, start_date: str) -> list[dict]
        # GET /tiingo/daily/{sym}/prices?startDate=YYYY-MM-DD
        # Returns list of {date, open, high, low, close, volume, adjClose}
```

Auth: `Authorization: Token {api_key}` header mounted on `self._session` in `__init__`. All methods call `self._session.get(url, timeout=(5, 15))`.

**HTTP contract for all TiingoClient methods:**
- Timeout: `(5, 15)` seconds (connect, read)
- Retry: 1 retry on `ConnectionError` or 5xx; no retry on 4xx
- Response validation: check `response.raise_for_status()`, parse JSON, guard list endpoints with `data[0] if data else {}`
- Logging: `logger.debug("tiingo %s failed: %s", endpoint, exc, exc_info=True)`

### Files to Modify

**`market_enrichment.py`**
- Add `_tiingo_quote_section(ticker, tiingo_client) -> tuple[str, list[str]]`
  - Calls `tiingo_client.get_quote()` and `tiingo_client.get_meta()`
  - Builds `=== Market Data (Tiingo EOD, as of {date} close) ===` — include the date so the LLM understands data is T-1 during market hours
  - Applies `trim_text(..., settings.max_market_section_chars)`
- **Rename `_task_yahoo()` to `_task_market_data()` in Phase 1** (not deferred to Phase 6 — a function called `_task_yahoo` that calls Tiingo first is confusing)
- Update task key from `"yahoo"` to `"market_data"` in `futures` dict AND in `_ENRICHMENT_TASK_ORDER`
- Update `if name == "yahoo":` sector extraction at `market_enrichment.py:770` to `if name == "market_data":`
- `_task_market_data()` tries `_tiingo_quote_section()` if `env_flag("ENABLE_TIINGO")` and key present; on success, bypasses `_yahoo_section()`; on failure, falls through to Yahoo
- Sector/industry: use Tiingo meta `sector` field if Yahoo cache is empty

**`config.py`**
```python
enable_tiingo: bool = True
tiingo_api_key: str = ""
```

**`app.py`**
- Add `TIINGO_API_KEY` to `_bootstrap_env_from_streamlit_secrets()` secret_keys list
- Add `enable_tiingo` checkbox in sidebar Enrichment section
- Pass `enable_tiingo` through `_set_runtime_env()` → `os.environ["ENABLE_TIINGO"]`

**`pyproject.toml`**
- Add `tiingo_client` to `[tool.setuptools] py-modules`

### New Env Vars
```
TIINGO_API_KEY      # required; skip Tiingo silently if absent
ENABLE_TIINGO=true  # default true
```

### New Dependencies
None — pure REST over `requests` (already in deps).

### Verification
Run with `TIINGO_API_KEY` set, `ENABLE_YAHOO=false`, ticker `AAPL`. The `market_data` section should show `=== Live Market Data (Tiingo) ===` with price and 52W range. Zero Sentry crumb errors.

### Integration Risks
- **Tiingo returns EOD data**, not real-time intraday. "Current price" is T-1 close during market hours. Date-stamp the section header to inform the LLM.
- **Beta not in Tiingo.** Dropped from Phase 1, restored by FMP in Phase 2.
- **`low52Week`/`high52Week`:** May be `null` for non-US ADRs and recently-listed tickers. Guard with `if val is not None`.
- **Sector resolution race:** `_task_tavily` at `market_enrichment.py:594` calls `cache.get_info(ticker)` independently to get sector — it does not wait for `_task_market_data` to complete. With Yahoo disabled, this returns `{}` and Tavily gets no sector. Fix: resolve sector/industry in a synchronous pre-step before the `ThreadPoolExecutor` (one `fmp_cache.get_quote()` call, ~100ms), then pass `sector` as a parameter to tasks that need it.

---

## Phase 2: FMP Client + Valuation Multiples + Analyst Estimates

*Depends on: Phase 1 complete*

**Goal:** Replace Yahoo valuation fields (P/E, EV/EBITDA, market cap, P/S, beta) and replace `_analyst_estimates_section()` entirely.

### Files to Create

**`fmp_client.py`**

Interface sketch:
```
class FMPClient:
    def __init__(self, api_key: str) -> None
    def get_quote(self, symbol: str) -> dict
        # GET /api/v3/quote/{symbol}?apikey=...  → list[dict], take [0]
        # Fields: price, marketCap, pe, eps, beta, volume, yearHigh, yearLow, sector, name
    def get_key_metrics(self, symbol: str) -> dict
        # GET /api/v3/key-metrics-ttm/{symbol}?apikey=...  → list[dict], take [0]
        # Fields: evToEbitdaTTM, priceToSalesRatioTTM, peRatioTTM, grossProfitMarginTTM
    def get_analyst_estimates(self, symbol: str, limit: int = 4) -> list[dict]
        # GET /api/v3/analyst-estimates/{symbol}?apikey=&limit=4
    def get_price_target(self, symbol: str) -> dict
        # GET /api/v4/price-target-summary?symbol=...&apikey=...
    def get_earnings_surprises(self, symbol: str, limit: int = 4) -> list[dict]
        # GET /api/v3/earnings-surprises/{symbol}?apikey=...&limit=4

class FMPCache:
    """Per-run cache for FMP responses, keyed by (symbol, endpoint). Same pattern as YahooLookupCache."""
    def get_quote(self, symbol) -> dict           # cached after first call per symbol
    def get_key_metrics(self, symbol) -> dict
    def get_analyst_estimates(self, symbol) -> list[dict]
    def get_price_target(self, symbol) -> dict
    def get_earnings_surprises(self, symbol) -> list[dict]
```

`FMPCache` wraps `FMPClient` with per-symbol, per-endpoint memoization for the duration of a single `build_enrichment_context()` call. Instantiated once, passed to all tasks that need it.

**FMPCache must implement the two-lock pattern from `yahoo_cache.py:28-62`:**
```
self._lock = threading.Lock()   # guards internal cache dict
# For each method: acquire lock → check cache → release → HTTP call → reacquire → write → return copy
```
`FMPClient` does not need a module-level global lock (unlike Yahoo's crumb model) — the per-instance lock is sufficient to prevent duplicate calls from concurrent thread pool workers.

**FMPClient HTTP contract:** Same as TiingoClient — one session per instance, `timeout=(5, 15)`, `response.raise_for_status()`, list endpoints return `data[0] if data else {}`.

**Data type guards required in all FMP methods:**
- `marketCap`: coerce with `int(data.get("marketCap") or 0)` — some FMP responses return it as a string
- `pe`: emit `N/A` when value is `None`, `0`, or negative — FMP returns `0` for loss-making companies, not `null`; `0.00` in LLM context is actively misleading
- Margin fields (`grossProfitMarginTTM`, `operatingProfitMarginTTM`): verify these are decimal fractions (0.45) before multiplying by 100 in `peer_enrichment.py:343`; FMP is consistent but confirm during integration test
- All list endpoints: `data[0] if data else {}` — never `data[0]` directly

### Files to Modify

**`market_enrichment.py`**
- Add `_fmp_valuation_section(ticker, fmp_cache) -> tuple[str, list[str]]`
  - Calls `fmp_cache.get_quote()` + `fmp_cache.get_key_metrics()`
  - Builds `=== Valuation (FMP) ===` with marketCap, P/E TTM, beta, EV/EBITDA, P/S
  - Applies `trim_text(..., settings.max_market_section_chars)`
- Add `_fmp_estimates_section(ticker, fmp_cache) -> tuple[str, list[str]]`
  - Calls `fmp_cache.get_analyst_estimates()`, `fmp_cache.get_price_target()`, `fmp_cache.get_earnings_surprises()`
  - Format: `=== Analyst Estimates & Consensus (FMP) ===`, price targets, forward EPS, earnings surprises last 4Q
  - Applies `trim_text(..., settings.max_estimates_section_chars)`
  - Returns sources `["FMP (Financial Modeling Prep)"]`
- Modify `_task_yahoo()`: after Tiingo quote, append FMP valuation section if `os.getenv("ENABLE_FMP")` and key present
- Modify `_task_estimates()`: accept `fmp_cache`; call `_fmp_estimates_section()` as primary, fall to Yahoo `_analyst_estimates_section()` if FMP unavailable
- Modify `build_enrichment_context()`: instantiate `FMPCache` at top alongside `YahooLookupCache`; pass to `_task_yahoo` and `_task_estimates` via `pool.submit()`

**`config.py`**
```python
enable_fmp: bool = True
fmp_api_key: str = ""
max_fmp_estimates_section_chars: int = 1800   # FMP returns more estimate rows than Yahoo; 1200 trims mid-table
```
Also raise `enrichment_max_chars` from `8000` to `10000` during the transition period — two new market sections (Tiingo + FMP) plus Yahoo fallback could consume 3600 chars before macro/peer sections are reached.

**`app.py`**
- Add `FMP_API_KEY` to `_bootstrap_env_from_streamlit_secrets()` secret_keys list

**`pyproject.toml`**
- Add `fmp_client` to `[tool.setuptools] py-modules`

### New Env Vars
```
FMP_API_KEY         # required; skip FMP silently if absent
ENABLE_FMP=true     # default true
```

### New Dependencies
None.

### Verification
Run with `FMP_API_KEY` set, `ENABLE_YAHOO=false`, `ENABLE_TIINGO=true`. Confirm `market_data` has both Tiingo price and FMP valuation. Confirm `analyst_estimates` populates from FMP. Confirm FMP call count ≤ 5 per run in debug logs.

### Integration Risks
- **FMP 250 calls/day free limit:** `FMPCache` deduplication is critical. 20 peer validations (Phase 5) + 5 subject calls = ~25 calls/run. Fine for low-traffic personal use.
- **`sector` for Tavily:** `_task_yahoo()` returns `sector` to `build_enrichment_context()` for Tavily query routing. FMP `/quote` includes `sector` — use it here instead of Yahoo.
- **FMP list endpoints:** `get_quote()`, `get_key_metrics()` return lists. Always guard `if data and len(data) > 0` before `data[0]`.

---

## Phase 3: Price History via Tiingo

*Depends on: Phase 1 (TiingoClient exists)*

**Goal:** Replace `_price_history_section()` and `agents/pattern.py`'s `_compute_risk_metrics()` with Tiingo EOD history.

### Files to Modify

**`tiingo_client.py`** — `get_eod_history()` already sketched in Phase 1.

**`market_enrichment.py`**
- Add `_tiingo_price_history_section(ticker, tiingo_client) -> tuple[str, list[str]]`
  - Fetch 2yr daily via `tiingo_client.get_eod_history(ticker, two_years_ago)`
  - Convert to DataFrame: `pd.DataFrame(data)`, normalize date index with `pd.to_datetime(...).dt.tz_localize(None)`
  - Run identical computation as existing `_price_history_section()`:
    - 1M/3M/6M/1Y/2Y returns, 52W high/low, position in range
    - 50-day SMA, 200-day SMA, golden/death cross
    - Annualized volatility, avg daily volume
  - Sources: `["Tiingo (price history)"]`
- Modify `_task_price()`: accept `tiingo_client`; call `_tiingo_price_history_section()` first; fall to existing Yahoo path on failure or absence

**`agents/pattern.py`**
- Modify `_compute_risk_metrics(ticker)`:
  - Check `env_flag("ENABLE_TIINGO")` and `os.getenv("TIINGO_API_KEY")` first
  - If available: use `TiingoClient.get_eod_history()` → convert to Series → run existing Sharpe/Sortino/drawdown/VaR calculations
  - Else: fall through to existing `yf.Ticker().history()` block (guarded by existing try/except)
  - Tiingo branch must execute **before** the `try` block that imports yfinance — so `yfinance` is never imported when Tiingo is configured
- `_compute_risk_metrics` is a blocking network call inside `build_context()` which is called from the `async` `analyze()` method (`agents/base.py:101`). Wrap it: `await asyncio.get_event_loop().run_in_executor(None, _compute_risk_metrics, ticker)` to avoid blocking the event loop. This issue exists today with yfinance; Phase 3 is the right moment to fix it.

**`tiingo_client.py` — add `TiingoCache`**
Both `_task_price` (via `_tiingo_price_history_section`) and `_compute_risk_metrics` in `agents/pattern.py` fetch 2yr history for the same ticker in the same analysis run. Add a `TiingoCache` class with a `get_eod_history(symbol, start_date)` method using the same two-lock pattern as `FMPCache`. Pass `TiingoCache` instance from `build_enrichment_context()` to both call sites to eliminate the duplicate HTTP call.

**`build_enrichment_context()`**
- Pass `tiingo_client` to `_task_price` via `pool.submit()`

### New Env Vars
None (reuses `TIINGO_API_KEY`, `ENABLE_TIINGO`).

### New Dependencies
None.

### Verification
Run with `ENABLE_TIINGO=true`, `ENABLE_YAHOO=false`. The `price_history` section should appear with all momentum/SMA/volatility lines. Pattern Agent risk metrics (Sharpe, Sortino, max drawdown) should populate from Tiingo data.

### Integration Risks
- **Tiingo date timezone — use `tz_convert`, NOT `tz_localize`:** Tiingo returns ISO-8601 timestamps with `+00:00` offset (tz-aware). The plan originally said `dt.tz_localize(None)` — this is **wrong** and raises `TypeError: Already tz-aware`. The correct call is `pd.to_datetime(df["date"]).dt.tz_convert(None)`. Using the wrong method silently kills the section on every call (caught by task wrapper, produces empty `price_history`).
- **Use `adjClose`, not `close`:** Tiingo returns both `close` and `adjClose`. The existing Yahoo `history()` path returns split- and dividend-adjusted close by default. Must use `adjClose` in all return/SMA/volatility computations or results are wrong for any ticker with dividends or splits in the 2yr window.
- **Replicate all `len(close) > days` guards:** The existing `_price_history_section` at `market_enrichment.py:354-389` guards every rolling window with `if len(close) > days`. These must be replicated exactly in `_tiingo_price_history_section` — missing a guard produces wrong returns from a misaligned index rather than omitting the line.
- **`agents/pattern.py` yfinance import:** Tiingo branch must execute before the `try` block that imports yfinance so the import never runs when Tiingo is configured.

---

## Phase 4: Macro Indices via Tiingo

*Depends on: Phase 1 (TiingoClient exists)*

**Goal:** Replace `yf.Ticker("^GSPC").history()`, `^VIX`, and sector ETF YTD calls in `_macro_section()`.

### Analysis

Yahoo usage in `_macro_section()` splits into three distinct calls:

1. **`cache.get_info(sym)` for yield tickers** (`^TNX`, `^FVX`, `^IRX`): Already behind a FRED primary check — if `ENABLE_FRED=true`, this is never reached. Low priority.
2. **`yf.Ticker("^GSPC").history(period="ytd")`**: Direct call, separate failure vector.
3. **`yf.Ticker(etf_sym).history(period="ytd")`** for sector ETFs (XLK, XLV, etc.): Same pattern.

Tiingo does not support `^GSPC` or `^VIX` (index tickers). Solutions:
- `^GSPC` → use `SPY` as YTD return proxy (identical YTD %, different price level — label clearly)
- `^VIX` → add `VIXCLS` to the existing FRED `series_map` in `_fred_macro_data()`
- Sector ETFs → Tiingo supports these natively (standard equity tickers)

### Files to Modify

**`market_enrichment.py`**
- Add `_tiingo_index_section(tiingo_client) -> tuple[list[str], list[str]]`
  - Fetch YTD history for `SPY` and sector ETFs via `tiingo_client.get_eod_history(sym, jan_1_this_year)`
  - Compute YTD return: `(last_close / first_close) - 1`
  - Label `S&P 500 (SPY proxy)` to avoid misleading the LLM
- Modify `_fred_macro_data()`:
  - Add `"VIXCLS": ("CBOE VIX", "")` to `series_map` — pulls VIX from FRED (1-day lag, acceptable)
  - No additional API calls — already parallelized in `ThreadPoolExecutor`
- Modify `_macro_section()`:
  - Accept `tiingo_client: Optional[TiingoClient]`
  - For `-- Market Indices --` block: if Tiingo available, call `_tiingo_index_section()` instead of `yf.Ticker(sym).history()` loop
- Modify `_task_macro()`: accept and pass `tiingo_client`
- Modify `build_enrichment_context()`: pass `tiingo_client` to `_task_macro`

### New Env Vars
None.

### New Dependencies
None.

### Verification
Run with `ENABLE_FRED=true`, `ENABLE_TIINGO=true`, `ENABLE_YAHOO=false`. The `macro_data` section should show SPY YTD, VIX from FRED, and sector ETF YTD — no Yahoo calls.

### Integration Risks
- **SPY vs. ^GSPC level:** SPY price level (~580) differs from the index value (~5800). Section header must clarify `(SPY proxy)`. YTD return percentage is equivalent.
- **YTD start date:** Use `datetime(datetime.now().year, 1, 1).strftime("%Y-%m-%d")` — `period="ytd"` is a Yahoo-specific parameter, not applicable to Tiingo.
- **FRED VIXCLS lag:** 1 business day. Acceptable for daily-granularity enrichment.

---

## Phase 5: Peer Enrichment Audit and Replacement

*Depends on: Phase 2 (FMPCache exists)*

**Goal:** Replace all Yahoo Finance calls in `peer_enrichment.py` with FMP-based data.

### Audit of `peer_enrichment.py` Yahoo Usage

| Function | Yahoo call | Replacement |
|---|---|---|
| `_validate_ticker()` | `cache.get_info(sym)` | FMP `/quote` — check `marketCap > 0` |
| `discover_peers()` | subject sector/industry/cap | FMP quote (already in `FMPCache` from Phase 2) |
| `discover_peers()` | `info.get("recommendedSymbols")` | Drop — this field doesn't exist in FMP. Tavily peer discovery path already handles this. |
| `_fetch_peer_metrics()` | `cache.get_info(peer_ticker)` | FMP `/quote` + `/key-metrics-ttm` via `FMPCache` |
| `build_peer_comparison()` | `yf.Ticker(ticker).info` | `FMPCache.get_quote()` |

### PEER_METRICS Field Mapping (Yahoo → FMP)

| PEER_METRICS key | FMP source |
|---|---|
| `marketCap` | `/quote` → `marketCap` |
| `trailingPE` | `/quote` → `pe` |
| `priceToSalesTrailing12Months` | `/key-metrics-ttm` → `priceToSalesRatioTTM` |
| `enterpriseToEbitda` | `/key-metrics-ttm` → `evToEbitdaTTM` |
| `grossMargins` | `/key-metrics-ttm` → `grossProfitMarginTTM` |
| `operatingMargins` | `/key-metrics-ttm` → `operatingProfitMarginTTM` |
| `shortName` | `/quote` → `name` |
| `sector` | `/quote` → `sector` |
| `totalRevenue` | Omit or use `/financial-statements` (extra call — skip for now) |
| `revenueGrowth` | Omit in FMP path; too costly in API calls |
| `industry` | Not in `/quote`; use sector-only matching in FMP path |
| `forwardPE` | Not clean in FMP free tier; emit `N/A` |

### Files to Modify

**`peer_enrichment.py`**
- Modify `_validate_ticker(sym, cache, fmp_cache=None)`:
  - New optional `fmp_cache` parameter
  - Primary: `fmp_cache.get_quote(sym)` — check `marketCap > 0` and `type == "stock"`
  - Fallback: `cache.get_info(sym)` (Yahoo, still active pre-Phase 6)
- Modify `discover_peers(ticker, ..., fmp_cache=None)`:
  - Subject info from `fmp_cache.get_quote(ticker)` if available
  - Remove `recommendedSymbols` block — Tavily path is sufficient
  - Pass `fmp_cache` to `_validate_ticker()` in thread pool submits
- Modify `_fetch_peer_metrics(peer_ticker, cache, fmp_cache=None)`:
  - FMP path: `fmp_cache.get_quote()` + `fmp_cache.get_key_metrics()` → map to `PEER_METRICS` keys
  - Fallback: existing `cache.get_info()` (Yahoo)
- Modify `build_peer_comparison(ticker, company_name, cache, fmp_cache=None)`:
  - Subject info from `fmp_cache.get_quote()` if available
  - Pass `fmp_cache` through to `_fetch_peer_metrics()` and `_validate_ticker()`
  - Sources: `["FMP (peer data)"]` when FMP path used

**`market_enrichment.py`**
- Modify `_task_peers()`: pass `fmp_cache` to `build_peer_comparison()`

### New Env Vars
None.

### New Dependencies
None.

### Verification
Run with `ENABLE_YAHOO=false`, `ENABLE_FMP=true`, ticker `MRNA` (Healthcare sector). Confirm peer table populates with correct sector proximity scores. Temporarily add `logger.warning` in `YahooLookupCache.get_info()` to detect any missed Yahoo calls.

### Integration Risks
- **FMP call volume:** 20 peer validations × 1 quote call each + 5 key_metrics = ~25 calls. With Phase 2, total run = ~30 FMP calls. Within 250/day for personal use but ~8 full runs/day is the limit.
- **Industry field gap and peer quality degradation:** `_industry_match_score()` at `peer_enrichment.py:69` awards 3 points for exact industry match, only 1 for same-sector. FMP `/quote` has `sector` but not `industry`, so all FMP-path peers within a sector score identically at 1 — cap proximity becomes the only differentiator. For large sectors like Technology or Healthcare, this can produce poor peers (e.g., ranking JNJ and UNH as equivalent peers to MRNA). Investigate FMP `/profile/{symbol}` as an alternative — it does include `industry` and may be worth the extra API call per peer.
- **`forwardPE` gap:** Peer table shows `N/A` for forward P/E. Acceptable — forward estimates come from the separate analyst estimates section.
- **Peer validation thread depth:** `_validate_ticker()` is called from a nested `ThreadPoolExecutor` inside `_task_peers`, which is itself a pool worker. This creates up to 8+5=13 concurrent threads. Not a deadlock risk, but document the thread budget and verify against Streamlit Cloud memory limits.

---

## Phase 6: Yahoo as Fallback Only

*Depends on: Phases 1–5 all verified on Streamlit Cloud with zero Sentry errors*

**Goal:** Demote Yahoo to last-resort fallback. Default `ENABLE_YAHOO_FALLBACK=false` on cloud deployments.

### Files to Modify

**`yahoo_cache.py`**
- Add check at top of `get_info()`:
  ```python
  if os.getenv("ENABLE_YAHOO_FALLBACK", "false").lower() not in ("1", "true", "yes"):
      return {}
  ```
- Update docstring: "Last-resort fallback — disabled by default in cloud deployments."

**`config.py`**
- Remove `enable_yahoo: bool = True`
- Add `enable_yahoo_fallback: bool = False`

**`market_enrichment.py`**
- Inside `_task_yahoo()` (or renamed `_task_market_data()`), the provider waterfall becomes:
  1. Tiingo quote if `ENABLE_TIINGO` + key present
  2. FMP quote if Tiingo fails + `ENABLE_FMP` + key present
  3. Yahoo via `cache.get_info()` only if `ENABLE_YAHOO_FALLBACK=true`
- Task is always submitted (no longer gated by `if settings.enable_yahoo`)

**`app.py`**
- Replace `enable_yahoo` checkbox with `enable_yahoo_fallback = st.checkbox("Enable Yahoo Finance fallback (unreliable on cloud)", value=False)`
- Update `_set_runtime_env()`: set `ENABLE_YAHOO_FALLBACK` instead of `ENABLE_YAHOO`

**`tests/test_market_enrichment.py`**
- Replace all `monkeypatch.setattr(settings, "enable_yahoo", True)` with `enable_yahoo_fallback`
- Existing mock-based tests (patch at `_task_*` level) remain structurally valid

**`tests/test_yahoo_cache.py`**
- Add test: `get_info()` returns `{}` immediately when `ENABLE_YAHOO_FALLBACK=false`

### New Env Vars
```
ENABLE_YAHOO_FALLBACK=false   # default false — Yahoo disabled on Streamlit Cloud
```

### Sentry Impact
With `ENABLE_YAHOO_FALLBACK=false`, zero Yahoo HTTP calls are made. PYTHON-2, PYTHON-3, PYTHON-4 errors drop to zero.

### New Dependencies
None.

### Verification
Deploy to Streamlit Cloud with `TIINGO_API_KEY`, `FMP_API_KEY`, `FRED_API_KEY` set and `ENABLE_YAHOO_FALLBACK=false`. Run 3 analyses on different tickers. Confirm zero Sentry Yahoo errors. Confirm all enrichment sections populate.

### Integration Risks
- **`sector`/`industry` for Tavily:** Must be populated from FMP quote before Tavily tasks run. Verify `_task_market_data()` returns `sector` from FMP when Yahoo is disabled.
- **Test suite:** `test_market_enrichment.py` uses `monkeypatch.setattr(settings, "enable_yahoo", True)`. After Phase 6 removes that field, tests will `AttributeError`. Update before merging.
- **Local dev without API keys:** `ENABLE_YAHOO_FALLBACK=true` remains the escape hatch for local development without Tiingo/FMP keys. Document this in `.env.example`.

---

## Full File Inventory

### New Files to Create

| File | Purpose |
|---|---|
| `tiingo_client.py` | Thin REST client for Tiingo API (quote, meta, EOD history) |
| `fmp_client.py` | REST client + per-run cache for FMP API (quote, key-metrics, estimates, price targets, earnings surprises) |

### Files to Modify

| File | Phases |
|---|---|
| `market_enrichment.py` | All phases — new provider sections, task waterfall, build_enrichment_context wiring |
| `yahoo_cache.py` | Phase 6 — add fallback gate |
| `peer_enrichment.py` | Phase 5 — FMP path for all four functions |
| `agents/pattern.py` | Phase 3 — Tiingo history for risk metrics |
| `config.py` | Phases 1, 2, 6 — add/remove flag fields |
| `app.py` | Phases 1, 2, 6 — secrets bootstrap, sidebar flags, _set_runtime_env |
| `pyproject.toml` | Phase 1 — add tiingo_client, fmp_client to py-modules |
| `requirements.txt` | No changes needed |
| `tests/test_market_enrichment.py` | Phase 6 — update monkeypatches |
| `tests/test_yahoo_cache.py` | Phase 6 — add fallback gate test |

---

## New Environment Variables — Complete Reference

| Variable | Default | Phase | Purpose |
|---|---|---|---|
| `TIINGO_API_KEY` | `""` | 1 | Tiingo auth token |
| `ENABLE_TIINGO` | `true` | 1 | Master Tiingo flag |
| `FMP_API_KEY` | `""` | 2 | FMP auth key |
| `ENABLE_FMP` | `true` | 2 | Master FMP flag |
| `ENABLE_YAHOO_FALLBACK` | `false` | 6 | Last-resort Yahoo; off by default on cloud |

---

## `.env.example` additions

```bash
# Tiingo market data (replaces Yahoo Finance)
TIINGO_API_KEY=
ENABLE_TIINGO=true

# Financial Modeling Prep (valuations + analyst estimates)
FMP_API_KEY=
ENABLE_FMP=true

# Yahoo Finance fallback (unreliable on cloud IPs — disabled by default)
ENABLE_YAHOO_FALLBACK=false
```

---

## Phase Dependency Map

```
Phase 1 (Tiingo client + live quote)
  ├── Phase 3 (Tiingo price history)       ← can run in parallel with Phase 2
  └── Phase 4 (Tiingo macro indices)       ← can run in parallel with Phase 2

Phase 2 (FMP client + valuations + estimates)
  └── Phase 5 (Peer enrichment via FMP)   ← blocked on Phase 2

Phase 6 (Yahoo fallback demotion)
  └── Blocked on ALL prior phases verified on Streamlit Cloud
```

Phases 3 and 4 are independent of Phase 2 and can be developed in parallel. Phase 5 requires Phase 2's `FMPCache`. Phase 6 is a hard gate — do not merge until zero Sentry Yahoo errors confirmed across 3+ production runs.

---

## Rollback Strategy

Each phase leaves the Yahoo fallback path intact until Phase 6. Setting `ENABLE_TIINGO=false` and `ENABLE_FMP=false` with `ENABLE_YAHOO=true` (pre-Phase 6) restores the original behavior at any point. Phase 6 is the only irreversible step, and even then `ENABLE_YAHOO_FALLBACK=true` re-enables Yahoo for emergency fallback.

---

## API Cost Budget Per Run

| Provider | Calls/run (subject only) | Calls/run (with 5 peers) | Daily free limit | Max full runs/day |
|---|---|---|---|---|
| Tiingo | 3 (quote + meta + history) | 3 | 1,000/day | 333 |
| FMP | 5 (quote + key-metrics + estimates + targets + surprises) | ~30 | 250/day | **~8** |
| FRED | 8 parallel series | 8 | Unlimited | ∞ |

FMP is the bottleneck. Eight full runs per day is tight for any active use session. Add a per-run call counter to `FMPClient` that logs `WARNING` at 200 calls and logs `ERROR` at 250 so exhaustion is visible in Sentry before it causes silent fallbacks.

---

## Field Mapping Reference (Yahoo → FMP/Tiingo, with Units and Null Handling)

| Consumer | Yahoo field | New source | Unit | Null / bad-value handling |
|---|---|---|---|---|
| `_yahoo_section` | `currentPrice` | Tiingo `close` (EOD) | USD | Guard `if val is not None` |
| `_yahoo_section` | `marketCap` | FMP `/quote` `marketCap` | USD (raw) | `int(data.get("marketCap") or 0)` — may be string |
| `_yahoo_section` | `trailingPE` | FMP `/quote` `pe` | ratio | Emit `N/A` if `None`, `0`, or negative |
| `_yahoo_section` | `forwardPE` | FMP `/key-metrics-ttm` `peRatioTTM` | ratio | Emit `N/A` if missing |
| `_yahoo_section` | `priceToSalesTrailing12Months` | FMP `priceToSalesRatioTTM` | ratio | Emit `N/A` if missing |
| `_yahoo_section` | `enterpriseToEbitda` | FMP `evToEbitdaTTM` | ratio | May be negative for loss-makers; emit as-is |
| `_yahoo_section` | `beta` | FMP `/quote` `beta` | ratio | Emit `N/A` if missing |
| `_yahoo_section` | `fiftyTwoWeekLow/High` | Tiingo `low52Week`/`high52Week` | USD | `null` for ADRs; guard `if val is not None` |
| `_price_history_section` | `history()["Close"]` | Tiingo `adjClose` | USD | Must be `adjClose` not `close` — see Principles |
| `_fetch_peer_metrics` | `grossMargins` | FMP `grossProfitMarginTTM` | decimal (0.45) | Verify fraction not percentage before `× 100` |
| `_fetch_peer_metrics` | `operatingMargins` | FMP `operatingProfitMarginTTM` | decimal (0.45) | Same as above |
| `_fetch_peer_metrics` | `marketCap` | FMP `/quote` `marketCap` | USD (raw) | `int(...)` coercion |
| `_fetch_peer_metrics` | `trailingPE` | FMP `/quote` `pe` | ratio | Prefer `peRatioTTM` from key-metrics for TTM consistency |
| `_fetch_peer_metrics` | `sector` | FMP `/quote` `sector` | string | `""` if missing — degrades Tavily routing |
| `_fetch_peer_metrics` | `industry` | FMP `/profile` `industry` (extra call) or `""` | string | Sector-only fallback degrades peer scoring; see Phase 5 |

---

## Observability Requirements

Log the following at `INFO` level for every `build_enrichment_context()` call:

```
"market_data served by {tiingo|fmp|yahoo|empty} for {ticker}"
"estimates served by {fmp|yahoo|empty} for {ticker}"
"price_history served by {tiingo|yahoo|empty} for {ticker}"
"fmp_calls_this_run={n}"
```

Log at `WARNING` on any waterfall fallback event:
```
"tiingo quote failed for {ticker}, falling back to FMP: {exc}"
"fmp quote failed for {ticker}, falling back to Yahoo: {exc}"
```

This is critical post-Phase 6: with Yahoo disabled and Sentry Yahoo errors gone, the only way to diagnose silent Tiingo/FMP failures is structured logs.

---

## Testing Strategy

| Phase | Approach |
|---|---|
| Phase 1 | Unit-test `TiingoClient.get_quote()` with `requests-mock`. Assert section text contains date-stamped header. Assert `sector` extracted from Tiingo meta. |
| Phase 2 | Unit-test `FMPClient` endpoints with `requests-mock`. Test `FMPCache` deduplication: assert HTTP call count == 1 per symbol even when called from 3 concurrent threads. Test `pe == 0` → `N/A`. Test `marketCap` string coercion. |
| Phase 3 | Feed identical synthetic OHLCV data to both `_price_history_section` (Yahoo) and `_tiingo_price_history_section` (Tiingo) and assert identical output. Test `tz_convert(None)` on tz-aware timestamps. Test `adjClose` vs `close` produces different results for a ticker with dividends. |
| Phase 4 | Test `_tiingo_index_section` with 2 data points; assert YTD formula. Test VIXCLS in FRED series map. |
| Phase 5 | Test `_validate_ticker` FMP path with mock quote. Test `_fetch_peer_metrics` field mapping. Add `logger.warning` canary in `YahooLookupCache.get_info()` to surface any missed Yahoo calls. |
| Phase 6 | Test `YahooLookupCache.get_info()` returns `{}` when `ENABLE_YAHOO_FALLBACK=false`. Test that `test_market_enrichment.py` monkeypatches are updated. Regression: assert zero `yfinance` imports via `sys.modules` inspection. |

---

## Architect Review: Additions and Risks

*Source: architect subagent review, 2026-03-25*

### Highest-Priority Findings

**Sector resolution race condition (blocking):** `_task_tavily` at `market_enrichment.py:594` calls `cache.get_info(ticker)` independently to get `sector` — it does not consume the `sector` returned by `_task_market_data`. Both tasks run concurrently. With Yahoo disabled, `cache.get_info()` returns `{}` and Tavily gets no sector, silently degrading all Tavily queries to generic (no sector-specific search terms). Fix: add a synchronous pre-step in `build_enrichment_context()` before the thread pool — call `fmp_cache.get_quote(ticker)` once, extract `sector`/`industry`, pass as parameters to tasks that need them.

**No abstraction layer between tasks and providers:** As the waterfall grows (Tiingo → FMP → Yahoo), each `_task_*` accumulates nested `if/try/except` chains. Consider a lightweight `ProviderChain` resolver (`get_quote(ticker) -> dict`) that encapsulates the waterfall and circuit-breaking logic, keeping task functions clean. Defer to post-Phase 2 if needed.

**No circuit breaker for provider outages:** If Tiingo returns 5xx errors, every task independently fails, logs, and falls through to Yahoo (which is also broken). Add a run-scoped flag: if the first Tiingo call in a run fails with a server/connection error, set `tiingo_available = False` so subsequent tasks skip directly to FMP without N redundant failing HTTP calls.

**FMP rate limit has no enforcement:** `FMPClient` has no mechanism to stop at 250 calls/day. Add a per-run counter that logs `WARNING` at 200 and `ERROR` at 250. HTTP 429 responses should be caught and surfaced as a warning (not silently returning empty dict) so Sentry captures the exhaustion event.

**Duplicate Tiingo history fetch (resolved in Phase 3 update above):** `_task_price` and `_compute_risk_metrics` both fetch 2yr history. Use `TiingoCache` to deduplicate.

### Data Consistency Risks

- **`adjClose` vs `close`:** Already corrected in Principles and Phase 3 above.
- **FMP margin field units:** `grossProfitMarginTTM` and `operatingProfitMarginTTM` from `/key-metrics-ttm` are decimal fractions (0.45). `peer_enrichment.py:343` multiplies by 100. Verify this specific endpoint during Phase 5 integration test — some FMP endpoint variants return percentages (45.0) instead.
- **FMP `pe` == 0 for negative earnings:** Corrected in Phase 2 above — emit `N/A`.
- **`marketCap` as string:** Corrected in Phase 2 above — `int(...)` coercion.
- **FMP `/quote` `pe` vs `peRatioTTM`:** FMP's `/quote` `pe` may use different earnings definitions than Yahoo's `trailingPE`. Prefer `peRatioTTM` from `/key-metrics-ttm` for the peer comparison table where TTM consistency matters.
- **`industry` field gap degrades peer scoring:** All FMP-path peers within a sector score max 1 point from `_industry_match_score()`. For Technology/Healthcare, cap proximity alone produces poor peers. Investigate FMP `/profile/{symbol}` for `industry`.

### Structural Recommendations

- Rename `_task_yahoo` → `_task_market_data` in Phase 1 (not Phase 6). Already incorporated above.
- Move sector resolution to a pre-step before the thread pool. Already incorporated in Phase 1 risks above.
- Add `TiingoCache` to Phase 3 to eliminate duplicate history fetch. Already incorporated above.
- Add partial enrichment warning lines to sections when a provider in the waterfall fails: `"Note: Valuation multiples unavailable (FMP timeout)"` — so the LLM does not interpret absence as "not applicable."

---

## Python Review: Correctness and Implementation Notes

*Source: python-reviewer subagent review, 2026-03-25*

### Blocking Issues (must resolve before implementation)

| # | Location | Issue |
|---|---|---|
| 1 | `fmp_client.py` (new) | `FMPCache` needs two-lock pattern from `yahoo_cache.py:28-62` — already corrected in Phase 2 above |
| 2 | Both new clients | Per-call sessions defeat connection pooling — use one session per instance. Already corrected in Principles above. |
| 3 | Both new clients | Missing `timeout=(5, 15)` on all `requests.get()` calls — already corrected in Principles and Phase 1 above |
| 4 | `fmp_client.py` | `data[0]` raises `IndexError` on empty list — guard with `data[0] if data else {}` — corrected in Phase 2 |
| 5 | `market_enrichment.py:770` | `if name == "yahoo":` sector extraction breaks when task is renamed — corrected in Phase 1 |
| 6 | Phase 3 new fn | `dt.tz_localize(None)` raises on tz-aware timestamps; must be `dt.tz_convert(None)` — corrected in Phase 3 |
| 7 | Phase 2 new fn | FMP `pe == 0` for negative earnings must emit `N/A` — corrected in Phase 2 |
| 8 | `agents/pattern.py` | Blocking HTTP inside `async build_context()`/`analyze()` — wrap in `run_in_executor` — corrected in Phase 3 |
| 9 | All new call sites | Use `env_flag()` from `utils.py:9`, not raw `os.getenv()` — corrected in Principles |
| 10 | `market_enrichment.py:25` | New task keys must be added to `_ENRICHMENT_TASK_ORDER` — corrected in Principles |

### Worth Fixing During Implementation

- **`_task_*` dict shape:** Both success and `except` branches must return all five keys (`section_entries`, `sources`, `warnings`, `filter_stats`, `sector`/`industry`). A missing key causes `KeyError` at `market_enrichment.py:762`.
- **FMP estimates char budget:** `max_estimates_section_chars = 1200` trims FMP estimate tables mid-row. Add `max_fmp_estimates_section_chars: int = 1800` to `config.py`. Already incorporated in Phase 2.
- **`enrichment_max_chars` during transition:** Raise from 8000 to 10000 while both Tiingo and FMP sections coexist with Yahoo fallback. Already incorporated in Phase 2.
- **`len(close) > days` guards in Phase 3:** All window guards from `market_enrichment.py:354-389` must be replicated in `_tiingo_price_history_section`. Already incorporated in Phase 3.
- **`operatingProfitMarginTTM` unit verification:** Confirm FMP returns decimal (0.45) not percentage (45.0) before shipping Phase 5.
- **FMP-path peer scoring degradation:** Without `industry`, `_industry_match_score` caps at 1 for all peers in a sector. Already noted in Phase 5 risks.
- **Nested executor in `_task_peers`:** `peer_enrichment.py:182` spawns a nested thread pool inside an outer pool worker — document thread budget, verify Streamlit Cloud memory limits.
