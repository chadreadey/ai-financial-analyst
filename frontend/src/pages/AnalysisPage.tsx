import React from "react";
import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useAnalysis } from "../hooks/useAnalysis";
import { Sidebar } from "../components/layout/Sidebar";
import { TickerInput } from "../components/analysis/TickerInput";
import { ProgressStream } from "../components/analysis/ProgressStream";
import { ResultView } from "../components/analysis/ResultView";
import { PastAnalysesPanel } from "../components/analysis/PastAnalysesPanel";
import { AlertTriangle } from "lucide-react";
import type { AnalysisResult } from "../api/types";

export interface AnalysisSettings {
  provider: string;
  api_key: string;
  enable_tiingo: boolean;
  enable_fmp: boolean;
  enable_yahoo: boolean;
  enable_tavily: boolean;
  max_agent_context_chars: number;
  max_agent_output_tokens: number;
  synthesis_report_max_chars: number;
  synthesis_input_max_chars: number;
  max_synthesis_output_tokens: number;
}

const DEFAULT_SETTINGS: AnalysisSettings = {
  provider: "openai",
  api_key: "",
  enable_tiingo: true,
  enable_fmp: true,
  enable_yahoo: true,
  enable_tavily: true,
  max_agent_context_chars: 12000,
  max_agent_output_tokens: 1200,
  synthesis_report_max_chars: 4500,
  synthesis_input_max_chars: 22000,
  max_synthesis_output_tokens: 1500,
};

export function AnalysisPage(): React.ReactElement {
  const [searchParams] = useSearchParams();
  const [ticker, setTicker] = useState(searchParams.get("ticker") || "");
  const [settings, setSettings] = useState<AnalysisSettings>(DEFAULT_SETTINGS);
  const [selectedPastResult, setSelectedPastResult] = useState<AnalysisResult | null>(null);

  useEffect(() => {
    const t = searchParams.get("ticker");
    if (t) setTicker(t.toUpperCase());
  }, [searchParams]);

  const { isRunning, progress, result, error, run } = useAnalysis();

  const handleRun = (): void => {
    if (!ticker.trim()) return;
    run({
      ticker: ticker.trim().toUpperCase(),
      provider: settings.provider,
      api_key: settings.api_key || undefined,
      enable_tiingo: settings.enable_tiingo,
      enable_fmp: settings.enable_fmp,
      enable_yahoo: settings.enable_yahoo,
      enable_tavily: settings.enable_tavily,
      max_agent_context_chars: settings.max_agent_context_chars,
      max_agent_output_tokens: settings.max_agent_output_tokens,
      synthesis_report_max_chars: settings.synthesis_report_max_chars,
      synthesis_input_max_chars: settings.synthesis_input_max_chars,
      max_synthesis_output_tokens: settings.max_synthesis_output_tokens,
    });
    setSelectedPastResult(null);
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-6">
      <aside>
        <Sidebar
          settings={settings}
          onSettingsChange={setSettings}
          onRun={handleRun}
          isRunning={isRunning}
          ticker={ticker}
        />
      </aside>

      <div className="space-y-4 min-w-0">
        <TickerInput
          ticker={ticker}
          onTickerChange={setTicker}
          onRun={handleRun}
          isRunning={isRunning}
        />

        {isRunning && progress && <ProgressStream progress={progress} />}

        {error && (
          <div
            className="flex items-start gap-3 rounded-lg p-4"
            style={{
              background: "rgba(239,68,68,0.08)",
              border: "1px solid rgba(239,68,68,0.3)",
              color: "var(--accent-red)",
            }}
          >
            <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" />
            <span className="text-sm">{error}</span>
          </div>
        )}

        {(result || selectedPastResult) && (
          <ResultView result={result || selectedPastResult!} />
        )}
        <PastAnalysesPanel onOpenResult={setSelectedPastResult} />
      </div>
    </div>
  );
}
