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
      <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
        Closed Trades ({trades.length})
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              {["Ticker", "Entry", "Exit", "P&L", "Date", "Reason"].map((h) => (
                <th key={h} className="text-left py-2 px-2 font-medium" style={{ color: "var(--text-muted)" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {trades.map((t, i) => (
              <tr key={i} style={{ borderBottom: "1px solid var(--border-subtle, var(--border))" }}>
                <td className="py-1.5 px-2 font-medium" style={{ color: "var(--text-primary)" }}>{t.ticker}</td>
                <td className="py-1.5 px-2" style={{ color: "var(--text-secondary)" }}>${t.entry_price.toFixed(2)}</td>
                <td className="py-1.5 px-2" style={{ color: "var(--text-secondary)" }}>${t.exit_price.toFixed(2)}</td>
                <td className="py-1.5 px-2 font-medium" style={{
                  color: t.pnl_pct >= 0 ? "var(--accent-green)" : "var(--accent-red)"
                }}>
                  {t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct.toFixed(2)}%
                </td>
                <td className="py-1.5 px-2" style={{ color: "var(--text-secondary)" }}>{t.exit_date}</td>
                <td className="py-1.5 px-2">
                  <Badge variant={reasonClassName[t.exit_reason] ? "outline" : "secondary"} className={reasonClassName[t.exit_reason] || ""}>{t.exit_reason}</Badge>
                </td>
              </tr>
            ))}
            {trades.length === 0 && (
              <tr>
                <td colSpan={6} className="text-center py-4" style={{ color: "var(--text-muted)" }}>
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
