# PR #5 TypeScript Fix Plan — modal-backtesting

> Scope: `frontend/src/` — hooks, pages, and components introduced in PR #5.
> All line numbers verified against the live branch as of review date.
> No line drift detected from the original review findings.

---

### Finding 1 — Stale closure in `useVisibilityInterval` stops polling on `runId` change

- **Severity:** Critical
- **File + line:** `frontend/src/hooks/useModalBacktests.ts:15-42`
- **Root cause:** The `useEffect` dep array is `[enabled, ms]`, with `cb` intentionally excluded via the `eslint-disable` comment at line 41. When a caller's `refresh` callback closes over `runId` (as in `useModalRun`, `useModalCombinations`, `useModalRunEvents`), the interval continues calling the stale closure after `runId` changes — silently polling the old run ID.
- **Proposed fix:** Introduce a stable ref that is updated on every render. The effect never needs `cb` in its dep array; the ref ensures the latest closure is always called at tick time.

```typescript
// frontend/src/hooks/useModalBacktests.ts — replace lines 15-43 in full

function useVisibilityInterval(
  cb: () => void | Promise<void>,
  ms: number,
  enabled: boolean,
): void {
  const cbRef = useRef(cb);
  // Keep ref current on every render — no extra effect, no dep-array change.
  cbRef.current = cb;

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const tick = async () => {
      if (cancelled) return;
      if (document.visibilityState === "visible") {
        try {
          await cbRef.current();
        } catch {
          // Swallow transient polling errors — caller error state handles first failure.
        }
      }
    };
    void tick();
    const handle = window.setInterval(tick, ms);
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
    // cb is accessed via ref; only interval identity matters here.
  }, [enabled, ms]);
}
```

The `eslint-disable-next-line react-hooks/exhaustive-deps` comment at the original line 41 must also be removed — it is no longer needed.

- **Why minimal:** Two lines added (`cbRef` declaration and assignment), one line changed (`cb()` → `cbRef.current()`), one comment removed.
- **Test / manual verification:** Open the detail page for run A while it is polling. Navigate to run B's detail page. In the Network tab confirm that all subsequent `/api/modal/runs/{id}` requests carry run B's ID, not run A's. A Vitest unit test is impractical here because testing setInterval behavior across React re-renders requires `vi.useFakeTimers` plus a full DOM environment — the browser smoke test is faster and more representative.
- **Risk of regression:** Low. The stable-ref pattern is the canonical React solution for this class of bug. The only semantic change is that `cbRef.current` is always the latest closure, which is the desired behavior and does not affect callers that never change their callback identity.

---

### Finding 2 — `setEvents([])` in effect body causes an extra render

- **Severity:** High
- **File + line:** `frontend/src/hooks/useModalBacktests.ts:188-191`
- **Root cause:** `setEvents([])` is called directly inside a `useEffect` body (not in a cleanup function). React runs the effect, schedules a re-render from `setEvents`, then runs child effects again — violating the `react-hooks/no-direct-set-state-in-use-effect` intent and causing a redundant render on every `runId` change.
- **Proposed fix:** Collapse the reset-and-fetch into a single effect:

```typescript
// frontend/src/hooks/useModalBacktests.ts — replace lines 187-195

  // Reset cursor and events when runId changes; fetch immediately.
  useEffect(() => {
    if (!runId) return;
    lastIdRef.current = null;
    setEvents([]);
    void refresh();
  }, [runId, refresh]);

  useVisibilityInterval(refresh, pollMs, !!runId && active && pollMs > 0);
```

Delete the standalone `useEffect(() => { lastIdRef.current = null; setEvents([]); }, [runId]);` that currently occupies lines 188-191. The `refresh` callback is already stable (its only dep is `runId`), so adding it to the dep array is correct and does not cause an infinite loop.

- **Why minimal:** Removes one `useEffect`, inlines two lines into the existing fetch effect.
- **Test / manual verification:** In React DevTools Profiler, navigate between two run detail pages. Before the fix the flamegraph shows two consecutive renders on navigation (state-reset render, then data render). After the fix only one render occurs.
- **Risk of regression:** Low. The behavior is identical — reset then fetch — just in a single render cycle.

---

### Finding 3 — Eight `any` annotations

