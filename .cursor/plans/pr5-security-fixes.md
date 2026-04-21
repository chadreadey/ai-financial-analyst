# PR #5 Security Fix Plan — Modal CPCV Router

Branch: `modal-backtesting`  
Reviewed: 2026-04-21  
Owner: senior engineer / Cursor / Codex  

Execute findings in the order listed in the Sequencing section at the bottom.

---

## Finding 1 — Unauthenticated backtest router (burn-money POST + full history GETs)

- **Severity:** Critical
- **File + line:** `backend/routers/backtest_modal.py:19`, `backend/main.py:94`

- **Exploit scenario:** Any unauthenticated caller on the internet can POST to
  `https://<host>/api/backtest/modal` with a payload such as
  `{"universe":"sp500"}` and immediately trigger a Modal GPU run billed to your
  account. The same caller can enumerate every run via `GET /api/backtest/modal/runs`
  and extract full trade-level signal vectors (including `signals_at_entry_json`)
  from `GET /api/backtest/modal/runs/{run_id}/trades` with no credential required.

- **Proposed fix:**

  **Step 1 — Add `INTERNAL_API_KEY` to `config.py`**

  In `config.py`, inside the `Settings` class, add the following field after the
  existing Alpaca keys block:

  ```python
  # ── Internal service auth ────────────────────────────────────────────
  internal_api_key: str = Field(
      default="",
      description=(
          "Shared secret for internal API endpoints (backtest dispatch, etc). "
          "Must be set in production. Generate with: python -c \"import secrets; print(secrets.token_hex(32))\""
      ),
  )
  ```

  **Step 2 — Create the FastAPI dependency in `backend/routers/backtest_modal.py`**

  Add the following import and dependency function at the top of
  `backend/routers/backtest_modal.py`, after the existing imports:

  ```python
  from fastapi import Depends, Header, HTTPException, status
  from config import settings


  def _require_api_key(x_api_key: str = Header(..., alias="X-API-Key")) -> None:
      """Dependency: validates X-API-Key against INTERNAL_API_KEY env var.

      Raises 403 (not 401) to avoid leaking that the endpoint exists and
      requires auth — returning 401 would invite credential-stuffing loops.
      Raises 500 at startup-time if the key is not configured so misconfigured
      deployments fail loudly.
      """
      configured = settings.internal_api_key
      if not configured:
          raise HTTPException(
              status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
              detail="Server misconfigured: INTERNAL_API_KEY not set.",
          )
      # Use hmac.compare_digest to prevent timing-oracle attacks.
      import hmac
      if not hmac.compare_digest(configured, x_api_key):
          raise HTTPException(
              status_code=status.HTTP_403_FORBIDDEN,
              detail="Forbidden.",
          )
  ```

  **Step 3 — Wire the dependency onto the router at `backend/routers/backtest_modal.py:19`**

  Replace the bare `router = APIRouter()` declaration with:

  ```python
  router = APIRouter(dependencies=[Depends(_require_api_key)])
  ```

  This applies the dependency to every route registered on this router — all 8
  endpoints — without touching individual handler signatures.

  **Step 4 — Frontend: send the header via the existing fetch wrapper**

  The project's single fetch wrapper is `frontend/src/api/client.ts`, in the
  `request<T>` function (line 3). Update the `headers` object to include the
  key pulled from a Vite env var:

  ```ts
  async function request<T>(path: string, options?: RequestInit): Promise<T> {
    const apiKey = import.meta.env.VITE_INTERNAL_API_KEY ?? "";
    const res = await fetch(`${API_URL}${path}`, {
      headers: {
        "Content-Type": "application/json",
        ...(apiKey ? { "X-API-Key": apiKey } : {}),
      },
      ...options,
    });
    // ... rest unchanged
  }
  ```

  Do not hard-code the key value. Set `VITE_INTERNAL_API_KEY` in the Vercel
  project's Environment Variables dashboard (Production + Preview environments).

  Note: Vite bakes `VITE_*` vars into the JS bundle at build time. For this
  project (single-user, internal tool) that is acceptable. If this ever becomes
  multi-tenant, move dispatch to a server-side proxy and keep the key out of
  the bundle entirely.

  **Step 5 — Rotate the key if it leaks**

  1. Generate a new key: `python -c "import secrets; print(secrets.token_hex(32))"`
  2. Update `INTERNAL_API_KEY` in the Railway dashboard (Environment Variables).
  3. Update `VITE_INTERNAL_API_KEY` in the Vercel dashboard (Environment Variables).
  4. Trigger a Railway redeploy (backend picks it up immediately on next request
     because `Settings` is instantiated at import time — a restart is required).
  5. Trigger a Vercel redeploy (frontend bundle must be rebuilt to bake the new
     `VITE_INTERNAL_API_KEY` value).
  6. Old key is dead as soon as the backend restarts. There is no key-versioning
     mechanism here; the window between Railway deploy and Vercel deploy will
     produce 403s for any in-flight frontend requests, which is acceptable.

