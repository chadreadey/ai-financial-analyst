import { useParams, Link, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PriceHistoryTab } from "@/components/deepdive/PriceHistoryTab";
import { AnalysisAccordion } from "@/components/deepdive/AnalysisAccordion";
import { useRecommendationHistory } from "@/hooks/useRecommendationHistory";
import { api } from "@/api/client";
import type { WatchlistSummary, HistoryEntry, AnalysisResult } from "@/api/types";
import { cn } from "@/lib/utils";

export function StockDeepDivePage() {
  const { ticker } = useParams<{ ticker: string }>();
  const navigate = useNavigate();
  const t = ticker?.toUpperCase() || "";

  const { records } = useRecommendationHistory(t);
  const [summary, setSummary] = useState<WatchlistSummary | undefined>();
  const [historyEntries, setHistoryEntries] = useState<HistoryEntry[]>([]);

  useEffect(() => {
    if (!t) return;
    api.getWatchlistSummary(t).then(setSummary).catch(() => {});
    api.getHistory(t, 50, 0).then((d) => setHistoryEntries(d.entries)).catch(() => {});
  }, [t]);

  const latestRecord = records[0];
  const latestVerdict = latestRecord?.verdict ?? "";

  const verdictColor =
    latestVerdict === "BUY"
      ? "text-[--positive] border-[--positive]/20 bg-[--positive]/10"
      : latestVerdict === "SELL"
      ? "text-[--negative] border-[--negative]/20 bg-[--negative]/10"
      : latestVerdict
      ? "text-[--warning] border-[--warning]/20 bg-[--warning]/10"
      : "";

  async function getFullResult(analysisId: string): Promise<AnalysisResult | null> {
    try {
      const detail = await api.getHistoryDetail(analysisId);
      if (detail.result_json) {
        return detail.result_json as unknown as AnalysisResult;
      }
      return null;
    } catch {
      return null;
    }
  }

  const statCards = [
    {
      label: "Current Price",
      value: summary?.current_price != null ? `$${summary.current_price.toFixed(2)}` : "—",
    },
    {
      label: "Hit Rate",
      value: summary?.hit_rate_pct != null ? `${summary.hit_rate_pct}%` : "—",
    },
    {
      label: "Alpha vs SPY",
      value:
        summary?.alpha_vs_spy != null
          ? `${summary.alpha_vs_spy > 0 ? "+" : ""}${summary.alpha_vs_spy}%`
          : "—",
    },
  ];

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-4">
      {/* Back link */}
      <Link
        to="/portfolio"
        className="inline-flex items-center gap-2 text-sm text-blue-500 hover:text-blue-400 transition-colors"
      >
        <ArrowLeft size={16} /> Back to Watchlist
      </Link>

      {/* Page header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-bold">{t}</h1>
          {latestVerdict && (
            <Badge variant="outline" className={cn("text-[10px]", verdictColor)}>
              {latestVerdict}
            </Badge>
          )}
        </div>
        <Button
          size="sm"
          onClick={() => navigate(`/analysis?ticker=${t}`)}
          className="flex items-center gap-2"
        >
          <RefreshCw size={14} /> Re-analyze
        </Button>
      </div>

      {/* Stat grid */}
      <div className="grid grid-cols-3 gap-3">
        {statCards.map((m) => (
          <Card key={m.label} className="p-2.5">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
              {m.label}
            </div>
            <div className="text-lg font-bold">{m.value}</div>
          </Card>
        ))}
      </div>

      {/* Price chart */}
      <Card className="p-4">
        <PriceHistoryTab ticker={t} />
      </Card>

      {/* Tabs */}
      <Tabs defaultValue="history">
        <TabsList className="bg-secondary border border-border h-8">
          <TabsTrigger value="history" className="text-xs h-7 data-[state=active]:text-primary">
            Analysis History
          </TabsTrigger>
          <TabsTrigger value="trades" className="text-xs h-7 data-[state=active]:text-primary">
            Trade History
          </TabsTrigger>
          <TabsTrigger
            value="fundamentals"
            className="text-xs h-7 data-[state=active]:text-primary"
          >
            Fundamentals
          </TabsTrigger>
        </TabsList>

        <TabsContent value="history" className="mt-3">
          <AnalysisAccordion entries={historyEntries} getFullResult={getFullResult} />
        </TabsContent>

        <TabsContent value="trades" className="mt-3">
          <p className="text-xs text-muted-foreground py-4">Trade history coming in Phase B.</p>
        </TabsContent>

        <TabsContent value="fundamentals" className="mt-3">
          <p className="text-xs text-muted-foreground py-4">
            Fundamentals view coming in Phase B.
          </p>
        </TabsContent>
      </Tabs>
    </div>
  );
}
