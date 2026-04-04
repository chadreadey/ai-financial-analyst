import { useState, useEffect, useRef } from "react";
import { api } from "../api/client";
import type { PriceBar } from "../api/types";

export function usePriceHistory(ticker: string, period: string) {
  const [bars, setBars] = useState<PriceBar[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const cacheRef = useRef<Record<string, PriceBar[]>>({});

  useEffect(() => {
    const key = `${ticker}:${period}`;
    if (cacheRef.current[key]) {
      setBars(cacheRef.current[key]);
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    api.getPriceHistory(ticker, period)
      .then((d) => {
        cacheRef.current[key] = d.bars;
        setBars(d.bars);
        setError(null);
      })
      .catch((e) => setError(e.message))
      .finally(() => setIsLoading(false));
  }, [ticker, period]);

  return { bars, isLoading, error };
}
