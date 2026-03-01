# AI Financial Analyst

An agentic financial analysis system that pulls real SEC filings and runs them through five specialist AI analysts — each modeled after a top-tier firm's methodology — then synthesizes their findings into a unified investment brief.

## How It Works

1. You input a stock ticker
2. The system fetches all relevant SEC data (10-K, 10-Q, XBRL financials) via the EDGAR API
3. Five analyst agents run in parallel, each examining the data through a different lens
4. A synthesis agent cross-references all five reports and produces a final investment brief with health scores

```
User Input (ticker)
       │
       ▼
 SEC Data Layer ─── fetch, parse, cache
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
├── main.py               # CLI entry point
├── orchestrator.py        # Phase 1 parallel fan-out + Phase 2 synthesis
├── report.py              # Output formatting
├── requirements.txt       # Dependencies
├── agents/
│   ├── base.py            # Shared agent interface (Anthropic SDK)
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
# OPENAI_BASE_URL=https://api.openai.com/v1
```

No other SEC configuration needed. The SEC EDGAR API is free and requires no key.

## Usage

### Analyze a stock

```bash
python main.py AAPL
```

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
- **Orchestration**: Python `asyncio.gather()` for parallel agent execution
- **Caching**: SQLite for SEC data (avoids redundant API calls across runs)
- **Data processing**: pandas for financial data manipulation
