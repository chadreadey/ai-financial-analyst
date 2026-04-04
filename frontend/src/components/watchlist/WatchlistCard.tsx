import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card } from "../common/Card";
import { Badge } from "../common/Badge";
import { StatusDots } from "./StatusDots";
import { SparklineChart } from "../charts/SparklineChart";
import { api } from "../../api/client";
import type { WatchlistEntry, WatchlistSummary } from "../../api/types";

interface Props {
  entry: WatchlistEntry;
  summary?: WatchlistSummary;
}

function verdictVariant(v?: string | null): "green" | "red" | "amber" | "muted" {
  if (!v) return "muted";
  const u = v.toUpperCase();
  if (u.includes("BUY") || u.includes("BULLISH")) return "green";
  if (u.includes("SELL") || u.includes("BEARISH")) return "red";
  if (u.includes("HOLD") || u.includes("NEUTRAL")) return "amber";
  return "muted";
}

export function WatchlistCard({ entry, summary }: Props) {
  const navigate = useNavigate();
  const [sparkline, setSparkline] = useState<number[]>([]);

  useEffect(() => {
    api.getSparkline(entry.ticker)
      .then((d) => setSparkline(d.closes))
      .catch(() => {});
  }, [entry.ticker]);

  return (
    <Card className="cursor-pointer hover:opacity-90 transition-opacity">
      <div onClick={() => navigate(`/stock/${entry.ticker}`)}>
        <div className="flex items-center justify-between mb-2">
          <span className="font-bold text-sm" style={{ color: "var(--text-primary)" }}>
            {entry.ticker}
          </span>
          <div className="flex items-center gap-2">
            {entry.latest_verdict && (
              <Badge label={entry.latest_verdict} variant={verdictVariant(entry.latest_verdict)} />
            )}
            {summary?.current_price != null && (
              <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                ${summary.current_price.toFixed(2)}
              </span>
            )}
          </div>
        </div>

        <div className="w-full h-10 mb-2">
          {sparkline.length > 0 ? (
            <SparklineChart closes={sparkline} isPositive={sparkline[sparkline.length - 1] > sparkline[0]} />
          ) : (
            <div className="w-full h-full rounded flex items-center justify-center" style={{ background: "var(--bg-primary)" }}>
              <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>Loading...</span>
            </div>
          )}
        </div>

        <div className="flex items-center justify-between mb-2">
          {summary?.hit_rate_pct != null && (
            <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
              Hit: {summary.hit_rate_pct}%
            </span>
          )}
          {summary?.alpha_vs_spy != null && (
            <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
              Alpha: {summary.alpha_vs_spy > 0 ? "+" : ""}{summary.alpha_vs_spy}%
            </span>
          )}
          {entry.latest_score != null && (
            <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
              Score: {entry.latest_score}/10
            </span>
          )}
        </div>

        {summary?.period_statuses && (
          <StatusDots statuses={summary.period_statuses} />
        )}
      </div>
    </Card>
  );
}
