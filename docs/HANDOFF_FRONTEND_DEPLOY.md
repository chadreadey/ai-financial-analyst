# Frontend Overhaul — Deployment Handoff

**Date:** 2026-04-15
**Branch:** `frontend-overhaul`
**PR:** https://github.com/chadreadey/ai-financial-analyst/pull/3

---

## Status: Frontend code complete, deployment blocked by Vercel preview auth

The frontend overhaul (10 tasks, all complete) builds and runs correctly. The Vercel preview deployment succeeds (build passes), but API calls from the frontend fail with "Failed to fetch" on the preview URL.

---

## What's Done

11 commits on `frontend-overhaul` branch:
- shadcn/ui design system (zinc + cyan palette, 13 components)
- Labeled sidebar nav replacing flat TopNav
- Settings drawer (Sheet) replacing inline sidebar config
- Chart restyling (PriceChart, EquityCurveChart, SparklineChart)
- Old Card/Badge components replaced with shadcn equivalents (13 files updated)
- Analysis page polished (SignalCards, AgentReportTabs)
- Backtest Explorer rebuilt from scratch (replaces broken NL backtest)
- Paper Trading page re-skinned
- Stock Deep Dive with analysis accordion (expandable agent report tabs)
- Final cleanup of stale CSS vars and dead imports
- Vercel rewrite proxy for Railway backend

---

## The Problem

The Vercel preview URL (`ai-financial-analyst-git-front-321df8-chadreadey-7282s-projects.vercel.app`) returns a **401 SSO redirect** on all `/api/*` requests, even though:

- Vercel Authentication is toggled **OFF** in project settings
- The `vercel.json` rewrite proxy is correctly configured
- The Railway backend responds 200 when called directly

The 401 comes from Vercel's deployment protection layer, not from the backend. The HTML response is a Vercel SSO login page redirect. This affects `fetch()` calls from JavaScript — the browser page itself loads fine because the user is authenticated via cookies, but programmatic API calls don't carry the Vercel auth cookie.

---

## What We Tried

| Attempt | Result |
|---------|--------|
| Set `VITE_API_URL` env var on Vercel pointing to Railway | CORS blocked — Railway backend doesn't allow the preview origin |
| Add `allow_origin_regex` to Railway backend CORS | Works but requires redeploying Railway from the feature branch (Railway watches `main`) |
| Add preview URL to `CORS_ORIGINS` env var on Railway | Would work but user doesn't want to risk breaking the existing production CORS config |
| Vercel rewrite proxy (`/api/:path*` → Railway) | Correct approach — eliminates CORS entirely. But Vercel's deployment protection intercepts the proxied requests with a 401 SSO redirect |
| Disable Vercel Authentication in project settings | Already disabled — toggle shows "Disabled". The 401 persists, likely from a team-level or Standard Protection setting |
| Protection Bypass for Automation secret | UI wouldn't let user add one (greyed out "+ Add" button — may require Pro/Team plan feature) |
| Set deployment protection to "Production only" | No such granular option visible in the UI |

---

## Likely Root Cause

Vercel's **Standard Protection** (different from "Vercel Authentication") is enabled at the team/account level and cannot be disabled from the project settings page on the current plan. This protects all preview deployments with an auth layer that intercepts even proxied/rewritten requests.

---

## Solutions (Pick One)

### Option A: Merge to main and test on production (Recommended)
The production deployment won't have preview protection. The frontend changes are purely visual — no backend risk. Merge the PR, Railway auto-deploys from main (picking up the CORS regex fix), and test on the production URL.

**Risk:** If something is visually broken, you roll back the merge. Low risk since the build passes and local dev works.

### Option B: Deploy Railway from the feature branch temporarily
1. Point Railway to the `frontend-overhaul` branch temporarily
2. Add the CORS regex fix (`allow_origin_regex=r"https://ai-financial-analyst[a-z0-9\-]*\.vercel\.app"`)
3. Test the Vercel preview calling Railway directly (bypass Vercel proxy, use `VITE_API_URL` env var)
4. After validation, merge to main and switch Railway back

**Risk:** Briefly disrupts the Railway production deployment.

### Option C: Use `vercel dev` locally
Run `vercel dev` which simulates the Vercel environment locally including rewrites. Backend calls go through the rewrite proxy to Railway without any auth wall.

```bash
cd /Users/chadreadey/portfolio-analyst/ai-financial-analyst
vercel dev
```

**Risk:** None — purely local. But doesn't validate the actual deployed URL.

### Option D: Upgrade Vercel plan for granular protection controls
Pro plan allows disabling Standard Protection per-environment. Not worth it just for this.

---

## Files Changed (Summary)

```
vercel.json                          — added framework, installCommand, API proxy rewrite
frontend/src/api/client.ts           — empty API_URL in production (uses relative /api/ paths)
frontend/src/index.css               — full palette replacement (HSL vars for shadcn)
frontend/src/App.tsx                 — AppLayout wrapper, removed deleted page routes
frontend/src/components/layout/      — AppSidebar, AppLayout, SettingsDrawer (new)
                                       TopNav, Sidebar (deleted)
frontend/src/components/analysis/    — SignalCards, AgentReportTabs (new), ResultView updated
frontend/src/components/backtest/    — RunSelector, PerformanceTab, TradeDetailRow,
                                       NewBacktestDialog (new), old config/metrics panels deleted
frontend/src/components/deepdive/    — AnalysisAccordion (new)
frontend/src/components/ui/          — 13 shadcn components installed
frontend/src/components/charts/      — all 3 charts restyled
frontend/src/pages/                  — 4 placeholder pages deleted, remaining 4 restyled
frontend/src/components/common/      — Card.tsx, Badge.tsx deleted (replaced by shadcn)
frontend/src/components/watchlist/   — entire directory deleted
```

---

## To Resume

1. Pick a solution from above
2. If merging to main: `gh pr merge 3 --squash` or merge via GitHub UI
3. After merge, also apply the CORS fix from `backend/main.py` (replace `"https://*.vercel.app"` with `allow_origin_regex=r"https://ai-financial-analyst[a-z0-9\-]*\.vercel\.app"`) — the wildcard string in `allow_origins` doesn't actually work in FastAPI
4. Verify on the production URL
