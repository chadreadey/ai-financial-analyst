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
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
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

  useEffect(() => {
    const startedAt = Date.now();
    const timer = setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const currentPct = progress.pct ?? 0;
  const currentStage = matchStage(progress.step ?? "");

  return (
    <div className="rounded-lg overflow-hidden bg-card border border-border">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-border">
        <Loader2 size={15} className="animate-spin text-primary" />
        <span className="text-sm font-medium text-foreground">
          {progress.step || "Initializing analysis..."}
        </span>
        {currentPct > 0 && (
          <div className="ml-auto flex items-center gap-3">
            <span className="text-[11px] tabular-nums text-muted-foreground">
              Elapsed: {elapsedSeconds}s
            </span>
            <span className="text-xs font-semibold tabular-nums text-primary">
              {currentPct}%
            </span>
          </div>
        )}
      </div>

      {/* Progress bar */}
      <div className="h-0.5 w-full bg-background">
        <div
          className="h-full transition-all duration-700 ease-out"
          style={{
            width: `${Math.max(currentPct, 4)}%`,
            background: "linear-gradient(90deg, hsl(var(--primary)), #60a5fa)",
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
                      <CheckCircle2 size={16} className="text-[--positive]" />
                    ) : isActive ? (
                      <Loader2 size={16} className="animate-spin text-primary" />
                    ) : (
                      <Circle size={16} className="text-border" />
                    )}
                  </div>
                  <span
                    className={[
                      "mt-1.5 text-[10px] text-center leading-tight max-w-[72px]",
                      isDone
                        ? "text-[--positive]"
                        : isActive
                        ? "text-foreground font-medium"
                        : "text-muted-foreground",
                    ].join(" ")}
                  >
                    {stage}
                  </span>
                </div>

                {/* Connector line */}
                {i < ANALYSIS_STAGES.length - 1 && (
                  <div
                    className={[
                      "flex-1 h-px mx-1 mt-[-1.25rem] transition-fast",
                      isDone ? "bg-[--positive]" : "bg-border",
                      isPending ? "opacity-40" : "opacity-100",
                    ].join(" ")}
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Step history */}
      {history.length > 1 && (
        <div className="px-4 pb-3 space-y-1 border-t border-border">
          <p className="text-[10px] pt-3 uppercase tracking-wider mb-2 text-muted-foreground">
            Log
          </p>
          {history.slice(-4).map((h, i) => (
            <div key={i} className="flex items-center gap-2">
              <div
                className={[
                  "w-1 h-1 rounded-full flex-shrink-0",
                  i === history.slice(-4).length - 1 ? "bg-primary" : "bg-border",
                ].join(" ")}
              />
              <span className="text-[11px] truncate text-muted-foreground">
                {h.step}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
