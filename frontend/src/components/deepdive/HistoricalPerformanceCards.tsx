import { Card } from "../common/Card";
import { Badge } from "../common/Badge";
import type { RecommendationRecord } from "../../api/types";

interface Props {
  records: RecommendationRecord[];
}

function verdictVariant(v: string): "green" | "red" | "amber" | "muted" {
  const u = v.toUpperCase();
  if (u.includes("BUY")) return "green";
  if (u.includes("SELL")) return "red";
  if (u.includes("HOLD")) return "amber";
  return "muted";
}

export function HistoricalPerformanceCards({ records }: Props) {
  if (records.length === 0) return null;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {records.slice(0, 5).map((rec, i) => {
        const date = new Date(rec.run_at * 1000).toLocaleDateString();
        return (
          <Card key={i} padding="sm">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>{date}</span>
              <Badge label={rec.verdict || "N/A"} variant={verdictVariant(rec.verdict)} size="sm" />
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <span style={{ color: "var(--text-muted)" }}>Entry: </span>
                <span style={{ color: "var(--text-secondary)" }}>
                  {rec.entry_price != null ? `$${rec.entry_price.toFixed(2)}` : "—"}
                </span>
              </div>
              <div>
                <span style={{ color: "var(--text-muted)" }}>Target: </span>
                <span style={{ color: "var(--text-secondary)" }}>
                  {rec.target_price != null ? `$${rec.target_price.toFixed(2)}` : "—"}
                </span>
              </div>
            </div>
            {rec.outcome && (
              <div className="mt-1">
                <Badge
                  label={rec.outcome}
                  variant={rec.outcome === "hit" ? "green" : rec.outcome === "miss" ? "red" : "muted"}
                  size="sm"
                />
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}