- **Why minimal:** One dependency function + one `APIRouter(dependencies=[...])` +
  one `Settings` field covers all 8 routes without per-handler changes.

- **Test to add:** `backend/tests/test_backtest_modal_auth.py`

  ```python
  import pytest
  from fastapi.testclient import TestClient
  from unittest.mock import patch

  GOOD_KEY = "test-secret-key-abc123"

  @pytest.fixture(autouse=True)
  def patch_settings():
      with patch("backend.routers.backtest_modal.settings") as m:
          m.internal_api_key = GOOD_KEY
          yield m

  @pytest.fixture
  def client():
      from backend.main import app
      return TestClient(app)

  def test_list_runs_unauthenticated_returns_403(client):
      r = client.get("/api/backtest/modal/runs")
      assert r.status_code == 403

  def test_dispatch_unauthenticated_returns_403(client):
      r = client.post("/api/backtest/modal", json={"universe": "liquid_10"})
      assert r.status_code == 403

  def test_dispatch_wrong_key_returns_403(client):
      r = client.post(
          "/api/backtest/modal",
          json={"universe": "liquid_10"},
          headers={"X-API-Key": "wrong-key"},
      )
      assert r.status_code == 403

  def test_list_runs_authenticated_succeeds(client):
      # Patch reader to return empty list so no DB needed.
      with patch("backend.backtest_reader.list_runs", return_value=[]), \
           patch("backend.cpcv_sqlite.sweep_stale_runs"), \
           patch("backend.supabase_backtest.sweep_stale_runs"):
          r = client.get(
              "/api/backtest/modal/runs",
              headers={"X-API-Key": GOOD_KEY},
          )
      assert r.status_code == 200
  ```

- **Deployment / rollout:**
  1. Generate key locally: `python -c "import secrets; print(secrets.token_hex(32))"`
  2. Set `INTERNAL_API_KEY=<value>` in Railway dashboard (service: ai-financial-analyst,
     Environment: production).
  3. Deploy backend to Railway. Verify `GET /api/backtest/modal/runs` returns 403
     without the header from curl.
  4. Set `VITE_INTERNAL_API_KEY=<same value>` in Vercel dashboard
     (project: ai-financial-analyst, Environment: Production and Preview).
  5. Trigger Vercel redeploy (or push any commit). Verify the UI can still list
     and dispatch runs.
  6. If step 5 fails, the backend key is already enforced — the frontend will
     show 403 errors until Vercel is fixed. That is a degraded-but-safe state,
     not a security regression.

- **Risk if wrong:** If `INTERNAL_API_KEY` is left empty in production, the
  dependency raises HTTP 500 on every request, which is visible but safe — it
  blocks all access including legitimate use until the env var is set.

---

## Finding 2 — No ticker count cap or format validation on `ModalCPCVRequest.tickers`

- **Severity:** Important
- **File + line:** `backend/routers/backtest_modal.py:29`, `backend/routers/backtest_modal.py:68`

- **Exploit scenario:** An authenticated caller (or someone who obtains the API
  key) posts `{"tickers": ["AAPL", "GOOG", ... <500 items>]}`. The handler
  uppercases and passes all 500 tickers to `BacktestConfig` and then to
  `kickoff_cpcv_background`, launching a 500-ticker Modal job. A second attack
  surface: tickers like `"../etc/passwd"` or a 10 KB string pass through
  `t.upper().strip()` unmodified and reach `BacktestConfig` and ultimately any
  downstream file-path construction or log lines without rejection.

