import { useState } from "react";
import { Badge } from "@/components/ui/badge";

interface Trade {
  ticker: string;
  entry_date: string;
  entry_price: number;
  exit_date: string;
  exit_price: number;
  pnl_pct: number;
  exit_reason: string;
}

interface Props {
  trades: Trade[] | Record<string, any>[];
}

const reasonClassName: Record<string, string> = {
  target_hit: "bg-[--positive]/10 text-[--positive] border-[--positive]/20",
  stop_loss: "bg-[--negative]/10 text-[--negative] border-[--negative]/20",
  signal_change: "bg-[--warning]/10 text-[--warning] border-[--warning]/20",
};

export function TradeLogTable({ trades }: Props) {
  const [filter, setFilter] = useState("");
  const filtered = filter
    ? trades.filter((t) => t.ticker.includes(filter.toUpperCase()))
    : trades;

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
          Trade Log ({filtered.length})
        </h3>
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter by ticker..."
          className="rounded px-3 py-1 text-xs w-32"
          style={{ background: "var(--bg-primary)", border: "1px solid var(--border)", color: "var(--text-primary)" }}
        />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              {["Date", "Ticker", "Entry", "Exit", "Return %", "Reason"].map((h) => (
                <th key={h} className="text-left py-2 px-2 font-medium" style={{ color: "var(--text-muted)" }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((t, i) => (
              <tr key={i} style={{ borderBottom: "1px solid var(--border-subtle, var(--border))" }}>
                <td className="py-1.5 px-2" style={{ color: "var(--text-secondary)" }}>{t.entry_date}</td>
                <td className="py-1.5 px-2 font-medium" style={{ color: "var(--text-primary)" }}>{t.ticker}</td>
                <td className="py-1.5 px-2" style={{ color: "var(--text-secondary)" }}>${t.entry_price.toFixed(2)}</td>
                <td className="py-1.5 px-2" style={{ color: "var(--text-secondary)" }}>${t.exit_price.toFixed(2)}</td>
                <td className="py-1.5 px-2 font-medium" style={{ color: t.pnl_pct >= 0 ? "var(--accent-green)" : "var(--accent-red)" }}>
                  {t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct.toFixed(2)}%
                </td>
                <td className="py-1.5 px-2">
                  <Badge variant={reasonClassName[t.exit_reason] ? "outline" : "secondary"} className={reasonClassName[t.exit_reason] || ""}>{t.exit_reason}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
