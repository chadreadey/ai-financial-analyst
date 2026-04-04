import { useState, useEffect, useCallback } from "react";
import { api } from "../api/client";
import type { WatchlistEntry } from "../api/types";

export function useWatchlist() {
  const [entries, setEntries] = useState<WatchlistEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(() => {
    setIsLoading(true);
    api.getWatchlist()
      .then((d) => { setEntries(d.entries); setError(null); })
      .catch((e) => setError(e.message))
      .finally(() => setIsLoading(false));
  }, []);

  useEffect(() => { fetch(); }, [fetch]);

  const add = useCallback(async (ticker: string) => {
    await api.addToWatchlist(ticker.toUpperCase());
    fetch();
  }, [fetch]);

  const remove = useCallback(async (ticker: string) => {
    await api.removeFromWatchlist(ticker.toUpperCase());
    fetch();
  }, [fetch]);

  return { entries, isLoading, error, add, remove };
}
