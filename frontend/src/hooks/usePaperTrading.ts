import { useState, useEffect, useCallback } from "react";
import { api } from "../api/client";
import type { AlpacaAccount, AlpacaOrder } from "../api/types";

export function usePaperTrading() {
  const [openPositions, setOpenPositions] = useState<any[]>([]);
  const [closedTrades, setClosedTrades] = useState<any[]>([]);
  const [equityCurve, setEquityCurve] = useState<{ date: string; equity: number }[]>([]);
  const [metrics, setMetrics] = useState<any>(null);
  const [account, setAccount] = useState<AlpacaAccount | null>(null);
  const [orders, setOrders] = useState<AlpacaOrder[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRebalancing, setIsRebalancing] = useState(false);

  const refresh = useCallback(() => {
    setIsLoading(true);
    Promise.all([
      api.getPaperPositions(),
      api.getPaperHistory(),
      api.getPaperMetrics(),
      api.getAlpacaAccount().catch(() => null),
      api.getAlpacaOrders().catch(() => ({ orders: [] as AlpacaOrder[] })),
    ])
      .then(([pos, hist, met, acct, ord]) => {
        setOpenPositions(pos.positions ?? []);
        setClosedTrades(hist.trades ?? []);
        setEquityCurve(hist.equity_curve ?? []);
        setMetrics(met);
        if (acct) setAccount(acct);
        setOrders(ord?.orders ?? []);
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

  const triggerRebalance = useCallback(async (tickers?: string[]) => {
    setIsRebalancing(true);
    try {
      const result = await api.triggerRebalance(tickers);
      refresh();
      return result;
    } finally {
      setIsRebalancing(false);
    }
  }, [refresh]);

  return {
    openPositions, closedTrades, equityCurve, metrics,
    account, orders,
    isLoading, isRebalancing,
    addPosition, closePosition, triggerRebalance,
  };
}
