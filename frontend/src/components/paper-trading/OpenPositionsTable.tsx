import { useState } from "react";
import { Badge } from "../common/Badge";

interface Position {
  ticker: string;
  entry_price: number;
  entry_date: string;
  current_price: number | null;
  verdict: string;
  unrealized_pnl_pct: number | null;
  days_held: number;
}

interface Props {
  positions: Position[];
  onClose: (ticker: string, exitPrice: number, reason: string) => void;
}

export function OpenPositionsTable({ positions, onClose }: Props) {
  const [closing, setClosing] = useState<string | null>(null);
  const [exitPrice, setExitPrice] = useState("");

  const handleClose = (ticker: string) => {
    const price = parseFloat(exitPrice);
    if (isNaN(price) || price <= 0) return;
    onClose(ticker, price, "manual_close");
    setClosing(null);
    setExitPrice("");
  };

  return (
    <div>
      <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
        Open Positions ({positions.length})
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              {["Ticker", "Entry", "Current", "P&L", "Days", "Action"].map((h) => (
                <th key={h} className="text-left py-2 px-2 font-medium" style={{ color: "var(--text-muted)" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr key={p.ticker} style={{ borderBottom: "1px solid var(--border-subtle, var(--border))" }}>
                <td className="py-1.5 px-2 font-medium" style={{ color: "var(--text-primary)" }}>{p.ticker}</td>
                <td className="py-1.5 px-2" style={{ color: "var(--text-secondary)" }}>${p.entry_price.toFixed(2)}</td>
                <td className="py-1.5 px-2" style={{ color: "var(--text-secondary)" }}>
                  {p.current_price != null ? `$${p.current_price.toFixed(2)}` : "—"}
                </td>
                <td className="py-1.5 px-2 font-medium" style={{
                  color: p.unrealized_pnl_pct != null
                    ? (p.unrealized_pnl_pct >= 0 ? "var(--accent-green)" : "var(--accent-red)")
                    : "var(--text-muted)"
                }}>
                  {p.unrealized_pnl_pct != null ? `${p.unrealized_pnl_pct >= 0 ? "+" : ""}${p.unrealized_pnl_pct.toFixed(2)}%` : "—"}
                </td>
                <td className="py-1.5 px-2" style={{ color: "var(--text-secondary)" }}>{p.days_held}d</td>
                <td className="py-1.5 px-2">
                  {closing === p.ticker ? (
                    <div className="flex items-center gap-1">
                      <input
                        value={exitPrice}
                        onChange={(e) => setExitPrice(e.target.value)}
                        placeholder="Exit $"
                        className="w-20 rounded px-2 py-0.5 text-xs"
                        style={{ background: "var(--bg-primary)", border: "1px solid var(--border)", color: "var(--text-primary)" }}
                      />
                      <button onClick={() => handleClose(p.ticker)} className="text-xs px-2 py-0.5 rounded"
                        style={{ background: "var(--accent-red)", color: "white" }}>OK</button>
                      <button onClick={() => setClosing(null)} className="text-xs px-2 py-0.5 rounded"
                        style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}>X</button>
                    </div>
                  ) : (
                    <button onClick={() => setClosing(p.ticker)} className="text-xs px-2 py-0.5 rounded"
                      style={{ background: "var(--bg-hover)", color: "var(--accent-red)" }}>Close</button>
                  )}
                </td>
              </tr>
            ))}
            {positions.length === 0 && (
              <tr>
                <td colSpan={6} className="text-center py-4" style={{ color: "var(--text-muted)" }}>
                  No open positions
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
