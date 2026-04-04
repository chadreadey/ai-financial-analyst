import { useState, useCallback, useRef } from "react";
import { api } from "../api/client";
import type { BacktestConfig, BacktestResult } from "../api/types";

export function useBacktest() {
  const [isRunning, setIsRunning] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [parsedConfig, setParsedConfig] = useState<BacktestConfig | null>(null);
  const [history, setHistory] = useState<Array<Record<string, any>>>([]);
  const intervalRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  const pollJob = useCallback(async (id: string) => {
    intervalRef.current = setInterval(async () => {
      try {
        const r = await api.getBacktestResult(id);
        if (r.status === "complete" || r.status === "error" || r.status === "insufficient_data") {
          clearInterval(intervalRef.current);
          setResult(r);
          setIsRunning(false);
          if (r.status === "error") setError((r as any).error || "Backtest failed");
          try {
            const hist = await api.getBacktestHistory();
            setHistory(hist.runs);
          } catch {
            // ignore history refresh failures
          }
        }
      } catch (e: any) {
        clearInterval(intervalRef.current);
        setError(e.message);
        setIsRunning(false);
      }
    }, 2000);
  }, []);

  const run = useCallback(async (config: BacktestConfig) => {
    setIsRunning(true);
    setResult(null);
    setError(null);
    setParsedConfig(config);

    try {
      const { job_id } = await api.runBacktest(config);
      setJobId(job_id);
      await pollJob(job_id);
    } catch (e: any) {
      setError(e.message);
      setIsRunning(false);
    }
  }, [pollJob]);

  const runNaturalLanguage = useCallback(async (query: string) => {
    setIsRunning(true);
    setResult(null);
    setError(null);
    try {
      const nl = await api.runBacktestNl(query);
      setParsedConfig(nl.parsed_config);
      setJobId(nl.job_id);
      await pollJob(nl.job_id);
    } catch (e: any) {
      setError(e.message);
      setIsRunning(false);
    }
  }, [pollJob]);

  const refreshHistory = useCallback(async () => {
    try {
      const hist = await api.getBacktestHistory();
      setHistory(hist.runs);
    } catch {
      // ignore history fetch errors
    }
  }, []);

  return { isRunning, jobId, result, error, run, runNaturalLanguage, parsedConfig, history, refreshHistory };
}
