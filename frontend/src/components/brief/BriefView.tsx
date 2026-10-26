import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { MarkdownRenderer } from "@/components/common/MarkdownRenderer";
import { AgentReportTabs } from "@/components/analysis/AgentReportTabs";
import { AgentConsensus } from "./AgentConsensus";
import type { AnalysisResult } from "@/api/types";
import { formatCompanyName } from "@/lib/showcase";
import { formatRunDate, upsidePct, verdictClassName } from "@/lib/brief";

interface Props {
  result: AnalysisResult;
  runAt?: string;
  isExample?: boolean;
}

const money = (n: number) => `$${n.toFixed(2)}`;

export function BriefView({ result, runAt, isExample }: Props) {
  const sv = result.structured_verdict;
  const entry = sv?.entry_price as number | null | undefined;
  const target = sv?.price_target as number | null | undefined;
  const verdictLabel = sv?.verdict as string | undefined;
  const conviction = sv?.conviction as string | number | undefined;
  const horizon = sv?.time_horizon as string | undefined;
  const upside = upsidePct(entry, target);
  const sources: string[] = result.enrichment_sources ?? [];

  return (
    <div className="space-y-4">
      <Card className="p-4 space-y-3">
        <div className="flex items-start justify-between flex-wrap gap-3">
          <div className="min-w-0">
            <span className="text-2xl font-bold text-foreground">{result.ticker}</span>
            <span className="ml-2 text-base text-muted-foreground break-words">
              {formatCompanyName(result.company_name)}
            </span>
          </div>
          {sv && (
            <div className="flex items-center gap-2 flex-wrap">
              {verdictLabel && (
                <Badge variant="outline" className={verdictClassName(verdictLabel)}>{verdictLabel}</Badge>
              )}
              {conviction != null && conviction !== "" && <Badge variant="secondary">Conviction: {conviction}</Badge>}
            </div>
          )}
        </div>
        {sv && (
          <dl className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
            {entry != null && (
              <div>
                <dt className="text-xs text-muted-foreground">Entry</dt>
                <dd className="font-medium text-foreground tabular-nums">{money(entry)}</dd>
              </div>
            )}
            {target != null && (
              <div>
                <dt className="text-xs text-muted-foreground">Price target</dt>
                <dd className="font-medium text-foreground tabular-nums">
                  {money(target)}
                  {upside != null && (
                    <span className="ml-1 text-muted-foreground">
                      ({upside > 0 ? "+" : ""}{upside.toFixed(1)}%)
                    </span>
                  )}
                </dd>
              </div>
            )}
            {horizon && (
              <div>
                <dt className="text-xs text-muted-foreground">Horizon</dt>
                <dd className="font-medium text-foreground">{horizon}</dd>
              </div>
            )}
          </dl>
        )}
        {isExample && runAt && (
          <p className="text-xs text-muted-foreground">Example run from {formatRunDate(runAt)}</p>
        )}
      </Card>

      <AgentConsensus verdict={sv} />

      {result.synthesis && (
        <Card className="p-4 overflow-x-auto">
          <h2 className="text-sm font-semibold text-foreground mb-2">Synthesis</h2>
          <MarkdownRenderer content={result.synthesis} />
        </Card>
      )}

      <details className="group">
        <summary className="cursor-pointer text-sm font-medium text-foreground select-none">
          Read each analyst's report
        </summary>
        <div className="overflow-x-auto">
          <AgentReportTabs synthesis={result.synthesis} agentReports={result.agent_reports} tradeParams={sv} hideSynthesis />
        </div>
      </details>

      {sources.length > 0 && (
        <Card className="p-4">
          <h2 className="text-sm font-semibold text-foreground mb-2">Sources</h2>
          <ul className="list-disc pl-5 space-y-1 text-xs text-muted-foreground break-words">
            {sources.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </Card>
      )}

      <p className="text-xs text-muted-foreground">
        Research demo, not investment advice.
      </p>
    </div>
  );
}
