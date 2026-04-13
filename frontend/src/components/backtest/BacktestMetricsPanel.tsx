import { Card } from "@/components/ui/card";

interface Props {
  sharpe: number | null;
  sortino: number | null;
  calmar: number | null;
  maxDrawdown: number | null;
  winRate: number | null;
  hitRate: number | null;
}

export function BacktestMetricsPanel({ sharpe, sortino, calmar, maxDrawdown, winRate, hitRate }: Props) {
  const items = [
    { label: "Sharpe", value: sharpe != null ? sharpe.toFixed(2) : "—" },
    { label: "Sortino", value: sortino != null ? sortino.toFixed(2) : "—" },
    { label: "Calmar", value: calmar != null ? calmar.toFixed(2) : "—" },
    { label: "Max Drawdown", value: maxDrawdown != null ? `${maxDrawdown.toFixed(1)}%` : "—" },
    { label: "Win Rate", value: winRate != null ? `${winRate.toFixed(1)}%` : "—" },
    { label: "Hit Rate", value: hitRate != null ? `${hitRate.toFixed(1)}%` : "—" },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      {items.map((m) => (
        <Card key={m.label} className="p-2.5">
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
