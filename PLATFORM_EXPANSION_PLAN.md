# Platform Expansion Plan — TimesFM + Trading Dashboard

**Created:** 2026-04-04  
**Status:** Planning complete, ready to build  
**Scope:** Two parallel tracks — (1) TimesFM nightly batch + Redis cache module, (2) React dashboard extension for portfolio, backtesting, and paper trading

---

## Overview

This document is the authoritative implementation plan for expanding the AI Financial Analyst platform. It covers two interlocking build tracks:

- **Track A** — `quant/timesfm/` module: Google TimesFM 2.5 zero-shot time series forecasting, pre-computed nightly, cached in Redis, injected into existing agent enrichment pipeline
- **Track B** — Frontend dashboard extension: portfolio/watchlist grid, single-stock deep dive with annotated price chart, backtesting dashboard, paper trading tracker

Both tracks are designed to preserve all existing behavior. Every change is additive and gated behind feature flags. The existing Streamlit app, 6-agent pipeline, and Vite React frontend continue to work unchanged when new features are disabled.

### Design constraints carried forward

- **Latency:** TimesFM inference never runs in the customer request path. All forecasts are pre-computed nightly and served from Redis (<5ms lookup at query time).
- **Graceful degradation:** If Redis is unavailable or the batch has not run, agents run exactly as they do today — no TimesFM sections, no errors.
- **Feature flags:** `ENABLE_TIMESFM=false` (default). All new code paths are gated.
- **No base class surgery:** TimesFM signals inject through the existing `enrichment_sections` dict mechanism. `BaseAgent` is untouched.
- **SQLite thread safety:** Maintained throughout. Redis reads happen in `asyncio.to_thread()` (synchronous redis-py is safe in thread pool). TimesFM model singleton uses `threading.Lock`.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  NIGHTLY BATCH (11 PM ET, APScheduler)                         │
│  scripts/run_timesfm_batch.py                                   │
│    └─ quant/timesfm/batch.py                                    │
│         ├─ TiingoClient.get_eod_history() → 512-day prices      │
│         ├─ FMPClient.get_income_statement_quarterly() → EPS      │
│         ├─ TimesFMModel.get().forecast() [GPU, ~150ms/ticker]    │
│         ├─ extract_signals() → named signal dict                 │
│         └─ cache.put_signals() → Redis (TTL 24h)                │
└──────────────────────────────┬──────────────────────────────────┘
                               │ pre-computed, cached
┌──────────────────────────────▼──────────────────────────────────┐
│  REDIS CACHE                                                    │
│  timesfm:{TICKER}:price_forecast  →  {p10, p50, p90, signals}  │
│  timesfm:{TICKER}:eps_forecast    →  {p10, p50, p90, signals}  │
└──────────────────────────────┬──────────────────────────────────┘
                               │ <5ms lookup at query time
┌──────────────────────────────▼──────────────────────────────────┐
│  QUERY-TIME: orchestrator.py → prepare_data()                   │
│    enrichment_sections["timesfm_price"] = format_price_signals()│
│    enrichment_sections["timesfm_eps"]   = format_eps_signals()  │
└─────┬──────────┬──────────┬──────────┬──────────────────────────┘
      │          │          │          │
   PatternAgent  RiskAgent  DCFAgent  MacroAgent
   (+timesfm_   (+timesfm_  (+timesfm_ (+timesfm_
    price)        price)      eps)       price)
      │          │          │          │
      └──────────┴──────────┴──────────┘
                 SynthesisAgent
                 (validates AI price target vs TimesFM P50/P10/P90)
```

```
┌─────────────────────────────────────────────────────────────────┐
│  REACT FRONTEND (Vite + React 19 + TypeScript)                  │
│                                                                  │
│  /analysis          ← existing, unchanged                       │
│  /portfolio         ← WatchlistPage (replaces PortfolioPage)    │
│  /stock/:ticker     ← StockDeepDivePage (extends analysis)      │
│  /backtest          ← BacktestPage (new)                        │
│  /paper-trading     ← PaperTradingPage (new)                    │
│                                                                  │
│  Key chart: TradingView Lightweight Charts (LWC v5)             │
│    ├─ Full price history (5yr)                                   │
│    ├─ BUY/SELL/HOLD annotation markers at rec entry points       │
│    ├─ Time-bounded dashed price target lines                     │
│    ├─ TimesFM confidence band (P10–P90 shaded region)           │
│    └─ Interactive crosshair: hover shows exact price + date     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Track A — TimesFM Nightly Batch + Redis Cache

### Codebase findings that shape implementation

| Finding | File | Impact |
|---|---|---|
| `append_enrichment_sections()` handles missing dict keys silently | `agents/base.py:92` | Zero regression risk on cold cache |
| `prepare_data()` runs in `asyncio.to_thread()` | `orchestrator.py` | Synchronous redis-py is safe; never use aioredis |
| Lazy import pattern established | `quant/discount_rate.py` | `model.py` must import `timesfm` inside `get()`, not at module top |
| `bulk_bootstrap.py` is the canonical entry point template | `scripts/bulk_bootstrap.py` | `run_timesfm_batch.py` mirrors it exactly |
| No APScheduler in codebase yet | — | New dependency |
| `ENABLE_*` feature flag pattern | `config.py` | Add 7 new fields with `model_config = {"extra": "ignore"}` safety |

### New file tree

```
quant/timesfm/
  __init__.py           exports TimesFMModel, extract_signals, get_signals, put_signals
  model.py              lazy singleton wrapper, threading.Lock, pre-warm on load
  signals.py            (point, quantiles) → named signal dict
  enrichment.py         signal dict → formatted text blocks for enrichment_sections
  batch.py              fetch → infer → Redis for all tickers in TIMESFM_BATCH_TICKERS
  cache.py              Redis get/set, graceful None on failure, never raises

scripts/
  run_timesfm_batch.py  APScheduler entry point, --run-now flag for testing
```

### New dependencies

Add to `requirements.txt` and `pyproject.toml`:

```toml
# Base deps (always installed):
redis>=5.0.0
apscheduler>=3.10.4

# Optional — only needed on the machine running the batch job:
[project.optional-dependencies]
timesfm = ["timesfm>=1.2.5", "torch>=2.1.0"]
dev = ["fakeredis>=2.20.0", "pytest-mock>=3.12"]
```

Install on batch machine: `pip install -e ".[timesfm]"`

Note: `timesfm[torch]` pulls ~800MB PyTorch. Keep it optional to avoid forcing it on every developer.

### New environment variables

| Variable | Default | Purpose |
|---|---|---|
| `ENABLE_TIMESFM` | `false` | Master gate. Must be `true` for any TimesFM code path to execute |
| `REDIS_URL` | `""` | Redis connection string. Empty = graceful no-op across all paths |
| `TIMESFM_CHECKPOINT_DIR` | `""` | Local dir for model weights. Empty = package default (`~/.cache/timesfm`) |
| `TIMESFM_BATCH_TICKERS` | `""` | Comma-separated tickers for nightly batch, e.g. `"AAPL,MSFT,NVDA"` |
| `TIMESFM_HORIZON_DAYS` | `10` | Number of forecast steps (price series) |
| `TIMESFM_PRICE_LOOKBACK_DAYS` | `512` | Trading days of price history fetched from Tiingo |
| `TIMESFM_TTL_SECONDS` | `86400` | Redis key TTL (24 hours) |

