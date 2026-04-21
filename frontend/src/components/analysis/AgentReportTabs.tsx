import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Card } from "@/components/ui/card";
import { MarkdownRenderer } from "@/components/common/MarkdownRenderer";
import type { AgentReport } from "@/api/types";

interface AgentReportTabsProps {
  synthesis: string;
  agentReports: AgentReport[];
  tradeParams?: Record<string, any> | null;
}

const AGENT_ORDER = ["Synthesis", "DCF", "Risk", "Earnings", "Competitive", "Pattern", "Macro"];

const AGENT_NAME_MAP: Record<string, string> = {
  "DCF Analyst": "DCF",
  "Risk Analyst": "Risk",
  "Earnings Analyst": "Earnings",
  "Competitive & Sector Analyst": "Competitive",
  "Pattern Analyst": "Pattern",
  "Macro Strategist": "Macro",
  "Sector Specialist": "Sector",
};

function normalizeAgentName(raw: string): string {
  if (AGENT_NAME_MAP[raw]) return AGENT_NAME_MAP[raw];
  // Fallback: strip common suffixes
  return raw.replace(/\s*(Analyst|Strategist|Specialist|Agent).*$/, "").trim();
}

export function AgentReportTabs({ synthesis, agentReports, tradeParams }: AgentReportTabsProps) {
  const reportMap: Record<string, string> = { Synthesis: synthesis };
  for (const r of agentReports) {
    // Handle both object form {agent_name, analysis} and legacy tuple [name, analysis]
    const [rawName, analysis] = Array.isArray(r)
      ? [r[0] as string, r[1] as string]
      : [r.agent_name, r.analysis];
    const name = normalizeAgentName(rawName);
    reportMap[name] = analysis;
  }

  const availableTabs = AGENT_ORDER.filter((name) => reportMap[name]);

  return (
    <Tabs defaultValue="Synthesis" className="mt-4">
      <TabsList className="bg-secondary border border-border h-8">
        {availableTabs.map((name) => (
          <TabsTrigger key={name} value={name} className="text-xs h-7 data-[state=active]:text-primary">
            {name}
          </TabsTrigger>
        ))}
      </TabsList>
      {availableTabs.map((name) => (
        <TabsContent key={name} value={name}>
          <Card className="p-4">
            <div className="prose text-sm">
              <MarkdownRenderer content={reportMap[name]} />
            </div>
            {name === "Synthesis" && tradeParams && (
              <div className="mt-3 pt-3 border-t border-border flex gap-2 flex-wrap">
                {tradeParams.entry_price && (
                  <span className="px-2 py-0.5 rounded bg-secondary text-[10px] text-muted-foreground border border-border">
                    Entry: ${tradeParams.entry_price}
                  </span>
                )}
                {tradeParams.price_target && (
                  <span className="px-2 py-0.5 rounded bg-secondary text-[10px] text-muted-foreground border border-border">
                    Target: ${tradeParams.price_target}
                  </span>
                )}
                {tradeParams.stop_loss_value && (
                  <span className="px-2 py-0.5 rounded bg-secondary text-[10px] text-muted-foreground border border-border">
                    Stop: ${tradeParams.stop_loss_value}
                  </span>
                )}
                {tradeParams.time_horizon && (
                  <span className="px-2 py-0.5 rounded bg-secondary text-[10px] text-muted-foreground border border-border">
                    Horizon: {tradeParams.time_horizon}
                  </span>
                )}
              </div>
            )}
          </Card>
        </TabsContent>
      ))}
    </Tabs>
  );
}
