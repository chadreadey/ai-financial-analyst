import { useParams, Link, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { Card } from "@/components/ui/card";
import { PriceHistoryTab } from "../components/deepdive/PriceHistoryTab";
import { HistoricalPerformanceCards } from "../components/deepdive/HistoricalPerformanceCards";
import { PerformanceMetricsPanel } from "../components/deepdive/PerformanceMetricsPanel";
import { useRecommendationHistory } from "../hooks/useRecommendationHistory";
import { api } from "../api/client";
import type { WatchlistSummary } from "../api/types";

export function StockDeepDivePage() {
  const { ticker } = useParams<{ ticker: string }>();
  const navigate = useNavigate();
  const t = ticker?.toUpperCase() || "";
  const { records } = useRecommendationHistory(t);
  const [summary, setSummary] = useState<WatchlistSummary | undefined>();

  useEffect(() => {
    if (t) {
      api.getWatchlistSummary(t).then(setSummary).catch(() => {});
    }
  }, [t]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <Link
          to="/portfolio"
          className="flex items-center gap-2 text-sm"
          style={{ color: "var(--accent-blue)" }}
        >
          <ArrowLeft size={16} /> Back to Watchlist
        </Link>
        <button
          onClick={() => navigate(`/analysis?ticker=${t}`)}
          className="flex items-center gap-2 text-sm px-3 py-1.5 rounded"
          style={{ background: "var(--accent-blue)", color: "#fff" }}
        >
          <RefreshCw size={14} /> Re-run Analysis
        </button>
      </div>

      <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
        {t}
        <span className="ml-2 text-base font-normal" style={{ color: "var(--text-muted)" }}>
          Deep Dive
        </span>
      </h1>

      <PerformanceMetricsPanel summary={summary} />

      <Card>
        <PriceHistoryTab ticker={t} />
      </Card>

      <div>
        <h2 className="text-lg font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
          Recommendation History
        </h2>
        <HistoricalPerformanceCards records={records} />
      </div>
    </div>
  );
}