---

### A-Phase 1: Model Wrapper + Redis Cache

**Goal:** Foundational I/O layer. Nothing downstream can be built until the model loads reliably and Redis is wired in.  
**Effort:** Medium (most time is checkpoint download and environment setup)  
**Dependencies:** None  
**Can run in parallel with:** A-Phase 7 (Docker Compose), Track B Phase 1

#### Subagent task — `quant/timesfm/model.py`

```
Implement TimesFMModel lazy singleton.

File: quant/timesfm/model.py

Requirements:
- Module-level threading.Lock (_model_lock) and _instance variable
- TimesFMModel.get() classmethod: acquires lock, checks _instance, loads if None, returns instance
- Import timesfm inside get() (lazy import — follow quant/discount_rate.py pattern)
- Load model: timesfm.TimesFM_2p5_200M_torch.from_pretrained("google/timesfm-2.5-200m-pytorch")
- Call model.compile() with ForecastConfig(normalize_inputs=True, use_continuous_quantile_head=True, fix_quantile_crossing=True)
- Pre-warm after load: call forecast([1.0]*64, horizon=5) and discard result
- forecast(series, horizon, freq) method:
    - Calls model.forecast(inputs=[np.array(series)], freq=freq, horizon=horizon)
    - Returns (point_list, {"p10": [...], "p50": [...], "p90": [...]})
    - Quantile index mapping: 0=mean, 1=p10, 5=p50, 9=p90
- TIMESFM_CHECKPOINT_DIR env var controls cache dir (pass to from_pretrained if set)
- Raises RuntimeError with clear message if timesfm package not installed

Existing pattern to follow: quant/discount_rate.py lazy imports
```

#### Subagent task — `quant/timesfm/cache.py`

```
Implement Redis cache client with graceful degradation.

File: quant/timesfm/cache.py

Requirements:
- Module-level _redis_client: Optional[redis.Redis] = None
- get_redis_client() → Optional[redis.Redis]:
    - Reads REDIS_URL from environment
    - Returns None if empty
    - Attempts redis.Redis.from_url(url, decode_responses=True)
    - Calls client.ping() to verify connection
    - Returns None (never raises) if connection fails
    - Caches the client as module singleton
- get_signals(ticker: str) → Optional[dict]:
    - Key: f"timesfm:{ticker.upper()}:{signal_type}" — actually fetches ALL keys for ticker
    - Use client.keys(f"timesfm:{ticker.upper()}:*") then mget
    - Returns dict keyed by signal_type with parsed JSON values
    - Returns None if Redis unavailable, key missing, or any exception
    - Never raises
- put_signals(ticker, signal_type, payload: dict, ttl_seconds=86400) → bool:
    - Key: f"timesfm:{ticker.upper()}:{signal_type}"
    - Serializes payload as JSON, calls setex
    - Returns False (never raises) on any failure
- All methods wrap their bodies in try/except Exception
```

#### Subagent task — `config.py` additions

```
Add 7 new fields to Settings in config.py.

File: ai-financial-analyst/config.py

Add these fields to the Settings class (Pydantic BaseSettings):
    enable_timesfm: bool = False
    redis_url: str = ""
    timesfm_checkpoint_dir: str = ""
    timesfm_batch_tickers: str = ""
    timesfm_horizon_days: int = 10
    timesfm_price_lookback_days: int = 512
    timesfm_ttl_seconds: int = 86400

The existing model_config = {"extra": "ignore"} already prevents breakage from new fields.
No other changes to this file.
```

#### Files to verify after A-Phase 1

```bash
# Redis graceful degradation (no REDIS_URL set)
python -c "from quant.timesfm.cache import get_signals; print(get_signals('AAPL'))"
# Expected: None (no crash)

# Model loads (requires timesfm installed and weights downloaded)
python -c "
from quant.timesfm.model import TimesFMModel
m = TimesFMModel.get()
pt, q = m.forecast([float(i) for i in range(64)], horizon=5)
print(len(pt), list(q.keys()))
"
# Expected: 5 ['p10', 'p50', 'p90']
```

---

### A-Phase 2: Signal Extractor

**Goal:** Pure Python math. Translates raw `(point, quantiles)` into named signal vocabulary agents consume.  
**Effort:** Low (2-3 hours)  
**Dependencies:** A-Phase 1 (model.py interface defined)  
**Can run in parallel with:** A-Phase 3

#### Subagent task — `quant/timesfm/signals.py`

```
Implement extract_signals() function.

File: quant/timesfm/signals.py

Function signature:
    def extract_signals(
        current_value: float,
        point_forecast: list[float],         # P50 values, length = horizon
        quantiles: dict[str, list[float]],   # keys: p10, p50, p90
    ) -> dict:

Return dict with these exact keys:
    trend_direction:   "bullish" | "bearish" | "neutral"
    momentum_score:    float  (clamped to [-1, 1])
    volatility_proxy:  float
    downside_risk_pct: float
    upside_target:     float
    confidence_band:   list[dict]  # one entry per horizon step

Computation rules:
- trend_direction: fit linear regression (numpy.polyfit degree 1) through point_forecast values.
    slope_pct = slope / point_forecast[0] (per-step % change)
    > +0.005 → "bullish", < -0.005 → "bearish", else "neutral"
- momentum_score: (point_forecast[-1] - point_forecast[0]) / point_forecast[0], clamped to [-1, 1]
- volatility_proxy: (quantiles["p90"][-1] - quantiles["p10"][-1]) / quantiles["p50"][-1]
- downside_risk_pct: (quantiles["p10"][-1] - current_value) / current_value * 100
- upside_target: quantiles["p90"][-1]
- confidence_band: [{"step": i+1, "p10": p10[i], "p50": p50[i], "p90": p90[i]} for i in range(len)]

Import numpy at top of file (not lazy — numpy is already in requirements).
No other imports needed.

Write 3 unit tests in tests/test_timesfm_signals.py:
1. Monotonically increasing P50 → trend_direction == "bullish", momentum_score > 0
2. Flat P50 → trend_direction == "neutral", momentum_score ~= 0 (abs < 0.001)
3. Decreasing P50 → trend_direction == "bearish", downside_risk_pct < 0
```

---

### A-Phase 3: Enrichment Text Formatter

**Goal:** Converts signal dicts to text blocks compatible with the existing `enrichment_sections` string format.  
**Effort:** Low (1-2 hours)  
**Dependencies:** A-Phase 2  
**Can run in parallel with:** A-Phase 2

#### Subagent task — `quant/timesfm/enrichment.py`

