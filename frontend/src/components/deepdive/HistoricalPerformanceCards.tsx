import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { RecommendationRecord } from "../../api/types";

interface Props {
  records: RecommendationRecord[];
}

function verdictClassName(v: string): string {
  const u = v.toUpperCase();
  if (u.includes("BUY")) return "bg-[--positive]/10 text-[--positive] border-[--positive]/20";
  if (u.includes("SELL")) return "bg-[--negative]/10 text-[--negative] border-[--negative]/20";
  if (u.includes("HOLD")) return "bg-[--warning]/10 text-[--warning] border-[--warning]/20";
  return "";
}

export function HistoricalPerformanceCards({ records }: Props) {
  if (records.length === 0) return null;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {records.slice(0, 5).map((rec, i) => {
        const date = new Date(rec.run_at * 1000).toLocaleDateString();
        return (
          <Card key={i} className="p-2.5">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-muted-foreground">{date}</span>
              <Badge className={verdictClassName(rec.verdict || "")}>{rec.verdict || "N/A"}</Badge>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <span className="text-muted-foreground">Entry: </span>
                <span className="text-foreground">
                  {rec.entry_price != null ? `$${rec.entry_price.toFixed(2)}` : "—"}
                </span>
              </div>
              <div>
                <span className="text-muted-foreground">Target: </span>
                <span className="text-foreground">
                  {rec.target_price != null ? `$${rec.target_price.toFixed(2)}` : "—"}
                </span>
              </div>
            </div>
            {rec.outcome && (
              <div className="mt-1">
                <Badge
                  className={
                    rec.outcome === "hit"
                      ? "bg-[--positive]/10 text-[--positive] border-[--positive]/20"
                      : rec.outcome === "miss"
                      ? "bg-[--negative]/10 text-[--negative] border-[--negative]/20"
                      : ""
                  }
                  variant={rec.outcome === "hit" || rec.outcome === "miss" ? "outline" : "secondary"}
                >{rec.outcome}</Badge>
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}
