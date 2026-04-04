import { useState } from "react";
import type { AnalysisResult } from "../../api/types";
import { Badge } from "../common/Badge";
import { Card } from "../common/Card";
import { MarkdownRenderer } from "../common/MarkdownRenderer";
import { AgentTabs } from "./AgentTabs";
import { DiagnosticsPanel } from "./DiagnosticsPanel";
import { PriceHistoryTab } from "../deepdive/PriceHistoryTab";
import { FileText } from "lucide-react";

interface Props {
  result: AnalysisResult;
}

function verdictColor(verdict: string): "green" | "amber" | "red" | "blue" {
  const v = verdict.toUpperCase();
  if (v.includes("BUY") || v.includes("BULLISH")) return "green";
  if (v.includes("SELL") || v.includes("BEARISH")) return "red";
  if (v.includes("HOLD") || v.includes("NEUTRAL")) return "amber";
  return "blue";
}

export function ResultView({ result }: Props) {
  const [activeTab, setActiveTab] = useState<"synthesis" | "agents" | "diagnostics" | "price-history">("synthesis");
  const sv = result.structured_verdict;

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h2 className="text-xl font-bold" style={{ color: "var(--text-primary)" }}>
              {result.company_name}
              <span className="ml-2 text-base font-normal" style={{ color: "var(--text-muted)" }}>
                ({result.ticker})
              </span>
            </h2>
          </div>
          {sv && (
            <div className="flex items-center gap-2 flex-wrap">
              {sv.verdict && (
                <Badge label={sv.verdict} variant={verdictColor(sv.verdict)} />
              )}
              {sv.conviction && <Badge label={`Conviction: ${sv.conviction}`} />}
              {sv.health_scores?.overall != null && (
                <Badge
                  label={`Score: ${sv.health_scores.overall}/10`}
                  variant={
                    sv.health_scores.overall >= 7 ? "green" :
                    sv.health_scores.overall >= 4 ? "amber" : "red"
                  }
                />
              )}
            </div>
          )}
        </div>
      </Card>

      <div className="flex gap-1" role="tablist">
        {(["synthesis", "agents", "diagnostics", "price-history"] as const).map((tab) => (
          <button
            key={tab}
            role="tab"
            onClick={() => setActiveTab(tab)}
            className="px-4 py-2 text-sm font-medium rounded-t-md transition-colors capitalize"
            style={{
              background: activeTab === tab ? "var(--bg-card)" : "transparent",
              color: activeTab === tab ? "var(--text-primary)" : "var(--text-muted)",
              borderBottom: activeTab === tab ? "2px solid var(--accent-blue)" : "2px solid transparent",
            }}
          >
            {tab === "agents" ? `Agents (${result.agent_reports.length})` : tab === "price-history" ? "Price History & Targets" : tab}
          </button>
        ))}
      </div>

      <Card>
        {activeTab === "synthesis" && (
          <div>
            <MarkdownRenderer content={result.synthesis} />
            <div className="mt-4 flex gap-2">
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
                className="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium"
                style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}
              >
                <FileText size={14} /> Download Text
              </button>
            </div>
          </div>
        )}
        {activeTab === "agents" && <AgentTabs reports={result.agent_reports} />}
        {activeTab === "diagnostics" && (
          <DiagnosticsPanel
            sources={result.enrichment_sources}
            warnings={result.enrichment_warnings}
            stats={result.enrichment_filter_stats}
            metrics={result.metrics}
          />
        )}
        {activeTab === "price-history" && (
          <PriceHistoryTab ticker={result.ticker} />
        )}
      </Card>
    </div>
  );
}