```
Implement two text formatter functions.

File: quant/timesfm/enrichment.py

Function 1:
    def format_price_signals(ticker: str, signals: dict) -> str:
    
    Output format (example):
    === TimesFM Price Forecast (AAPL) ===
      Trend Direction: bullish
      Momentum Score: +0.42
      Volatility Proxy (P90-P10)/P50: 0.08
      Downside Risk (P10 vs current): -4.2%
      Upside Target (P90, horizon end): $234.50
      Confidence Band:
        Step 1:  P10=$218.20  P50=$221.40  P90=$224.60
        Step 2:  P10=$219.10  P50=$222.80  P90=$226.50
        ... (show up to 5 steps to control context budget)

Function 2:
    def format_eps_signals(ticker: str, signals: dict) -> str:
    
    Output format (example):
    === TimesFM EPS Forecast (AAPL) ===
      Trend Direction: bullish
      Forward EPS P50 (next 4 steps): [6.10, 6.25, 6.40, 6.58]
      Downside Risk (P10 vs current): -8.1%
      Upside (P90, final step): $7.12

Both functions:
- Start with the === header line (used by append_enrichment_sections pattern)
- Limit confidence_band output to first 5 steps to stay within ~600 char budget
- Handle KeyError gracefully (missing signal key → skip that line)
- Return empty string "" if signals dict is empty or None

Write tests in tests/test_timesfm_enrichment.py:
- Assert output starts with "=== TimesFM"
- Assert "Trend Direction:" appears in price formatter output
- Assert format_price_signals({}, "AAPL") returns ""
```

---

### A-Phase 4: Nightly Batch Job

**Goal:** Production data pipeline. Fetches real price + EPS series, runs TimesFM, populates Redis.  
**Effort:** Medium (highest-risk phase — budget a full day)  
**Dependencies:** A-Phase 1, A-Phase 2, A-Phase 3

#### Subagent task — `quant/timesfm/batch.py`

```
Implement run_batch() function.

File: quant/timesfm/batch.py

Function signature:
    def run_batch(tickers: list[str]) -> dict[str, str]:
    # Returns: {"AAPL": "ok", "MSFT": "error: insufficient data", ...}

Implementation steps per ticker (inside try/except — single failure never aborts loop):
    1. Fetch price series:
        tiingo = TiingoClient(settings)  # created once outside loop
        prices = tiingo.get_eod_history(ticker, days=settings.timesfm_price_lookback_days)
        # Extract adjClose values as list[float], chronological order
        # Skip ticker if len(prices) < 64 (log warning, mark "error: insufficient price data")
        
    2. Fetch quarterly EPS series:
        fmp = FMPClient(settings)  # created once outside loop
        income = fmp.get_income_statement_quarterly(ticker, limit=20)
        # Extract (report_date, eps) pairs, sort chronological
        # Interpolate to monthly using numpy.interp on epoch timestamps
        # Skip EPS forecast if fewer than 8 quarters available (log, continue with price only)
        
    3. Run price forecast:
        model = TimesFMModel.get()  # loads once before loop, reuses singleton
        point, quantiles = model.forecast(prices, horizon=settings.timesfm_horizon_days, freq=0)
        
    4. Extract price signals:
        price_signals = extract_signals(current_value=prices[-1], point_forecast=point, quantiles=quantiles)
        
    5. Cache price signals:
        cache.put_signals(ticker, "price_forecast", price_signals, ttl_seconds=settings.timesfm_ttl_seconds)
        
    6. If EPS data available, run EPS forecast and cache similarly with signal_type="eps_forecast"
    
    7. Mark result "ok" for this ticker

Before the loop:
    - Call TimesFMModel.get() to pre-warm the model (load + dummy inference)
    - Create TiingoClient and FMPClient instances (one each for the whole batch)

Logging:
    - Use module-level logger = logging.getLogger(__name__)
    - Log INFO at start: "Starting TimesFM batch for %d tickers"
    - Log INFO per ticker: "AAPL: price_forecast cached (512 points → 10-step forecast)"
    - Log WARNING on skip: "AAPL: insufficient EPS data (6 quarters), skipping eps_forecast"
    - Log ERROR on exception: "MSFT: batch failed — %s" (include exception str)

Import pattern:
    from quant.timesfm.model import TimesFMModel
    from quant.timesfm.signals import extract_signals
    from quant.timesfm import cache
    from config import settings
    from tiingo_client import TiingoClient
    from fmp_client import FMPClient
```

---

### A-Phase 5: Scheduler Entry Point

**Goal:** Wraps batch in APScheduler for unattended nightly execution.  
**Effort:** Low (1 hour)  
**Dependencies:** A-Phase 4

#### Subagent task — `scripts/run_timesfm_batch.py`

```
Implement the APScheduler entry point script.

File: scripts/run_timesfm_batch.py

Pattern to follow exactly: scripts/bulk_bootstrap.py structure
    - sys.path.insert(0, ...) for project root
    - load_dotenv()
    - logging.basicConfig with format "%(asctime)s %(levelname)-7s %(name)s — %(message)s"
    - argparse

Arguments:
    --run-now     Run the batch immediately and exit (used for testing, CI, manual triggers)
    --hour INT    Cron hour (default 23 = 11 PM)
    --minute INT  Cron minute (default 0)

run_job() function (what APScheduler calls):
    - Read settings.enable_timesfm — if False, log "ENABLE_TIMESFM=false — skipping" and return
    - Parse settings.timesfm_batch_tickers (comma-split, strip, upper)
    - If empty, log warning and return
    - Call run_batch(tickers) from quant.timesfm.batch
    - Log summary: "TimesFM batch complete: X/Y tickers OK"

main() function:
    - If --run-now: call run_job() directly, return
    - Else: create BlockingScheduler(timezone="America/New_York")
    - Add cron job: scheduler.add_job(run_job, "cron", hour=args.hour, minute=args.minute)
    - Log "Scheduler started — job fires at HH:MM ET"
    - scheduler.start() wrapped in try/except KeyboardInterrupt

Verification commands (document in module docstring):
    # Test with gate disabled (should skip silently):
    python scripts/run_timesfm_batch.py --run-now
    
    # Test with full env (requires REDIS_URL, TIINGO_API_KEY, FMP_API_KEY, ENABLE_TIMESFM=true):
    ENABLE_TIMESFM=true TIMESFM_BATCH_TICKERS=AAPL python scripts/run_timesfm_batch.py --run-now
    
    # Start scheduled mode:
    python scripts/run_timesfm_batch.py --hour 23
```

---

### A-Phase 6: Agent Integration

**Goal:** Wires Redis signals into enrichment pipeline. 5 file edits, zero base class changes.  
**Effort:** Low (1-2 hours)  
**Dependencies:** A-Phase 3, A-Phase 4 (Redis must have data for full verification)

#### Subagent task — orchestrator.py injection + agent tuple additions

