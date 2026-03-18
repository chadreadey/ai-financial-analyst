# AI Financial Analyst — Platform Expansion Plan

## Context

The system is a production-grade 6-agent equity research platform. It ingests SEC EDGAR data
(XBRL + 10-K text), enriches with Yahoo Finance and Tavily web search, runs 5-6 specialist AI
agents in parallel, and synthesizes them into an investment brief. The goal of this expansion is
to improve data depth, analytical sophistication, and platform breadth across three categories:
(1) better/new data sources, (2) richer quantitative analysis, and (3) new agents and workflows.

All changes follow the existing architecture patterns:
- New data sources → new enrichment sections in `market_enrichment.py` or a new module
- New agents → new file in `agents/`, new prompt in `prompts/`, wired into `orchestrator.py`
- New libraries → added to `requirements.txt`
- All features behind env var feature flags (ENABLE_* pattern)
- Context trimmed via existing `trim_context()` / character-budget system

---

## Phase 1: Data Layer Upgrades

### 1A — Migrate SEC Parsing to edgartools

**Why:** `sec/filing_parser.py` uses fragile BeautifulSoup + regex to extract 10-K sections.
`sec/xbrl_parser.py` is a large custom parser. edgartools handles both cleanly with a proper
object model and gives access to Form 4 (insider transactions), 8-K exhibits (earnings call
transcripts), and more filing types for free.

**Files affected:**
- `sec/filing_parser.py` → replace with edgartools calls
- `sec/xbrl_parser.py` → incrementally supplement with edgartools financials objects
- `sec/client.py` → keep caching layer; swap underlying fetch methods
- `requirements.txt` → add `edgartools>=2.0`

**Implementation pattern:**
```python
from edgar import Company

company = Company("AAPL")
filing = company.get_filings(form="10-K").latest()

# Section extraction (replaces filing_parser.py regex)
obj = filing.obj()
mda_text    = obj.mda          # Management Discussion & Analysis
risks_text  = obj.risk_factors # Risk Factors
biz_text    = obj.business     # Business Description

# Financials (replaces xbrl_parser.py partially)
financials = company.get_financials()
income_df   = financials.income_statement
balance_df  = financials.balance_sheet
cashflow_df = financials.cash_flow_statement
```

**Migration strategy:**
1. Replace `sec/filing_parser.py` first (isolated, no downstream API changes)
2. Add edgartools financial objects as a *parallel path* alongside existing XBRL parser
3. Use edgartools data to fill gaps (segment data, geographic breakdowns) that current parser misses
4. Keep the SQLite cache layer — wrap edgartools calls the same way as current SEC API calls

**New data unlocked:**
- Revenue segment breakdown (business units, geographic)
- Proper object-model access to all filing sections
- Form 4 insider transactions (needed for Phase 3 Insider Agent)
- 8-K exhibit text (earnings call transcripts)

---

### 1B — FRED API for Macro Data

**Why:** Yahoo Finance macro data (yields, indices) is informal and prone to breakage.
FRED (Federal Reserve Economic Data) is the authoritative, free, stable source for macro
indicators. No API key required for most endpoints; optional key for higher rate limits.

**Files affected:**
- `market_enrichment.py` → add `fetch_fred_macro()` function
- `requirements.txt` → add `fredapi>=0.5`

**Key series to pull:**

| Series ID        | Description                       |
|------------------|-----------------------------------|
| DGS10            | 10-Year Treasury Yield            |
| DGS2             | 2-Year Treasury Yield             |
| FEDFUNDS         | Fed Funds Rate                    |
| CPIAUCSL         | CPI (inflation)                   |
| UNRATE           | Unemployment Rate                 |
| BAMLH0A0HYM2     | High Yield Credit Spread          |
| BAMLC0A0CM       | Investment Grade Credit Spread    |
| UMCSENT          | Consumer Sentiment (UMich)        |
| ISM              | ISM Manufacturing PMI             |

**Integration:**
- Replace `macro_data` enrichment section with FRED data
- Macro Agent gets far richer, more reliable inputs
- Free, no rate limit issues at normal usage

**Environment variables:**
```bash
ENABLE_FRED=true
FRED_API_KEY=your_key_here   # optional but raises rate limits
```

---

### 1C — n8n RAG Pipeline (Newsletter / Research Ingestion)

**Why:** Agents currently lack curated analyst sentiment, buy-side color, and real-time
narrative context. A RAG layer gives them targeted, high-quality qualitative signal that
Tavily's generic web search cannot provide.

**Architecture:**

