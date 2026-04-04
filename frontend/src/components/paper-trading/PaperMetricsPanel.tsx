import { Card } from "../common/Card";
import type { PaperMetrics } from "../../api/types";

interface Props {
  metrics: PaperMetrics | null;
}

export function PaperMetricsPanel({ metrics }: Props) {
  const items = [
    { label: "Sharpe", value: metrics?.sharpe != null ? metrics.sharpe.toFixed(2) : "—" },
    { label: "Sortino", value: metrics?.sortino != null ? metrics.sortino.toFixed(2) : "—" },
    { label: "Win Rate", value: metrics?.win_rate_pct != null ? `${metrics.win_rate_pct.toFixed(1)}%` : "—" },
    { label: "Total P&L", value: metrics?.total_pnl_pct != null ? `${metrics.total_pnl_pct >= 0 ? "+" : ""}${metrics.total_pnl_pct.toFixed(2)}%` : "—" },
    { label: "Total Trades", value: metrics?.total_trades != null ? String(metrics.total_trades) : "—" },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
      {items.map((m) => (
        <Card key={m.label} padding="sm">
          <div className="text-[10px] uppercase tracking-wider mb-1" style={{ color: "var(--text-muted)" }}>
            {m.label}
          </div>
          <div className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>
            {m.value}
          </div>
        </Card>
      ))}
    </div>
  );
}