```
Wire TimesFM signals into the enrichment pipeline.

Changes required across 5 files:

FILE 1: orchestrator.py
In prepare_data(), after the line:
    enrichment_sections = dict(enrichment.get("sections", {}))
(approximately line 269 — find by searching for "enrichment_sections = dict")

ADD this block immediately before the return AnalysisData(...) statement:
    if settings.enable_timesfm:
        try:
            from quant.timesfm.cache import get_signals
            from quant.timesfm.enrichment import format_price_signals, format_eps_signals
            tfm_signals = get_signals(ticker_upper)
            if tfm_signals:
                price_sig = tfm_signals.get("price_forecast")
                eps_sig   = tfm_signals.get("eps_forecast")
                if price_sig:
                    enrichment_sections["timesfm_price"] = format_price_signals(ticker_upper, price_sig)
                if eps_sig:
                    enrichment_sections["timesfm_eps"] = format_eps_signals(ticker_upper, eps_sig)
        except Exception as exc:
            logger.warning("TimesFM enrichment injection failed: %s", exc)

FILE 2: agents/pattern.py
Find enrichment_sections tuple (approximately line 116).
Add "timesfm_price" as the last entry in the tuple.

FILE 3: agents/risk.py
Find enrichment_sections tuple (approximately line 20).
Add "timesfm_price" as the last entry in the tuple.

FILE 4: agents/dcf.py
Find enrichment_sections tuple (approximately line 23).
Add "timesfm_eps" as the last entry in the tuple.

FILE 5: agents/macro.py
Find enrichment_sections tuple (approximately line 19).
Add "timesfm_price" as the last entry in the tuple.

BONUS — prompts/synthesis.md:
Add this section after the existing verdict/conviction/price target sections:
    ## TimesFM Forecast Validation (include only if TimesFM sections present in any agent report)
    - Does the AI price target align with the TimesFM P50 forecast range?
    - Flag if current price is below P10 (quantified downside risk)
    - Flag if analyst EPS estimates diverge significantly from TimesFM EPS P50

Verification:
    # With ENABLE_TIMESFM=false (default): behavior identical to today
    python main.py AAPL
    
    # With warm Redis:
    # PatternAgent, RiskAgent, MacroAgent context should contain "=== TimesFM Price Forecast"
    # DCFAgent context should contain "=== TimesFM EPS Forecast"
    ENABLE_TIMESFM=true REDIS_URL=redis://localhost:6379/0 python main.py AAPL
    
    # With ENABLE_TIMESFM=true but cold Redis (batch not yet run):
    # Should run cleanly with no TimesFM sections, no errors
```

---

### A-Phase 7: Docker Compose Redis Service

**Goal:** Local Redis with one command.  
**Effort:** Low (30 min)  
**Dependencies:** None — can be merged on day one

#### Subagent task — `docker-compose.yml`

```
Add Redis service to Docker Compose.

Check if docker-compose.yml already exists at:
    /Users/chadreadey/portfolio-analyst/ai-financial-analyst/docker-compose.yml

If it exists: add the redis service and redis_data volume to the existing file.
If it does not exist: create it.

Redis service config:
    redis:
      image: redis:7-alpine
      ports:
        - "6379:6379"
      volumes:
        - redis_data:/data
      command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru
      healthcheck:
        test: ["CMD", "redis-cli", "ping"]
        interval: 10s
        timeout: 3s
        retries: 3

Add volume declaration:
    volumes:
      redis_data:

Add to .env.example (or create it if absent):
    REDIS_URL=redis://localhost:6379/0
    ENABLE_TIMESFM=false
    TIMESFM_BATCH_TICKERS=AAPL,MSFT,NVDA,GOOGL
    TIMESFM_HORIZON_DAYS=10
    TIMESFM_PRICE_LOOKBACK_DAYS=512

Verification:
    docker compose up redis -d
    redis-cli ping  # → PONG
```

---

### A-Phase 8: Testing

**Effort:** Medium  
**Dependencies:** A-Phase 1–6

#### Subagent task — unit tests

```
Write unit test suite for the TimesFM module.

Tests must NOT require a running Redis server, a real TimesFM model, or live API keys.
Use fakeredis for Redis mocking and pytest-mock (MagicMock) for external clients.

FILE 1: tests/test_timesfm_signals.py
    Test extract_signals() with three parametrized cases:
    1. Monotonically increasing P50 [100, 101, 102, ..., 109]
       → trend_direction == "bullish", momentum_score > 0
    2. Flat P50 [100, 100, 100, ..., 100]
       → trend_direction == "neutral", abs(momentum_score) < 0.001
    3. Monotonically decreasing P50 [100, 99, 98, ..., 91]
       → trend_direction == "bearish", downside_risk_pct < 0

FILE 2: tests/test_timesfm_cache.py
    Use fakeredis.FakeRedis as the mock client (patch get_redis_client to return it).
    Test 1: put_signals("AAPL", "price_forecast", {"trend": "bullish"}) → True
    Test 2: get_signals("AAPL") returns dict containing "price_forecast" key
    Test 3: get_signals("MSFT") returns None when key absent
    Test 4: Graceful degradation — patch get_redis_client to raise ConnectionError
             → put_signals returns False (no exception propagates)
             → get_signals returns None (no exception propagates)

FILE 3: tests/test_timesfm_enrichment.py
    Test format_price_signals():
        - Output starts with "=== TimesFM Price Forecast"
        - Output contains "Trend Direction:"
        - format_price_signals("AAPL", {}) returns ""
    Test format_eps_signals():
        - Output starts with "=== TimesFM EPS Forecast"
        - format_eps_signals("AAPL", None) returns ""

FILE 4: tests/test_timesfm_batch_unit.py
    Mock: TiingoClient, FMPClient, TimesFMModel.get(), cache.put_signals
    Test 1: run_batch(["AAPL"]) calls put_signals with signal_type="price_forecast"
    Test 2: A single ticker raising an exception does NOT abort the loop
            → run_batch(["AAPL", "FAIL_TICKER"]) returns results for both keys
            → "AAPL" → "ok", "FAIL_TICKER" → starts with "error:"
    Test 3: Ticker with fewer than 64 price points is skipped gracefully
```

---

## Track B — React Dashboard Extension

### Codebase findings that shape implementation

| Finding | File | Impact |
|---|---|---|
| Routes are flat `<Route>` entries under `BrowserRouter` | `frontend/src/App.tsx` | New routes slot directly in |
| Nav is a `links` array | `frontend/src/components/layout/TopNav.tsx` | One array push per new route |
| Design tokens are CSS custom properties | `frontend/src/index.css` | Use `--bg-primary` (`#070b12`), not hardcoded hex |
| `Card` and `Badge` are atomic building blocks | `frontend/src/components/common/` | All new pages use these, not new wrappers |
| `Badge` already supports `green/amber/red/blue/muted` | `Badge.tsx` | BUY=green, SELL=red, HOLD=amber — no new variants |
| Tabs in `ResultView` are hand-rolled button arrays, not Radix Tabs | `ResultView.tsx` | New "Price History" tab matches existing pattern |
| `api.request<T>()` typed wrapper | `frontend/src/api/client.ts` | All new API calls as typed methods on `api` object |
| `PortfolioPage` at `/portfolio` already exists | `frontend/src/pages/PortfolioPage.tsx` | Phase 1 replaces its contents, route stays |
| `analysis_history` table exists with `ticker, run_at, verdict, conviction, composite_score` | `sec/cache.py` | Missing `entry_price` + `target_price` columns — handle nulls in chart |
| LWC v5 API: `chart.addSeries(CandlestickSeries)` | — | Not `addCandlestickSeries()` — confirm version before writing PriceChart |

