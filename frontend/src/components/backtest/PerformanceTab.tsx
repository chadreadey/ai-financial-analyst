import { Card } from "@/components/ui/card";
import { EquityCurveChart } from "@/components/charts/EquityCurveChart";

interface PerformanceTabProps {
  sharpe: number | null;
  totalReturn: number | null;
  maxDrawdown: number | null;
  alpha: number | null;
  equityCurve: { date: string; equity: number }[];
}

function MetricCard({
  label,
  value,
  colorClass = "",
}: {
  label: string;
  value: string;
  colorClass?: string;
}) {
  return (
    <Card className="p-3">
      <div className="text-[10px] font-medium uppercase tracking-[0.8px] text-muted-foreground">
        {label}
      </div>
      <div className={`text-sm font-semibold mt-0.5 ${colorClass}`}>{value}</div>
    </Card>
  );
}

export function PerformanceTab({
  sharpe,
  totalReturn,
  maxDrawdown,
  alpha,
  equityCurve,
}: PerformanceTabProps) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-3">
        <MetricCard
          label="Sharpe Ratio"
          value={sharpe?.toFixed(2) ?? "—"}
          colorClass="text-primary"
        />
        <MetricCard
          label="Total Return"
          value={
            totalReturn != null
              ? `${totalReturn > 0 ? "+" : ""}${totalReturn.toFixed(1)}%`
              : "—"
          }
          colorClass={
            totalReturn != null && totalReturn > 0
              ? "text-[--positive]"
              : "text-[--negative]"
          }
        />
        <MetricCard
          label="Max Drawdown"
          value={maxDrawdown != null ? `${maxDrawdown.toFixed(1)}%` : "—"}
          colorClass="text-[--negative]"
        />
        <MetricCard
          label="Alpha (ann.)"
          value={alpha != null ? `${alpha > 0 ? "+" : ""}${alpha.toFixed(1)}%` : "—"}
          colorClass={
            alpha != null && alpha > 0 ? "text-[--positive]" : "text-muted-foreground"
          }
        />
      </div>

      {equityCurve.length > 0 && (
        <div className="rounded-lg border border-border p-3" style={{ background: "#0f0f11" }}>
          <EquityCurveChart data={equityCurve} height={200} />
        </div>
      )}
    </div>
  );
}
