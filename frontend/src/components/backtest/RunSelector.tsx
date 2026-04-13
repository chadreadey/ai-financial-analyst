import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

interface BacktestRun {
  id: string;
  config_summary: string;
  sharpe: number | null;
  pbo?: number | null;
  date: string;
}

interface RunSelectorProps {
  runs: BacktestRun[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function RunSelector({ runs, selectedId, onSelect }: RunSelectorProps) {
  const selected = runs.find((r) => r.id === selectedId) ?? runs[0];
  if (!selected) return null;

  return (
    <Card className="p-3 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <span className="text-xs text-muted-foreground">Run:</span>
        <select
          value={selected.id}
          onChange={(e) => onSelect(e.target.value)}
          className="bg-secondary border border-border rounded px-2 py-1 text-xs text-foreground"
        >
          {runs.map((r) => (
            <option key={r.id} value={r.id}>
              {r.date} — {r.config_summary}
            </option>
          ))}
        </select>
      </div>
      <div className="flex gap-2">
        {selected.sharpe != null && (
          <Badge variant="outline" className="text-primary border-primary/20 bg-primary/10">
            Sharpe {selected.sharpe.toFixed(2)}
          </Badge>
        )}
        {selected.pbo != null && (
          <Badge
            variant="outline"
            className={
              selected.pbo === 0
                ? "text-[--positive] border-[--positive]/20 bg-[--positive]/10"
                : "text-[--warning] border-[--warning]/20 bg-[--warning]/10"
            }
          >
            PBO {(selected.pbo * 100).toFixed(0)}%
          </Badge>
        )}
      </div>
    </Card>
  );
}
