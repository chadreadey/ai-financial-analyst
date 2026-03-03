# AI Financial Analyst

An agentic financial analysis system that pulls real SEC filings, market data, and external research, then runs them through six specialist AI analysts — each modeled after a top-tier firm's methodology — and synthesizes their findings into a unified investment brief.

## How It Works

1. You input a stock ticker
2. The system fetches SEC data (10-K, 10-Q, XBRL financials) via EDGAR, extracts 10-K narrative sections (MD&A, Risk Factors, Business Description), and enriches with Yahoo market data (price history, analyst estimates, macro indicators), dynamic peer comparisons, and Tavily external research
3. Six analyst agents run in parallel, each examining the data through a different lens
4. A synthesis agent cross-references all six reports and produces a final investment brief with health scores

```
User Input (ticker)
       │
       ▼
 SEC Data Layer ─── XBRL financials + 10-K filing text extraction
       │
       ├── Multi-Year Metrics ─── 3Y/5Y CAGRs, margin trends, quarterly data
       │
       ├── Enrichment Layer
       │   ├── Yahoo Finance ─── price history, analyst estimates, market data
       │   ├── Peer Comparison ─── dynamic industry-matched peers with medians
       │   ├── Macro Data ─── treasury yields, VIX, sector ETF, S&P 500
       │   └── Tavily ─── external research (company, industry, risks)
       │
       ├── DCF Analyst (Morgan Stanley)
       ├── Risk Analyst (Bridgewater)
       ├── Earnings Analyst (JPMorgan)
       ├── Competitive Analyst (Bain)
       ├── Pattern Analyst (Renaissance Tech)
       └── Macro Strategist (Goldman Sachs)
       │
       ▼
 Synthesis Agent ─── cross-reference, resolve contradictions
       │
       ▼
 Investment Brief ─── verdict, health scores, risks, catalysts
```

## Analyst Agents

| Agent | Style | Focus |
|---|---|---|
| DCF Analyst | Morgan Stanley | Intrinsic valuation, FCF projections, WACC, price target |
| Risk Analyst | Bridgewater | Balance sheet risk, macro sensitivity, tail scenarios |
| Earnings Analyst | JPMorgan | EPS trajectory, margin analysis, earnings quality |
| Competitive Analyst | Bain & Company | Moat analysis, Porter's Five Forces, sector dynamics |
| Pattern Analyst | Renaissance Tech | Quantitative trends, mean reversion, statistical anomalies |
| Macro Strategist | Goldman Sachs | Macro regime, monetary policy impact, sector positioning |

The synthesis agent acts as a CIO — it reads all reports, flags where analysts agree or contradict each other, and delivers a final rating (Strong Buy → Strong Sell) with a 1-10 health score across each dimension including macro environment.

## Data Pipeline

The system enriches raw SEC filings with multiple data sources before feeding agents:

| Data Source | What It Provides |
|---|---|
| SEC EDGAR (XBRL) | 8 years of annual financials, 8 quarters of quarterly data, multi-year CAGRs, margin trends, FCF series |
| SEC 10-K Filing Text | MD&A narrative, Risk Factors, Business Description (extracted via BeautifulSoup) |
| Yahoo Finance | Current price, multiples, 2-year price history, 50/200 SMA, volatility, volume trends |
| Yahoo Analyst Data | Consensus price targets, EPS/revenue estimates, earnings revisions, growth estimates |
| Dynamic Peer Discovery | Industry-matched peers with market cap proximity scoring, sector medians for key multiples |
| Macro Indicators | Treasury yields (10Y/5Y/13W), VIX, S&P 500, sector ETF performance |
| Tavily Search | Company developments, industry landscape, risk/bear case research |

Each agent receives only the enrichment sections relevant to its analysis via targeted routing.

## Project Structure

```
ai-financial-analyst/
├── app.py                # Streamlit UI
├── main.py               # CLI entry point
├── orchestrator.py        # Phase 1 parallel fan-out + Phase 2 synthesis
├── market_enrichment.py   # Yahoo, Tavily, price history, macro, estimates
├── peer_enrichment.py     # Dynamic peer discovery + comparison tables
├── report.py              # Output formatting (text + PDF)
├── utils.py               # Shared helpers (env_flag, format_money)
├── context_budget.py      # Deterministic context trimming
├── prompt_loader.py       # Markdown prompt loader + token rendering
├── requirements.txt       # Dependencies
├── .streamlit/
│   ├── config.toml
│   └── secrets.toml.example
├── prompts/
│   ├── dcf.md
│   ├── risk.md
│   ├── earnings.md
│   ├── competitive.md
│   ├── pattern.md
│   ├── macro.md
│   └── synthesis.md
├── llm/
│   ├── __init__.py
│   └── providers.py       # LLM provider abstraction (Anthropic/OpenAI)
├── agents/
│   ├── base.py            # Shared agent interface
│   ├── dcf.py             # DCF Analyst
│   ├── risk.py            # Risk Analyst
│   ├── earnings.py        # Earnings Analyst
│   ├── competitive.py     # Competitive & Sector Analyst
│   ├── pattern.py         # Pattern Analyst
│   └── macro.py           # Macro Strategist
└── sec/
    ├── client.py          # SEC EDGAR API client + rate limiting
    ├── xbrl_parser.py     # XBRL → structured financials + computed metrics
    ├── filing_parser.py   # 10-K HTML → MD&A, Risk Factors, Business Desc
    └── cache.py           # SQLite caching layer
```

