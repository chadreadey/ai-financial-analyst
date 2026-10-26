import { Card } from "@/components/ui/card";
import { buildConsensus, describeConflict } from "@/lib/brief";
import type { Stance, VerdictData } from "@/lib/brief";

const STANCE_COLOR: Record<Stance, string> = {
  bullish: "var(--positive)",
  bearish: "var(--negative)",
  neutral: "var(--warning)",
};

interface Props {
  verdict: VerdictData | null;
}

export function AgentConsensus({ verdict }: Props) {
  const agents = buildConsensus(verdict);
  if (agents.length === 0) return null;
  const raw = verdict?.signal_conflicts;
  const conflicts: string[] = Array.isArray(raw) ? raw.filter((c): c is string => typeof c === "string") : [];

  return (
    <Card className="p-4 space-y-4">
      <div>
        <h2 className="text-sm font-semibold text-foreground">Where the agents landed</h2>
        <p className="text-xs text-muted-foreground">
          Each analyst scores the stock from -1 (bearish) to +1 (bullish); weight is its share of the verdict.
        </p>
      </div>
      <ul className="space-y-2">
        {agents.map((a) => {
          const color = STANCE_COLOR[a.stance];
          const half = Math.min(Math.abs(a.score), 1) * 50;
          return (
            <li key={a.agent} className="flex items-center gap-2 sm:gap-3 text-xs">
              <span className="w-20 sm:w-24 shrink-0 font-medium text-foreground">{a.label}</span>
              <div
                className="relative h-2 flex-1 min-w-0 rounded bg-secondary"
                role="img"
                aria-label={`${a.label}: ${a.stance}, score ${a.score.toFixed(2)}`}
              >
                <div className="absolute inset-y-0 left-1/2 w-px bg-border" />
                <div
                  className="absolute inset-y-0 rounded"
                  style={{
                    background: color,
                    width: `${half}%`,
                    left: a.score >= 0 ? "50%" : `${50 - half}%`,
                  }}
                />
              </div>
              <span className="w-10 shrink-0 text-right tabular-nums" style={{ color }}>
                {a.score > 0 ? "+" : ""}
                {a.score.toFixed(2)}
              </span>
              <span className="w-14 sm:w-20 shrink-0 text-right text-muted-foreground tabular-nums">
                <span className="hidden sm:inline">weight </span>
                {Math.round(a.weight * 100)}%
              </span>
            </li>
          );
        })}
      </ul>
      {conflicts.length > 0 && (
        <div className="pt-3 border-t border-border">
          <h3 className="text-sm font-semibold text-foreground mb-2">Where the agents disagreed</h3>
          <ul className="list-disc pl-5 space-y-1 text-xs text-muted-foreground break-words">
            {conflicts.map((c) => (
              <li key={c}>{describeConflict(c)}</li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}
