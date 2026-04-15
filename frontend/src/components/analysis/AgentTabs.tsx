import { useState } from "react";
import type { AgentReport } from "../../api/types";
import { MarkdownRenderer } from "../common/MarkdownRenderer";

interface Props {
  reports: AgentReport[];
}

export function AgentTabs({ reports }: Props) {
  const [active, setActive] = useState(0);

  if (reports.length === 0) {
    return <p className="text-muted-foreground">No agent reports available.</p>;
  }

  return (
    <div>
      <div className="flex gap-1 mb-4 overflow-x-auto pb-2">
        {reports.map((r, i) => (
          <button
            key={i}
            onClick={() => setActive(i)}
            className={[
              "px-3 py-1.5 text-xs font-medium rounded-md whitespace-nowrap transition-colors",
              active === i
                ? "bg-secondary text-foreground"
                : "bg-transparent text-muted-foreground hover:text-foreground",
            ].join(" ")}
          >
            {r.agent_name}
          </button>
        ))}
      </div>
      <MarkdownRenderer content={reports[active].analysis} />
    </div>
  );
}
