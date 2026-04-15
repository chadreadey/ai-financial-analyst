import { Card } from "@/components/ui/card";

interface SignalCardProps {
  label: string;
  value: string;
  colorClass?: string;
}

function SignalCard({ label, value, colorClass = "text-foreground" }: SignalCardProps) {
  return (
    <Card className="p-3">
      <div className="text-[10px] font-medium uppercase tracking-[0.8px] text-muted-foreground">{label}</div>
      <div className={`text-sm font-semibold mt-0.5 ${colorClass}`}>{value}</div>
    </Card>
  );
}

interface SignalCardsProps {
  verdict: Record<string, any> | null;
}

export function SignalCards({ verdict }: SignalCardsProps) {
  if (!verdict) return null;

  const score = verdict.weighted_score ?? verdict.composite_score;
  const scoreColor = score > 0.5 ? "text-[--positive]" : score > 0 ? "text-primary" : "text-[--negative]";

  return (
    <div className="grid grid-cols-4 gap-3">
      <SignalCard
        label="Weighted Score"
        value={score != null ? score.toFixed(2) : "—"}
        colorClass={scoreColor}
      />
      <SignalCard
        label="Conviction"
        value={verdict.conviction ?? "—"}
        colorClass="text-primary"
      />
      <SignalCard
        label="Verdict"
        value={verdict.verdict ?? "—"}
        colorClass={
          verdict.verdict === "BUY" ? "text-[--positive]" :
          verdict.verdict === "SELL" ? "text-[--negative]" :
          "text-[--warning]"
        }
      />
      <SignalCard
        label="Time Horizon"
        value={verdict.time_horizon ?? "—"}
      />
    </div>
  );
}
