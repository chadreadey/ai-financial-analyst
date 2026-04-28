import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type {
  PortfolioOverviewResponse,
  PortfolioOverviewTotals,
  PositionWithVerdict,
} from "../api/types";

const POLL_INTERVAL_MS = 60_000;

const EMPTY_TOTALS: PortfolioOverviewTotals = {
  total_positions: 0,
  total_equity_at_entry: 0,
  avg_unrealized_pnl_pct: null,
  stale_count: 0,
};

interface UsePortfolioOverviewResult {
  positions: PositionWithVerdict[];
  totals: PortfolioOverviewTotals;
  isLoading: boolean;
  error: string | null;
  refresh: () => void;
}

/**
 * Polls /api/paper-trading/positions-with-verdicts every 60s.
 *
 * Mounts → fetch immediately, then poll. Pauses while a fetch is in-flight to
 * avoid request pile-up if the backend is slow.
 */
export function usePortfolioOverview(): UsePortfolioOverviewResult {
  const [positions, setPositions] = useState<PositionWithVerdict[]>([]);
  const [totals, setTotals] = useState<PortfolioOverviewTotals>(EMPTY_TOTALS);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const inFlightRef = useRef(false);

  const refresh = useCallback(async () => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    try {
      const data: PortfolioOverviewResponse = await api.getPortfolioOverview();
      setPositions(data.positions ?? []);
      setTotals(data.totals ?? EMPTY_TOTALS);
      setError(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load portfolio overview";
      setError(msg);
    } finally {
      inFlightRef.current = false;
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [refresh]);

  return { positions, totals, isLoading, error, refresh };
}