- **Proposed fix:**

  Replace the `tickers` field declaration at line 29 and the inline processing
  loop at lines 67–68 as follows.

  Field declaration (in `ModalCPCVRequest`):

  ```python
  import re
  from pydantic import field_validator

  _TICKER_RE = re.compile(r'^[A-Z]{1,5}$')

  class ModalCPCVRequest(BaseModel):
      tickers: Optional[list[str]] = Field(
          default=None,
          max_length=50,   # Pydantic v2: enforces list item count
          description="Up to 50 ticker symbols. Each must match [A-Z]{1,5}.",
      )
      # ... rest of fields unchanged

      @field_validator("tickers", mode="before")
      @classmethod
      def validate_tickers(cls, v: object) -> object:
          if v is None:
              return v
          if not isinstance(v, list):
              raise ValueError("tickers must be a list")
          if len(v) > 50:
              raise ValueError(f"tickers list exceeds 50-item limit (got {len(v)})")
          cleaned = []
          for raw in v:
              if not isinstance(raw, str):
                  raise ValueError(f"each ticker must be a string, got {type(raw)}")
              t = raw.upper().strip()
              if not _TICKER_RE.match(t):
                  raise ValueError(
                      f"Invalid ticker {raw!r}. Must be 1–5 uppercase ASCII letters."
                  )
              cleaned.append(t)
          return cleaned
  ```

  Remove the inline `.upper().strip()` loop at lines 67–68 in
  `dispatch_modal_cpcv` since validation now happens in the model:

  ```python
  # Before (lines 66-68):
  if payload.tickers:
      tickers = [t.upper().strip() for t in payload.tickers if t and t.strip()]

  # After:
  if payload.tickers:
      tickers = list(payload.tickers)   # already validated + uppercased by the model
  ```

  The 50-ticker ceiling aligns with the project's `liquid_50` universe maximum.
  If a larger sweep is ever needed, it should be launched via the named-universe
  path (`universe="liquid_50"`) rather than an unbounded ticker list.

- **Why minimal:** The validator runs inside Pydantic at deserialization time —
  no middleware, no separate route wrapper.

- **Test to add:** `backend/tests/test_backtest_modal_validation.py`

  ```python
  import pytest
  from backend.routers.backtest_modal import ModalCPCVRequest
  from pydantic import ValidationError

  def test_too_many_tickers_rejected():
      with pytest.raises(ValidationError, match="50"):
          ModalCPCVRequest(tickers=["AAPL"] * 51)

  def test_invalid_ticker_format_rejected():
      for bad in ["../etc/passwd", "TOOLONG", "123", "", " "]:
          with pytest.raises(ValidationError):
              ModalCPCVRequest(tickers=[bad])

  def test_valid_tickers_accepted():
      req = ModalCPCVRequest(tickers=["aapl", "goog", "msft"])
      assert req.tickers == ["AAPL", "GOOG", "MSFT"]

  def test_none_tickers_with_universe_accepted():
      req = ModalCPCVRequest(universe="liquid_20")
      assert req.tickers is None
  ```

- **Deployment / rollout:** Backend-only change. No env vars. Deploy to Railway.
  Existing valid requests from the frontend (which sends short named-universe
  payloads) are unaffected. Any integration test that posts more than 50 tickers
  will start failing — update those tests to use the named-universe path.

- **Risk if wrong:** Overly strict regex rejects legitimate tickers (e.g.,
  `BRK.B`, `BF.B`). The current universe sets (`liquid_10/20/50`) contain only
  plain alpha tickers so this is low risk. If dot-tickers are needed later,
  expand the regex to `r'^[A-Z]{1,4}(\.[A-Z])?$'`.

---

## Finding 3 — Supabase RLS policies allow anon reads and writes

- **Severity:** Important
- **File + line:** `supabase/migrations/0001_backtest_tables.sql:68,95,129,148`

- **Exploit scenario:** If the Supabase anon key is ever exposed to a browser
  (e.g., via `VITE_SUPABASE_ANON_KEY`), any unauthenticated user can read the
  full `backtest_runs`, `backtest_combinations`, `backtest_trades`, and
  `backtest_events` tables — including `config_json` (tickers, dates, signal
  weights) and `signals_at_entry_json` (full per-trade signal vector). The
  `WITH CHECK (true)` clause also allows anon INSERT/UPDATE/DELETE directly
  against the tables, bypassing the FastAPI layer entirely.

