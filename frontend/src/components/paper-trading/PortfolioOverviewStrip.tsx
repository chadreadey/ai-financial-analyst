import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { PortfolioOverviewTotals } from "@/api/types";

interface Props {
  totals: PortfolioOverviewTotals;
}

interface Stat {
  label: string;
  value: string;
  tone?: "positive" | "negative" | "warning" | "muted";
}

function buildStats(totals: PortfolioOverviewTotals): Stat[] {
  const pnl = totals.avg_unrealized_pnl_pct;
  return [
    {
      label: "Open Positions",
      value: String(totals.total_positions),
    },
    {
      label: "Equity at Entry",
      value: `$${totals.total_equity_at_entry.toLocaleString(undefined, {
        maximumFractionDigits: 2,
      })}`,
    },
    {
      label: "Avg Unrealized P&L",
      value: pnl != null ? `${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}%` : "—",
      tone: pnl == null ? "muted" : pnl >= 0 ? "positive" : "negative",
    },
    {
      label: "Stale Verdicts",
      value: String(totals.stale_count),
      tone: totals.stale_count > 0 ? "warning" : undefined,
    },
  ];
}

export function PortfolioOverviewStrip({ totals }: Props) {
  const stats = buildStats(totals);

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {stats.map((s) => (
        <Card key={s.label} className="p-3">
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
            {s.label}
          </div>
          <div
            className={cn(
              "text-lg font-bold",
              s.tone === "positive" && "text-[--positive]",
              s.tone === "negative" && "text-[--negative]",
              s.tone === "warning" && "text-[--warning]",
              s.tone === "muted" && "text-muted-foreground"
            )}
          >
            {s.value}
          </div>
        </Card>
      ))}
    </div>
  );
}