### New npm dependency (only one)

```bash
npm install lightweight-charts
```

TypeScript types are bundled. No `@types/` install needed. Recharts (already installed) handles sparklines and equity curves.

### Route structure

| Path | Component | Notes |
|---|---|---|
| `/analysis` | `AnalysisPage` | Unchanged |
| `/portfolio` | `WatchlistPage` | Replaces `PortfolioPage` content; route unchanged |
| `/stock/:ticker` | `StockDeepDivePage` | New — extends analysis with chart + performance |
| `/backtest` | `BacktestPage` | New |
| `/paper-trading` | `PaperTradingPage` | New |

---

### B-Phase 1: Foundation — Routes, Navigation, Watchlist Grid, API Stubs

**Goal:** All routes are navigable, watchlist grid renders (with placeholder sparklines), API client has all typed methods.  
**Effort:** Medium  
**Dependencies:** None  
**Can run in parallel with:** Track A Phase 1, A-Phase 7

#### Subagent task — backend routers (3 new files)

```
Create three new FastAPI routers and mount them.

FILE 1: backend/routers/watchlist.py
Endpoints:
    GET  /api/watchlist/             → list all watchlist entries (reads watchlist table + latest analysis_history)
    POST /api/watchlist/{ticker}     → add ticker to watchlist
    DELETE /api/watchlist/{ticker}   → remove ticker from watchlist
    GET  /api/watchlist/{ticker}/summary  → hit rate, alpha, P&L, period statuses

Watchlist persistence: new SQLite table "watchlist_entries" with columns:
    ticker TEXT PRIMARY KEY, added_at TEXT

"summary" endpoint:
    - Current price from Tiingo (or None)
    - period_statuses: dict with keys "3mo", "1yr", "3yr", "5yr", "current"
      Each value: "hit" | "miss" | "pending" | "none"
      Logic: compare run_at date to now to determine which period bucket a recommendation falls in
      For now, return "pending" for all (full implementation in Phase 2 when entry_price exists)

FILE 2: backend/routers/market_data.py
Endpoints:
    GET /api/market/sparkline/{ticker}      → 60-point closing prices (last 60 trading days)
    GET /api/market/price-history/{ticker}  → OHLCV bars, query param period=1mo|3mo|1yr|3yr|5yr

Price data from TiingoClient.get_eod_history().
Response format for price-history:
    { "ticker": str, "bars": [{"time": "YYYY-MM-DD", "open": f, "high": f, "low": f, "close": f, "volume": i}] }
    "time" must be "YYYY-MM-DD" string (TradingView LWC canonical format)

FILE 3: backend/routers/recommendations.py
Endpoints:
    GET /api/recommendations/history/{ticker}  → recommendation records from analysis_history table

Response includes all analysis_history rows for the ticker.
entry_price and target_price are null until migration adds those columns — return null, do not error.
outcome is null for now — Phase 2 adds logic to determine hit/miss/pending.

FILE 4: backend/main.py modifications
Mount the three new routers:
    from backend.routers import watchlist, market_data, recommendations
    app.include_router(watchlist.router, prefix="/api/watchlist")
    app.include_router(market_data.router, prefix="/api/market")
    app.include_router(recommendations.router, prefix="/api/recommendations")

FILE 5: backend/schemas.py additions
Add Pydantic response models:
    WatchlistEntry, WatchlistSummary, PriceBar, RecommendationRecord
    (skeleton models with Optional fields for the columns that don't exist yet)

Preserve ALL existing routes. This is additive only.
Follow the pattern in backend/routers/portfolio.py for SQLite access pattern.
```

#### Subagent task — frontend Phase 1 (routes, nav, watchlist page, API types)

```
Build the frontend foundation: routing, navigation, watchlist grid, API stubs.

Read these files before starting:
    frontend/src/App.tsx
    frontend/src/components/layout/TopNav.tsx
    frontend/src/api/client.ts
    frontend/src/api/types.ts (or api/index.ts — check which exists)
    frontend/src/components/common/Card.tsx
    frontend/src/components/common/Badge.tsx
    frontend/src/index.css

STEP 1: frontend/src/api/types.ts — add new interfaces:
    WatchlistEntry { ticker, added_at, latest_verdict?, latest_conviction?, latest_score? }
    WatchlistSummary { ticker, current_price?, hit_rate_pct?, alpha_vs_spy?, period_statuses }
    PriceBar { time: string, open, high, low, close, volume }
    RecommendationRecord { run_at, verdict, conviction, composite_score?, entry_price?, target_price?, time_horizon?, outcome?, outcome_price?, outcome_date? }
    SparklineData { ticker, closes: number[], dates: string[] }

STEP 2: frontend/src/api/client.ts — add typed methods to existing api object:
    getWatchlist() → WatchlistEntry[]
    addToWatchlist(ticker) → void
    removeFromWatchlist(ticker) → void
    getWatchlistSummary(ticker) → WatchlistSummary
    getPriceHistory(ticker, period: "1mo"|"3mo"|"1yr"|"3yr"|"5yr") → { bars: PriceBar[] }
    getSparkline(ticker) → SparklineData
    getRecommendationHistory(ticker) → { records: RecommendationRecord[] }

STEP 3: frontend/src/index.css — add two CSS custom properties:
    --accent-purple: #818cf8;
    --accent-yellow: #fbbf24;
    (--accent-green and --accent-red already exist — verify before adding)

STEP 4: Create frontend/src/components/watchlist/StatusDots.tsx
    Props: statuses: Record<"3mo"|"1yr"|"3yr"|"5yr"|"current", "hit"|"miss"|"pending"|"none">
    Renders 5 colored dots in a row with period labels below
    hit=green (--accent-green), miss=red (--accent-red), pending=yellow (--accent-yellow), none=gray

STEP 5: Create frontend/src/components/watchlist/WatchlistCard.tsx
    Props: entry: WatchlistEntry, summary?: WatchlistSummary
    Layout:
        - Top: ticker (bold) + Badge (verdict, green/red/amber) + current price
        - Middle: 60x40 div placeholder for sparkline (gray background, "chart" label)
        - Bottom row: hit rate %, alpha vs SPY %, P&L %
        - Status dots row (StatusDots component)
    Use existing Card component as outer wrapper
    onClick → navigate to /stock/{ticker}

STEP 6: Create frontend/src/hooks/useWatchlist.ts
    Fetches api.getWatchlist() on mount
    Exposes: entries, isLoading, error, add(ticker), remove(ticker)
    add/remove call the API then refetch

STEP 7: Create frontend/src/pages/WatchlistPage.tsx
    Uses useWatchlist hook
    Renders a responsive grid of WatchlistCard components (grid-cols-1 md:grid-cols-2 xl:grid-cols-3)
    Add button: "Add Ticker" opens a simple text input inline (no modal needed)
    Loading state: skeleton cards (gray animated pulses, same width as real cards)
    Preserve the existing "manage holdings" add/remove form from the old PortfolioPage
    in a collapsible section at the bottom — do not delete that functionality

STEP 8: Create shell pages (minimal content, no errors):
    frontend/src/pages/StockDeepDivePage.tsx  — shows ticker from useParams, placeholder chart area
    frontend/src/pages/BacktestPage.tsx        — header + 3 placeholder Card panels
    frontend/src/pages/PaperTradingPage.tsx    — header + 2 placeholder Card panels

STEP 9: frontend/src/App.tsx — add Route entries:
    <Route path="/stock/:ticker" element={<StockDeepDivePage />} />
    <Route path="/backtest" element={<BacktestPage />} />
    <Route path="/paper-trading" element={<PaperTradingPage />} />
    Change /portfolio route to use <WatchlistPage /> instead of <PortfolioPage />

STEP 10: frontend/src/components/layout/TopNav.tsx — add 3 nav entries to links array:
    { to: "/portfolio", label: "Watchlist", icon: LayoutGrid }   (replaces old Portfolio entry)
    { to: "/backtest", label: "Backtest", icon: FlaskConical }
    { to: "/paper-trading", label: "Paper Trading", icon: Wallet }
    Import new icons from lucide-react

Verification:
    npm run dev
    Navigate to /portfolio → watchlist grid renders
    Navigate to /stock/AAPL → shell page loads, ticker shows in header
    Navigate to /backtest and /paper-trading → shell pages render
    All 5 nav links show correct active underline
```