- **Severity:** High
- **Files + lines:**
  - `frontend/src/hooks/useModalBacktests.ts:69,99,144,182,219,243` — `catch (e: any)`
  - `frontend/src/pages/ModalComboDetailPage.tsx:34` — `(t as any)[k]` in CSV exporter
  - `frontend/src/pages/ModalComboDetailPage.tsx:327` — `(trade.signals_at_entry_json as any)?.flags`
  - `frontend/src/pages/ModalRunDetailPage.tsx:320` — inline `Record<string, any>` in `EventsList` prop type
  - `frontend/src/pages/ModalRunDetailPage.tsx:370` — inline `Record<string, any>` in `ConfigCard` prop type
- **Root cause:** `catch (e: any)` bypasses TypeScript's `useUnknownInCatchVariables` strictness. The CSV cast forces an escape hatch that is unnecessary because `ModalTrade` is a typed interface. The inline `Record<string, any>` props duplicate information already present in `ModalEvent` and `ModalRun` from `types.ts`.

**Fix A — catch blocks (6 occurrences in `useModalBacktests.ts`):**

Add a private helper near the top of the file, after the imports:

```typescript
// frontend/src/hooks/useModalBacktests.ts — add after line 10

function toMessage(e: unknown, fallback: string): string {
  if (e instanceof Error) return e.message;
  if (typeof e === "string") return e;
  return fallback;
}
```

Replace every `catch (e: any)` block. Example for line 69:

```typescript
// Before:
} catch (e: any) {
  setError(e?.message ?? "Failed to load Modal runs");
}

// After:
} catch (e: unknown) {
  setError(toMessage(e, "Failed to load Modal runs"));
}
```

Apply identically to lines 99, 144, 182, 219, 243 — substituting the appropriate fallback string already present in each catch block.

**Fix B — CSV exporter cast (`ModalComboDetailPage.tsx:34`):**

```typescript
// Before (line 33-35):
const rows = trades.map((t) =>
  keys.map((k) => {
    const v = (t as any)[k];

// After:
const rows = trades.map((t) =>
  keys.map((k) => {
    const v = t[k as keyof ModalTrade];
```

`keys` is a `string[]` that is manually constructed from valid `ModalTrade` field names; the cast is semantically correct and type-safe.

**Fix C — `flags` read in `TradeRow` (`ModalComboDetailPage.tsx:327`):**

`signals_at_entry_json` is typed `Record<string, any> | null` on `ModalTrade` (see `types.ts:298`). `Record<string, any>` already permits any string key, so `as any` is redundant:

```typescript
// Before (line 326-328):
const flags: string[] = useMemo(() => {
  const f = (trade.signals_at_entry_json as any)?.flags;

// After:
const flags: string[] = useMemo(() => {
  const f = trade.signals_at_entry_json?.flags;
```

**Fix D — `EventsList` and `ConfigCard` prop types (`ModalRunDetailPage.tsx:320,370`):**

Add `ModalEvent` and `ModalRun` to the existing import at line 22:

```typescript
// ModalRunDetailPage.tsx — line 22, replace
import type { ModalCombination } from "../api/types";
// with:
import type { ModalCombination, ModalEvent, ModalRun } from "../api/types";
```

Replace the `EventsList` signature at line 320:

```typescript
function EventsList({ events }: { events: ModalEvent[] }) {
```

Replace the `ConfigCard` signature at line 370:

```typescript
function ConfigCard({ run }: { run: Pick<ModalRun, "config_json" | "config_hash" | "git_sha" | "metrics_json"> }) {
```

- **Why minimal:** Each sub-fix is a targeted annotation change; no logic is altered.
- **Test / manual verification:** `npm run typecheck` must pass with zero errors after all four sub-fixes are applied.
- **Risk of regression:** Low. Fix D makes prop types stricter — TypeScript will surface any caller passing an incompatible shape at compile time.

---

### Finding 4 — Fast Refresh broken: component and utilities co-located in `.tsx` file

- **Severity:** High
- **File + line:** `frontend/src/components/backtest/modal-format.tsx:1-99`
- **Root cause:** Vite Fast Refresh requires a `.tsx` file to export only React components or only non-component values. `modal-format.tsx` exports both `StatusBadge` (a component) and `formatDate`, `formatDateTime`, `formatDuration`, `formatNum`, `formatPct`, `shortHash`, `signedClass`, `extractSignalScores` (pure utilities), causing Vite to fall back to full page reload on any edit.
- **Proposed fix:**

