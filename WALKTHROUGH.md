# AI Financial Analyst — Full Codebase Walkthrough

This document explains the current codebase end-to-end so you can understand, modify, or extend it with minimal ambiguity.

---

## 1) What this project does

This is a multi-agent equity research system with both a CLI and a Streamlit web UI.

Input: a stock ticker (e.g. `AAPL`).
Output: a full research report composed of:

- 5 parallel analyst outputs (DCF, Risk, Earnings, Competitive, Pattern)
- 1 synthesized executive brief with health scores, rating, and verdict
- Downloadable PDF report

Primary data sources:

- SEC EDGAR filings (`10-K`, `10-Q`, `8-K`) and XBRL structured financials
- Optional: Yahoo Finance live market data via `yfinance`
- Optional: Tavily web research (company/industry/risk queries)

---

## 2) Repository map and responsibilities

```
ai-financial-analyst/
├── app.py                # Streamlit web UI entry point
├── main.py               # CLI entry point
├── orchestrator.py        # Two-phase pipeline: parallel agents → synthesis
├── report.py              # Text + PDF report formatting
├── utils.py               # Shared helpers (env_flag, format_money)
├── context_budget.py      # Deterministic text trimming for context windows
├── prompt_loader.py       # Loads markdown prompts, replaces [TICKER] etc.
├── market_enrichment.py   # Optional Yahoo + Tavily enrichment layer
├── requirements.txt       # Python dependencies
├── .env.example           # Environment variable template
├── .streamlit/
│   ├── config.toml        # Streamlit server config
│   └── secrets.toml.example
├── prompts/               # Externalized agent + synthesis prompts
│   ├── dcf.md
│   ├── risk.md
│   ├── earnings.md
│   ├── competitive.md
│   ├── pattern.md
│   └── synthesis.md
├── llm/
│   ├── __init__.py
│   └── providers.py       # LLM provider abstraction (Anthropic / OpenAI)
├── agents/
│   ├── base.py            # BaseAgent class (context building, trimming, LLM call)
│   ├── dcf.py             # DCF Analyst (Morgan Stanley style)
│   ├── risk.py            # Risk Analyst (Bridgewater style)
│   ├── earnings.py        # Earnings Analyst (JPMorgan style)
│   ├── competitive.py     # Competitive & Sector Analyst (Bain style)
│   └── pattern.py         # Pattern Analyst (Renaissance Tech style)
└── sec/
    ├── client.py          # SEC EDGAR API client (rate-limited, cached)
    ├── xbrl_parser.py     # XBRL JSON → DataFrames + computed metrics
    └── cache.py           # SQLite cache with TTL expiration
```

---

## 3) Runtime prerequisites and configuration

### 3.1 Python and packages

Install from `requirements.txt`:

- `streamlit` — web UI
- `anthropic` — Anthropic Claude SDK
- `openai` — OpenAI SDK (also used for OpenAI-compatible endpoints)
- `python-dotenv` — `.env` loading
- `pandas` — financial data manipulation
- `requests` — SEC API calls
- `yfinance` — Yahoo Finance market data (optional)
- `tavily-python` — Tavily search API (optional)
- `fpdf2` — PDF generation

### 3.2 Environment variables

Copy `.env.example` to `.env` and configure:

- `LLM_PROVIDER` — `anthropic` (default) or `openai`
- `ANTHROPIC_API_KEY` — required for Anthropic mode
- `OPENAI_API_KEY` — required for OpenAI mode
- `OPENAI_BASE_URL` — defaults to Columbia CBS endpoint
- `ENABLE_YAHOO` — `true`/`false` (default: `true`)
- `ENABLE_TAVILY` — `true`/`false` (default: `true`)
- `TAVILY_API_KEY` — required if Tavily is enabled

Context budget env vars (all optional, have sensible defaults):

- `MAX_AGENT_CONTEXT_CHARS` (default: 7000)
- `MAX_AGENT_OUTPUT_TOKENS` (default: 1200)
- `SYNTHESIS_REPORT_MAX_CHARS` (default: 3200)
- `SYNTHESIS_INPUT_MAX_CHARS` (default: 14000)
- `MAX_SYNTHESIS_OUTPUT_TOKENS` (default: 1500)
- Per-agent overrides: `MAX_CONTEXT_DCF_CHARS`, `MAX_CONTEXT_RISK_CHARS`, etc.

### 3.3 SEC API

The SEC EDGAR API is free and requires no API key. It does require a descriptive `User-Agent` header (handled by `SECClient`). Rate limit: 10 requests/second (client throttles to ~8/s).

---

## 4) End-to-end execution flow

This section traces what happens when the user runs `python main.py AAPL` or clicks **Run Analysis** in the Streamlit UI.

### Step 1: Entry point