---

### B-Phase 2: Charts, Annotations, Deep Dive Completion

**Goal:** The annotated TradingView price chart with interactive hover, sparklines in watchlist cards, and the full single-stock deep dive.  
**Effort:** High  
**Dependencies:** B-Phase 1 (routes exist, API methods exist)

#### Subagent task — `PriceChart.tsx` (TradingView LWC)

```
Build the TradingView Lightweight Charts annotated price chart component.

BEFORE STARTING: Run `npm info lightweight-charts version` and confirm v5.x is installed.
The v5 API uses chart.addSeries(CandlestickSeries) — NOT chart.addCandlestickSeries().
If v4 is installed for any reason, notify and halt — do not implement against the wrong API.

File: frontend/src/components/charts/PriceChart.tsx

Props interface:
    interface PriceChartProps {
        bars: PriceBar[]
        recommendations: RecommendationRecord[]
        forecast?: ForecastBand[]   // [{time: string, p10: number, p50: number, p90: number}]
        height?: number             // default 400
    }

Implementation steps inside useEffect:
    1. createChart(containerRef.current, {
           layout: { background: { color: '#111827' }, textColor: '#94a3b8' },
           grid: { vertLines: { color: '#1e2d40' }, horzLines: { color: '#1e2d40' } },
           crosshair: { mode: CrosshairMode.Normal },
           rightPriceScale: { borderColor: '#1e2d40' },
           timeScale: { borderColor: '#1e2d40' },
       })
       
    2. const candleSeries = chart.addSeries(CandlestickSeries, {
           upColor: '#34d399', downColor: '#f87171',
           borderUpColor: '#34d399', borderDownColor: '#f87171',
           wickUpColor: '#34d399', wickDownColor: '#f87171',
       })
       candleSeries.setData(bars)  // bars must be sorted by time ascending
       
    3. For each RecommendationRecord with a non-null entry_price:
       - Create a LineSeries with lineStyle: LineStyle.Dashed, color by verdict
         BUY: '#34d399', SELL: '#f87171', HOLD: '#fbbf24'
       - Set data as a two-point line from run_at date to run_at + 90 days
         at the target_price value (horizontal target line)
         
    4. Add recommendation markers to candleSeries via setMarkers():
       - BUY: { time, position: 'belowBar', color: '#34d399', shape: 'arrowUp', text: 'BUY' }
       - SELL: { time, position: 'aboveBar', color: '#f87171', shape: 'arrowDown', text: 'SELL' }
       - HOLD: { time, position: 'belowBar', color: '#fbbf24', shape: 'circle', text: 'HOLD' }
       Handle null entry_price gracefully — still show marker, just no target line
       
    5. If forecast prop provided, add confidence band:
       - AreaSeries for P90 upper bound: topColor '#818cf8' at 0.12 opacity, bottomColor transparent
       - AreaSeries for P10 lower bound: topColor transparent, bottomColor '#818cf8' at 0.08 opacity
       - LineSeries for P50 central forecast: color '#818cf8', lineWidth 1, lineStyle LineStyle.Dashed
       
    6. Crosshair tooltip (interactive hover):
       - Create a div inside the container: position absolute, pointer-events none, display none
       - chart.subscribeCrosshairMove((param) => {
             if (!param.point || !param.time) { hideTooltip(); return; }
             const price = param.seriesPrices.get(candleSeries);
             setTooltip({ date: param.time, open: price.open, high: price.high,
                          low: price.low, close: price.close, visible: true });
             positionTooltip(param.point.x, param.point.y);
         })
       - Tooltip shows: date (formatted), OHLC values, change from prev close
       
    7. chart.timeScale().fitContent() after all data is set
    
    8. return () => chart.remove()   // cleanup

Use useRef<HTMLDivElement> for container. Chart width = container.clientWidth (ResizeObserver to handle resize).
The tooltip state is React state (useState) to avoid direct DOM mutation inside the crosshair handler.

Do NOT use any hardcoded hex colors — use the CSS variable values documented in this plan.
```

#### Subagent task — sparklines + deep dive wiring

