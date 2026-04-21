import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type {
  ModalCombination,
  ModalEvent,
  ModalRun,
  ModalRunRequest,
  ModalRunStatus,
  ModalTrade,
} from "../api/types";

// Runs that are still moving — worth polling.
const ACTIVE_STATUSES: ReadonlySet<ModalRunStatus> = new Set(["queued", "running"]);

function toMessage(e: unknown, fallback: string): string {
  if (e instanceof Error) return e.message;
  if (typeof e === "string") return e;
  return fallback;
}

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

// ── Runs list ───────────────────────────────────────────────────────────

export interface UseModalRunsOptions {
  status?: ModalRunStatus;
  configHash?: string;
  limit?: number;
  offset?: number;
  /** Poll interval in ms. Set 0 to disable auto-refresh. Default 5000. */
  pollMs?: number;
}

export function useModalRuns(opts: UseModalRunsOptions = {}) {
  const { status, configHash, limit = 50, offset = 0, pollMs = 5000 } = opts;
  const [runs, setRuns] = useState<ModalRun[]>([]);
  const [source, setSource] = useState<string>("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await api.listModalRuns({ status, config_hash: configHash, limit, offset });
      setRuns(r.runs);
      setSource(r.source);
      setError(null);
    } catch (e: unknown) {
      setError(toMessage(e, "Failed to load Modal runs"));
    } finally {
      setIsLoading(false);
    }
  }, [status, configHash, limit, offset]);

  useVisibilityInterval(refresh, pollMs, pollMs > 0);

  // Manual refresh path (non-polling mount).
  useEffect(() => {
    if (pollMs === 0) void refresh();
  }, [refresh, pollMs]);

  return { runs, source, isLoading, error, refresh };
}

// ── Single run detail ───────────────────────────────────────────────────

export function useModalRun(runId: string | undefined, pollMs: number = 3000) {
  const [run, setRun] = useState<ModalRun | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!runId) return;
    try {
      const r = await api.getModalRun(runId);
      setRun(r);
      setError(null);
    } catch (e: unknown) {
      setError(toMessage(e, "Failed to load run"));
    } finally {
      setIsLoading(false);
    }
  }, [runId]);

  // Stop polling once terminal — saves bandwidth + battery on detail page.
  const isActive = run ? ACTIVE_STATUSES.has(run.status) : true;
  useVisibilityInterval(refresh, pollMs, !!runId && isActive);

  useEffect(() => {
    if (!runId) return;
    setIsLoading(true);
    void refresh();
  }, [runId, refresh]);

  return { run, isLoading, error, refresh };
}

// ── Combinations for a run ──────────────────────────────────────────────

export interface UseModalCombinationsOptions {
  orderBy?: "oos_sharpe" | "combo_idx" | "return_pct" | "n_trades";
  descending?: boolean;
  limit?: number;
  /** Poll while run is still active so new rows stream in. */
  pollMs?: number;
  active?: boolean;
}

export function useModalCombinations(runId: string | undefined, opts: UseModalCombinationsOptions = {}) {
  const { orderBy = "oos_sharpe", descending = true, limit, pollMs = 5000, active = true } = opts;
  const [combinations, setCombinations] = useState<ModalCombination[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!runId) return;
    try {
      const r = await api.getModalRunCombinations(runId, {
        order_by: orderBy, descending, limit,
      });
      setCombinations(r.combinations);
      setError(null);
    } catch (e: unknown) {
      setError(toMessage(e, "Failed to load combinations"));
    } finally {
      setIsLoading(false);
    }
  }, [runId, orderBy, descending, limit]);

  useVisibilityInterval(refresh, pollMs, !!runId && active && pollMs > 0);

  useEffect(() => {
    if (!runId) return;
    setIsLoading(true);
    void refresh();
  }, [runId, refresh]);

  return { combinations, isLoading, error, refresh };
}

// ── Events (incremental polling via after_id cursor) ────────────────────

export function useModalRunEvents(runId: string | undefined, opts: { pollMs?: number; active?: boolean } = {}) {
  const { pollMs = 2000, active = true } = opts;
  const [events, setEvents] = useState<ModalEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const lastIdRef = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    if (!runId) return;
    try {
      const r = await api.getModalRunEvents(runId, {
        after_id: lastIdRef.current ?? undefined,
      });
      if (r.events.length > 0) {
        // Server returns events in ascending id order; append in place.
        setEvents((prev) => [...prev, ...r.events]);
        lastIdRef.current = r.events[r.events.length - 1].id;
      }
      setError(null);
    } catch (e: unknown) {
      setError(toMessage(e, "Failed to load events"));
    }
  }, [runId]);

  // Reset cursor and events when runId changes; fetch immediately.
  useEffect(() => {
    if (!runId) return;
    lastIdRef.current = null;
    setEvents([]);
    void refresh();
  }, [runId, refresh]);

  useVisibilityInterval(refresh, pollMs, !!runId && active && pollMs > 0);

  return { events, error, refresh };
}

// ── Trades for a single combination ─────────────────────────────────────

export function useModalComboTrades(
  runId: string | undefined,
  comboIdx: number | undefined,
) {
  const [trades, setTrades] = useState<ModalTrade[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId || comboIdx == null) return;
    let cancelled = false;
    setIsLoading(true);
    (async () => {
      try {
        const r = await api.getModalComboTrades(runId, comboIdx);
        if (!cancelled) {
          setTrades(r.trades);
          setError(null);
        }
      } catch (e: unknown) {
        if (!cancelled) setError(toMessage(e, "Failed to load trades"));
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [runId, comboIdx]);

  return { trades, isLoading, error };
}

// ── Dispatch new run ────────────────────────────────────────────────────

export function useDispatchModalRun() {
  const [isDispatching, setIsDispatching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dispatch = useCallback(async (req: ModalRunRequest) => {
    setIsDispatching(true);
    setError(null);
    try {
      const k = await api.dispatchModalRun(req);
      return k;
    } catch (e: unknown) {
      setError(toMessage(e, "Dispatch failed"));
      throw e;
    } finally {
      setIsDispatching(false);
    }
  }, []);

  return { dispatch, isDispatching, error };
}
