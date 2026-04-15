import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { AgentReportTabs } from "@/components/analysis/AgentReportTabs";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AnalysisResult } from "@/api/types";

interface HistoryEntry {
  analysis_id: string;
  run_at: number;
  verdict: string;
  conviction: string;
  composite_score: number | null;
}

interface AnalysisAccordionProps {
  entries: HistoryEntry[];
  getFullResult: (analysisId: string) => Promise<AnalysisResult | null>;
}

function AccordionRow({
  entry,
  getFullResult,
}: {
  entry: HistoryEntry;
  getFullResult: (id: string) => Promise<AnalysisResult | null>;
}) {
  const [open, setOpen] = useState(false);
  const [fullResult, setFullResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);

  const handleToggle = async () => {
    const nextOpen = !open;
    setOpen(nextOpen);
    if (nextOpen && !fullResult && !loading) {
      setLoading(true);
      const result = await getFullResult(entry.analysis_id);
      setFullResult(result);
      setLoading(false);
    }
  };

  const verdictColor =
    entry.verdict === "BUY"
      ? "text-[--positive] border-[--positive]/20 bg-[--positive]/10"
      : entry.verdict === "SELL"
      ? "text-[--negative] border-[--negative]/20 bg-[--negative]/10"
      : "text-[--warning] border-[--warning]/20 bg-[--warning]/10";

  const date = new Date(entry.run_at * 1000).toISOString().split("T")[0];

  return (
    <div>
      <button
        onClick={handleToggle}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-secondary/50 transition-colors cursor-pointer text-left"
      >
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground">{date}</span>
          <Badge variant="outline" className={cn("text-[9px]", verdictColor)}>
            {entry.verdict}
          </Badge>
          <span className="text-xs text-primary">Conviction: {entry.conviction}</span>
          {entry.composite_score != null && (
            <span className="text-xs text-muted-foreground">
              Score: {entry.composite_score.toFixed(2)}
            </span>
          )}
        </div>
        <ChevronRight
          size={12}
          className={cn("text-muted-foreground transition-transform", open && "rotate-90")}
        />
      </button>
      {open && (
        <div className="px-4 pb-4 border-t border-border">
          {loading && (
            <p className="text-xs text-muted-foreground py-4">Loading full analysis...</p>
          )}
          {fullResult && (
            <AgentReportTabs
              synthesis={fullResult.synthesis}
              agentReports={fullResult.agent_reports}
              tradeParams={fullResult.structured_verdict}
            />
          )}
          {!loading && !fullResult && (
            <p className="text-xs text-muted-foreground py-4">Analysis data unavailable.</p>
          )}
        </div>
      )}
    </div>
  );
}

export function AnalysisAccordion({ entries, getFullResult }: AnalysisAccordionProps) {
  if (!entries.length) {
    return (
      <p className="text-xs text-muted-foreground py-4">No past analyses for this ticker.</p>
    );
  }

  return (
    <div className="border border-border rounded-lg overflow-hidden divide-y divide-border">
      {entries.map((entry) => (
        <AccordionRow key={entry.analysis_id} entry={entry} getFullResult={getFullResult} />
      ))}
    </div>
  );
}
