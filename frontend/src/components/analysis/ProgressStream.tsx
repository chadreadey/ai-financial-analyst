import React from "react";
import { useState, useEffect, useRef } from "react";
import { CheckCircle2, Circle, Loader2 } from "lucide-react";
import type { ProgressEvent } from "../../api/types";

interface ProgressStreamProps {
  progress: ProgressEvent;
}

interface StepRecord {
  step: string;
  pct: number;
  timestamp: number;
}

const ANALYSIS_STAGES = [
  "Fetching SEC/XBRL data",
  "Running analyst agents",
  "Synthesizing investment brief",
  "Finalizing report",
];

function matchStage(step: string): number {
  const s = step.toLowerCase();
  if (s.includes("sec") || s.includes("xbrl") || s.includes("fetch")) return 0;
  if (s.includes("agent") || s.includes("parallel") || s.includes("analyst")) return 1;
  if (s.includes("synth") || s.includes("brief") || s.includes("invest")) return 2;
  if (s.includes("complete") || s.includes("final") || s.includes("report")) return 3;
  return -1;
}

export function ProgressStream({ progress }: ProgressStreamProps): React.ReactElement {
  const [history, setHistory] = useState<StepRecord[]>([]);
  const prevStep = useRef<string>("");

  useEffect(() => {
    if (progress.step && progress.step !== prevStep.current) {
      prevStep.current = progress.step;
      setHistory((h) => [
        ...h,
        { step: progress.step, pct: progress.pct ?? 0, timestamp: Date.now() },
      ]);
    }
  }, [progress.step, progress.pct]);

  const currentPct = progress.pct ?? 0;
  const currentStage = matchStage(progress.step ?? "");

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      {/* Header */}
      <div
        className="flex items-center gap-3 px-4 py-3 border-b"
        style={{ borderColor: "var(--border-subtle)" }}
      >
        <Loader2 size={15} className="animate-spin" style={{ color: "var(--accent-blue)" }} />
        <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
          {progress.step || "Initializing analysis..."}
        </span>
        {currentPct > 0 && (
          <span className="ml-auto text-xs font-semibold tabular-nums" style={{ color: "var(--accent-blue)" }}>
            {currentPct}%
          </span>
        )}
      </div>

      {/* Progress bar */}
      <div className="h-0.5 w-full" style={{ background: "var(--bg-primary)" }}>
        <div
          className="h-full transition-all duration-700 ease-out"
          style={{
            width: `${Math.max(currentPct, 4)}%`,
            background: "linear-gradient(90deg, var(--accent-blue), #60a5fa)",
            boxShadow: "0 0 8px rgba(59,130,246,0.5)",
          }}
        />
      </div>

      {/* Stage indicators */}
      <div className="px-4 py-4">
        <div className="flex items-start gap-0">
          {ANALYSIS_STAGES.map((stage, i) => {
            const isDone = currentStage > i;
            const isActive = currentStage === i;
            const isPending = currentStage < i;

            return (
              <div key={stage} className="flex items-center flex-1 min-w-0">
                {/* Step */}
                <div className="flex flex-col items-center flex-shrink-0">
                  <div className="transition-fast">
                    {isDone ? (
                      <CheckCircle2 size={16} style={{ color: "var(--accent-green)" }} />
                    ) : isActive ? (
                      <Loader2 size={16} className="animate-spin" style={{ color: "var(--accent-blue)" }} />
                    ) : (
                      <Circle size={16} style={{ color: "var(--border)" }} />
                    )}
                  </div>
                  <span
                    className="mt-1.5 text-[10px] text-center leading-tight max-w-[72px]"
                    style={{
                      color: isDone
                        ? "var(--accent-green)"
                        : isActive
                        ? "var(--text-primary)"
                        : "var(--text-muted)",
                      fontWeight: isActive ? 500 : 400,
                    }}
                  >
                    {stage}
                  </span>
                </div>

                {/* Connector line */}
                {i < ANALYSIS_STAGES.length - 1 && (
                  <div
                    className="flex-1 h-px mx-1 mt-[-1.25rem] transition-fast"
                    style={{
                      background: isDone ? "var(--accent-green)" : "var(--border-subtle)",
                      opacity: isPending ? 0.4 : 1,
                    }}
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Step history */}
      {history.length > 1 && (
        <div
          className="px-4 pb-3 space-y-1 border-t"
          style={{ borderColor: "var(--border-subtle)" }}
        >
          <p className="text-[10px] pt-3 uppercase tracking-wider mb-2" style={{ color: "var(--text-muted)" }}>
            Log
          </p>
          {history.slice(-4).map((h, i) => (
            <div key={i} className="flex items-center gap-2">
              <div
                className="w-1 h-1 rounded-full flex-shrink-0"
                style={{ background: i === history.slice(-4).length - 1 ? "var(--accent-blue)" : "var(--border)" }}
              />
              <span className="text-[11px] truncate" style={{ color: "var(--text-muted)" }}>
                {h.step}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
