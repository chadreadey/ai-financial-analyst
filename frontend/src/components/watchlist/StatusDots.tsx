interface StatusDotsProps {
  statuses: Record<string, string>;
}

const periodLabels = ["3mo", "1yr", "3yr", "5yr", "current"];

const dotColors: Record<string, string> = {
  hit: "var(--accent-green)",
  miss: "var(--accent-red)",
  pending: "var(--accent-yellow)",
  none: "var(--text-muted)",
};

export function StatusDots({ statuses }: StatusDotsProps) {
  return (
    <div className="flex items-center gap-3">
      {periodLabels.map((p) => {
        const status = statuses[p] || "none";
        return (
          <div key={p} className="flex flex-col items-center gap-0.5">
            <div
              className="w-2.5 h-2.5 rounded-full"
              style={{ background: dotColors[status] || dotColors.none }}
            />
            <span className="text-[9px]" style={{ color: "var(--text-muted)" }}>
              {p}
            </span>
          </div>
        );
      })}
    </div>
  );
}
