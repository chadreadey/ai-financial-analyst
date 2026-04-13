import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface Trade {
  date: string;
  ticker: string;
  direction: string;
  entry_price: number;
  exit_price: number;
  return_pct: number;
  regime?: string;
  signals?: Record<string, number>;
  vix_level?: number;
  [key: string]: any;
}

export function TradeDetailRow({ trade }: { trade: Trade }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <tr
        className="cursor-pointer hover:bg-secondary/50 transition-colors"
        onClick={() => setOpen(!open)}
      >
        <td className="px-3 py-2 text-xs text-muted-foreground">{trade.date}</td>
        <td className="px-3 py-2 text-xs font-medium text-foreground">{trade.ticker}</td>
        <td className="px-3 py-2">
          <Badge
            variant="outline"
            className={cn(
              "text-[9px]",
              trade.direction === "LONG"
                ? "text-[--positive] border-[--positive]/20 bg-[--positive]/10"
                : "text-[--negative] border-[--negative]/20 bg-[--negative]/10"
            )}
          >
            {trade.direction}
          </Badge>
        </td>
        <td className="px-3 py-2 text-xs text-muted-foreground">
          ${trade.entry_price?.toFixed(2)}
        </td>
        <td className="px-3 py-2 text-xs text-muted-foreground">
          ${trade.exit_price?.toFixed(2)}
        </td>
        <td
          className={cn(
            "px-3 py-2 text-xs font-medium",
            trade.return_pct >= 0 ? "text-[--positive]" : "text-[--negative]"
          )}
        >
          {trade.return_pct >= 0 ? "+" : ""}
          {trade.return_pct?.toFixed(1)}%
        </td>
        <td className="px-3 py-2 text-xs text-muted-foreground">{trade.regime ?? "—"}</td>
        <td className="px-3 py-2 text-xs">
          <ChevronRight
            size={12}
            className={cn(
              "text-muted-foreground transition-transform",
              open && "rotate-90"
            )}
          />
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={8} className="px-3 py-3 bg-card border-t border-border">
            <div className="grid grid-cols-2 gap-4 text-xs">
              {trade.signals && Object.keys(trade.signals).length > 0 && (
                <div>
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/50 mb-1">
                    Signal Scores at Entry
                  </div>
                  <div className="flex flex-wrap gap-3">
                    {Object.entries(trade.signals).map(([name, value]) => (
                      <div key={name}>
                        <span className="text-[9px] uppercase tracking-wider text-muted-foreground/50">
                          {name}
                        </span>
                        <span
                          className={cn(
                            "ml-1 font-medium",
                            Number(value) > 0
                              ? "text-primary"
                              : Number(value) < 0
                              ? "text-[--negative]"
                              : "text-muted-foreground"
                          )}
                        >
                          {Number(value) > 0 ? "+" : ""}
                          {Number(value).toFixed(2)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/50 mb-1">
                  Regime at Entry
                </div>
                <span className="text-muted-foreground">{trade.regime ?? "Unknown"}</span>
                {trade.vix_level && (
                  <span className="ml-2 text-muted-foreground">VIX {trade.vix_level}</span>
                )}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
