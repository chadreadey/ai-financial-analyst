import { Card } from "../common/Card";
import type { WatchlistSummary } from "../../api/types";

interface Props {
  summary: WatchlistSummary | undefined;
}

export function PerformanceMetricsPanel({ summary }: Props) {
  const metrics = [
    { label: "Hit Rate", value: summary?.hit_rate_pct != null ? `${summary.hit_rate_pct}%` : "—" },
    { label: "Alpha vs SPY", value: summary?.alpha_vs_spy != null ? `${summary.alpha_vs_spy > 0 ? "+" : ""}${summary.alpha_vs_spy}%` : "—" },
    { label: "Current Price", value: summary?.current_price != null ? `$${summary.current_price.toFixed(2)}` : "—" },
  ];

  return (
    <div className="grid grid-cols-3 gap-3">
      {metrics.map((m) => (
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
