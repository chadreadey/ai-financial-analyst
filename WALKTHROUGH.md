# AI Financial Analyst - Full Codebase Walkthrough

This document explains the current codebase end-to-end so you can merge its functionality into another base repository with minimal ambiguity.

---

## 1) What this project does

This app is a Streamlit-based multi-agent equity research system.  
Input: a company name or ticker (for example, `AAPL` or `Apple`).  
Output: a full research report composed of:

- 9 parallel analyst outputs
- 1 synthesized executive brief with health score, price target, and rating
- 1 downloadable PDF report
- Background prompt auto-improvements that rewrite prompt files for the next run

Primary data sources:

- SEC EDGAR filings (`10-K`, `10-Q`, `8-K`)
- Tavily web research (company/industry/risk queries)
- Live market data from Yahoo Finance via `yfinance`

---

## 2) Repository map and responsibilities

- `app.py`: Main application entrypoint, Streamlit UI, orchestration, LLM calls, parallel analysis, synthesis, PDF generation, and background prompt improvement.
- `context_builder.py`: Builds one combined research context string used by all analysis agents.
- `sec_client.py`: SEC utilities (ticker resolution, filing list retrieval, filing content fetch/cleaning).
- `tavily_client.py`: Tavily search wrapper for company, industry, and risk research.
- `prompts/*.md`: Prompt templates for each analysis role + synthesis + prompt improver.
- `.env.example`: Required/optional environment variables template.
- `requirements.txt`: Python dependencies.
- `README.md`: Project-level overview and quick start.

---

## 3) Runtime prerequisites and configuration

### 3.1 Python and packages

Install dependencies from `requirements.txt`:

- `streamlit`
- `openai`
- `tavily-python`
- `requests`
- `python-dotenv`
- `beautifulsoup4`
- `fpdf2`
- `yfinance`

### 3.2 Environment variables

Expected in `.env`:

- `OPENAI_API_KEY` (required for analysis)
- `OPENAI_MODEL` (optional, defaults to `gpt-4o-mini`)
- `TAVILY_API_KEY` (required for Tavily searches)
- `SEC_API_KEY` (present in template but not used by current code path)

### 3.3 LLM endpoint

In `app.py`, the OpenAI client is created with:

- `base_url = "https://cbsai.business.columbia.edu/api/v1"`
- `api_key = OPENAI_API_KEY`
- `model = OPENAI_MODEL or gpt-4o-mini`

So this implementation expects an OpenAI-compatible endpoint at that URL.

---

## 4) End-to-end execution flow (step-by-step)

This section tracks exactly what happens when the user clicks **Analyze**.

### Step 1: App starts and loads config (`app.py`)

1. Imports required modules.
2. Calls `load_dotenv()` to load `.env`.
3. Initializes logging.
4. Defines constants:
   - `BASE_URL`, `API_KEY`, `MODEL`
   - Prompt paths
   - `ANALYSES` dictionary (9 analysis configs)
   - Concurrency and context limits

### Step 2: Streamlit UI is rendered (`app.py`)

1. `st.set_page_config(...)`
2. `st.title("AI Equity Analyst")`
3. Renders a form with:
   - Text input: ticker/company
   - Analyze submit button

### Step 3: Input validation (`app.py`)

1. If `OPENAI_API_KEY` missing, app warns and stops.
2. If form not submitted or input empty, app shows info and stops.

### Step 4: Ticker/company resolution (`sec_client.py`)

1. `resolve_ticker(stock_input)` is called.
2. `resolve_ticker()` behavior:
   - Normalizes input to uppercase.
   - Applies alias map (`GOOGLE -> GOOGL`, `FACEBOOK -> META`).
   - Loads SEC ticker dataset once and caches it (`_fetch_tickers_data()`).
   - Tries, in order:
     1) exact ticker
     2) exact company name
     3) company name startswith input
     4) input substring in name
     5) word-level partial startswith matching
3. Returns `(ticker, company_name)` or `None`.
4. If unresolved, app shows error and stops.

### Step 5: Build research context (`context_builder.py`)

`build_context(ticker, company_name, on_status=...)` is called.

Detailed internal sequence:

1. Creates top header:
   - `# Research Context: Company (Ticker)`
   - report date
2. Fetches live market data via `yfinance.Ticker(ticker).info`:
   - current price, market cap, valuation multiples, 52-week range, beta, dividend yield, EPS, revenue growth
   - if unavailable, inserts an "Unavailable" section with error message
3. Fetches SEC filing list:
   - calls `get_filings(ticker, form_types=["10-K","10-Q","8-K"], limit=20)`
   - appends a visible list of latest filings
4. Selects filings to download:
   - latest 10-K, latest 10-Q, latest 8-K
   - keeps only up to `num_filings` (default `2`)
5. Downloads each selected filing full text:
   - `fetch_filing_content(filing, max_chars=filing_max_chars)`
   - default cap per filing: `30,000` chars
