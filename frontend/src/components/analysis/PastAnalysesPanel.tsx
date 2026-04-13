import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { AnalysisResult, HistoryEntry } from "../../api/types";
import { Card } from "@/components/ui/card";

interface Props {
  onOpenResult: (result: AnalysisResult) => void;
}

function formatDate(ts: number): string {
  try {
    return new Date(ts * 1000).toLocaleString();
  } catch {
    return "—";
  }
}

function stopLossLabel(entry: HistoryEntry): string {
  if (entry.stop_loss_value == null) return "—";
  if (entry.stop_loss_unit === "percent") return `${entry.stop_loss_value}%`;
  return `$${entry.stop_loss_value.toFixed(2)}`;
}

export function PastAnalysesPanel({ onOpenResult }: Props) {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setIsLoading(true);
    api
      .getHistory(undefined, 25, 0)
      .then((res) => {
        setEntries(res.entries);
        setError(null);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setIsLoading(false));
  }, []);

  const openDetail = async (analysisId: string) => {
    try {
      const detail = await api.getHistoryDetail(analysisId);
      if (detail.result_json) {
        onOpenResult(detail.result_json as AnalysisResult);
      }
    } catch {
      // ignore detail failures; list view still usable
    }
  };

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-foreground">
          Past Analyses
        </h3>
        <span className="text-xs text-muted-foreground">
          {entries.length} saved
        </span>
      </div>

      {isLoading && (
        <div className="text-sm text-muted-foreground">
          Loading past analyses...
        </div>
      )}
      {error && (
        <div className="text-sm text-[--negative]">
          {error}
        </div>
      )}
      {!isLoading && !error && entries.length === 0 && (
        <div className="text-sm text-muted-foreground">
          No analyses saved yet.
        </div>
      )}

      {!isLoading && !error && entries.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border">
                {[
                  "Date",
                  "Ticker",
                  "Recommendation",
                  "Price Target",
                  "Time Horizon",
                  "Stop Loss",
                  "Return %",
                  "Outcome",
                  "Days Left",
                ].map((h) => (
                  <th key={h} className="text-left py-2 px-2 font-medium text-muted-foreground">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr
                  key={entry.analysis_id || `${entry.ticker}-${entry.run_at}`}
                  className="border-b border-border cursor-pointer hover:bg-secondary/50 transition-colors"
                  onClick={() => openDetail(entry.analysis_id)}
                >
                  <td className="py-1.5 px-2 text-muted-foreground">{formatDate(entry.run_at)}</td>
                  <td className="py-1.5 px-2 font-medium text-foreground">{entry.ticker}</td>
                  <td className="py-1.5 px-2 text-muted-foreground">{entry.verdict || "—"}</td>
                  <td className="py-1.5 px-2 text-muted-foreground">
                    {entry.price_target != null ? `$${entry.price_target.toFixed(2)}` : "—"}
                  </td>
                  <td className="py-1.5 px-2 text-muted-foreground">{entry.time_horizon || "—"}</td>
                  <td className="py-1.5 px-2 text-muted-foreground">{stopLossLabel(entry)}</td>
                  <td className="py-1.5 px-2 text-muted-foreground">
                    {entry.return_since_analysis_pct != null
                      ? `${entry.return_since_analysis_pct > 0 ? "+" : ""}${entry.return_since_analysis_pct}%`
                      : "—"}
                  </td>
                  <td className="py-1.5 px-2 text-muted-foreground">{entry.outcome_status || "—"}</td>
                  <td className="py-1.5 px-2 text-muted-foreground">
                    {entry.days_remaining != null ? String(entry.days_remaining) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
