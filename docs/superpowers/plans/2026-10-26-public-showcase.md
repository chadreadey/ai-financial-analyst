# Public Showcase Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the deployed app into a public showcase: instant example briefs, rate-limited live runs, one honest "How it performs" page, and the research lab hidden behind an admin key.

**Architecture:** Example briefs and evidence data are static JSON under `frontend/public/` (served by Vercel, no Railway dependency, so they load instantly even if the backend is cold). Public live runs go through the existing `/api/analysis/run` + SSE stream, hardened server-side: request params are clamped, auto paper trading is off, and an in-memory limiter caps per-IP, daily and concurrent runs. Every write or compute-heavy lab endpoint requires `X-API-Key`; the lab UI moves under `/lab/*` and sends the key from localStorage.

**Tech Stack:** FastAPI + pytest (TestClient), React 19 + Vite + Tailwind + recharts, Vitest (new, frontend unit tests only), Vercel static + rewrites, Railway.

**Spec:** No separate spec doc. The decisions this plan implements (agreed in chat on 2026-10-26):
1. The landing page is a ticker box plus 4 precomputed example briefs that open instantly; no empty "Past Analyses" list.
2. The brief is the main page: verdict, price target, where the six agents agreed and disagreed, the synthesis, sources.
3. Backtest Lab is replaced publicly by one static page with the three-series result (SPY 0.74 / Quant-only 1.15 / AI-augmented 1.01 Sharpe) and its caveats.
4. Paper Trading, Backtest Lab, Modal runs, Settings and run history are hidden from the public nav and gated by an admin key.
5. Anonymous live runs are allowed but rate-limited.
6. Repo hygiene: tracked run artifacts removed from the root; README leads with the product.

## Global Constraints

