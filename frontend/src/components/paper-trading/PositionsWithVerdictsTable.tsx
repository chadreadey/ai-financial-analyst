import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { PositionWithVerdict } from "@/api/types";

interface Props {
  positions: PositionWithVerdict[];
  onClose: (ticker: string, exitPrice: number, reason: string) => void;
}

function verdictRowTint(verdict: string | undefined | null): string {
  if (!verdict) return "";
  const v = verdict.toUpperCase();
  if (v.includes("STRONG BUY")) return "bg-[--positive]/10";
  if (v.includes("BUY")) return "bg-[--positive]/[0.04]";
  if (v.includes("STRONG SELL")) return "bg-[--negative]/10";
  if (v.includes("SELL")) return "bg-[--negative]/[0.04]";
  return "";
}

function verdictBadgeClass(verdict: string | undefined | null): string {
  if (!verdict) return "";
  const v = verdict.toUpperCase();
  if (v.includes("BUY")) return "text-[--positive] border-[--positive]/30 bg-[--positive]/10";
  if (v.includes("SELL")) return "text-[--negative] border-[--negative]/30 bg-[--negative]/10";
  return "text-[--warning] border-[--warning]/30 bg-[--warning]/10";
}

function staleBadge(daysStale: number | null | undefined) {
  if (daysStale == null) {
    return (
      <Badge variant="outline" className="text-[10px] text-muted-foreground border-dashed">
        no analysis
      </Badge>
    );
  }
  if (daysStale > 14) {
    return (
      <Badge
        variant="outline"
        className="text-[10px] text-[--negative] border-[--negative]/30 bg-[--negative]/10"
      >
        Stale ({daysStale}d)
      </Badge>
    );
  }
  if (daysStale > 7) {
    return (
      <Badge
        variant="outline"
        className="text-[10px] text-[--warning] border-[--warning]/30 bg-[--warning]/10"
      >
        Stale ({daysStale}d)
      </Badge>
    );
  }
  return <span className="text-[11px] text-muted-foreground">{daysStale}d</span>;
}

export function PositionsWithVerdictsTable({ positions, onClose }: Props) {
  const [closing, setClosing] = useState<string | null>(null);
  const [exitPrice, setExitPrice] = useState("");

  const handleClose = (ticker: string) => {
    const price = parseFloat(exitPrice);
    if (isNaN(price) || price <= 0) return;
    onClose(ticker, price, "manual_close");
    setClosing(null);
    setExitPrice("");
  };

  const cols = [
    "Ticker",
    "Entry",
    "Current",
    "P&L",
    "Entry V.",
    "Current V.",
    "Conv.",
    "Target",
    "Upside",
    "Stale",
    "Action",
  ];

  return (
    <div>
      <div className="px-3 py-2 border-b border-border">
        <span className="text-xs font-medium text-foreground">
          Open Positions ({positions.length})
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border bg-secondary">
              {cols.map((h) => (
                <th
                  key={h}
                  className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => {
              const lv = p.latest_verdict;
              const pnlPositive = p.unrealized_pnl_pct != null && p.unrealized_pnl_pct >= 0;
              const upsidePositive = lv?.implied_upside_pct != null && lv.implied_upside_pct >= 0;
              const tint = verdictRowTint(lv?.verdict);

              return (
                <tr
                  key={p.ticker}
                  className={cn(
                    "border-b border-border last:border-0 transition-colors hover:bg-secondary/40",
                    tint
                  )}
                >
                  <td className="px-3 py-1.5 text-xs font-medium">
                    <Link
                      to={`/deepdive/${p.ticker}?source=portfolio`}
                      className="text-primary hover:underline"
                    >
                      {p.ticker}
                    </Link>
                  </td>
                  <td className="px-3 py-1.5 text-xs text-muted-foreground">
                    ${p.entry_price.toFixed(2)}
                  </td>
                  <td className="px-3 py-1.5 text-xs text-muted-foreground">
                    {p.current_price != null ? `$${p.current_price.toFixed(2)}` : "—"}
                  </td>
                  <td
                    className={cn(
                      "px-3 py-1.5 text-xs font-medium",
                      p.unrealized_pnl_pct == null
                        ? "text-muted-foreground"
                        : pnlPositive
                        ? "text-[--positive]"
                        : "text-[--negative]"
                    )}
                  >
                    {p.unrealized_pnl_pct != null
                      ? `${pnlPositive ? "+" : ""}${p.unrealized_pnl_pct.toFixed(2)}%`
                      : "—"}
                  </td>
                  <td className="px-3 py-1.5 text-[11px] text-muted-foreground">
                    {p.entry_verdict || "—"}
                  </td>
                  <td className="px-3 py-1.5">
                    {lv?.verdict ? (
                      <Badge
                        variant="outline"
                        className={cn("text-[10px]", verdictBadgeClass(lv.verdict))}
                      >
                        {lv.verdict}
                      </Badge>
                    ) : (
                      <span className="text-[11px] text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="px-3 py-1.5 text-[11px] text-muted-foreground">
                    {lv?.conviction || "—"}
                  </td>
                  <td className="px-3 py-1.5 text-[11px] text-muted-foreground">
                    {lv?.price_target != null ? `$${lv.price_target.toFixed(2)}` : "—"}
                  </td>
                  <td
                    className={cn(
                      "px-3 py-1.5 text-[11px] font-medium",
                      lv?.implied_upside_pct == null
                        ? "text-muted-foreground"
                        : upsidePositive
                        ? "text-[--positive]"
                        : "text-[--negative]"
                    )}
                  >
                    {lv?.implied_upside_pct != null
                      ? `${upsidePositive ? "+" : ""}${lv.implied_upside_pct.toFixed(1)}%`
                      : "—"}
                  </td>
                  <td className="px-3 py-1.5">{staleBadge(lv?.days_stale ?? null)}</td>
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
                <td
                  colSpan={cols.length}
                  className="px-3 py-6 text-center text-xs text-muted-foreground"
                >
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
