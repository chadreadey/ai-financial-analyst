import type { AnalysisResult } from "../../api/types";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { DiagnosticsPanel } from "./DiagnosticsPanel";
import { PriceHistoryTab } from "../deepdive/PriceHistoryTab";
import { SignalCards } from "./SignalCards";
import { AgentReportTabs } from "./AgentReportTabs";
import { FileText } from "lucide-react";
import { useState } from "react";
import { verdictClassName } from "@/lib/brief";

interface Props {
  result: AnalysisResult;
}

export function ResultView({ result }: Props) {
  const [activeTab, setActiveTab] = useState<"reports" | "diagnostics" | "price-history">("reports");
  const sv = result.structured_verdict;

  return (
    <div className="space-y-4">
      {/* Header */}
      <Card className="p-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <span className="text-xl font-bold text-foreground">{result.ticker}</span>
            <span className="ml-2 text-base text-muted-foreground">{result.company_name}</span>
          </div>
          {sv && (
            <div className="flex items-center gap-2 flex-wrap">
              {sv.verdict && (
                <Badge variant="outline" className={verdictClassName(sv.verdict)}>{sv.verdict}</Badge>
              )}
              {sv.conviction && (
                <Badge variant="secondary">Conviction: {sv.conviction}</Badge>
              )}
            </div>
          )}
        </div>
      </Card>

      {/* Signal Cards */}
      <SignalCards verdict={sv} />

      {/* Tab nav */}
      <div className="flex gap-1" role="tablist">
        {(["reports", "diagnostics", "price-history"] as const).map((tab) => (
          <button
            key={tab}
            role="tab"
            aria-selected={activeTab === tab}
            onClick={() => setActiveTab(tab)}
            className={[
              "px-4 py-2 text-sm font-medium rounded-t-md transition-colors capitalize",
              activeTab === tab
                ? "bg-card text-foreground border-b-2 border-primary"
                : "text-muted-foreground border-b-2 border-transparent hover:text-foreground",
            ].join(" ")}
          >
            {tab === "price-history" ? "Price History & Targets" : tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === "reports" && (
        <>
          <AgentReportTabs
            synthesis={result.synthesis}
            agentReports={result.agent_reports}
            tradeParams={sv}
          />
          <div className="mt-2 flex gap-2">
            <button
              onClick={() => {
                const blob = new Blob([result.synthesis], { type: "text/plain" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `${result.ticker}_analysis.txt`;
                a.click();
                URL.revokeObjectURL(url);
              }}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium bg-secondary text-muted-foreground hover:text-foreground transition-colors"
            >
              <FileText size={14} /> Download Text
            </button>
          </div>
        </>
      )}

      {activeTab === "diagnostics" && (
        <Card className="p-4">
          <DiagnosticsPanel
            sources={result.enrichment_sources}
            warnings={result.enrichment_warnings}
            stats={result.enrichment_filter_stats}
            metrics={result.metrics}
          />
        </Card>
      )}

      {activeTab === "price-history" && (
        <Card className="p-4">
          <PriceHistoryTab ticker={result.ticker} />
        </Card>
      )}
    </div>
  );
}