**CLI** (`main.py`): Parses args, creates `SECCache` + `SECClient` + `Orchestrator`, calls `orchestrator.run(ticker)`.

**Streamlit** (`app.py`): Renders sidebar config (provider, enrichment toggles, budget sliders), then calls `orchestrator.prepare_data()` → `run_phase1()` → `run_phase2()` with progress updates.

Both paths converge on the same `Orchestrator` class.

### Step 2: Data preparation (`orchestrator.prepare_data`)

1. **Ticker resolution** (`sec/client.py`): Maps ticker to CIK via SEC's `company_tickers.json`. Result is cached for 7 days.
2. **Fetch SEC data** (`sec/client.py`): Pulls recent filings list and full XBRL company facts JSON. Both are cached in SQLite.
3. **Parse XBRL** (`sec/xbrl_parser.py`): Extracts income statement, balance sheet, and cash flow concepts from raw XBRL. Computes derived metrics (margins, ratios, FCF, growth rates). Produces a human-readable financial summary string.
4. **Build enrichment** (`market_enrichment.py`): Optionally fetches Yahoo Finance market snapshot and runs Tavily search queries (company analysis, industry overview, risk/bear case). Each section is trimmed to a character budget. Failures are recorded as warnings and do not block the pipeline.
5. **Assemble data dict**: Combines `financial_core_summary` (SEC-only), `financial_summary` (SEC + enrichment), `metrics`, `historical_revenue`, `historical_net_income`, `recent_filings`, and enrichment metadata into a single dict passed to all agents.

### Step 3: Phase 1 — Parallel agent execution (`orchestrator.run_phase1`)

1. Five agent instances are created in `Orchestrator.__init__`, each receiving the same LLM provider and model.
2. Each agent's `analyze()` method:
   - Calls `build_context(data)` to select the relevant data slice for its specialty
   - Calls `trim_context()` to enforce the per-agent character cap
   - Loads its system prompt from `prompts/*.md` (falls back to inline string if file is missing)
   - Calls `provider.generate()` with the system prompt + trimmed context
3. All five agents run concurrently via `asyncio.gather()`.
4. Returns a list of `(agent_name, analysis_text)` tuples.

### Step 4: Phase 2 — Synthesis (`orchestrator.run_phase2`)

1. Each agent report is trimmed to `SYNTHESIS_REPORT_MAX_CHARS` (default 3200).
2. All reports are concatenated and trimmed to `SYNTHESIS_INPUT_MAX_CHARS` (default 14000).
3. The synthesis prompt is loaded from `prompts/synthesis.md` with `[COMPANY NAME]` and `[TICKER]` replaced.
4. The LLM is called with the synthesis system prompt + all agent reports as user content.
5. Returns the final executive brief string.

### Step 5: Output

**CLI**: `report.format_report()` renders a text report. Optionally saved to `reports/` directory.

**Streamlit**: Synthesis is rendered as markdown. Agent reports appear in tabs. PDF is built via `report.build_pdf_report()` and offered as a download button. Reports are also saved to `reports/` for the cached report viewer.

---

## 5) Module-level technical details

### 5.1 `sec/client.py` — SEC EDGAR API client

- `resolve_ticker(ticker)` → `{cik, cik_padded, name}`. Raises `ValueError` for unknown tickers.
- `get_submissions(ticker)` → full filing history JSON.
- `get_recent_filings(ticker, form_types, limit)` → list of filing dicts with `form`, `filingDate`, `accessionNumber`, `primaryDocument`.
- `get_company_facts(ticker)` → raw XBRL company facts JSON.
- `fetch_all_data(ticker)` → convenience method combining the above.
- Rate limiting: enforces 120ms minimum between requests (~8 req/s).
- All responses cached in SQLite via `SECCache` (default TTL: 24 hours, ticker map: 7 days).

### 5.2 `sec/xbrl_parser.py` — XBRL data extraction

- Extracts ~25 US-GAAP concepts across income statement, balance sheet, and cash flow.
- `_extract_concept()` handles unit filtering (USD, shares, USD/shares), form filtering (10-K vs 10-Q), and duration filtering (annual vs quarterly periods).
- `compute_metrics()` → dict of derived metrics: margins, ratios, FCF, EPS, revenue growth.
- `to_summary_text(metrics)` → formatted text block for LLM prompts. Accepts pre-computed metrics to avoid redundant computation.
- `get_historical_revenue(years)` / `get_historical_net_income(years)` → lists of `{period_end, fiscal_year, value}` dicts for trend analysis.

### 5.3 `sec/cache.py` — SQLite caching

- Keyed by `(namespace, key)` with TTL-based expiration.
- Uses WAL journal mode for concurrent read safety.
- Stored at `.sec_cache.db` (gitignored).

### 5.4 `llm/providers.py` — LLM provider abstraction

