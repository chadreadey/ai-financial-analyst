import { useState, useCallback, useRef } from "react";
import { api } from "../api/client";
import type { AnalysisResult, ProgressEvent, RunAnalysisRequest } from "../api/types";

interface AnalysisState {
  isRunning: boolean;
  progress: ProgressEvent | null;
  result: AnalysisResult | null;
  error: string | null;
}

export function useAnalysis() {
  const [state, setState] = useState<AnalysisState>({
    isRunning: false,
    progress: null,
    result: null,
    error: null,
  });
  const esRef = useRef<EventSource | null>(null);

  const run = useCallback(async (request: RunAnalysisRequest) => {
    setState({ isRunning: true, progress: null, result: null, error: null });

    try {
      const { job_id } = await api.runAnalysis(request);

      const es = new EventSource(api.streamUrl(job_id));
      esRef.current = es;

      es.onmessage = (e) => {
        try {
          const data: ProgressEvent = JSON.parse(e.data);
          if (data.step === "complete" && data.result) {
            setState({
              isRunning: false,
              progress: null,
              result: data.result,
              error: null,
            });
            es.close();
          } else if (data.step === "error" || data.error) {
            setState({
              isRunning: false,
              progress: null,
              result: null,
              error: data.error || "Analysis failed",
            });
            es.close();
          } else {
            setState((prev) => ({ ...prev, progress: data }));
          }
        } catch {
          // ignore parse errors
        }
      };

      es.onerror = () => {
        es.close();
        const poll = setInterval(async () => {
          try {
            const res = await api.getResult(job_id);
            if (res.status === "complete" || res.ticker) {
              clearInterval(poll);
              setState({
                isRunning: false,
                progress: null,
                result: res.status ? null : res,
                error: null,
              });
            } else if (res.status === "error") {
              clearInterval(poll);
              setState({
                isRunning: false,
                progress: null,
                result: null,
                error: res.error || "Analysis failed",
              });
            }
          } catch {
            clearInterval(poll);
          }
        }, 2000);
      };
    } catch (err: any) {
      setState({
        isRunning: false,
        progress: null,
        result: null,
        error: err.message || "Failed to start analysis",
      });
    }
  }, []);

  const reset = useCallback(() => {
    esRef.current?.close();
    setState({ isRunning: false, progress: null, result: null, error: null });
  }, []);

  return { ...state, run, reset };
}