- Public product name everywhere visible: `AI Financial Analyst` (replaces `ATIS` in the UI).
- Public run limits (env-overridable via `config.Settings`): `public_runs_per_ip_per_hour = 3`, `public_runs_per_day = 30`, `public_max_concurrent_runs = 2`.
- Public runs always use server defaults for `provider`, `model`, and all five budget fields (`max_agent_context_chars` … `max_synthesis_output_tokens`), ignore `api_key`, and run with `auto_paper_trade=False`.
- Ticker format accepted on public runs: `^[A-Z]{1,5}(\.[A-Z])?$` after `.strip().upper()`.
- Admin auth: header `X-API-Key` compared with `hmac.compare_digest` against `settings.internal_api_key`; wrong or missing → 403 `{"detail": "Forbidden."}`; unset key → 500 (same contract as today's `_require_api_key`).
- Evidence numbers come only from `docs/eval/three_series_llm/latest.json` and `daily_returns.csv` (generated 2026-08-25). Do not cite `backtests/GOLD_STANDARD.md` (its 1.35 Sharpe relies on signals NORTHSTAR.md says are disproven).
- Every brief and the evidence page show: "Research demo, not investment advice."
- The old URL `/analysis` (linked from the portfolio site) must keep working and redirect to `/`.

## Review Focus

1. **Client IP behind Vercel → Railway.** Requests arrive via the Vercel rewrite, so `request.client.host` is a proxy address. Expected: the limiter keys on the first entry of `X-Forwarded-For`, falling back to `request.client.host`. Pinned in Task 2 (`test_limiter_uses_first_forwarded_for_entry`).
2. **Failed or crashed runs leak concurrency slots.** Expected: a job that raises still releases its slot. Pinned in Task 2 (`test_slot_released_when_job_raises`).
3. **Admin caller hitting the public limiter.** Expected: a valid `X-API-Key` bypasses limits and keeps the client's provider/budget settings, so the lab still works. Pinned in Task 2 (`test_admin_run_bypasses_limits_and_keeps_params`).
4. **Example brief missing optional fields** (`signal_breakdown`, `price_target`, `signal_conflicts` absent or null in older runs). Expected: the brief renders without those panels and never crashes. Pinned in Task 5 (`buildConsensus` / `upsidePct` null tests).
5. **Visitor types a ticker that has an example.** Expected: they get the instant static brief, not a paid live run. Pinned in Task 4 (`test resolveTickerRoute`).

---

## File Map

Backend
- Create `backend/auth.py`: `require_admin` dependency and `is_admin(request)` helper (moved from `backtest_modal.py`).
- Create `backend/rate_limit.py`: `RunLimiter`.
- Modify `backend/routers/backtest_modal.py`: import `require_admin` from `backend/auth.py`.
- Modify `backend/main.py`: attach `require_admin` to lab routers.
- Modify `backend/routers/analysis.py`: public-run hardening and limiter.
- Modify `config.py`: the three limit settings.
- Delete `api/backtest/modal/[...path].ts` (the Vercel proxy that injects the key for any caller).
- Create `scripts/build_showcase.py` and `scripts/build_evidence.py`.
- Tests: `tests/test_auth.py`, `tests/test_rate_limit.py`, `tests/routers/test_analysis_public.py`, `tests/test_build_evidence.py`.

Frontend
- Create `src/lib/adminKey.ts`, `src/lib/showcase.ts`, `src/lib/brief.ts`, `src/lib/evidence.ts` (pure helpers + types).
- Create `src/components/layout/PublicLayout.tsx`, `src/components/brief/BriefView.tsx`, `src/components/brief/AgentConsensus.tsx`.
- Create `src/pages/HomePage.tsx`, `src/pages/BriefPage.tsx`, `src/pages/LiveRunPage.tsx`, `src/pages/EvidencePage.tsx`, `src/pages/LabGatePage.tsx`.
- Modify `src/App.tsx`, `src/api/client.ts`, `src/components/layout/AppSidebar.tsx`, `package.json`.
- Generated data: `frontend/public/showcase/index.json`, `frontend/public/showcase/<TICKER>.json`, `frontend/public/evidence/three_series.json`.
- Tests: `src/lib/*.test.ts`.

Other repo: `~/portfolio-site/index.html` (link update, Task 7).

---

### Task 1: Gate the lab endpoints behind the admin key

**Files:**
- Create: `backend/auth.py`
- Modify: `backend/routers/backtest_modal.py:25-46`, `backend/main.py:124-136`
- Delete: `api/backtest/modal/[...path].ts`
- Test: `tests/test_auth.py`

**Interfaces:**
- Produces: `require_admin(x_api_key: str | None = Header(None, alias="X-API-Key")) -> None` (FastAPI dependency, raises 403/500 per Global Constraints); `is_admin(request: Request) -> bool` (never raises; False when the key is unset or wrong).

- [ ] **Step 1: Write the failing tests** in `tests/test_auth.py`, using a TestClient on `backend.main.app` with `settings.internal_api_key` monkeypatched to `"test-key"`:
  - `test_lab_endpoints_forbidden_without_key`: parametrize over `("POST","/api/paper-trading/rebalance")`, `("POST","/api/portfolio/holdings")`, `("DELETE","/api/watchlist/AAPL")`, `("POST","/api/backtest/run")`, `("POST","/api/industry/technology/analyze")`, `("GET","/api/analysis/history")`, `("GET","/api/diagnostics/assumptions")`; each → `status_code == 403`.
  - `test_public_endpoints_open`: `GET /api/health` → 200; `GET /api/config/defaults` → 200.
  - `test_is_admin`: `is_admin` on a request with header `X-API-Key: test-key` → True; `wrong` → False; no header → False; with `internal_api_key=""` → False.
- [ ] **Step 2: Run** `pytest tests/test_auth.py -v`. Expected: FAIL (`ModuleNotFoundError: backend.auth`).
- [ ] **Step 3: Implement `backend/auth.py`.** Move `_require_api_key` out of `backtest_modal.py` as `require_admin` (header now optional so a missing header gives 403, not 422), add `is_admin`. In `backtest_modal.py` use `APIRouter(dependencies=[Depends(require_admin)])`. In `main.py`, pass `dependencies=[Depends(require_admin)]` to `include_router` for `reports`, `portfolio`, `news`, `industry`, `watchlist`, `recommendations`, `backtest`, `paper_trading`, `diagnostics`. Leave `analysis`, `config`, `market_data` open, and gate only the two history routes in `analysis.py` with route-level `dependencies=[Depends(require_admin)]`.
- [ ] **Step 4: Delete the Vercel proxy** `api/backtest/modal/[...path].ts`. The `/api/:path*` rewrite in `vercel.json` now forwards these calls, and the browser sends the key itself (Task 4).
- [ ] **Step 5: Run** `pytest tests/test_auth.py tests/routers/test_backtest_modal.py tests/test_paper_trading_router.py tests/test_portfolio_router.py -v`. Expected: all PASS. Existing router tests that call gated routes without a key must add `AUTH_HEADERS`; update them, don't loosen the gate.
- [ ] **Step 6: Commit** `git commit -m "feat(auth): require admin key on lab endpoints; drop key-injecting proxy"`

### Task 2: Harden and rate-limit public live runs

**Files:**
- Create: `backend/rate_limit.py`
- Modify: `config.py` (after the auto paper trading block), `backend/routers/analysis.py:16-25`
- Test: `tests/test_rate_limit.py`, `tests/routers/test_analysis_public.py`

**Interfaces:**
- Consumes: `is_admin(request)` from Task 1.
- Produces:
  - `class RunLimiter(per_ip_per_hour: int, per_day: int, max_concurrent: int, clock: Callable[[], float] = time.time)`
  - `RunLimiter.acquire(ip: str) -> tuple[bool, str | None, int | None]`: returns `(ok, reason, retry_after_seconds)`; `reason` is one of `"ip_hourly"`, `"daily"`, `"concurrent"`. Thread-safe (`threading.Lock`). The daily window is the rolling 24h.
  - `RunLimiter.release() -> None`: decrements the concurrent count, floor 0.
  - `client_ip(request: Request) -> str`: first `X-Forwarded-For` entry, stripped, else `request.client.host`, else `"unknown"`.
  - Module-level `limiter = RunLimiter(settings.public_runs_per_ip_per_hour, settings.public_runs_per_day, settings.public_max_concurrent_runs)` in `backend/routers/analysis.py`.

- [ ] **Step 1: Write the failing limiter tests** in `tests/test_rate_limit.py` with a fake clock:
  - `test_ip_hourly_limit`: `RunLimiter(3, 30, 10)`; 3 acquires+releases for `"1.1.1.1"` ok, 4th → `(False, "ip_hourly", r)` with `0 < r <= 3600`; advance clock 3601s → ok again.
  - `test_other_ip_unaffected`: after `"1.1.1.1"` is exhausted, `"2.2.2.2"` → ok.
  - `test_daily_limit`: `RunLimiter(100, 2, 10)`; 2 ok from different IPs, 3rd → `"daily"`.
  - `test_concurrent_limit`: `RunLimiter(10, 30, 2)`; 2 acquires without release, 3rd → `"concurrent"`; after one `release()` → ok.
  - `test_limiter_uses_first_forwarded_for_entry`: `client_ip` on a request with `X-Forwarded-For: "9.9.9.9, 10.0.0.1"` → `"9.9.9.9"`; no header → the client host.
- [ ] **Step 2: Write the failing router tests** in `tests/routers/test_analysis_public.py`. Monkeypatch `backend.routers.analysis.run_analysis_job` with a fake that records `(request, auto_paper_trade)`, and `threading.Thread` so the target runs inline. Replace `analysis.limiter` with a fresh `RunLimiter(3, 30, 2)` per test.
  - `test_public_run_clamps_params`: POST `{"ticker":" nvda ","provider":"openai","model":"gpt-x","api_key":"sk-x","max_agent_output_tokens":99999}` → 200; the recorded request has `ticker == "NVDA"`, `provider == settings.llm_provider`, `model is None`, `api_key is None`, `max_agent_output_tokens == RunAnalysisRequest.model_fields["max_agent_output_tokens"].default`; `auto_paper_trade is False`.
  - `test_public_run_rejects_bad_ticker`: `"DROP TABLE"`, `"TOOLONG"`, `""` → 422.
  - `test_public_run_429_after_limit`: 4th POST from the same `X-Forwarded-For` → 429, body `detail` contains `"limit"`, header `Retry-After` present.
  - `test_slot_released_when_job_raises`: fake job raises; after 3 sequential runs with `max_concurrent=1`, the limiter still accepts (no leaked slot).
  - `test_admin_run_bypasses_limits_and_keeps_params`: with `X-API-Key: test-key`, 5 POSTs → all 200; recorded `provider == "openai"`, `max_agent_output_tokens == 99999`, `auto_paper_trade is None`.
- [ ] **Step 3: Run** `pytest tests/test_rate_limit.py tests/routers/test_analysis_public.py -v`. Expected: FAIL (import errors).
- [ ] **Step 4: Add settings** `public_runs_per_ip_per_hour: int = 3`, `public_runs_per_day: int = 30`, `public_max_concurrent_runs: int = 2` to `config.Settings`.
- [ ] **Step 5: Implement `backend/rate_limit.py`** (per-IP deque of timestamps, global deque, int counter) and change `run_analysis(req, request: Request)`. If `is_admin(request)`, keep today's behaviour. Otherwise: validate the ticker (422 `"Ticker must look like AAPL or BRK.B"`), `limiter.acquire(client_ip(request))` → on failure raise 429 with a reason-specific human message ("Live run limit reached for now; try one of the example briefs or come back in N minutes.") and `Retry-After`; build a clamped `RunAnalysisRequest(ticker=..., provider=settings.llm_provider)`. Start the thread with a wrapper that calls `run_analysis_job(job, clamped, auto_paper_trade=False)` in `try/finally: limiter.release()`.
- [ ] **Step 6: Run** both test files plus `pytest tests/test_orchestrator.py -q`. Expected: PASS.
- [ ] **Step 7: Commit** `git commit -m "feat(analysis): clamp and rate-limit public live runs; no paper trades from public"`

### Task 3: Generate static example briefs and evidence data

**Files:**
- Create: `scripts/build_showcase.py`, `scripts/build_evidence.py`
- Create (generated, committed): `frontend/public/showcase/index.json`, `frontend/public/showcase/{NVDA,JPM,KO,XOM}.json`, `frontend/public/evidence/three_series.json`
- Test: `tests/test_build_evidence.py`

**Interfaces:**
- Produces the static JSON contracts the frontend reads:
  - `showcase/index.json`: `{"generated_at": str, "briefs": [{"ticker": str, "company_name": str, "verdict": str, "conviction": str, "price_target": float|null, "entry_price": float|null, "has_conflicts": bool, "run_at": str}]}`
  - `showcase/<TICKER>.json`: `{"run_at": str, "result": AnalysisResult.model_dump()}`
  - `evidence/three_series.json`: `{"generated_at": str, "config": {...}, "series": {name: {"sharpe","sortino","ann_return_pct","max_dd_pct","total_return_pct","days"}}, "attribution": {...}, "curve": [{"date": "YYYY-MM-DD", "SPY": float, "Quant-only": float, "AI-augmented": float}]}`. `curve` is cumulative growth of $1, weekly (last trading day of each ISO week), NaN returns treated as 0.
- `build_evidence.to_payload(latest: dict, returns: pandas.DataFrame) -> dict`

- [ ] **Step 1: Write the failing test** `tests/test_build_evidence.py::test_payload_from_repo_files`: load the real `docs/eval/three_series_llm/latest.json` and CSV; assert `series["SPY"]["sharpe"] == 0.74`, `series["Quant-only"]["sharpe"] == 1.15`, `series["AI-augmented"]["sharpe"] == 1.01`; `curve[0]` values are within 0.05 of 1.0; `curve` is date-ascending; `len(curve)` is between 300 and 400; no value is NaN. Plus `test_nan_first_row_treated_as_zero` with a 3-row synthetic frame whose first SPY value is empty.
- [ ] **Step 2: Run** `pytest tests/test_build_evidence.py -v`. Expected: FAIL. Then implement `to_payload` + a `__main__` that writes the file. Map `latest.json` series keys onto the field names above. Run again → PASS.
- [ ] **Step 3: Implement `scripts/build_showcase.py`** with args `--tickers NVDA JPM KO XOM --out frontend/public/showcase`. It runs the orchestrator directly (same entry `run_analysis_job` uses) with server defaults and `auto_paper_trade=False`, writes one file per ticker and the index, and prints each ticker's `signal_conflicts`. If none of the four has conflicts it exits non-zero with "No brief shows agent disagreement; swap a ticker". The agreement/disagreement panel is the point of the page.
- [ ] **Step 4: Run the scripts for real** (costs about 4 live runs): `python scripts/build_showcase.py --tickers NVDA JPM KO XOM` then `python scripts/build_evidence.py`. Expected: 5 showcase files + 1 evidence file; at least one brief with conflicts. Spot-check one brief: `verdict` is present and `signal_breakdown` has all six agents.
- [ ] **Step 5: Commit** `git commit -m "feat(showcase): static example briefs and three-series evidence data"`

### Task 4: Public shell, routing, and the lab gate

**Files:**
- Create: `src/lib/adminKey.ts`, `src/lib/showcase.ts`, `src/components/layout/PublicLayout.tsx`, `src/pages/HomePage.tsx`, `src/pages/LabGatePage.tsx`, `src/lib/showcase.test.ts`
- Modify: `src/App.tsx`, `src/api/client.ts:8-21`, `src/components/layout/AppSidebar.tsx`, `frontend/package.json`

**Interfaces:**
- Consumes: `showcase/index.json` contract from Task 3.
- Produces:
  - `getAdminKey(): string | null`, `setAdminKey(k: string): void`, `clearAdminKey(): void` (localStorage key `afa.adminKey`, every access in try/catch).
  - `type ShowcaseIndexEntry` and `fetchShowcaseIndex(): Promise<ShowcaseIndexEntry[]>`, `fetchShowcaseBrief(ticker: string): Promise<{run_at: string; result: AnalysisResult} | null>` (null on 404).
  - `resolveTickerRoute(input: string, examples: string[]): string`. Returns `/brief/NVDA` when the normalized ticker is an example, else `/run?ticker=XYZ`.
  - Routes: `/` HomePage, `/brief/:ticker` BriefPage, `/run` LiveRunPage, `/evidence` EvidencePage (pages from Tasks 5–6), `/lab` LabGatePage, and under `/lab/*` the existing AnalysisPage, StockDeepDivePage, BacktestPage, Modal pages, PaperTradingPage wrapped in `AppLayout`. Redirects: `/analysis` → `/`; `/backtest/*`, `/paper-trading`, `/stock/:ticker`, `/deepdive/:ticker` → the same path under `/lab`.

- [ ] **Step 1: Add Vitest.** Add `vitest` to devDependencies and a `"test": "vitest run"` script.
- [ ] **Step 2: Write the failing test** `src/lib/showcase.test.ts` → `test resolveTickerRoute`: `(" nvda ", ["NVDA","JPM"]) → "/brief/NVDA"`; `("amd", ["NVDA"]) → "/run?ticker=AMD"`; `("brk.b", []) → "/run?ticker=BRK.B"`. Run `npm test`. Expected: FAIL.
- [ ] **Step 3: Implement** the lib files. `client.ts` `request()` adds `X-API-Key: getAdminKey()` when one is set. `PublicLayout`: a top bar with "AI Financial Analyst", links Examples (`/`), How it performs (`/evidence`), View code (GitHub repo), and a footer with the disclaimer; no sidebar; usable at 375px. `HomePage`: one-line pitch (reuse the portfolio one-liner), ticker input using `resolveTickerRoute`, and a grid of example cards from `fetchShowcaseIndex` (ticker, company, verdict badge, price target, "Agents disagree" chip when `has_conflicts`). `LabGatePage`: a password-type input that saves the key, then links to `/lab/analysis`. `AppSidebar`: brand text `AI Financial Analyst · Lab`, nav paths prefixed `/lab`, plus a "Public site" link and a "Lock lab" action calling `clearAdminKey`. Update internal `navigate()`/`<Link>` targets in lab pages to the `/lab` prefix (`grep -rn '"/backtest\|"/stock\|"/deepdive\|"/paper-trading\|"/analysis' src`).
- [ ] **Step 4: Run** `npm test && npm run build`. Expected: PASS, no type errors.
- [ ] **Step 5: Commit** `git commit -m "feat(frontend): public shell, example-aware routing, admin-gated /lab"`

### Task 5: The brief page

**Files:**
- Create: `src/lib/brief.ts`, `src/lib/brief.test.ts`, `src/components/brief/BriefView.tsx`, `src/components/brief/AgentConsensus.tsx`, `src/pages/BriefPage.tsx`, `src/pages/LiveRunPage.tsx`

**Interfaces:**
- Consumes: `fetchShowcaseBrief` (Task 4); existing `useAnalysis`, `ProgressStream`, `AgentReportTabs`, `AnalysisResult`.
- Produces:
  - `type AgentStance = { agent: "dcf"|"risk"|"earnings"|"competitive"|"pattern"|"macro"; label: string; score: number; weight: number; stance: "bullish"|"neutral"|"bearish" }`
  - `buildConsensus(verdict: Record<string, any> | null): AgentStance[]`. Reads `signal_breakdown`, keeps the fixed agent order above, labels `DCF, Risk, Earnings, Competitive, Pattern, Macro`, and sets stance by `score >= 0.2` bullish, `<= -0.2` bearish, else neutral. Returns `[]` when absent.
  - `parseConflict(code: string): string | null`. `"risk_bearish_vs_earnings_bullish"` → `"Risk (bearish) vs Earnings (bullish)"`; returns null when the code doesn't match `<agent>_<stance>_vs_<agent>_<stance>`.
  - `upsidePct(entry: number | null | undefined, target: number | null | undefined): number | null`. Returns `(target/entry - 1) * 100`, null if either is missing or `entry <= 0`.
  - `<BriefView result runAt? isExample />`

- [ ] **Step 1: Write the failing tests** in `src/lib/brief.test.ts` for the three helpers: the cases above, plus `buildConsensus(null)` → `[]`; `buildConsensus({})` → `[]`; `upsidePct(210.35, 242)` ≈ `15.05` (toBeCloseTo 2); `upsidePct(null, 242)` → null; `upsidePct(0, 242)` → null; `parseConflict("garbage")` → null. Run `npm test`. Expected: FAIL.
- [ ] **Step 2: Implement `src/lib/brief.ts`**, then run `npm test`. Expected: PASS.
- [ ] **Step 3: Build `BriefView`**, top to bottom:
  1. Header: ticker, company, verdict badge (reuse the `verdictClassName` logic from `ResultView.tsx`, moved into `brief.ts`), conviction, price target with upside %, time horizon, and "Example run from <date>" when `isExample`.
  2. `AgentConsensus`: six rows with a centered −1…+1 bar per agent, a weight label, and stance color tokens (`--positive`/`--negative`/`--warning`); under it, the parsed conflicts as "Where the agents disagreed". The panel is hidden when `buildConsensus` is empty.
  3. Synthesis rendered with the existing markdown renderer used by `AgentReportTabs`.
  4. "Read each analyst's report": `AgentReportTabs`, collapsed by default.
  5. Sources: `enrichment_sources` as a list.
  6. Disclaimer line.
  No Diagnostics tab and no "Download Text" on the public view.
- [ ] **Step 4: Build the pages.** `BriefPage` loads `fetchShowcaseBrief(ticker)`; on null it shows "No example for TICKER" with a "Run it live" button to `/run?ticker=`. `LiveRunPage` reads `?ticker`, starts `useAnalysis().run({ticker})` once on mount (make every field except `ticker` optional in the TS `RunAnalysisRequest` in `src/api/types.ts`; the server fills defaults) (with a ref guard against StrictMode double-run), shows `ProgressStream`, then `BriefView`. On a 429 it shows the server's message and links to the examples; other errors show a retry button.
- [ ] **Step 5: Verify in the browser.** Run `npm run dev` with the backend running locally. Open `/brief/NVDA`: the consensus grid shows 6 rows and the conflicts render. Open a brief with no conflicts: the "Where the agents disagreed" section is absent. Check at 375px width: no horizontal scroll. Open `/run?ticker=AMD`: progress streams, then the brief renders.
- [ ] **Step 6: Commit** `git commit -m "feat(frontend): brief view with agent consensus; live run page"`

### Task 6: "How it performs" page

**Files:**
- Create: `src/lib/evidence.ts`, `src/lib/evidence.test.ts`, `src/pages/EvidencePage.tsx`

**Interfaces:**
- Consumes: `evidence/three_series.json` (Task 3).
- Produces: `type EvidencePayload`; `fetchEvidence(): Promise<EvidencePayload>`; `formatDelta(a: number, b: number): string` (`formatDelta(1.01, 1.15)` → `"−0.14"` with a true minus sign, `formatDelta(1.15, 0.74)` → `"+0.41"`).

- [ ] **Step 1: Write the failing test** for `formatDelta` (the two cases above, plus `formatDelta(1, 1)` → `"0.00"`). Run → FAIL; implement → PASS.
- [ ] **Step 2: Build `EvidencePage`.** Headline: "Adding the LLM agents made the backtest worse." A three-row stat table (Sharpe, Sortino, annual return, max drawdown) for SPY / Quant-only / AI-augmented. A recharts `LineChart` of `curve` on a log y-axis (three series, legend, date x-axis by year). Then the fixed copy below, verbatim:
  > In a 2018–2025 backtest (10 positions), the quantitative screen alone had a Sharpe ratio of 1.15 against 0.74 for SPY; adding the LLM agents lowered it to 1.01. Survivorship bias and LLM look-ahead are not corrected, so treat these as upper bounds.

  Close with "What this means for the app": the agents are shown here as a research and explanation layer, not as the source of returns. Include the disclaimer.
- [ ] **Step 3: Verify** `/evidence` in the browser in light and dark, at desktop and 375px: the chart renders and the numbers match the table in `docs/eval/three_series_llm/latest.md`.
- [ ] **Step 4: Commit** `git commit -m "feat(frontend): evidence page from three-series eval"`

### Task 7: Repo hygiene, README, deploy, portfolio link

**Files:**
- Modify: `README.md` (top section), `.gitignore` (verify the patterns already cover the root artifacts)
- Remove from the index: the 13 tracked root `phase0_*.json` / `backtest_*.json` files
- Modify: `~/portfolio-site/index.html:167` (separate repo, separate commit)

- [ ] **Step 1: Untrack the artifacts.** Run `git ls-files | grep -E '^(phase0_|backtest_bt_|backtest_wf_)' | xargs git rm --cached`; then `git ls-files | grep -cE '^(phase0_|backtest_)'` → `0`. Files stay on disk.
- [ ] **Step 2: Rewrite the top of the README** in this order: a screenshot of `/brief/NVDA` (save it to `docs/img/brief.png`), the live link, a two-sentence description, the evidence result with the same caveat sentence as Task 6, then "Run locally". Move the roadmap and NORTHSTAR material below a "Research notes" heading. Don't delete it.
- [ ] **Step 3: Run the full suite.** Run `pytest -q && (cd frontend && npm test && npm run build)`. Expected: all PASS.
- [ ] **Step 4: Commit** `git commit -m "chore: untrack run artifacts; README leads with the product"`
- [ ] **Step 5: Deploy and smoke-test** (needs Chad's go-ahead: production change). Push to main; confirm Railway and Vercel deploys succeed. Then on the production URL:
  - `/analysis` redirects to `/`.
  - Example briefs load with the backend unreachable (check the network panel: no `/api` calls on `/` or `/brief/*`).
  - `curl -X POST <prod>/api/paper-trading/rebalance` → 403.
  - A 4th live run within an hour from one IP → 429 message shown.
  - `/lab` with the key → lab works.
- [ ] **Step 6: Update the portfolio link.** In `~/portfolio-site/index.html`, change the "Try the live app" href from `/analysis` to the site root, and swap the thumbnail for a `/brief` screenshot if it reads better. Commit there with `git commit -m "Point AI Financial Analyst link at the showcase home"`.