- **Proposed fix (framing only — DB migration shape belongs to the DB plan):**

  Each of the four `CREATE POLICY "allow all ..."` statements should be replaced
  with service-role-only policies. The pattern is:

  ```sql
  -- Drop the permissive allow-all policy
  DROP POLICY IF EXISTS "allow all backtest_runs" ON backtest_runs;

  -- Read: service role only (anon and authenticated roles cannot read)
  CREATE POLICY "service_role read backtest_runs"
      ON backtest_runs FOR SELECT
      USING (auth.role() = 'service_role');

  -- Write: service role only
  CREATE POLICY "service_role write backtest_runs"
      ON backtest_runs FOR ALL
      USING (auth.role() = 'service_role')
      WITH CHECK (auth.role() = 'service_role');
  ```

  Apply the same pattern to `backtest_combinations`, `backtest_trades`, and
  `backtest_events`.

  The `supabase_backtest.py` backend wrapper authenticates using
  `settings.supabase_service_key` (a server-side env var), so it will continue
  to work. No frontend code currently calls Supabase directly for these tables —
  all reads go through the FastAPI read-side endpoints.

  See the DB migration plan for the exact migration file and rollout steps.

- **Why minimal:** RLS change is a two-line DROP + two-line CREATE per table;
  no application code changes required.

- **Test to add:** Not in this plan — verify via Supabase SQL editor that
  `SET ROLE anon; SELECT * FROM backtest_runs;` returns zero rows after the
  migration is applied. Add to DB plan test checklist.

- **Deployment / rollout:** Apply via `supabase db push` or paste into the
  Supabase SQL editor. No Railway/backend changes required. Verify
  `supabase_backtest.py` writes still succeed (smoke test: dispatch one run,
  confirm row appears in `backtest_runs`).

- **Risk if wrong:** If the migration is applied before confirming the
  `supabase_service_key` is set in Railway, all backend writes will fail with
  RLS violations. Verify `SUPABASE_SERVICE_KEY` is set in Railway env vars
  before running the migration.

---

## Finding 4 — CORS `allow_origin_regex` matches any Vercel tenant

- **Severity:** Important
- **File + line:** `backend/main.py:73`

- **Exploit scenario:** The regex `r"https://.*\.vercel\.app"` matches
  `https://evil-app.vercel.app`. Any attacker who deploys a free Vercel project
  can make credentialed cross-origin requests (`allow_credentials=True`) to your
  Railway backend from a browser. Combined with Finding 1 (now fixed), this was
  an open door. After Finding 1 is fixed the practical blast radius is reduced,
  but a malicious Vercel tenant can still read run history and trade data if a
  user's browser is tricked into visiting the attacker's page while authenticated.

- **Proposed fix:**

  In `backend/main.py`, replace the `allow_origin_regex` line at line 73 with
  a pinned pattern matching only your Vercel project slug. If your Vercel project
  slug is `ai-financial-analyst` (check Vercel dashboard — it appears in the
  default `.vercel.app` domain), the replacement is:

  ```python
  # Replace line 73:
  allow_origin_regex=r"https://.*\.vercel\.app",

  # With (substitute your actual PROJECT-SLUG):
  allow_origin_regex=r"https://ai-financial-analyst(-[a-z0-9]+)?\.vercel\.app",
  ```

  The `(-[a-z0-9]+)?` suffix matches Vercel's preview deployment subdomains
  (e.g., `ai-financial-analyst-git-modal-backtesting-chadreadey.vercel.app`)
  while excluding all other tenants.

  If the exact slug is unknown, look it up: in the Vercel dashboard go to the
  project, click Settings > Domains. The canonical production domain is
  `<PROJECT-SLUG>.vercel.app`. Use that slug literally in the regex.

  Alternatively, enumerate the exact preview patterns and use `allow_origins`
  (list) instead of a regex, adding preview URLs explicitly via the existing
  `CORS_ORIGINS` env var mechanism already present at line 67:

  ```
  CORS_ORIGINS=https://ai-financial-analyst.vercel.app,https://ai-financial-analyst-git-modal-backtesting-chadreadey.vercel.app
  ```

  and remove the `allow_origin_regex` line entirely. This is more explicit but
  requires updating `CORS_ORIGINS` each time a new preview branch is created.

