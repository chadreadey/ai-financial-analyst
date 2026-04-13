import React from "react";
import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useAnalysis } from "@/hooks/useAnalysis";
import { TickerInput } from "@/components/analysis/TickerInput";
import { ProgressStream } from "@/components/analysis/ProgressStream";
import { ResultView } from "@/components/analysis/ResultView";
import { PastAnalysesPanel } from "@/components/analysis/PastAnalysesPanel";
import { getSettings } from "@/components/layout/SettingsDrawer";
import { AlertTriangle } from "lucide-react";
import type { AnalysisResult } from "@/api/types";

export function AnalysisPage(): React.ReactElement {
  const [searchParams] = useSearchParams();
  const [ticker, setTicker] = useState(searchParams.get("ticker") || "");
  const [selectedPastResult, setSelectedPastResult] = useState<AnalysisResult | null>(null);

  useEffect(() => {
    const t = searchParams.get("ticker");
    if (t) setTicker(t.toUpperCase());
  }, [searchParams]);

  const { isRunning, progress, result, error, run } = useAnalysis();

  const handleRun = (): void => {
    if (!ticker.trim()) return;
    const s = getSettings();
    run({
      ticker: ticker.trim().toUpperCase(),
      provider: s.provider,
      api_key: s.api_key || undefined,
      enable_tiingo: s.enable_tiingo,
      enable_fmp: s.enable_fmp,
      enable_yahoo: s.enable_yahoo,
      enable_tavily: s.enable_tavily,
      max_agent_context_chars: s.max_agent_context_chars,
      max_agent_output_tokens: s.max_agent_output_tokens,
      synthesis_report_max_chars: s.synthesis_report_max_chars,
      synthesis_input_max_chars: s.synthesis_input_max_chars,
      max_synthesis_output_tokens: s.max_synthesis_output_tokens,
    });
    setSelectedPastResult(null);
  };

  return (
    <div className="space-y-4">
      {/* Page header */}
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-lg font-semibold text-foreground">Analysis</h1>
        <div className="flex-1 max-w-md">
          <TickerInput
            ticker={ticker}
            onTickerChange={setTicker}
            onRun={handleRun}
            isRunning={isRunning}
          />
        </div>
      </div>

      {/* Progress */}
      {isRunning && progress && <ProgressStream progress={progress} />}

      {/* Error */}
      {error && (
        <div className="flex items-start gap-3 rounded-lg p-4 bg-destructive/10 border border-destructive/30 text-destructive">
          <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" />
          <span className="text-sm">{error}</span>
        </div>
      )}

      {/* Result */}
      {(result || selectedPastResult) && (
        <ResultView result={result || selectedPastResult!} />
      )}

      {/* Past analyses */}
      <PastAnalysesPanel onOpenResult={setSelectedPastResult} />
    </div>
  );
}