**Step 1 — Create `frontend/src/components/backtest/modal-utils.ts`** and move these exports verbatim from `modal-format.tsx`:

- `formatDate`
- `formatDateTime`
- `formatDuration`
- `formatNum`
- `formatPct`
- `shortHash`
- `signedClass`
- `extractSignalScores`

The new file has no JSX; use `.ts` extension. It only needs the `ModalRunStatus` type import removed (that belongs in `modal-format.tsx`). The `extractSignalScores` function signature takes `Record<string, any> | null | undefined` — no type import required.

**Step 2 — `modal-format.tsx` becomes component-only:**

```typescript
// frontend/src/components/backtest/modal-format.tsx — final state

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { ModalRunStatus } from "../../api/types";

const STATUS_STYLES: Record<ModalRunStatus, string> = {
  queued: "text-muted-foreground border-muted-foreground/20 bg-muted/20",
  running: "text-primary border-primary/20 bg-primary/10",
  complete: "text-[--positive] border-[--positive]/20 bg-[--positive]/10",
  degraded: "text-[--warning] border-[--warning]/20 bg-[--warning]/10",
  failed: "text-[--negative] border-[--negative]/20 bg-[--negative]/10",
};

export function StatusBadge({ status, className }: { status: ModalRunStatus; className?: string }) {
  const style = STATUS_STYLES[status];
  return (
    <Badge variant="outline" className={cn("text-[9px] uppercase tracking-wider", style, className)}>
      {status}
    </Badge>
  );
}
```

Note: the `?? STATUS_STYLES.queued` fallback is also removed here (see Finding 8).

**Step 3 — Update import sites.** These three files import utilities from `modal-format` and must be updated to import them from `modal-utils` instead. `StatusBadge` stays imported from `modal-format` in all three.

| File | Symbols to re-point to `modal-utils` |
|------|--------------------------------------|
| `frontend/src/pages/ModalComboDetailPage.tsx` | `extractSignalScores`, `formatDate`, `formatNum`, `formatPct`, `shortHash`, `signedClass` |
| `frontend/src/pages/ModalRunDetailPage.tsx` | `formatDateTime`, `formatDuration`, `formatNum`, `formatPct`, `shortHash`, `signedClass` |
| `frontend/src/components/backtest/ModalRunsPanel.tsx` | `formatDateTime`, `formatDuration`, `formatNum`, `shortHash`, `signedClass` |

- **Why minimal:** Purely mechanical file split; no logic changes anywhere.
- **Test / manual verification:** In dev mode (`npm run dev`), edit a utility function in `modal-utils.ts` and confirm the browser hot-reloads the affected component without a full page reload (HMR overlay should not show "full reload"). Then edit `StatusBadge` in `modal-format.tsx` and confirm the same. `npm run typecheck` must still pass.
- **Risk of regression:** Low. The only risk is a missed import site; `tsc --noEmit` will surface any unresolved names immediately.

---

### Finding 5 — No run-list refresh after `dispatchModalRun` succeeds

- **Severity:** Important
- **File + line:** `frontend/src/pages/BacktestPage.tsx:73-75`
- **Root cause:** After `dispatchModal` resolves, the code navigates immediately to the run detail page. `ModalRunsPanel` polls on its own 5 s interval. If the user presses Back, the new run may not appear in the list for up to 5 s.
- **Proposed fix:** Force `ModalRunsPanel` to remount on the next visit by keying it off a counter that increments on successful dispatch:

```typescript
// BacktestPage.tsx — add to state declarations (near line 59):
const [panelKey, setPanelKey] = useState(0);

// BacktestPage.tsx — replace lines 73-75:
const kickoff = await dispatchModal(sub.config);
setPanelKey((k) => k + 1); // triggers fresh fetch when user navigates back
navigate(`/backtest/modal/runs/${kickoff.run_id}`);
```

```tsx
// BacktestPage.tsx — TabsContent for "modal" (line 127-129):
<TabsContent value="modal">
  <ModalRunsPanel key={panelKey} />
</TabsContent>
```