## Setup

### Requirements

- Python 3.9+
- An [Anthropic API key](https://console.anthropic.com/) or OpenAI-compatible API key

### Install

```bash
git clone https://github.com/chadreadey/ai-financial-analyst.git
cd ai-financial-analyst
pip install -r requirements.txt
```

### Configure provider and API keys

```bash
cp .env.example .env
```

Then edit `.env`:

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-anthropic-key
OPENAI_API_KEY=your-openai-key
# Optional override. Default is:
# OPENAI_BASE_URL=https://cbsai.business.columbia.edu/api/v1
TAVILY_API_KEY=your-tavily-key

# --- Feature toggles (all default to true) ---
ENABLE_YAHOO=true
ENABLE_TAVILY=true
ENABLE_PRICE_HISTORY=true
ENABLE_MACRO=true
ENABLE_ESTIMATES=true
ENABLE_PEERS=true
ENABLE_FILING_TEXT=true
ENABLE_MACRO_AGENT=true

# --- Context budgets ---
TAVILY_MAX_RESULTS=3
TAVILY_SNIPPET_CHARS=600
ENRICHMENT_MAX_CHARS=8000
MAX_MARKET_SECTION_CHARS=1200
MAX_EXTERNAL_COMPANY_SECTION_CHARS=2500
MAX_EXTERNAL_INDUSTRY_SECTION_CHARS=2500
MAX_EXTERNAL_RISKS_SECTION_CHARS=2500
MAX_PRICE_HISTORY_CHARS=1500
MAX_MACRO_SECTION_CHARS=1500
MAX_ESTIMATES_SECTION_CHARS=1200
MAX_PEER_SECTION_CHARS=2500
MAX_MDA_CHARS=4000
MAX_RISK_FACTORS_CHARS=3000
MAX_BIZ_DESC_CHARS=2000
MAX_AGENT_CONTEXT_CHARS=12000
MAX_AGENT_OUTPUT_TOKENS=1200
SYNTHESIS_REPORT_MAX_CHARS=4500
SYNTHESIS_INPUT_MAX_CHARS=22000
MAX_SYNTHESIS_OUTPUT_TOKENS=1500
# Per-agent overrides (optional):
# MAX_CONTEXT_DCF_CHARS=12000
# MAX_CONTEXT_RISK_CHARS=12000
# MAX_CONTEXT_EARNINGS_CHARS=12000
# MAX_CONTEXT_COMPETITIVE_CHARS=12000
# MAX_CONTEXT_PATTERN_CHARS=12000
# MAX_CONTEXT_MACRO_CHARS=12000
```

No SEC configuration needed. The SEC EDGAR API is free and requires no key.

### Prompt customization

All agent/synthesis prompts live in `prompts/` as Markdown files. You can edit these directly without changing Python code. Supported placeholder tokens:

- `[COMPANY NAME]`
- `[STOCK NAME]`
- `[TICKER]`

## Usage

### Run Streamlit UI

```bash
python -m streamlit run app.py
```

The UI exposes provider selection, enrichment toggles, budget guardrails, PDF download, and a cached report viewer so you can toggle between historical runs.
OpenAI mode uses `OPENAI_CBS_API_KEY` as the default deployed key (fallback to `OPENAI_API_KEY` if needed).
Anthropic mode is BYOK in the UI: users must paste their own Anthropic key per run.

### Deploy on Streamlit Community Cloud

1. Push this repository to GitHub.
2. In Streamlit Community Cloud, create a new app and set entrypoint to `app.py`.
3. Add secrets in app settings (use `.streamlit/secrets.toml.example` as template):
   - `OPENAI_CBS_API_KEY` (default OpenAI key fallback)
   - `OPENAI_BASE_URL` (if using CBS endpoint)
   - `OPENAI_API_KEY` (optional fallback)
   - `TAVILY_API_KEY` (optional)
4. Deploy and test with both provider modes.

### Analyze a stock

```bash
python main.py AAPL
```

### Disable enrichment (SEC/XBRL only mode)

```bash
ENABLE_YAHOO=false ENABLE_TAVILY=false python main.py AAPL
```

### Inspect context sizes without calling any LLM

```bash
python main.py AAPL --inspect-context --preview-chars 1200
```

The inspection output includes enrichment section sizes and per-agent context caps/sent size, so you can tune token cost before running any model calls.

Tavily results are used directly (no domain filtering). Inspection output shows how many sources were included per bucket.

### Save the report to a file

```bash
python main.py MSFT --save
```

Reports are saved to `reports/{TICKER}_{timestamp}.txt`.

### Save to a specific path

```bash
python main.py TSLA --output my_report.txt
```

### Custom SEC User-Agent

The SEC asks for a descriptive User-Agent header. The default works, but you can provide your own:

```bash
python main.py AAPL --user-agent "YourName your@email.com"
```

## Tech Stack

- **LLM**: Provider-selectable Anthropic Claude or OpenAI-compatible APIs
- **Data**: SEC EDGAR API (XBRL structured financials + 10-K filing text)
- **Enrichment**: Yahoo Finance (price history, estimates, macro), dynamic peer comparison, Tavily research
- **Filing parsing**: BeautifulSoup + lxml for 10-K HTML section extraction
- **Orchestration**: Python `asyncio.gather()` for parallel agent execution
- **Caching**: SQLite for SEC data (avoids redundant API calls across runs)
- **Data processing**: pandas + numpy for financial data manipulation
