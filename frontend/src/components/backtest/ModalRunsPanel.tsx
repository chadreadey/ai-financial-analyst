import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useModalRuns } from "../../hooks/useModalBacktests";
import type { ModalRun, ModalRunStatus } from "../../api/types";
import { StatusBadge } from "./modal-format";
import {
  formatDateTime,
  formatDuration,
  formatNum,
  shortHash,
  signedClass,
} from "./modal-utils";
import { RefreshCw } from "lucide-react";

const STATUS_FILTERS: Array<{ value: ModalRunStatus | ""; label: string }> = [
  { value: "", label: "All" },
  { value: "running", label: "Running" },
  { value: "queued", label: "Queued" },
  { value: "complete", label: "Complete" },
  { value: "degraded", label: "Degraded" },
  { value: "failed", label: "Failed" },
];

interface GroupedRow {
  head: ModalRun;
  siblings: ModalRun[];
}

/** Collapse runs by config_hash: latest at top, `×N` pill when >1. */
function groupByConfigHash(runs: ModalRun[]): GroupedRow[] {
  const seen = new Map<string, GroupedRow>();
  for (const r of runs) {
    const key = r.config_hash;
    const existing = seen.get(key);
    if (!existing) {
      seen.set(key, { head: r, siblings: [] });
    } else {
      existing.siblings.push(r);
    }
  }
  return Array.from(seen.values());
}

export function ModalRunsPanel() {
  const navigate = useNavigate();
  const [statusFilter, setStatusFilter] = useState<ModalRunStatus | "">("");
  const { runs, source, isLoading, error, refresh } = useModalRuns({
    status: statusFilter || undefined,
    limit: 100,
  });

  const grouped = useMemo(() => groupByConfigHash(runs), [runs]);

  return (
    <div className="space-y-3">
      {/* Controls */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-1 bg-secondary/40 rounded-md p-0.5">
          {STATUS_FILTERS.map((s) => (
            <button
              key={s.value || "all"}
              type="button"
              onClick={() => setStatusFilter(s.value)}
              className={
                "px-2.5 py-1 rounded text-[11px] font-medium transition-colors " +
                (statusFilter === s.value
                  ? "bg-primary/15 text-primary"
                  : "text-muted-foreground hover:text-foreground")
              }
            >
              {s.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          {source && (
            <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60">
              source: {source}
            </span>
          )}
          <Button size="sm" variant="secondary" onClick={() => void refresh()}>
            <RefreshCw size={12} className="mr-1.5" />
            Refresh
          </Button>
        </div>
      </div>

      {error && (
        <Card className="p-3">
          <p className="text-xs text-[--negative]">{error}</p>
        </Card>
      )}

      <Card className="p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border">
                {[
                  "Started",
                  "Universe",
                  "Config",
                  "Status",
                  "Median OOS",
                  "PBO",
                  "DSR",
                  "Combos",
                  "Runtime",
                ].map((h) => (
                  <th
                    key={h}
                    className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/50"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {grouped.map(({ head, siblings }) => {
                const combosSummary = `${head.n_completed}/${head.n_combinations ?? "—"}`;
                const failedNote = head.n_failed > 0 ? ` · ${head.n_failed} failed` : "";
                return (
                  <tr
                    key={head.run_id}
                    className="cursor-pointer hover:bg-secondary/40 transition-colors border-b border-border/50"
                    onClick={() => navigate(`/backtest/modal/runs/${head.run_id}`)}
                  >
                    <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">
                      {formatDateTime(head.started_at)}
                    </td>
                    <td className="px-3 py-2 text-xs text-foreground">
                      {head.universe ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      <div className="flex items-center gap-1.5">
                        <code className="text-[10px] text-muted-foreground font-mono">
                          {shortHash(head.config_hash)}
                        </code>
                        {siblings.length > 0 && (
                          <Badge
                            variant="outline"
                            className="text-[9px] text-muted-foreground border-muted-foreground/20"
                          >
                            ×{siblings.length + 1}
                          </Badge>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge status={head.status} />
                    </td>
                    <td className={`px-3 py-2 text-xs font-medium ${signedClass(head.median_oos_sharpe)}`}>
                      {formatNum(head.median_oos_sharpe)}
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {head.pbo != null ? `${(head.pbo * 100).toFixed(0)}%` : "—"}
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {formatNum(head.deflated_sharpe)}
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">
                      {combosSummary}
                      {failedNote && (
                        <span className="text-[--negative]">{failedNote}</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap">
                      {formatDuration(head.started_at, head.finished_at)}
                    </td>
                  </tr>
                );
              })}
              {!isLoading && grouped.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-3 py-8 text-center text-xs text-muted-foreground">
                    No Modal runs yet. Queue one with the "New Backtest" button above.
                  </td>
                </tr>
              )}
              {isLoading && grouped.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-3 py-8 text-center text-xs text-muted-foreground">
                    Loading runs…
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