- `LLMProvider` abstract base: defines `async generate(system, user, model, max_tokens) → str`.
- `AnthropicProvider`: wraps `AsyncAnthropic`. Default model: `claude-sonnet-4-20250514`.
- `OpenAIProvider`: wraps `AsyncOpenAI`. Default model: `gpt-4o-mini`. Default base URL: Columbia CBS endpoint. Tries the Responses API first, falls back to Chat Completions for compatible providers.
- `get_provider(name)` → factory function. Reads `LLM_PROVIDER` env var if no name given.

### 5.5 `agents/base.py` — Base agent

- `build_context(data)` → assembles user-message context from `financial_core_summary` + recent filings + targeted enrichment sections.
- `get_system_prompt(data)` → loads from `prompts/*.md` if the file exists, otherwise uses the inline `system_prompt` string.
- `trim_context(context)` → applies `trim_text()` to enforce per-agent character budget.
- `append_enrichment_sections(parts, data)` → appends only the enrichment keys declared in `self.enrichment_sections`.
- `analyze(data)` → trims context, loads prompt, calls LLM provider.

Each subclass overrides `build_context()` to select the specific metrics and historical data relevant to its specialty, and sets `enrichment_sections` to declare which external data sections it needs.

### 5.6 Agent subclasses

| Agent | Key context selections | Enrichment sections |
|---|---|---|
| DCF (`dcf.py`) | Revenue/income history, FCF/debt/equity metrics | `market_data`, `external_company` |
| Risk (`risk.py`) | Balance sheet metrics, net income history | `market_data`, `external_risks` |
| Earnings (`earnings.py`) | Revenue/income history, margin/EPS metrics | `market_data`, `external_company` |
| Competitive (`competitive.py`) | Revenue history, margin metrics, recent filings | `external_company`, `external_industry` |
| Pattern (`pattern.py`) | Full revenue/income history, all metrics | `market_data` |

### 5.7 `orchestrator.py` — Pipeline coordinator

- `prepare_data(ticker)` — synchronous data fetch + parse + enrichment.
- `run_phase1(data)` — async parallel agent execution.
- `run_phase2(ticker, company_name, agent_reports)` — synthesis with context trimming.
- `run(ticker)` — convenience method that chains all three steps.

### 5.8 `market_enrichment.py` — Optional enrichment

- Yahoo Finance: live price, market cap, P/E, P/S, EV/EBITDA, 52-week range, beta.
- Tavily: three search queries (company analysis, industry overview, risk/bear case), each returning up to `TAVILY_MAX_RESULTS` results with trimmed snippets.
- Entirely fail-safe: disabled providers or network errors produce warnings, not crashes.

### 5.9 `report.py` — Output formatting

- `clean_generated_text()` — normalizes LLM artifacts (spaced-out letters, excess whitespace, Unicode issues).
- `format_report()` → plain text investment brief.
- `build_pdf_report()` → PDF bytes with section formatting, markdown-aware rendering, and Latin-1 safe encoding.
- `save_report()` / `save_pdf_report()` — persist to `reports/` directory.
- `list_cached_reports()` — returns recent `.txt` reports sorted by modification time (used by Streamlit cached report viewer).
- `streamlit_markdown_text()` — escapes `$` signs so dollar amounts don't render as LaTeX.

### 5.10 `context_budget.py` — Text trimming

- `trim_text(text, max_chars, marker)` — deterministic truncation with a visible `[trimmed]` marker. Used throughout to enforce context window budgets.

### 5.11 `prompt_loader.py` — Prompt loading

- `load_prompt_file(path)` — reads a UTF-8 markdown file.
- `render_prompt(template, data)` — replaces `[COMPANY NAME]`, `[STOCK NAME]`, `[TICKER]` tokens.

### 5.12 `utils.py` — Shared helpers

- `env_flag(name, default)` — reads a boolean from an env var (`true`/`1`/`yes`/`on`).
- `format_money(value, abbreviate)` — formats numbers as `$1.23T`, `$4.56B`, `$7.8M`, or `$1,234`.

---

## 6) Prompt system (`prompts/`)

Each agent has a corresponding markdown prompt file:

| File | Agent | Key instructions |
|---|---|---|
| `dcf.md` | DCF Analyst | Revenue projection, FCF, WACC, terminal value, fair value, BUY/HOLD/SELL |
| `risk.md` | Risk Analyst | Balance sheet risk, earnings quality, macro sensitivity, tail scenarios, 1-10 risk scores |
| `earnings.md` | Earnings Analyst | EPS trajectory, margins, cash conversion, forward outlook, STRONG/STABLE/DETERIORATING/WEAK |
| `competitive.md` | Competitive Analyst | Market position, moat analysis, sector dynamics, Porter's Five Forces, DOMINANT/STRONG/AVERAGE/WEAK |
| `pattern.md` | Pattern Analyst | Trend analysis, mean reversion, statistical anomalies, ratio dynamics, GROWTH/CYCLICAL/MEAN-REVERTING/DETERIORATING |
| `synthesis.md` | CIO Synthesis | Cross-reference all 5 reports, top 3 risks + catalysts, STRONG BUY→STRONG SELL rating, 1-10 health scores |

