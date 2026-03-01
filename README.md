# AI Financial Analyst

An agentic financial analysis system that pulls real SEC filings and runs them through five specialist AI analysts — each modeled after a top-tier firm's methodology — then synthesizes their findings into a unified investment brief.

## How It Works

1. You input a stock ticker
2. The system fetches SEC data (10-K, 10-Q, XBRL financials) via EDGAR, then optionally enriches with Yahoo market data and Tavily external research
3. Five analyst agents run in parallel, each examining the data through a different lens
4. A synthesis agent cross-references all five reports and produces a final investment brief with health scores

```
User Input (ticker)
       │
       ▼
 SEC Data Layer ─── fetch, parse, cache
       │
       ├── Optional Enrichment ─── Yahoo market snapshot + Tavily research
       │
       ├── DCF Analyst (Morgan Stanley)
       ├── Risk Analyst (Bridgewater)
       ├── Earnings Analyst (JPMorgan)
       ├── Competitive Analyst (Bain)
       └── Pattern Analyst (Renaissance Tech)
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

The synthesis agent acts as a CIO — it reads all five reports, flags where analysts agree or contradict each other, and delivers a final rating (Strong Buy → Strong Sell) with a 1-10 health score across each dimension.

## Project Structure

```
ai-financial-analyst/
├── app.py                # Streamlit UI (same orchestrator core)
├── main.py               # CLI entry point
├── orchestrator.py        # Phase 1 parallel fan-out + Phase 2 synthesis
├── report.py              # Output formatting
├── prompt_loader.py       # Markdown prompt loader + token rendering
├── market_enrichment.py   # Optional Yahoo + Tavily enrichment context
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
│   └── pattern.py         # Pattern Analyst
└── sec/
    ├── client.py          # SEC EDGAR API client + rate limiting
    ├── xbrl_parser.py     # XBRL → structured financials + computed metrics
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
ENABLE_YAHOO=true
ENABLE_TAVILY=true
TAVILY_API_KEY=your-tavily-key
TAVILY_MAX_RESULTS=3
TAVILY_SNIPPET_CHARS=220
ENRICHMENT_MAX_CHARS=3500
MAX_MARKET_SECTION_CHARS=900
MAX_EXTERNAL_COMPANY_SECTION_CHARS=1200
MAX_EXTERNAL_INDUSTRY_SECTION_CHARS=1200
MAX_EXTERNAL_RISKS_SECTION_CHARS=1200
MAX_AGENT_CONTEXT_CHARS=7000
MAX_CONTEXT_DCF_CHARS=7000
MAX_CONTEXT_RISK_CHARS=7000
MAX_CONTEXT_EARNINGS_CHARS=7000
MAX_CONTEXT_COMPETITIVE_CHARS=7000
MAX_CONTEXT_PATTERN_CHARS=7000
MAX_AGENT_OUTPUT_TOKENS=1200
SYNTHESIS_REPORT_MAX_CHARS=3200
SYNTHESIS_INPUT_MAX_CHARS=14000
MAX_SYNTHESIS_OUTPUT_TOKENS=1500
```

No other SEC configuration needed. The SEC EDGAR API is free and requires no key.

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
- **Data**: SEC EDGAR API (filings + XBRL structured financials)
- **Optional enrichment**: Yahoo Finance + Tavily research
- **Orchestration**: Python `asyncio.gather()` for parallel agent execution
- **Caching**: SQLite for SEC data (avoids redundant API calls across runs)
- **Data processing**: pandas for financial data manipulation