```
[RSS Feeds / Newsletter webhooks]
         ↓
    [n8n Workflow]
    ├── Fetch & deduplicate articles
    ├── Chunk text (512 tokens, 50-token overlap)
    ├── Embed via text-embedding-3-small
    └── Upsert into Qdrant vector DB (keyed by ticker + date)
         ↓
[rag_enrichment.py] — new module
    ├── query_rag(ticker, query, top_k=5) → ranked chunks
    └── format_rag_section(chunks) → enrichment text block
         ↓
[market_enrichment.py] — call rag_enrichment
    └── adds "rag_research" section to enrichment_sections dict
         ↓
[agents/*.py] — add "rag_research" to enrichment_sections tuple
```

**Recommended data sources (free/accessible):**
- Substack RSS feeds (analyst newsletters with public feeds)
- Yahoo Finance RSS (per-ticker news feed)
- SEC EDGAR full-text search API (EFTS — search all filings for keywords)
- Motley Fool / Seeking Alpha article RSS (public articles only)
- Google News RSS (per-ticker query)

**SeekingAlpha note:** Their API requires a paid plan and scraping violates their ToS.
Use their public RSS feed (limited) or substitute with Substack newsletters and EDGAR EFTS.

**New files to create:**
- `rag_enrichment.py` — Qdrant client, query function, formatter
- `n8n/` directory — workflow JSON exports for documentation

**Files modified:**
- `market_enrichment.py` — call `rag_enrichment.fetch_rag_section(ticker)`
- `agents/*.py` — add `"rag_research"` to each agent's `enrichment_sections` tuple
- `requirements.txt` — add `qdrant-client>=1.7`

**Environment variables:**
```bash
ENABLE_RAG=true
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=financial_research
RAG_TOP_K=5
RAG_MAX_CHARS=2000
OPENAI_EMBED_KEY=sk-...   # for text-embedding-3-small
```

**Context budget:** Add `MAX_RAG_SECTION_CHARS=2000` to the existing budget system.

---

## Phase 2: Quantitative Analysis Upgrades

### 2A — quantstats Integration (Pattern Agent)

**Why:** The Pattern agent currently analyzes trends qualitatively. quantstats computes
proper risk-adjusted return metrics from price history and generates tear sheets.
(Note: pyfolio is archived/deprecated since Quantopian shut down — use quantstats instead.)

**Files affected:**
- `agents/pattern.py` → add `compute_quantstats_metrics()` helper
- `market_enrichment.py` → pass raw price Series (already fetched from yfinance)
- `requirements.txt` → add `quantstats>=0.0.62`

**Metrics to extract and inject into Pattern agent context:**
- Sharpe ratio, Sortino ratio, Calmar ratio
- Max drawdown, average drawdown duration
- Rolling 30/90-day Sharpe
- Value at Risk (95%, 99%)
- Skewness, kurtosis of returns
- Best/worst month, quarterly return profile

**Implementation pattern:**
```python
import quantstats as qs

def compute_quantstats_metrics(price_series: pd.Series) -> dict:
    returns = price_series.pct_change().dropna()
    return {
        "sharpe":       qs.stats.sharpe(returns),
        "sortino":      qs.stats.sortino(returns),
        "max_drawdown": qs.stats.max_drawdown(returns),
        "calmar":       qs.stats.calmar(returns),
        "var_95":       qs.stats.value_at_risk(returns),
        "skew":         qs.stats.skew(returns),
        "kurtosis":     qs.stats.kurtosis(returns),
    }
```

**Context injection:** Format as a "QUANTITATIVE RISK METRICS" block appended to Pattern
agent's `build_context()` output. Guarded by `ENABLE_QUANTSTATS=true`.

---

### 2B — pmdarima ARIMA Forecasting (Pattern Agent)

**Why:** Pattern agent currently describes historical trends. ARIMA adds statistically
grounded forward projections with confidence intervals for revenue, operating income, and FCF.

**Files affected:**
- `agents/pattern.py` → add `forecast_series()` function
- `sec/xbrl_parser.py` → expose raw annual revenue/income lists (already computed internally)
- `requirements.txt` → add `pmdarima>=2.0`

**Implementation pattern:**
```python
from pmdarima import auto_arima

def forecast_series(values: list[float], periods: int = 3) -> dict:
    model = auto_arima(values, seasonal=False, suppress_warnings=True)
    forecast, conf_int = model.predict(n_periods=periods, return_conf_int=True)
    return {
        "forecast":  forecast.tolist(),
        "lower_95":  conf_int[:, 0].tolist(),
        "upper_95":  conf_int[:, 1].tolist(),
        "aic":       model.aic(),
    }
```

**Context injection:** Add a "STATISTICAL FORECAST (ARIMA)" block to Pattern agent context
showing 3-year forward projections for revenue and FCF with confidence bands.
Guarded by `ENABLE_ARIMA=true`.

---

### 2C — QuantLib (DCF Agent — Yield Curve & WACC)