- **Why minimal:** Two state lines and one `key` prop; no changes to `ModalRunsPanel`.
- **Test / manual verification:** Dispatch a Modal run. Press Back. The new run appears at the top of the panel immediately without waiting for the 5 s poll interval. Confirm in the Network tab that a `GET /api/modal/runs` request fires on panel mount.
- **Risk of regression:** Low. `ModalRunsPanel` remounts cleanly and re-initializes its polling.

---

### Finding 6 — `limit: 20000` on `useModalCombinations` to find one combo

- **Severity:** Important
- **File + line:** `frontend/src/pages/ModalComboDetailPage.tsx:56-63`
- **Root cause:** The page fetches up to 20 000 combinations on every mount solely to call `.find(c => c.combo_idx === idx)` and render the combo summary card. Every combo detail page load sends a potentially large response payload.
- **Proposed fix:** This requires a backend endpoint `GET /api/modal/runs/{run_id}/combinations/{combo_idx}` that returns a single `ModalCombination`. The frontend change is then:

```typescript
// ModalComboDetailPage.tsx — replace lines 56-63
// TODO: replace with useModalCombination(runId, idx) once the single-combo
// endpoint is available. Tracking issue: <link>.
const { combinations } = useModalCombinations(runId, {
  active: false,
  pollMs: 0,
  limit: 20000,
});
```

Do not change `limit` without the backend filter in place — a `limit: 1` without server-side `combo_idx` filtering returns the wrong row.

- **Why minimal:** Adds a TODO comment; no functional change until the backend endpoint exists.
- **Test / manual verification:** Once the backend endpoint is added: navigate to any combo detail page and confirm the combinations request returns exactly one row. Record response size before/after.
- **Risk of regression:** None as a comment-only change. Changing limit without the backend filter would be a regression — hence the deferral.

---

### Finding 7 — Zero-trade combination has no empty state on stats card

- **Severity:** Important
- **File + line:** `frontend/src/pages/ModalComboDetailPage.tsx:74-75, 202`
- **Root cause:** `stats` is `null` when `trades.length === 0` (line 74-75). The stats `Card` renders only when `stats` is truthy (line 202). A zero-trade combination silently omits the stats area, leaving a visual gap between the combo summary card and the trade log with no explanation.
- **Proposed fix:** Add an else branch to the `{stats && ...}` conditional:

```tsx
// ModalComboDetailPage.tsx — replace lines 201-235

{/* Trade stats */}
{stats ? (
  <Card className="p-4">
    <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
      <StatBox label="Total Trades" value={String(stats.total)} />
      <StatBox
        label="Win Rate"
        value={`${stats.winRate.toFixed(1)}%`}
        sub={`${stats.wins}W / ${stats.losses}L`}
      />
      <StatBox
        label="Avg PnL %"
        value={formatPct(stats.avgPct)}
        className={signedClass(stats.avgPct)}
      />
      <StatBox
        label="Total $ PnL"
        value={`$${stats.totalPnl.toFixed(0)}`}
        className={signedClass(stats.totalPnl)}
      />
      <div>
        <label className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">
          Filter by Ticker
        </label>
        <input
          type="text"
          value={filterTicker}
          onChange={(e) => setFilterTicker(e.target.value)}
          placeholder="e.g. AAPL"
          className="mt-1 w-full bg-secondary border border-border rounded-md px-2 py-1 text-xs text-foreground"
        />
      </div>
    </div>
  </Card>
) : !isLoading ? (
  <Card className="p-4">
    <p className="text-xs text-muted-foreground">This combination produced no trades.</p>
  </Card>
) : null}
```

- **Why minimal:** One conditional branch added to the existing render; no structural changes to the stats grid.
- **Test / manual verification:** Navigate to a combo where `n_trades = 0` (a skipped or gate-filtered combo). The stats area must show "This combination produced no trades." instead of blank space.
- **Risk of regression:** None. The existing stats grid is unchanged; only the else branch is new.

---

### Finding 8 — Unknown `status` strings silently inherit `queued` style

- **Severity:** Important
- **File + line:** `frontend/src/components/backtest/modal-format.tsx:93`
- **Root cause:** `STATUS_STYLES[status] ?? STATUS_STYLES.queued` hides any future `ModalRunStatus` member that is added to `types.ts` without a corresponding entry in `STATUS_STYLES`. The fallback silently renders a misleading style.
- **Proposed fix:** Remove the fallback. `STATUS_STYLES` is typed `Record<ModalRunStatus, string>`, so TypeScript already enforces that every current member is present. Removing `?? STATUS_STYLES.queued` causes a compile error if a new member is ever added without updating `STATUS_STYLES` — which is exactly the desired behavior.

