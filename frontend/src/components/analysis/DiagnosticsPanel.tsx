import { Badge } from "@/components/ui/badge";

interface Props {
  sources: string[];
  warnings: string[];
  stats: Record<string, number>;
  metrics: Record<string, any>;
}

export function DiagnosticsPanel({ sources, warnings, stats, metrics }: Props) {
  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-semibold mb-2 text-foreground">
          Enrichment Sources
        </h3>
        {sources.length > 0 ? (
          <ul className="space-y-1">
            {sources.map((s, i) => (
              <li key={i} className="text-xs text-muted-foreground">
                {s}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-muted-foreground">
            No external enrichment sources captured.
          </p>
        )}
      </section>

      <section>
        <h3 className="text-sm font-semibold mb-2 text-foreground">
          Warnings
        </h3>
        {warnings.length > 0 ? (
          <div className="space-y-1">
            {warnings.map((w, i) => (
              <div
                key={i}
                className="text-xs px-3 py-2 rounded bg-[--warning]/10 text-[--warning]"
              >
                {w}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">No warnings.</p>
        )}
      </section>

      <section>
        <h3 className="text-sm font-semibold mb-2 text-foreground">
          Filter Stats
        </h3>
        <div className="flex flex-wrap gap-2">
          {Object.entries(stats).map(([k, v]) => (
            <Badge key={k} variant="secondary">{k}: {v}</Badge>
          ))}
          {Object.keys(stats).length === 0 && (
            <p className="text-xs text-muted-foreground">No filter stats.</p>
          )}
        </div>
      </section>

      {Object.keys(metrics).length > 0 && (
        <section>
          <h3 className="text-sm font-semibold mb-2 text-foreground">
            Key Metrics
          </h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {Object.entries(metrics).slice(0, 12).map(([k, v]) => (
              <div key={k} className="px-3 py-2 rounded bg-background">
                <div className="text-xs truncate text-muted-foreground">{k}</div>
                <div className="text-sm font-medium text-foreground">
                  {v !== null && v !== undefined ? String(v) : "N/A"}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