**Why:** DCF agent currently estimates discount rates heuristically. QuantLib enables proper
risk-free rate derivation from the Treasury yield curve and correct present value of debt.

**Scope: Narrow. Two functions only:**
1. `get_risk_free_rate(maturity_years)` — bootstrap from Treasury yields (FRED data from 1B)
2. `pv_of_debt(coupon, face, maturity, yield_to_maturity)` — proper bond math for net debt calc

**New file:** `quant/discount_rate.py` — QuantLib wrappers (keep isolated from agents/)

**Files affected:**
- `agents/dcf.py` → call QuantLib helpers for WACC inputs
- `quant/discount_rate.py` → new QuantLib wrapper module
- `requirements.txt` → add `QuantLib>=1.31`

**Note:** QuantLib is a large C++ dependency. Keep scope narrow. Complete FRED integration
(1B) first — the yield curve data it provides is the input QuantLib needs.

**Environment variables:**
```bash
ENABLE_QUANTLIB=true
```

---

## Phase 3: New Agents

### 3A — Insider Transactions Agent (Form 4)

**Why:** Insider buying is one of the most statistically reliable long-run price signals.
edgartools makes Form 4 parsing straightforward once Phase 1A is complete.

**New files:**
- `agents/insider.py` — Insider Transactions Analyst
- `prompts/insider.md` — Joel Greenblatt / insider-signal persona

**Data source:** SEC Form 4 via edgartools:
```python
from edgar import Company
filings = Company(ticker).get_filings(form="4").latest(20)
```

**Analysis output:**
- Net insider sentiment: BUY / NEUTRAL / SELL
- Rolling 90-day / 6-month insider buy/sell volume and dollar value
- Notable individual transactions (CEO, CFO, large block purchases)
- Cluster buying detection (3+ insiders buying within a 30-day window)

**Integration:**
- Add `InsiderAgent` to `orchestrator.py` Phase 1 pool
- Update `prompts/synthesis.md` to reference insider signal
- Guarded by `ENABLE_INSIDER_AGENT=true`

**Dependency:** Phase 1A (edgartools) must be complete first.

---

### 3B — Earnings Call Transcript Agent

**Why:** Management tone, guidance language, and Q&A dynamics contain signals that no
financial statement captures. 8-K filings include earnings call transcripts as exhibits.

**New files:**
- `agents/transcript.py` — Earnings Call Analyst
- `prompts/transcript.md` — communication analyst persona

**Data source:** edgartools 8-K exhibit extraction:
```python
filing = Company(ticker).get_filings(form="8-K").latest()
transcript_text = filing.exhibit("EX-99.1").text()
```

**Analysis focus:**
- Management confidence vs. hedging language in forward guidance
- Analyst Q&A tone (pushback, probing questions on guidance)
- Delta analysis vs. prior call language
- Key themes: pricing power, demand outlook, cost pressure, hiring pace

**Output:** POSITIVE / CAUTIOUS / NEGATIVE sentiment + key quote extracts.

**Integration:** Same wiring pattern as Insider Agent.
Guarded by `ENABLE_TRANSCRIPT_AGENT=true`.

**Dependency:** Phase 1A (edgartools) must be complete first.

---

## Phase 4: Platform Breadth

### 4A — Multi-Ticker Portfolio Scanner

**Why:** Analysts and PMs need to screen a basket of stocks, not just analyze one at a time.
The existing asyncio architecture already supports this with minimal structural changes.

**New files:**
- `scanner.py` — CLI entry point for batch analysis
- New tab in `app.py` — Streamlit scanner UI

**CLI usage:**
```bash
python scanner.py AAPL MSFT GOOGL NVDA META --output scanner_report.csv
```

**Implementation approach:**
- Run `Orchestrator` for each ticker concurrently behind an `asyncio.Semaphore(3)` to
  rate-limit concurrent LLM calls
- Parse synthesis output to extract verdict + health scores for each ticker
- Produce ranked table: ticker, verdict, composite score, top risk, top catalyst
- Output: CSV table + PDF summary

---

### 4B — Analysis History & Drift Tracking

**Why:** Trend across analyses is more powerful than any single snapshot. A STRONG BUY
degrading to HOLD over three quarters is a high-signal event.

**Schema addition to `.sec_cache.db`:**
```sql
CREATE TABLE analysis_history (
    ticker          TEXT NOT NULL,
    run_at          REAL NOT NULL,   -- unix timestamp
    verdict         TEXT,
    composite_score REAL,
    health_scores   TEXT,            -- JSON blob of 6 dimension scores
    PRIMARY KEY (ticker, run_at)
);
```

**Files affected:**
- `orchestrator.py` → write verdict + scores to history table after each run
- `report.py` → read history, include delta section ("vs. last analysis") in report
- `app.py` → history sparkline chart in Streamlit sidebar per ticker

---