```
Complete the deep dive page and wire sparklines into watchlist cards.

FILE 1: frontend/src/components/charts/SparklineChart.tsx
    Props: closes: number[], isPositive: boolean, height?: number (default 40)
    Use Recharts LineChart (already installed, no new deps)
    No axes, no grid, no tooltip (it's a micro-chart inside a card)
    Line color: isPositive ? var(--accent-green) : var(--accent-red)
    Fill area below line with 10% opacity version of same color

FILE 2: frontend/src/hooks/usePriceHistory.ts
    Fetches api.getPriceHistory(ticker, period) on mount and when period changes
    Returns { bars: PriceBar[], isLoading, error }
    Caches last result per (ticker, period) in useRef to prevent flash on period toggle

FILE 3: frontend/src/hooks/useRecommendationHistory.ts
    Fetches api.getRecommendationHistory(ticker) on mount
    Returns { records: RecommendationRecord[], isLoading, error }

FILE 4: frontend/src/components/deepdive/PriceHistoryTab.tsx
    Uses usePriceHistory and useRecommendationHistory hooks
    Time range selector: pill buttons [1mo] [3mo] [1yr] [3yr] [5yr], active state highlighted
    Renders PriceChart with bars + recommendations
    Loading state: gray rectangle same height as chart with pulse animation

FILE 5: frontend/src/components/deepdive/HistoricalPerformanceCards.tsx
    Props: records: RecommendationRecord[]
    Renders up to 5 cards (3mo/1yr/3yr/5yr/current) from records array
    Each card: period label, verdict badge, entry price, target price, return %, hit/miss status chip
    Null entry_price/target_price → show "—" (data pending)
    Uses existing Card component

FILE 6: frontend/src/components/deepdive/PerformanceMetricsPanel.tsx
    Props: summary: WatchlistSummary | undefined
    Shows: Hit Rate, Alpha vs SPY, P&L, Win Rate in a 4-column grid using existing Card
    Shows "—" for null values

FILE 7: Modify frontend/src/components/analysis/ResultView.tsx
    IMPORTANT: Read the file carefully before editing. The activeTab state is typed as a string union.
    Add "price-history" to the union type.
    Add a tab button: { id: "price-history", label: "Price History & Targets" }
    Add a case in the tab content switch/conditional that renders:
        <PriceHistoryTab ticker={result.ticker} />
    The tab only appears after result is loaded (same condition as existing tabs).
    Verify existing tabs (synthesis/agents/diagnostics) are completely unaffected.

FILE 8: Modify frontend/src/components/watchlist/WatchlistCard.tsx
    Replace the sparkline placeholder div with <SparklineChart closes={...} isPositive={...} />
    Fetch sparkline data via api.getSparkline(ticker) in a useEffect inside the card
    isPositive = closes[closes.length-1] > closes[0]

FILE 9: Modify frontend/src/pages/StockDeepDivePage.tsx
    Get ticker from useParams
    Render HistoricalPerformanceCards and PerformanceMetricsPanel below the analysis section
    Include a link: "← Back to Watchlist" navigating to /portfolio
```

---

### B-Phase 3: Backtest Dashboard + Paper Trading Tracker

**Goal:** Full backtest and paper trading workflows.  
**Effort:** High  
**Dependencies:** B-Phase 1 (routes, API), B-Phase 2 (`EquityCurveChart` component)

#### Subagent task — backend backtest engine + paper trading

```
Build the backtest engine and paper trading backend.

FILE 1: backend/backtest_engine.py
Pure Python class. No new external dependencies. Uses tiingo_client.py for historical prices.

class BacktestEngine:
    def run(self, config: BacktestConfig) -> BacktestResult:
        # Walk-forward: 2-year training windows, 3-month test windows, step 1 month
        # Signal source: analysis_history table (existing stored recommendations)
        # Entry rule: market open next day after recommendation
        # Exit rules: target hit | 15% stop loss | 90-day time decay | signal flip
        # Transaction costs: 0.1% per trade (commission + slippage)
        # Returns: walk_forward periods, equity curve, trade log, aggregate metrics

IMPORTANT: Cache historical prices in SQLite under namespace "price_history" to avoid
repeated Tiingo API calls. Check cache before fetching. If Tiingo rate limit hit,
abort the ticker gracefully (skip, do not corrupt results).

If analysis_history has fewer than 10 recommendations, return a BacktestResult with
status="insufficient_data" and empty arrays rather than producing meaningless metrics.

FILE 2: backend/routers/backtest.py
    POST /api/backtest/run
        Accepts BacktestConfig, launches BacktestEngine.run() in background thread
        (same pattern as run_analysis_job in backend/jobs.py)
        Returns { job_id: str }
    GET /api/backtest/result/{job_id}
        Returns BacktestResult with status field ("pending"|"running"|"complete"|"error")
    GET /api/backtest/history
        Returns list of past backtest run summaries from backtest_runs SQLite table

FILE 3: backend/routers/paper_trading.py
    GET  /api/paper-trading/positions → open positions + running metrics
    POST /api/paper-trading/positions → add position { ticker, entry_price, verdict, exit_conditions }
    PUT  /api/paper-trading/positions/{ticker}/close → { exit_price, exit_reason }
    GET  /api/paper-trading/history → closed trades + equity curve (cumulative P&L by date)
    GET  /api/paper-trading/metrics → Sharpe, Sortino, win rate, etc. from closed trades

SQLite tables (use _ensure_table() pattern from backend/routers/portfolio.py):
    paper_positions:
        ticker TEXT PRIMARY KEY, entry_price REAL, entry_date TEXT,
        current_price REAL, verdict TEXT, exit_conditions TEXT
    paper_trades:
        id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, entry_price REAL,
        entry_date TEXT, exit_price REAL, exit_date TEXT, pnl_pct REAL, exit_reason TEXT
    backtest_runs:
        id INTEGER PRIMARY KEY AUTOINCREMENT, run_at REAL, config_json TEXT, result_json TEXT

FILE 4: backend/main.py — mount both new routers
FILE 5: backend/schemas.py — add BacktestConfig, BacktestResult, WalkForwardPeriod,
         EquityPoint, TradeLogEntry, PaperPosition, PaperMetrics Pydantic models
```

#### Subagent task — frontend backtest + paper trading pages

```
Build the Backtest and Paper Trading frontend pages.

Read these existing files before starting:
    frontend/src/components/common/Card.tsx
    frontend/src/components/common/Badge.tsx
    frontend/src/components/charts/EquityCurveChart.tsx (from Phase 2)

FILE 1: frontend/src/components/charts/EquityCurveChart.tsx (if not created in Phase 2)
    Props: data: EquityPoint[], height?: number
    EquityPoint: { date: string, equity: number }
    Recharts AreaChart with gradient fill
    Color: equity going up = green fill, going down = red fill (check last value vs first)
    Show percentage return on Y axis (not dollar value)

FILE 2: frontend/src/components/backtest/BacktestConfigPanel.tsx
    Form fields: start date (date input), end date (date input), tickers (comma-separated text input)
    Run button: calls onSubmit(config)
    Disable Run if isRunning prop is true (show spinner)

FILE 3: frontend/src/components/backtest/BacktestMetricsPanel.tsx
    6-card grid: Sharpe, Sortino, Calmar, Max Drawdown, Win Rate, Hit Rate
    Null values display as "—"

FILE 4: frontend/src/components/backtest/WalkForwardTable.tsx
    Columns: Period, Train Sharpe, Test Sharpe, Train Win Rate, Test Win Rate, Delta (test-train)
    Delta column: green if positive, red if negative
    Use a plain HTML table styled with Tailwind (no external grid library)

FILE 5: frontend/src/components/backtest/TradeLogTable.tsx
    Columns: Date, Ticker, Entry, Exit, Return %, Exit Reason
    Client-side filter: text input filters by ticker
    Return % colored green/red
    Exit Reason as Badge (target_hit=green, stop_loss=red, time_decay=gray, signal_change=yellow)

FILE 6: frontend/src/components/paper-trading/OpenPositionsTable.tsx
    Columns: Ticker, Entry Price, Current Price, Unrealized P&L %, Days Held, Exit Conditions
    "Close Position" button per row → opens inline confirmation with exit price input

FILE 7: frontend/src/components/paper-trading/ClosedTradesTable.tsx
    Same columns as trade log + Exit Reason badge

FILE 8: frontend/src/components/paper-trading/PaperMetricsPanel.tsx
    Same 6 metrics as BacktestMetricsPanel, computed from closed trades history

FILE 9: frontend/src/hooks/useBacktest.ts
    State: isRunning, jobId, result, error
    run(config) → POST /api/backtest/run → starts polling GET /api/backtest/result/{id}
    Polls every 2 seconds while status is "pending" or "running"
    Stops polling on "complete" or "error"

FILE 10: frontend/src/hooks/usePaperTrading.ts
    Fetches positions on mount and after mutations
    Exposes: openPositions, closedTrades, metrics, addPosition, closePosition

FILE 11: frontend/src/pages/BacktestPage.tsx (replace shell from Phase 1)
    Layout: BacktestConfigPanel (top), EquityCurveChart + BacktestMetricsPanel (middle row),
            WalkForwardTable (below), TradeLogTable (bottom)
    All sections hidden until result.status === "complete"
    Loading: spinner + "Running backtest..." message while isRunning

FILE 12: frontend/src/pages/PaperTradingPage.tsx (replace shell from Phase 1)
    Layout: PaperMetricsPanel (top), EquityCurveChart (middle),
            OpenPositionsTable + ClosedTradesTable side by side (or stacked on smaller screens)
    "Add Position" button opens an inline form above the open positions table
```