- **Why minimal:** One line change in `main.py`; no dependency installs; the
  `CORS_ORIGINS` env-var escape hatch already exists for adding origins.

- **Test to add:** `backend/tests/test_cors.py`

  ```python
  from fastapi.testclient import TestClient
  from backend.main import app

  client = TestClient(app)

  def test_cors_evil_vercel_tenant_rejected():
      r = client.options(
          "/api/backtest/modal/runs",
          headers={
              "Origin": "https://evil-attacker.vercel.app",
              "Access-Control-Request-Method": "GET",
          },
      )
      assert "evil-attacker.vercel.app" not in r.headers.get(
          "access-control-allow-origin", ""
      )

  def test_cors_own_vercel_project_allowed():
      r = client.options(
          "/api/backtest/modal/runs",
          headers={
              "Origin": "https://ai-financial-analyst.vercel.app",
              "Access-Control-Request-Method": "GET",
          },
      )
      assert r.headers.get("access-control-allow-origin") == (
          "https://ai-financial-analyst.vercel.app"
      )
  ```

  Substitute the actual project slug in the test.

- **Deployment / rollout:**
  1. Confirm your Vercel project slug from the Vercel dashboard.
  2. Update `allow_origin_regex` in `backend/main.py` with the pinned pattern.
  3. Deploy backend to Railway.
  4. Open the deployed frontend in a browser and verify the backtest explorer
     loads without CORS errors (check browser console).
  5. If preview deployments break, add their URLs to `CORS_ORIGINS` in the
     Railway env var dashboard rather than widening the regex.

- **Risk if wrong:** If the regex is too narrow, the frontend gets CORS errors
  in production or preview deployments. The fix is to update `CORS_ORIGINS` in
  Railway without a code deploy — the existing `_extra` merge at line 67 handles
  this at runtime.

---

## Sequencing

Execute in this order to avoid a window where the backend is hardened but the
frontend is broken, or vice versa:

1. **Finding 2 first** (ticker validation) — backend-only, no coordination
   required, zero user impact.
2. **Finding 4** (CORS pin) — backend-only, deploy to Railway, verify frontend
   still works from Vercel.
3. **Finding 1** (API key auth) — generate key, set Railway env var, deploy
   backend, set Vercel env var, redeploy frontend, verify end-to-end, then
   smoke-test that unauthenticated curl returns 403.
4. **Finding 3** (RLS) — after Finding 1 is live (so even if the Supabase
   service key is confirmed server-side before locking down RLS). Coordinate
   with DB plan.

Do not apply Finding 3 before Finding 1. If RLS is locked to service-role-only
before the backend auth gate is up, a brief outage window exists where neither
the API nor direct PostgREST access works.

---

## Cross-refs

- **Finding 3 (RLS migration)** — the exact SQL shape, migration filename, and
  `supabase db push` rollout belong to a separate DB migration plan. This plan
  owns only the security framing: anon policies must be replaced with
  service-role-only policies before the Supabase anon key is ever used in a
  browser context.
- **Finding 1 (API key in Vite bundle)** — if this project becomes multi-tenant
  or public, dispatch must move behind a server-side proxy (Next.js API route,
  Vercel Edge Function, etc.) so `VITE_INTERNAL_API_KEY` is never shipped to
  the browser. That is out of scope for this PR.

---

## Deferred / out-of-scope

The following item was acknowledged in the PR body and must not be lost:

**Split Supabase secret from admin secret in Modal** — the Modal CPCV worker
currently receives `SUPABASE_SERVICE_KEY` (admin-level) to write backtest
results. The correct fix is a write-only Supabase key scoped to insert on
`backtest_runs`, `backtest_combinations`, `backtest_trades`, and
`backtest_events` only (via a Postgres role with `GRANT INSERT` and no `SELECT`
or `DELETE`). This limits blast radius if the Modal container environment is
compromised. Not addressed in this PR — track as a follow-up task.