### 4C — AKShare (China/HK Coverage)

**Why:** For Chinese ADRs and HK-listed companies (BABA, JD, NIO, etc.) yfinance data
is unreliable. AKShare has native SZSE/SSE data.

**Scope:** Supplement only. Do NOT replace yfinance. Activate when ticker is detected as
China-listed (`.HK` suffix, `HKG` exchange, or known ADR list).

**Files affected:**
- `market_enrichment.py` → add `fetch_akshare_data(ticker)` fallback branch
- `requirements.txt` → add `akshare>=1.10`

**Guarded by:** `ENABLE_AKSHARE=true`

---

## Implementation Order

| # | Item                                    | Phase | Effort | Dependency    |
|---|-----------------------------------------|-------|--------|---------------|
| 1 | FRED API macro data                     | 1B    | Low    | None          |
| 2 | edgartools — filing_parser migration    | 1A    | Medium | None          |
| 3 | edgartools — XBRL supplement + Form 4   | 1A    | Medium | Step 2        |
| 4 | quantstats (Pattern agent)              | 2A    | Low    | None          |
| 5 | pmdarima ARIMA (Pattern agent)          | 2B    | Medium | None          |
| 6 | Insider Transactions Agent              | 3A    | Medium | Step 3        |
| 7 | Earnings Call Transcript Agent          | 3B    | Medium | Step 3        |
| 8 | Multi-ticker scanner                    | 4A    | Medium | None          |
| 9 | Analysis history & drift tracking       | 4B    | Low    | None          |
| 10| n8n RAG pipeline (Qdrant)               | 1C    | High   | None (async)  |
| 11| QuantLib WACC helpers                   | 2C    | High   | Step 1 (FRED) |
| 12| AKShare China/HK coverage               | 4C    | Low    | None          |

---

## New Files to Create

| File                        | Purpose                                      |
|-----------------------------|----------------------------------------------|
| `rag_enrichment.py`         | Qdrant client, query, and formatter          |
| `quant/discount_rate.py`    | QuantLib wrappers for WACC / yield curve     |
| `agents/insider.py`         | Insider Transactions Analyst agent           |
| `agents/transcript.py`      | Earnings Call Transcript Analyst agent       |
| `prompts/insider.md`        | Insider agent system prompt                  |
| `prompts/transcript.md`     | Transcript agent system prompt               |
| `scanner.py`                | Multi-ticker CLI scanner entry point         |
| `n8n/`                      | n8n workflow JSON exports (docs/reference)   |

---

## Files to Modify

| File                    | Change                                                         |
|-------------------------|----------------------------------------------------------------|
| `sec/filing_parser.py`  | Replace BeautifulSoup/regex with edgartools section extraction |
| `sec/xbrl_parser.py`    | Supplement with edgartools financials objects                  |
| `sec/client.py`         | Wrap edgartools calls in existing SQLite cache layer           |
| `market_enrichment.py`  | Add FRED, RAG, AKShare enrichment functions                    |
| `agents/pattern.py`     | Add quantstats metrics block + ARIMA forecast block            |
| `agents/dcf.py`         | Add QuantLib WACC helpers                                      |
| `orchestrator.py`       | Wire new agents; write to analysis_history table               |
| `report.py`             | Include delta-vs-history section in output                     |
| `app.py`                | Scanner tab; history sparkline chart                           |
| `prompts/synthesis.md`  | Reference insider + transcript agent signals                   |
| `requirements.txt`      | Add all new library dependencies                               |

---

## New Environment Variables

```bash
# Phase 1B — FRED
ENABLE_FRED=true
FRED_API_KEY=optional_but_recommended

# Phase 1C — RAG
ENABLE_RAG=true
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=financial_research
RAG_TOP_K=5
RAG_MAX_CHARS=2000
OPENAI_EMBED_KEY=sk-...

# Phase 2A — quantstats
ENABLE_QUANTSTATS=true

# Phase 2B — ARIMA
ENABLE_ARIMA=true

# Phase 2C — QuantLib
ENABLE_QUANTLIB=true

# Phase 3A — Insider Agent
ENABLE_INSIDER_AGENT=true

# Phase 3B — Transcript Agent
ENABLE_TRANSCRIPT_AGENT=true

# Phase 4C — AKShare
ENABLE_AKSHARE=true
```

---

## Verification Checklist

After each phase, run:

1. `python main.py AAPL --inspect-context` — verify new enrichment sections appear in context
2. `python main.py AAPL` — verify no regressions; new sections appear in report output
3. `python main.py AAPL --provider anthropic` — verify synthesis references new agents
4. `python scanner.py AAPL MSFT GOOGL` — verify ranked table output (after Phase 4A)
5. Check `.sec_cache.db` for `analysis_history` table entries (after Phase 4B)