---

## Risk Register

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| A1 | `TimesFMModel` singleton + `asyncio` — threading.Lock deadlocks in event loop | High | Batch job MUST stay synchronous. Never call `TimesFMModel.get()` inside the agent asyncio gather loop. Redis reads only at query time. |
| A2 | `timesfm_price` enrichment block near context budget ceiling | Medium | Block is ~400-600 chars. `trim_text()` trims last-listed keys first — TimesFM keys are last in each tuple, so they are dropped first under pressure. Acceptable since they are supplementary. |
| A3 | `timesfm[torch]` package size (~800MB) breaks CI/CD or Streamlit Cloud deploy | High | Keep as optional dep (`pip install -e ".[timesfm]"`). Never import at module top. The batch job runs separately from the web app. |
| A4 | Tiingo rate limits in batch | Medium | Cache historical prices in SQLite under `"price_history"` namespace. Abort gracefully per ticker. |
| B1 | `ResultView.tsx` TypeScript union widening causes compiler errors | Low | Audit all callers of the `activeTab` state before widening. Currently self-contained in `ResultView.tsx`. |
| B2 | `PortfolioPage` holdings form deleted | Medium | Keep add/remove holdings UI in `WatchlistPage` as collapsible section. Don't silently drop existing functionality. |
| B3 | `analysis_history` missing `entry_price` / `target_price` | Medium | Phase 2 chart renders gracefully with nulls. Show annotation markers without target lines. Add columns in a migration that runs at startup — do not block Phase 2 launch. |
| B4 | Backtest engine hits Tiingo rate limits on large universes | Medium | SQLite price history cache + graceful per-ticker abort. Display "insufficient data" status rather than corrupt metrics. |
| B5 | LWC v4 vs v5 API incompatibility | High | Run `npm info lightweight-charts version` before writing `PriceChart.tsx`. This plan documents v5 API only. |

---

## Implementation Order (Combined)

Start these in parallel on day one:
- **A-Phase 7:** Docker Compose Redis service (30 min)
- **A-Phase 1:** model.py + cache.py + config.py fields (half day — most time is checkpoint download)
- **B-Phase 1 backend:** Three new routers (1 day)

After A-Phase 1:
- **A-Phase 2+3:** signals.py + enrichment.py (2-3 hrs)
- **B-Phase 1 frontend:** WatchlistPage, shell pages, routes, nav (1-2 days)

After signals + routes:
- **A-Phase 4+5:** batch.py + scheduler script (half day)
- **B-Phase 2:** PriceChart, sparklines, deep dive completion (2-3 days)

After batch job running:
- **A-Phase 6:** 5-file agent integration (1-2 hrs)
- **B-Phase 3:** Backtest engine + paper trading (2-3 days)

Final:
- **A-Phase 8:** Unit tests
- End-to-end smoke test (batch → Redis → agent run → frontend chart)

---

## Verification Checklist

### Track A — end-to-end smoke test

```bash
# 1. Start Redis
docker compose up redis -d && redis-cli ping  # → PONG

# 2. Run batch for one ticker (requires timesfm installed and API keys set)
ENABLE_TIMESFM=true \
TIINGO_API_KEY=<key> FMP_API_KEY=<key> \
REDIS_URL=redis://localhost:6379/0 \
TIMESFM_BATCH_TICKERS=AAPL \
python scripts/run_timesfm_batch.py --run-now

# 3. Confirm Redis keys
redis-cli KEYS "timesfm:AAPL:*"                         # shows price_forecast + eps_forecast
redis-cli TTL "timesfm:AAPL:price_forecast"             # ≈ 86400
redis-cli GET "timesfm:AAPL:price_forecast" | python -m json.tool

# 4. Run analyst pipeline — TimesFM sections should appear in agent context
ENABLE_TIMESFM=true REDIS_URL=redis://localhost:6379/0 python main.py AAPL
# → PatternAgent, RiskAgent, MacroAgent get "=== TimesFM Price Forecast (AAPL) ==="
# → DCFAgent gets "=== TimesFM EPS Forecast (AAPL) ==="

# 5. Run with ENABLE_TIMESFM=false — must be identical to pre-expansion behavior
python main.py AAPL
```

### Track B — end-to-end

```bash
cd frontend && npm run dev

# /portfolio     → watchlist grid with sparklines, status dots, metrics
# /stock/AAPL   → deep dive with "Price History & Targets" tab
#                → tab shows TradingView candle chart
#                → hover over chart → crosshair + price/date tooltip appears
#                → annotation markers at recommendation dates (if analysis_history has data)
# /backtest      → config form, run backtest, equity curve + metrics render
# /paper-trading → add position, positions table, close position, metrics
# /analysis      → existing analysis flow completely unchanged
```

---

## Related Plan Documents

| File | Contents |
|---|---|
| `FMP_EXPANSION_PLAN.md` | 7 additional FMP data sources (Phase 1a–5, not yet implemented) |
| `MARKET_DATA_PLAN.md` | Yahoo → Tiingo/FMP migration |
| `WAREHOUSE_PLAN.md` | Warehouse schema expansion |
| `RAG_FRESHNESS_PLAN.md` | RAG index refresh strategy |

The TimesFM batch job uses the same `TiingoClient` and `FMPClient` as the FMP expansion plan. Coordinate API call budgets — the FMP free tier allows 250 req/day. After all FMP expansion phases, a full analysis run costs ~21 calls. The TimesFM batch costs ~2 additional calls per ticker per day (EPS + price). For a 50-ticker watchlist, that is 100 additional FMP calls/day — within budget but worth monitoring.
