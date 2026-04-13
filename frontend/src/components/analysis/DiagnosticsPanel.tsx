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
        <h3 className="text-sm font-semibold mb-2" style={{ color: "var(--text-primary)" }}>
          Enrichment Sources
        </h3>
        {sources.length > 0 ? (
          <ul className="space-y-1">
            {sources.map((s, i) => (
              <li key={i} className="text-xs" style={{ color: "var(--text-secondary)" }}>
                {s}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>
            No external enrichment sources captured.
          </p>
        )}
      </section>

      <section>
        <h3 className="text-sm font-semibold mb-2" style={{ color: "var(--text-primary)" }}>
          Warnings
        </h3>
        {warnings.length > 0 ? (
          <div className="space-y-1">
            {warnings.map((w, i) => (
              <div
                key={i}
                className="text-xs px-3 py-2 rounded"
                style={{ background: "rgba(245,158,11,0.1)", color: "var(--accent-amber)" }}
              >
                {w}
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs" style={{ color: "var(--text-muted)" }}>No warnings.</p>
        )}
      </section>

      <section>
        <h3 className="text-sm font-semibold mb-2" style={{ color: "var(--text-primary)" }}>
          Filter Stats
        </h3>
        <div className="flex flex-wrap gap-2">
          {Object.entries(stats).map(([k, v]) => (
            <Badge key={k} variant="secondary">{k}: {v}</Badge>
          ))}
          {Object.keys(stats).length === 0 && (
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>No filter stats.</p>
          )}
        </div>
      </section>

      {Object.keys(metrics).length > 0 && (
        <section>
          <h3 className="text-sm font-semibold mb-2" style={{ color: "var(--text-primary)" }}>
            Key Metrics
          </h3>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {Object.entries(metrics).slice(0, 12).map(([k, v]) => (
              <div key={k} className="px-3 py-2 rounded"
                style={{ background: "var(--bg-primary)" }}>
                <div className="text-xs truncate" style={{ color: "var(--text-muted)" }}>{k}</div>
                <div className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
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
