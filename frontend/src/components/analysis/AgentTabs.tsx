import { useState } from "react";
import type { AgentReport } from "../../api/types";
import { MarkdownRenderer } from "../common/MarkdownRenderer";

interface Props {
  reports: AgentReport[];
}

export function AgentTabs({ reports }: Props) {
  const [active, setActive] = useState(0);

  if (reports.length === 0) {
    return <p style={{ color: "var(--text-muted)" }}>No agent reports available.</p>;
  }

  return (
    <div>
      <div className="flex gap-1 mb-4 overflow-x-auto pb-2">
        {reports.map((r, i) => (
          <button
            key={i}
            onClick={() => setActive(i)}
            className="px-3 py-1.5 text-xs font-medium rounded-md whitespace-nowrap transition-colors"
            style={{
              background: active === i ? "var(--bg-hover)" : "transparent",
              color: active === i ? "var(--text-primary)" : "var(--text-muted)",
            }}
          >
            {r.agent_name}
          </button>
        ))}
      </div>
      <MarkdownRenderer content={reports[active].analysis} />
    </div>
  );
}
