import { Card } from "@/components/ui/card";
import type { PaperMetrics } from "../../api/types";

interface Props {
  metrics: PaperMetrics | null;
}

function MetricCard({ label, value, colorClass = "" }: { label: string; value: string; colorClass?: string }) {
  return (
    <Card className="p-3">
      <div className="text-[10px] font-medium uppercase tracking-[0.8px] text-muted-foreground">
        {label}
      </div>
      <div className={`text-sm font-semibold mt-0.5 ${colorClass || "text-foreground"}`}>{value}</div>
    </Card>
  );
}

export function PaperMetricsPanel({ metrics }: Props) {
  const totalPnl = metrics?.total_pnl_pct ?? null;
  const winRate = metrics?.win_rate_pct ?? null;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
      <MetricCard
        label="Sharpe"
        value={metrics?.sharpe != null ? metrics.sharpe.toFixed(2) : "—"}
        colorClass="text-primary"
      />
      <MetricCard
        label="Sortino"
        value={metrics?.sortino != null ? metrics.sortino.toFixed(2) : "—"}
        colorClass="text-primary"
      />
      <MetricCard
        label="Win Rate"
        value={winRate != null ? `${winRate.toFixed(1)}%` : "—"}
        colorClass={winRate != null && winRate >= 50 ? "text-[--positive]" : "text-[--negative]"}
      />
      <MetricCard
        label="Total P&L"
        value={totalPnl != null ? `${totalPnl >= 0 ? "+" : ""}${totalPnl.toFixed(2)}%` : "—"}
        colorClass={totalPnl != null ? (totalPnl >= 0 ? "text-[--positive]" : "text-[--negative]") : ""}
      />
      <MetricCard
        label="Total Trades"
        value={metrics?.total_trades != null ? String(metrics.total_trades) : "—"}
      />
    </div>
  );
}
