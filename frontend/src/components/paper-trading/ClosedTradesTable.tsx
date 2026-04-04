import { Badge } from "../common/Badge";

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

const reasonVariant: Record<string, "green" | "red" | "muted" | "amber"> = {
  target_hit: "green",
  stop_loss: "red",
  time_decay: "muted",
  manual_close: "amber",
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
                  <Badge label={t.exit_reason} variant={reasonVariant[t.exit_reason] || "muted"} size="sm" />
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