Prompts support `[COMPANY NAME]`, `[STOCK NAME]`, and `[TICKER]` placeholders which are replaced at runtime. If a prompt file is missing, agents fall back to their inline `system_prompt` string.

---

## 7) Concurrency model

- **Agent execution**: 5 agents run concurrently via `asyncio.gather()`. All share the same provider instance (async-safe).
- **Data fetch**: SEC API calls are synchronous and sequential (rate-limited). They complete before agents start.
- **Enrichment**: Yahoo and Tavily calls are synchronous, run during data preparation.

---

## 8) Data contracts and key structures

### 8.1 Orchestrator data dict

Produced by `prepare_data()`, consumed by all agents:

```python
{
    "ticker": "AAPL",
    "company_name": "Apple Inc",
    "financial_core_summary": "=== Financial Summary ... ===",  # SEC-only text
    "financial_summary": "...",  # SEC text + enrichment text (used by base agent)
    "metrics": {"revenue": 394328000000, "net_margin": 0.2639, ...},
    "recent_filings": [{"form": "10-K", "filingDate": "2025-11-01", ...}],
    "historical_revenue": [{"period_end": "2025-09-27", "fiscal_year": 2025, "revenue": 394328000000}],
    "historical_net_income": [...],
    "enrichment_sections": {"market_data": "...", "external_company": "...", ...},
    "enrichment_warnings": ["Yahoo enrichment unavailable: ..."],
    "enrichment_sources": ["Article Title - https://..."],
    "enrichment_filter_stats": {"company_kept": 3, ...},
}
```

### 8.2 Agent reports

List of `(agent_name: str, analysis_text: str)` tuples.

### 8.3 Orchestrator result dict

Returned by `orchestrator.run()`:

```python
{
    "ticker": "AAPL",
    "company_name": "Apple Inc",
    "agent_reports": [("DCF Analyst", "..."), ...],
    "synthesis": "...",
    "metrics": {...},
    "enrichment_warnings": [...],
    "enrichment_sources": [...],
    "enrichment_filter_stats": {...},
}
```

---

## 9) Streamlit-specific details (`app.py`)

The web UI adds:

- **Sidebar**: LLM provider selector, Anthropic BYOK field, SEC User-Agent, enrichment toggles, context budget sliders, cached report viewer.
- **Provider handling**: OpenAI uses `OPENAI_CBS_API_KEY` as default. Anthropic requires a user-provided key per run (ephemeral — not stored).
- **Event loop**: Wraps async pipeline in `asyncio.run()` with fallback for Streamlit's existing event loop.
- **Session state**: Latest result is stored in `st.session_state` so it persists across reruns.
- **PDF download**: Built on every successful run via `build_pdf_report()`.
- **Cached reports**: Lists `.txt` files from `reports/` directory, selectable in sidebar.

### Streamlit Cloud deployment

1. Push to GitHub.
2. Create app in Streamlit Community Cloud, entrypoint: `app.py`.
3. Add secrets (see `.streamlit/secrets.toml.example`).
4. The `_bootstrap_env_from_streamlit_secrets()` function copies secrets into env vars at startup.

---

## 10) CLI-specific details (`main.py`)

```bash
python main.py TICKER [--save] [--output FILE] [--provider anthropic|openai] [--model MODEL] [--user-agent STR] [--inspect-context] [--preview-chars N]
```

- `--inspect-context`: Runs data preparation only (no LLM calls). Prints context sizes, enrichment stats, and per-agent payload dimensions. Useful for tuning budgets before spending tokens.
- `--provider` / `--model`: Override LLM provider and model for this run.
- `--save`: Auto-save to `reports/{TICKER}_{timestamp}.txt`.

---

## 11) Testing checklist

After making changes, verify:

1. **Ticker resolution**: `python main.py AAPL --inspect-context` resolves and fetches data.
2. **Context sizing**: Inspect output shows reasonable section sizes and per-agent caps.
3. **Agent execution**: All 5 agents return output (no crashes from missing data).
4. **Synthesis**: Executive brief includes rating, health scores, and verdict.
5. **PDF**: Download button works in Streamlit; PDF contains all sections.
6. **Enrichment off**: `ENABLE_YAHOO=false ENABLE_TAVILY=false python main.py AAPL` still works with SEC-only data.
7. **Provider switch**: Both `--provider anthropic` and `--provider openai` produce results.
8. **Cached reports**: Streamlit sidebar shows saved reports and renders them.
