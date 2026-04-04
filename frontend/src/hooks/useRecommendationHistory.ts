import { useState, useEffect } from "react";
import { api } from "../api/client";
import type { RecommendationRecord } from "../api/types";

export function useRecommendationHistory(ticker: string) {
  const [records, setRecords] = useState<RecommendationRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setIsLoading(true);
    api.getRecommendationHistory(ticker)
      .then((d) => { setRecords(d.records); setError(null); })
      .catch((e) => setError(e.message))
      .finally(() => setIsLoading(false));
  }, [ticker]);

  return { records, isLoading, error };
}