```typescript
// modal-format.tsx — replace line 93 (within StatusBadge)
const style = STATUS_STYLES[status];
```

This fix is bundled with Finding 4 (the file split) since both touch `modal-format.tsx`.

- **Why minimal:** One-line deletion.
- **Test / manual verification:** `npm run typecheck` must pass. To verify the exhaustiveness guarantee: temporarily add `"cancelled"` to `ModalRunStatus` in `types.ts` and confirm that `tsc` errors at `STATUS_STYLES` for the missing key.
- **Risk of regression:** None. `STATUS_STYLES[status]` is never `undefined` for a valid `ModalRunStatus` member.

---

### Finding 9 — `active` defaults to `false` before first fetch completes

- **Severity:** Important
- **File + line:** `frontend/src/pages/ModalRunDetailPage.tsx:32`
- **Root cause:** On first render `run` is `null`, so `isActiveStatus(run?.status)` evaluates to `false`. `useModalCombinations` and `useModalRunEvents` are both initialized with `active: false` and `pollMs: 0`, meaning polling is disabled for the first render cycle. For a run in `"queued"` or `"running"` state, events and combinations miss the first polling window.
- **Proposed fix:**

```typescript
// ModalRunDetailPage.tsx — replace line 32
const active = run == null ? true : isActiveStatus(run.status);
```

When `run` has not yet loaded, optimistically treat the run as active. Once the first fetch completes and `run.status` is a terminal value, polling stops as intended.

- **Why minimal:** Single ternary expression; no downstream changes.
- **Test / manual verification:** Open the detail page for a `"running"` run on a cold cache. In the Network tab confirm that `GET /api/modal/runs/{id}/combinations` and `GET /api/modal/runs/{id}/events` requests fire on the first render, not only after the run meta request resolves.
- **Risk of regression:** Low. For a completed run, the initial optimistic poll results in one extra unnecessary request per hook, which is immediately cancelled by the deps update. Acceptable.

---

## Sequencing

Apply fixes in this order to keep CI green at each step:

1. **Finding 4 + Finding 8** — split `modal-format.tsx`, remove fallback. Purely mechanical; no logic changes. Do this first so subsequent import updates target the correct file.
2. **Finding 1** — stale-closure fix in `useVisibilityInterval`. Foundational; all polling hooks depend on it.
3. **Finding 2** — `setEvents([])` effect consolidation. Small; touches the same file as Finding 1. Batch with it.
4. **Finding 3** — `any` elimination. Touches multiple files; do after the file split so import paths are stable.
5. **Finding 9** — `active` default. One line; low risk.
6. **Finding 7** — zero-trade empty state. UI-only.
7. **Finding 5** — `panelKey` remount on dispatch. Isolated to `BacktestPage.tsx`.
8. **Finding 6** — `limit: 20000` comment/TODO. Track as a separate backend + frontend task; do not block merge on it.

---

## Cross-refs

`frontend/src/pages/BacktestPage.tsx:121` — `<Tabs defaultValue="modal">` defaults to the Modal CPCV tab. This violates the project rule that walk-forward is the default view (`feedback_backtest_default.md`). This finding is owned by the general reviewer and should not be bundled with the TypeScript fixes above.

---

## Deferred / out-of-scope

- **`signals_at_entry_json` typed as `Record<string, any>`** on `ModalTrade` (`types.ts:298`) and `ModalRun` (`types.ts:249-250`): the `any` here is architectural — the JSON column is genuinely schema-free at the DB level. A proper fix requires a discriminated union for canonical vs. legacy signal payload shapes and an update to `extractSignalScores`. Separate refactor task.
- **Silent zeros** (`.get(key, 0)` masking missing API fields): tracked in project memory as `project_silent_zeros.md`. Out of scope for this PR.
- **CSV newline escaping** (`ModalComboDetailPage.tsx:24-47`): field values containing `\n` are not escaped. Acceptable for current data shapes; harden before external distribution.
- **`BacktestPage.tsx` inline `Record<string, any>[]`** at lines 19 and 42-43 (`buildRunSelectorItems`, `exportCsv`): these reference the legacy backtest history, which has no typed interface. Tracked separately.
