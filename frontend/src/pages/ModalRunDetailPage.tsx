import { useMemo, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import {
  useModalCombinations,
  useModalRun,
  useModalRunEvents,
} from "../hooks/useModalBacktests";
import { StatusBadge } from "../components/backtest/modal-format";
import {
  formatDateTime,
  formatDuration,
  formatNum,
  formatPct,
  shortHash,
  signedClass,
} from "../components/backtest/modal-utils";
import { ArrowLeft, RefreshCw } from "lucide-react";
import type { ModalCombination, ModalEvent, ModalRun } from "../api/types";

// Terminal statuses disable polling of combinations/events.
const isActiveStatus = (s: string | undefined) => s === "queued" || s === "running";

export function ModalRunDetailPage() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const { run, isLoading, error, refresh } = useModalRun(runId);

  const active = run == null ? true : isActiveStatus(run.status);
  const { combinations, isLoading: combosLoading } = useModalCombinations(runId, {
    active,
    pollMs: active ? 4000 : 0,
    limit: 1000,
  });
  const { events } = useModalRunEvents(runId, { active, pollMs: active ? 2000 : 0 });

  if (!runId) {
    return <p className="text-sm text-muted-foreground">Missing run ID.</p>;
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <Button variant="secondary" size="sm" onClick={() => navigate("/backtest")}>
            <ArrowLeft size={13} className="mr-1.5" />
            Runs
          </Button>
          <h1 className="text-lg font-semibold text-foreground">
            Run <code className="font-mono text-sm">{shortHash(runId, 12)}</code>
          </h1>
          {run && <StatusBadge status={run.status} />}
        </div>
        <Button variant="ghost" size="sm" onClick={() => void refresh()}>
          <RefreshCw size={12} className="mr-1.5" />
          Refresh
        </Button>
      </div>

      {error && (
        <Card className="p-3">
          <p className="text-xs text-[--negative]">{error}</p>
        </Card>
      )}

      {isLoading && !run && (
        <Card className="p-3">
          <p className="text-xs text-muted-foreground">Loading run…</p>
        </Card>
      )}

      {run && (
        <>
          {/* Summary metrics */}
          <Card className="p-4">
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
              <Metric
                label="Median OOS Sharpe"
                value={formatNum(run.median_oos_sharpe)}
                valueClass={signedClass(run.median_oos_sharpe)}
              />
              <Metric
                label="OOS Range"
                value={
                  run.oos_sharpe_min != null && run.oos_sharpe_max != null
                    ? `${formatNum(run.oos_sharpe_min)} / ${formatNum(run.oos_sharpe_max)}`
                    : "—"
                }
              />
              <Metric
                label="PBO"
                value={run.pbo != null ? `${(run.pbo * 100).toFixed(0)}%` : "—"}
                valueClass={
                  run.pbo != null && run.pbo <= 0.2
                    ? "text-[--positive]"
                    : run.pbo != null && run.pbo >= 0.5
                    ? "text-[--warning]"
                    : "text-foreground"
                }
              />
              <Metric label="Deflated Sharpe" value={formatNum(run.deflated_sharpe)} />
              <Metric
                label="Combinations"
                value={`${run.n_completed}/${run.n_combinations ?? "—"}`}
                sub={run.n_failed > 0 ? `${run.n_failed} failed` : run.n_skipped > 0 ? `${run.n_skipped} skipped` : undefined}
              />
              <Metric
                label="Runtime"
                value={formatDuration(run.started_at, run.finished_at)}
                sub={formatDateTime(run.started_at)}
              />
            </div>
          </Card>

          <Tabs defaultValue="combinations">
            <TabsList>
              <TabsTrigger value="combinations">
                Combinations ({combinations.length})
              </TabsTrigger>
              <TabsTrigger value="events">Events ({events.length})</TabsTrigger>
              <TabsTrigger value="config">Config</TabsTrigger>
            </TabsList>

            <TabsContent value="combinations">
              <CombinationsTable
                runId={runId}
                combinations={combinations}
                isLoading={combosLoading}
              />
            </TabsContent>

            <TabsContent value="events">
              <EventsList events={events} />
            </TabsContent>

            <TabsContent value="config">
              <ConfigCard run={run} />
            </TabsContent>
          </Tabs>
        </>
      )}
    </div>
  );
}