6. Runs 3 Tavily searches:
   - company analysis: `search_company()`
   - industry overview: `search_industry()`
   - risk/bear queries: `search_risks()`
7. Formats Tavily results with title, URL, published date, and content snippet.
8. Adds consolidated `Sources Used` list.
9. Applies hard cap `MAX_TOTAL_CONTEXT = 60,000` characters.
10. Returns one large string used as LLM context for all agents.

### Step 6: Load system prompt (`app.py`)

1. `SYSTEM_PROMPT_PATH` points to `prompts/long-term-equity-analyst.md`.
2. `_load_prompt()` replaces placeholders:
   - `[STOCK NAME]`
   - `[COMPANY NAME]`
   - `[TICKER]`
3. This loaded prompt is used as the **system instruction** for all analysis calls.

### Step 7: Run nine analyses in parallel (`app.py`)

1. App creates a `ThreadPoolExecutor(max_workers=3)`.
2. For each key in `ANALYSES`, it submits `_run_single_analysis(...)`.
3. Each analysis execution:
   - Creates a fresh OpenAI client (`_make_client()`).
   - Determines user prompt:
     - For `initial_memo`: uses inline `user_request`.
     - For other analyses: loads corresponding prompt file from `prompts/`.
   - Trims context by analysis-specific cap (`CONTEXT_LIMITS`).
   - Builds final user payload:
     - analysis instructions
     - separator
     - `RESEARCH CONTEXT`
   - Calls `_call_llm(...)` with retry/fallback strategy:
     - First tries `client.responses.create(...)`
     - On failure, tries `client.chat.completions.create(...)`
     - Up to 3 attempts with increasing wait
4. As futures complete, app stores each output in `results[key]`.
5. If any analysis errors, that key stores `Error: ...`.

### Step 8: Synthesize executive brief (`app.py`)

1. Loads `prompts/synthesis.md`.
2. Injects all 9 analysis outputs into template placeholders.
3. Calls `_call_llm(...)` with system role:
   - `"You are a senior equity research director."`
4. Receives `brief` (final executive summary block shown in UI).

### Step 9: Start prompt self-improvement in background (`app.py`)

1. Spawns daemon thread calling `_run_prompt_improvement_background(...)`.
2. For each analysis prompt file:
   - Loads current prompt text
   - Uses `prompts/prompt-improver.md` template with:
     - brief summary (first 2000 chars)
     - analysis output (first 3000 chars)
     - current prompt
   - Calls LLM to generate improved prompt text
3. Computes unified diff (`_compute_diff()`).
4. If changed, overwrites that prompt file on disk.
5. Logs number of prompt files updated.

Important behavior:

- This modifies prompt files automatically.
- Changes apply to future runs, not current one.
- This can create noisy git diffs if left enabled during testing.

### Step 10: Generate PDF report (`app.py`)

1. Calls `_build_pdf(...)` with:
   - company name/ticker
   - executive brief
   - all analysis outputs
2. PDF generation details:
   - Uses `fpdf2`
   - Sanitizes Unicode to avoid rendering issues in Latin-1
   - Adds:
     - cover page
     - executive brief section
     - one page section per analysis output
   - Includes page header/footer and basic markdown rendering logic
3. Returns bytes for download button.

### Step 11: Render final UI (`app.py`)

1. Shows header and PDF download button.
2. Renders executive brief markdown.
3. Creates tabs:
   - one tab per analysis output
   - one tab for full research context
   - one tab for prompts used
4. Prompts tab displays every prompt file and synthesis prompt in expanders.
5. Displays caption about background prompt improvement.

---

## 5) Module-level technical details

### 5.1 `sec_client.py`

Core functions:

- `_fetch_tickers_data()`: downloads SEC ticker master list and caches it globally.
- `get_cik_from_ticker()`: ticker -> 10-digit CIK.
- `resolve_ticker()`: robust input resolver (ticker/name/partial match).
- `get_filings()`: calls `https://data.sec.gov/submissions/CIK{cik}.json`, filters by forms, builds filing URLs.
- `fetch_filing_content()`:
  - for filing dict input, converts primary doc URL to complete submission `.txt` URL
  - fetches content with SEC-compliant headers
  - strips SGML/HTML and noisy artifacts
  - truncates to max chars

Notable constraints:

- Requires valid SEC `User-Agent` header (`USER_AGENT` constant).
- Uses network requests without retries beyond default requests behavior.

### 5.2 `tavily_client.py`

Core functions:

- `_get_client()`: validates `TAVILY_API_KEY`.
- `search_company()`: recent company/stock-specific query (`topic="news"`, `days=90`).
- `search_industry()`: broader sector query (`topic="general"`, `time_range="month"`).
- `search_risks()`: negative/risk query variant (`topic="news"`, `days=90`).

Each function returns a normalized list containing title/url/content/score/published_date.

### 5.3 `context_builder.py`

Purpose: create one context payload balancing breadth and token limits.

Design choices:

- Mixes fundamental filings + external qualitative context + real-time market snapshot.
- Limits per filing and total context to prevent model overload.
- Emits status messages via callback for UI progress updates.

### 5.4 `app.py`

Contains:

- UI setup
- task orchestration
- LLM helper methods
- parallel execution
- synthesis
- background prompt evolution
- PDF export pipeline

Reliability mechanisms:

- LLM retry logic with fallback API method
- per-analysis try/except (single failure does not crash full run)
- PDF generation failure is non-fatal

---

## 6) Prompt system details (`prompts/`)

### 6.1 Analysis prompts

The 9 analyst prompts enforce evidence-first output from provided context:

1. `long-term-equity-analyst.md` (used as global system prompt)
2. `bull-case.md`
3. `bear-case.md`
4. `quarterly-update.md`
5. `dcf-analyst.md`
6. `risk-analyst.md`
7. `earnings-analyst.md`
8. `competitive-analysis.md`
9. `pattern-analysis.md`

### 6.2 Synthesis prompt

`synthesis.md`:

- receives the 9 generated outputs
- enforces exact report shape (health score, up/down cases, target, rating, verdict)
- includes consistency guardrails (rating must match implied upside/downside)

### 6.3 Prompt improver prompt

`prompt-improver.md`:

- asks the model to improve one prompt based on observed output quality
- hard cap: improved prompt must be <=40 lines
- instructs surgical, minimal changes

---

## 7) Current concurrency model

- Analysis generation: parallelized with thread pool (`max_workers=3`) across 9 jobs.
- Prompt improvement: separate daemon thread; internally parallelized (`max_workers=3`) across prompt files.
- Net effect: faster user response, with deferred self-optimization after visible output.

---

## 8) Data contracts and key structures

### 8.1 `ANALYSES` dict (`app.py`)

Each analysis entry contains:

- `label`: UI/display name
- `prompt_file`: markdown file path
- optional `user_request`: inline request string (used by `initial_memo`)

### 8.2 Filing dict shape (`sec_client.py`)

Produced by `get_filings()`:

- `form`
- `filing_date`
- `accession_number`
- `primary_document`
- `url`

### 8.3 Tavily result shape (`tavily_client.py`)

Normalized fields:

- `title`
- `url`
- `content`
- `score`
- `published_date`

---

## 9) Known behavior and merge-sensitive points

When merging into another base codebase, these are the highest-friction parts:

1. **Endpoint compatibility**
   - This code uses OpenAI-compatible SDK calls and a custom `BASE_URL`.
2. **Prompt auto-mutation**
   - Prompt files are rewritten automatically in background after each run.
3. **Context truncation**
   - Filing and total context caps can affect analysis quality and determinism.
4. **Ticker resolution strategy**
   - Uses SEC ticker JSON heuristic matching logic; not symbol service APIs.
5. **SEC scraping assumptions**
   - Relies on SEC submission JSON + filing text clean-up heuristics.
6. **UI and orchestration coupling**
   - `app.py` holds both presentation and business pipeline logic.

---

## 10) Recommended merge mapping into your classmate's base repo

Since your classmate repo is the base, import this project by capability slices (not one giant merge):

1. **Slice A: Data connectors**
   - Port `sec_client.py` and `tavily_client.py`.
2. **Slice B: Context builder**
   - Port `context_builder.py` with status callback support.
3. **Slice C: Prompt package**
   - Copy `prompts/` and placeholder substitution behavior.
4. **Slice D: Parallel analysis executor**
   - Port `_run_single_analysis`, `_call_llm`, `_load_prompt`, `CONTEXT_LIMITS`.
5. **Slice E: Synthesis**
   - Port `synthesis.md` integration and final rating logic.
6. **Slice F: PDF**
   - Port `_build_pdf` (or adapt to their export system).
7. **Slice G: Prompt auto-improver**
   - Add last; keep behind a feature flag initially.

For each slice:

- integrate code
- run automated checks
- run your manual smoke test
- commit before moving to next slice

---

## 11) Manual test checklist (suggested)

Run these after each merge slice:

1. Input resolution:
   - test ticker (`AAPL`)
   - test company name (`Apple`)
   - test partial string (`Micro`)
2. Data acquisition:
   - SEC filings list appears
   - at least one filing content block loads
   - Tavily sections populate
3. Agent execution:
   - all 9 analyses return output
   - one forced failure does not crash the app
4. Synthesis integrity:
   - health score appears
   - price target and rating appear
   - rating direction matches target logic
5. PDF:
   - download button works
   - PDF contains executive brief + all sections
6. Prompt improvement:
   - verify whether prompt files changed after run
   - disable feature if reproducibility is required

---

## 12) Commands for local execution

```bash
pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
```

---

## 13) Short implementation summary

This codebase is a Streamlit orchestrator over a research-context pipeline and a 9-agent LLM analysis stack, followed by synthesis, PDF export, and background prompt self-improvement. The highest-value merge strategy into your base repo is capability-by-capability integration with test checkpoints after each slice.

