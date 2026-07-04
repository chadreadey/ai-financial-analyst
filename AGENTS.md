# AGENTS.md

## Cursor Cloud specific instructions

This repo is the **AI Financial Analyst** — a Python FastAPI backend + Vite/React
frontend. Enter a stock ticker and six LLM "analyst" agents run in parallel, then
a synthesis agent issues a verdict. Standard setup/run commands live in
`README.md` ("Local Development"); notes below are the non-obvious gotchas.

### Services

| Service | Dir | Dev command | URL |
|---|---|---|---|
| Backend API (FastAPI) | repo root | `python3 -m uvicorn backend.main:app --reload --port 8000` | http://localhost:8000 (docs at `/docs`, health at `/api/health`) |
| Frontend SPA (Vite/React) | `frontend/` | `npm run dev` | http://localhost:5173 |

The Streamlit app (`app.py`) and CLI (`python3 main.py AAPL`) are alternative
front ends over the same engine; the React + FastAPI pair is the primary path.

### Non-obvious notes

- **Use `python3 -m …`, not bare console scripts.** Python deps install to the
  user site, so `uvicorn`/`pytest`/`fastapi` land in `~/.local/bin`, which is not
  on `PATH`. Run `python3 -m uvicorn …` and `python3 -m pytest` to avoid this.
- **Tests:** `python3 -m pytest` (329 pass, 7 skipped). Two dependencies used only
  by tests are not in `requirements.txt` and are installed by the update script:
  `responses` (used by `tests/test_kalshi_client.py`) and `tzdata` (APScheduler
  needs the IANA `US/Eastern` zone in `tests/test_paper_scheduler.py`).
- **Lint:** `cd frontend && npm run lint`. This currently reports ~54 pre-existing
  ESLint errors in the repo's own source (not caused by env setup).
- **LLM key is required for a real analysis.** The pipeline runs fully (SEC/XBRL
  fetch → all 6 agents → synthesis) but the LLM call returns `401 Invalid API key`
  unless `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` is set (select via `LLM_PROVIDER`).
  To exercise the whole flow without a paid key, point it at any OpenAI-compatible
  endpoint: `LLM_PROVIDER=openai OPENAI_API_KEY=… OPENAI_BASE_URL=…`. The
  OpenAI provider tries the Responses API first and falls back to Chat Completions.
- **Market data / enrichment degrade gracefully.** Tiingo/Alpaca/FMP/Finnhub/FRED/
  Tavily are each behind feature flags and need keys; Yahoo (the free fallback) is
  frequently rate-limited (HTTP 429) from cloud IPs, so `/api/market/price-history`
  may return empty bars. Analysis still completes; those sections just show
  warnings ("no price data available", "Tavily enrichment unavailable").
- **Env files are optional for local dev.** Settings default sensibly and the
  frontend API client defaults to `http://localhost:8000` in dev mode. Copy
  `.env.example`→`.env` and `frontend/.env.example`→`frontend/.env.local` only when
  you need to add API keys.
- **Databases are zero-config SQLite by default** (SEC cache, warehouse, FMP
  cache). Redis, Supabase/Postgres, Pinecone, and Modal are all optional.
