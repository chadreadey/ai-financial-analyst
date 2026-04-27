import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { api } from "@/api/client";
import { getSettings } from "@/components/layout/SettingsDrawer";
import type { PortfolioCandidate, PortfolioCandidatesResponse } from "@/api/types";
import { Sparkles } from "lucide-react";

const POLL_INTERVAL_MS = 5 * 60_000; // 5 min

function directionTone(direction: string | undefined): string {
  const d = (direction || "").toUpperCase();
  if (d.includes("BUY")) return "text-[--positive] border-[--positive]/30 bg-[--positive]/10";
  if (d.includes("SELL")) return "text-[--negative] border-[--negative]/30 bg-[--negative]/10";
  return "text-muted-foreground border-border";
}

function fmtSignal(score: number): string {
  const sign = score >= 0 ? "+" : "";
  return `${sign}${score.toFixed(2)}`;
}

export function CandidatePipeline() {
  const navigate = useNavigate();
  const [data, setData] = useState<PortfolioCandidatesResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [analyzingTicker, setAnalyzingTicker] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const resp = await api.getPortfolioCandidates(20);
        if (!cancelled) {
          setData(resp);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : "Failed to load candidates";
          setError(msg);
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };
    load();
    const id = window.setInterval(load, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const handleAnalyze = async (c: PortfolioCandidate) => {
    setAnalyzingTicker(c.ticker);
    try {
      const s = getSettings();
      const job = await api.runAnalysis({
        ticker: c.ticker,
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
      navigate(`/deepdive/${c.ticker}?source=portfolio&job_id=${job.job_id}`);
    } catch (err) {
      // Navigate anyway — the deep dive page can show prior history
      navigate(`/deepdive/${c.ticker}?source=portfolio`);
    } finally {
      setAnalyzingTicker(null);
    }
  };

  return (
    <Card className="p-0 overflow-hidden">
      <div className="px-3 py-2 border-b border-border flex items-center gap-2">
        <Sparkles size={13} className="text-muted-foreground" />
        <span className="text-xs font-medium text-foreground">Candidate Pipeline</span>
        {data?.universe && (
          <Badge variant="outline" className="text-[10px] ml-auto text-muted-foreground">
            {data.universe}
          </Badge>
        )}
      </div>
      <div className="max-h-[520px] overflow-y-auto divide-y divide-border">
        {isLoading && (
          <div className="px-3 py-3 text-[11px] text-muted-foreground">Loading candidates…</div>
        )}
        {error && (
          <div className="px-3 py-3 text-[11px] text-[--negative]">
            {error}
          </div>
        )}
        {!isLoading && !error && data && data.candidates.length === 0 && (
          <div className="px-3 py-3 text-[11px] text-muted-foreground">
            No fresh candidates. The ranker may still be warming up.
          </div>
        )}
        {data?.candidates.map((c) => (
          <div key={c.ticker} className="px-3 py-2 hover:bg-secondary/40 transition-colors">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-xs font-medium text-foreground">{c.ticker}</span>
                <Badge variant="outline" className={cn("text-[10px]", directionTone(c.composite_direction))}>
                  {fmtSignal(c.composite_score)}
                </Badge>
                {c.actionable && (
                  <Badge variant="outline" className="text-[9px] uppercase tracking-wide border-primary/40 text-primary">
                    actionable
                  </Badge>
                )}
              </div>
              <Button
                size="sm"
                variant="outline"
                className="h-6 px-2 text-[10px]"
                onClick={() => handleAnalyze(c)}
                disabled={analyzingTicker === c.ticker}
              >
                {analyzingTicker === c.ticker ? "Starting…" : "Analyze"}
              </Button>
            </div>
            {c.top_signals.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1.5 text-[10px] text-muted-foreground">
                {c.top_signals.slice(0, 3).map((s) => (
                  <span key={s.name} className="px-1.5 py-0.5 rounded bg-secondary/50">
                    {s.name} {fmtSignal(s.score)}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      {data?.errors && data.errors.length > 0 && (
        <div className="px-3 py-1.5 border-t border-border text-[10px] text-muted-foreground">
          {data.errors.length} ticker(s) failed to score
        </div>
      )}
    </Card>
  );
}
