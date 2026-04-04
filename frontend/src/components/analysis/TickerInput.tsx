import React from "react";
import { useRef } from "react";
import { Search, CornerDownLeft } from "lucide-react";

interface TickerInputProps {
  ticker: string;
  onTickerChange: (value: string) => void;
  onRun: () => void;
  isRunning: boolean;
}

export function TickerInput({ ticker, onTickerChange, onRun, isRunning }: TickerInputProps): React.ReactElement {
  const inputRef = useRef<HTMLInputElement>(null);
  const hasValue = ticker.trim().length > 0;

  return (
    <div
      className="rounded-lg overflow-hidden transition-fast"
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border)",
        boxShadow: "var(--shadow-sm)",
      }}
    >
      <div className="flex items-center px-4 py-3 gap-3">
        <Search
          size={18}
          className="flex-shrink-0 transition-fast"
          style={{ color: hasValue ? "var(--accent-blue)" : "var(--text-muted)" }}
        />

        <input
          ref={inputRef}
          value={ticker}
          onChange={(e) => onTickerChange(e.target.value.toUpperCase().replace(/[^A-Z.]/g, ""))}
          onKeyDown={(e) => e.key === "Enter" && !isRunning && onRun()}
          placeholder="Enter ticker symbol (e.g. AAPL)"
          className="flex-1 bg-transparent outline-none font-semibold tracking-wide placeholder:font-normal"
          style={{
            fontSize: "1.125rem",
            color: "var(--text-primary)",
          }}
          spellCheck={false}
          autoComplete="off"
          autoCapitalize="characters"
          disabled={isRunning}
        />

        {/* Enter hint */}
        {hasValue && !isRunning && (
          <span
            className="flex items-center gap-1 text-[11px] flex-shrink-0"
            style={{ color: "var(--text-muted)" }}
          >
            <CornerDownLeft size={11} />
            Enter
          </span>
        )}

        <button
          onClick={onRun}
          disabled={isRunning || !hasValue}
          className="flex-shrink-0 flex items-center gap-2 px-5 py-2 rounded-md text-sm font-semibold transition-fast disabled:opacity-40 disabled:cursor-not-allowed"
          style={{
            background: hasValue && !isRunning ? "var(--accent-blue)" : "var(--bg-hover)",
            color: hasValue && !isRunning ? "white" : "var(--text-muted)",
            boxShadow: hasValue && !isRunning ? "0 0 16px rgba(59,130,246,0.3)" : "none",
          }}
        >
          {isRunning ? (
            <>
              <span
                className="inline-block w-3.5 h-3.5 rounded-full border-2 animate-spin"
                style={{ borderColor: "rgba(255,255,255,0.2)", borderTopColor: "white" }}
              />
              Analyzing
            </>
          ) : (
            "Analyze"
          )}
        </button>
      </div>

      {/* Progress stripe when running */}
      {isRunning && (
        <div
          className="h-0.5 w-full animate-pulse"
          style={{ background: "linear-gradient(90deg, transparent, var(--accent-blue), transparent)" }}
        />
      )}
    </div>
  );
}
