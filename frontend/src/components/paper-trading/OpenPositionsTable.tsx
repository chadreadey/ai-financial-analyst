import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

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
      <div className="px-3 py-2 border-b border-border">
        <span className="text-xs font-medium text-foreground">Open Positions ({positions.length})</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border bg-secondary">
              {["Ticker", "Entry", "Current", "P&L", "Days", "Action"].map((h) => (
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
            {positions.map((p) => {
              const pnlPositive = p.unrealized_pnl_pct != null && p.unrealized_pnl_pct >= 0;
              return (
                <tr key={p.ticker} className="border-b border-border last:border-0 hover:bg-secondary/40 transition-colors">
                  <td className="px-3 py-1.5 text-xs font-medium text-foreground">{p.ticker}</td>
                  <td className="px-3 py-1.5 text-xs text-muted-foreground">${p.entry_price.toFixed(2)}</td>
                  <td className="px-3 py-1.5 text-xs text-muted-foreground">
                    {p.current_price != null ? `$${p.current_price.toFixed(2)}` : "—"}
                  </td>
                  <td className={`px-3 py-1.5 text-xs font-medium ${
                    p.unrealized_pnl_pct != null
                      ? pnlPositive ? "text-[--positive]" : "text-[--negative]"
                      : "text-muted-foreground"
                  }`}>
                    {p.unrealized_pnl_pct != null
                      ? `${p.unrealized_pnl_pct >= 0 ? "+" : ""}${p.unrealized_pnl_pct.toFixed(2)}%`
                      : "—"}
                  </td>
                  <td className="px-3 py-1.5 text-xs text-muted-foreground">{p.days_held}d</td>
                  <td className="px-3 py-1.5">
                    {closing === p.ticker ? (
                      <div className="flex items-center gap-1">
                        <Input
                          value={exitPrice}
                          onChange={(e) => setExitPrice(e.target.value)}
                          placeholder="Exit $"
                          className="h-6 w-20 text-xs px-2"
                        />
                        <Button
                          size="sm"
                          variant="destructive"
                          className="h-6 px-2 text-xs"
                          onClick={() => handleClose(p.ticker)}
                        >
                          OK
                        </Button>
                        <Button
                          size="sm"
                          variant="secondary"
                          className="h-6 px-2 text-xs"
                          onClick={() => setClosing(null)}
                        >
                          ✕
                        </Button>
                      </div>
                    ) : (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-6 px-2 text-xs text-[--negative] hover:text-[--negative]"
                        onClick={() => setClosing(p.ticker)}
                      >
                        Close
                      </Button>
                    )}
                  </td>
                </tr>
              );
            })}
            {positions.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-xs text-muted-foreground">
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
