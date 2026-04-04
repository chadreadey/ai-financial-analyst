import { useState, useEffect, useCallback } from "react";
import { api } from "../api/client";
import type { PaperMetrics } from "../api/types";

export function usePaperTrading() {
  const [openPositions, setOpenPositions] = useState<any[]>([]);
  const [closedTrades, setClosedTrades] = useState<any[]>([]);
  const [equityCurve, setEquityCurve] = useState<{ date: string; equity: number }[]>([]);
  const [metrics, setMetrics] = useState<PaperMetrics | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const refresh = useCallback(() => {
    setIsLoading(true);
    Promise.all([
      api.getPaperPositions(),
      api.getPaperHistory(),
      api.getPaperMetrics(),
    ])
      .then(([pos, hist, met]) => {
        setOpenPositions(pos.positions);
        setClosedTrades(hist.trades);
        setEquityCurve(hist.equity_curve);
        setMetrics(met);
      })
      .catch(() => {})
      .finally(() => setIsLoading(false));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const addPosition = useCallback(async (position: any) => {
    await api.addPaperPosition(position);
    refresh();
  }, [refresh]);

  const closePosition = useCallback(async (ticker: string, exitPrice: number, exitReason: string) => {
    await api.closePaperPosition(ticker, { exit_price: exitPrice, exit_reason: exitReason });
    refresh();
  }, [refresh]);

  return { openPositions, closedTrades, equityCurve, metrics, isLoading, addPosition, closePosition };
}