function Metric({
  label,
  value,
  sub,
  valueClass,
}: {
  label: string;
  value: string;
  sub?: string;
  valueClass?: string;
}) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">
        {label}
      </div>
      <div className={`mt-1 text-sm font-medium ${valueClass ?? "text-foreground"}`}>
        {value}
      </div>
      {sub && <div className="text-[10px] text-muted-foreground/70 mt-0.5">{sub}</div>}
    </div>
  );
}

function CombinationsTable({
  runId,
  combinations,
  isLoading,
}: {
  runId: string;
  combinations: ModalCombination[];
  isLoading: boolean;
}) {
  const [sortKey, setSortKey] = useState<"oos_sharpe" | "combo_idx" | "return_pct" | "n_trades">("oos_sharpe");
  const [descending, setDescending] = useState(true);

  const sorted = useMemo(() => {
    const copy = [...combinations];
    copy.sort((a, b) => {
      const av = (a[sortKey] as number | null) ?? Number.NEGATIVE_INFINITY;
      const bv = (b[sortKey] as number | null) ?? Number.NEGATIVE_INFINITY;
      return descending ? bv - av : av - bv;
    });
    return copy;
  }, [combinations, sortKey, descending]);

  const toggleSort = (k: typeof sortKey) => {
    if (k === sortKey) setDescending((d) => !d);
    else {
      setSortKey(k);
      setDescending(true);
    }
  };

  const columns: Array<{ key: typeof sortKey | "status" | "gates"; label: string; sortable: boolean }> = [
    { key: "combo_idx", label: "#", sortable: true },
    { key: "status", label: "Status", sortable: false },
    { key: "oos_sharpe", label: "OOS Sharpe", sortable: true },
    { key: "return_pct", label: "Return", sortable: true },
    { key: "n_trades", label: "# Trades", sortable: true },
    { key: "gates", label: "Gates", sortable: false },
  ];

  return (
    <Card className="p-0 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border">
              {columns.map((c) => (
                <th
                  key={c.key}
                  onClick={c.sortable ? () => toggleSort(c.key as typeof sortKey) : undefined}
                  className={
                    "px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/50 " +
                    (c.sortable ? "cursor-pointer hover:text-foreground select-none" : "")
                  }
                >
                  {c.label}
                  {c.sortable && sortKey === c.key && (
                    <span className="ml-1 text-primary">{descending ? "↓" : "↑"}</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((c) => (
              <ComboRow key={c.combo_idx} runId={runId} combo={c} />
            ))}
            {!isLoading && sorted.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-xs text-muted-foreground">
                  No combinations reported yet.
                </td>
              </tr>
            )}
            {isLoading && sorted.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-xs text-muted-foreground">
                  Loading…
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function ComboRow({ runId, combo }: { runId: string; combo: ModalCombination }) {
  const gateHits = useMemo(() => {
    const g = combo.gates_json ?? {};
    // gates_json is a dict like { "sharpe_gate": true, "min_trades": false, ... }
    const entries = Object.entries(g).filter(([, v]) => typeof v === "boolean");
    const hits = entries.filter(([, v]) => !v).map(([k]) => k);
    return hits;
  }, [combo.gates_json]);

  const statusStyle =
    combo.status === "complete"
      ? "text-[--positive] border-[--positive]/20 bg-[--positive]/10"
      : combo.status === "skipped"
      ? "text-muted-foreground border-muted-foreground/20 bg-muted/20"
      : "text-[--negative] border-[--negative]/20 bg-[--negative]/10";

  return (
    <tr className="hover:bg-secondary/40 transition-colors border-b border-border/50">
      <td className="px-3 py-2 text-xs text-muted-foreground">
        <Link
          to={`/backtest/modal/runs/${runId}/combos/${combo.combo_idx}`}
          className="hover:text-primary transition-colors"
        >
          #{combo.combo_idx}
        </Link>
      </td>
      <td className="px-3 py-2">
        <Badge variant="outline" className={`text-[9px] uppercase tracking-wider ${statusStyle}`}>
          {combo.status}
        </Badge>
      </td>
      <td className={`px-3 py-2 text-xs font-medium ${signedClass(combo.oos_sharpe)}`}>
        {formatNum(combo.oos_sharpe)}
      </td>
      <td className={`px-3 py-2 text-xs ${signedClass(combo.return_pct)}`}>
        {formatPct(combo.return_pct)}
      </td>
      <td className="px-3 py-2 text-xs text-muted-foreground">{combo.n_trades ?? "—"}</td>
      <td className="px-3 py-2 text-xs">
        {gateHits.length === 0 ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {gateHits.map((g) => (
              <Badge
                key={g}
                variant="outline"
                className="text-[9px] text-[--warning] border-[--warning]/20 bg-[--warning]/10"
              >
                {g}
              </Badge>
            ))}
          </div>
        )}
      </td>
    </tr>
  );
}

function EventsList({ events }: { events: ModalEvent[] }) {
  if (events.length === 0) {
    return (
      <Card className="p-6 text-center">
        <p className="text-xs text-muted-foreground">No events yet.</p>
      </Card>
    );
  }
  return (
    <Card className="p-0 overflow-hidden">
      <div className="max-h-[60vh] overflow-y-auto">
        <table className="w-full">
          <thead className="sticky top-0 bg-card">
            <tr className="border-b border-border">
              {["Time", "Kind", "Combo", "Payload"].map((h) => (
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
            {events.map((e) => (
              <tr key={e.id} className="border-b border-border/50">
                <td className="px-3 py-2 text-xs text-muted-foreground whitespace-nowrap font-mono">
                  {formatDateTime(e.created_at)}
                </td>
                <td className="px-3 py-2 text-xs">
                  <Badge variant="outline" className="text-[9px] uppercase tracking-wider">
                    {e.kind}
                  </Badge>
                </td>
                <td className="px-3 py-2 text-xs text-muted-foreground font-mono">
                  {e.combo_idx ?? "—"}
                </td>
                <td className="px-3 py-2 text-[10px] text-muted-foreground font-mono">
                  {e.payload ? JSON.stringify(e.payload) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function ConfigCard({ run }: { run: Pick<ModalRun, "config_json" | "config_hash" | "git_sha" | "metrics_json"> }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <Card className="p-4">
        <div className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50 mb-2">
          Reproducibility
        </div>
        <div className="space-y-1.5 text-xs">
          <KV label="config_hash" value={run.config_hash} mono />
          <KV label="git_sha" value={run.git_sha} mono />
        </div>
      </Card>
      <Card className="p-4">
        <div className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50 mb-2">
          Config
        </div>
        <pre className="text-[10px] text-muted-foreground font-mono whitespace-pre-wrap max-h-[40vh] overflow-y-auto">
          {JSON.stringify(run.config_json, null, 2)}
        </pre>
      </Card>
      {run.metrics_json && (
        <Card className="p-4 md:col-span-2">
          <div className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50 mb-2">
            Aggregate Metrics
          </div>
          <pre className="text-[10px] text-muted-foreground font-mono whitespace-pre-wrap max-h-[40vh] overflow-y-auto">
            {JSON.stringify(run.metrics_json, null, 2)}
          </pre>
        </Card>
      )}
    </div>
  );
}

function KV({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground/50 w-24 shrink-0">
        {label}
      </span>
      <code className={`${mono ? "font-mono" : ""} text-foreground break-all`}>{value}</code>
    </div>
  );
}
