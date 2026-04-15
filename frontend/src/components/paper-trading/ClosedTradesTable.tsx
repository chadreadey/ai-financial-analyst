import { Badge } from "@/components/ui/badge";

interface Trade {
  ticker: string;
  entry_price: number;
  entry_date: string;
  exit_price: number;
  exit_date: string;
  pnl_pct: number;
  exit_reason: string;
}

interface Props {
  trades: Trade[];
}

const reasonClassName: Record<string, string> = {
  target_hit: "bg-[--positive]/10 text-[--positive] border-[--positive]/20",
  stop_loss: "bg-[--negative]/10 text-[--negative] border-[--negative]/20",
  manual_close: "bg-[--warning]/10 text-[--warning] border-[--warning]/20",
};

export function ClosedTradesTable({ trades }: Props) {
  return (
    <div>
      <div className="px-3 py-2 border-b border-border">
        <span className="text-xs font-medium text-foreground">Closed Trades ({trades.length})</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border bg-secondary">
              {["Ticker", "Entry", "Exit", "P&L", "Date", "Reason"].map((h) => (
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
            {trades.map((t, i) => (
              <tr key={i} className="border-b border-border last:border-0 hover:bg-secondary/40 transition-colors">
                <td className="px-3 py-1.5 text-xs font-medium text-foreground">{t.ticker}</td>
                <td className="px-3 py-1.5 text-xs text-muted-foreground">${t.entry_price.toFixed(2)}</td>
                <td className="px-3 py-1.5 text-xs text-muted-foreground">${t.exit_price.toFixed(2)}</td>
                <td className={`px-3 py-1.5 text-xs font-medium ${t.pnl_pct >= 0 ? "text-[--positive]" : "text-[--negative]"}`}>
                  {t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct.toFixed(2)}%
                </td>
                <td className="px-3 py-1.5 text-xs text-muted-foreground">{t.exit_date}</td>
                <td className="px-3 py-1.5">
                  <Badge
                    variant={reasonClassName[t.exit_reason] ? "outline" : "secondary"}
                    className={`text-[10px] ${reasonClassName[t.exit_reason] || ""}`}
                  >
                    {t.exit_reason}
                  </Badge>
                </td>
              </tr>
            ))}
            {trades.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-xs text-muted-foreground">
                  No closed trades yet
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
