import React from "react";
import { useState, useEffect } from "react";
import { Eye, EyeOff, ChevronDown, ChevronRight, Key, Database, Cpu } from "lucide-react";
import { api } from "../../api/client";
import type { AnalysisSettings } from "../../pages/AnalysisPage";

interface SidebarProps {
  settings: AnalysisSettings;
  onSettingsChange: (settings: AnalysisSettings) => void;
  onRun: () => void;
  isRunning: boolean;
  ticker: string;
}

interface DataSource {
  key: keyof Pick<AnalysisSettings, "enable_tiingo" | "enable_fmp" | "enable_yahoo" | "enable_tavily">;
  label: string;
  description: string;
}

const DATA_SOURCES: DataSource[] = [
  { key: "enable_tiingo", label: "Tiingo", description: "Price & fundamentals" },
  { key: "enable_fmp", label: "FMP", description: "Financial statements" },
  { key: "enable_yahoo", label: "Yahoo Finance", description: "Fallback data source" },
  { key: "enable_tavily", label: "Tavily Research", description: "News & web search" },
];

const inputStyle: React.CSSProperties = {
  background: "var(--bg-primary)",
  border: "1px solid var(--border)",
  color: "var(--text-primary)",
  borderRadius: 6,
  outline: "none",
  transition: "border-color var(--transition)",
};

function SectionHeader({ icon: Icon, label }: { icon: React.ComponentType<{ size?: number }>; label: string }): React.ReactElement {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon size={13} />
      <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
        {label}
      </span>
    </div>
  );
}

export function Sidebar({ settings, onSettingsChange, onRun, isRunning, ticker }: SidebarProps): React.ReactElement {
  const [showKey, setShowKey] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Load API key from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem("analyst_api_key");
    if (saved) {
      onSettingsChange({ ...settings, api_key: saved });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load backend defaults on mount
  useEffect(() => {
    api.getDefaults().then((d) => {
      onSettingsChange({
        ...settings,
        enable_tiingo: d.enable_tiingo,
        enable_fmp: d.enable_fmp,
        enable_yahoo: d.enable_yahoo,
        enable_tavily: d.enable_tavily,
        max_agent_context_chars: d.max_agent_context_chars,
        max_agent_output_tokens: d.max_agent_output_tokens,
        synthesis_report_max_chars: d.synthesis_report_max_chars,
        synthesis_input_max_chars: d.synthesis_input_max_chars,
        max_synthesis_output_tokens: d.max_synthesis_output_tokens,
      });
    }).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleKeyChange = (key: string): void => {
    localStorage.setItem("analyst_api_key", key);
    onSettingsChange({ ...settings, api_key: key });
  };

  const handleProviderChange = (provider: string): void => {
    onSettingsChange({ ...settings, provider });
  };

  const handleSourceToggle = (key: keyof Pick<AnalysisSettings, "enable_tiingo" | "enable_fmp" | "enable_yahoo" | "enable_tavily">): void => {
    onSettingsChange({ ...settings, [key]: !settings[key] });
  };

  const handleBudgetChange = (key: string, value: string): void => {
    const num = parseInt(value, 10);
    if (!isNaN(num) && num > 0) {
      onSettingsChange({ ...settings, [key]: num });
    }
  };

  const budgetFields: Array<{ key: keyof AnalysisSettings; label: string }> = [
    { key: "max_agent_context_chars", label: "Agent context chars" },
    { key: "max_agent_output_tokens", label: "Agent output tokens" },
    { key: "synthesis_report_max_chars", label: "Report max chars" },
    { key: "synthesis_input_max_chars", label: "Synthesis input chars" },
    { key: "max_synthesis_output_tokens", label: "Synthesis output tokens" },
  ];

  return (
    <div
      className="rounded-lg overflow-hidden"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      {/* Header */}
      <div
        className="px-4 py-3 border-b"
        style={{ borderColor: "var(--border-subtle)", background: "rgba(255,255,255,0.02)" }}
      >
        <h3 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
          Configuration
        </h3>
      </div>

      <div className="p-4 space-y-5">
        {/* API Key */}
        <div>
          <SectionHeader icon={Key} label="API Key" />
          <div className="relative">
            <input
              type={showKey ? "text" : "password"}
              value={settings.api_key}
              onChange={(e) => handleKeyChange(e.target.value)}
              placeholder={`${settings.provider === "anthropic" ? "Anthropic" : "OpenAI"} API key`}
              className="w-full px-3 py-2 text-sm pr-9"
              style={inputStyle}
              spellCheck={false}
              autoComplete="off"
            />
            <button
              type="button"
              onClick={() => setShowKey(!showKey)}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 transition-fast"
              style={{ color: "var(--text-muted)" }}
              title={showKey ? "Hide key" : "Show key"}
            >
              {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
          <p className="mt-1.5 text-[11px]" style={{ color: "var(--text-muted)" }}>
            Saved locally in your browser
          </p>
        </div>

        {/* Divider */}
        <div style={{ height: 1, background: "var(--border-subtle)" }} />

        {/* LLM Provider */}
        <div>
          <SectionHeader icon={Cpu} label="Provider" />
          <div className="grid grid-cols-2 gap-1.5">
            {["openai", "anthropic"].map((p) => (
              <button
                key={p}
                onClick={() => handleProviderChange(p)}
                className="py-1.5 px-2 rounded text-xs font-medium transition-fast"
                style={{
                  background: settings.provider === p ? "var(--accent-blue-dim)" : "var(--bg-hover)",
                  color: settings.provider === p ? "var(--accent-blue)" : "var(--text-secondary)",
                  border: `1px solid ${settings.provider === p ? "rgba(59,130,246,0.35)" : "transparent"}`,
                }}
              >
                {p === "openai" ? "OpenAI" : "Anthropic"}
              </button>
            ))}
          </div>
        </div>

        {/* Divider */}
        <div style={{ height: 1, background: "var(--border-subtle)" }} />

        {/* Data Sources */}
        <div>
          <SectionHeader icon={Database} label="Data Sources" />
          <div className="space-y-1.5">
            {DATA_SOURCES.map(({ key, label, description }) => {
              const enabled = settings[key] as boolean;
              return (
                <label
                  key={key}
                  className="flex items-center justify-between gap-3 px-2.5 py-2 rounded cursor-pointer transition-fast"
                  style={{
                    background: enabled ? "rgba(59,130,246,0.05)" : "var(--bg-hover)",
                    border: `1px solid ${enabled ? "rgba(59,130,246,0.15)" : "transparent"}`,
                  }}
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-medium" style={{ color: enabled ? "var(--text-primary)" : "var(--text-secondary)" }}>
                      {label}
                    </div>
                    <div className="text-[11px]" style={{ color: "var(--text-muted)" }}>
                      {description}
                    </div>
                  </div>
                  {/* Toggle */}
                  <div
                    className="relative flex-shrink-0 w-8 h-4 rounded-full transition-fast"
                    style={{ background: enabled ? "var(--accent-blue)" : "var(--border)" }}
                    onClick={() => handleSourceToggle(key)}
                  >
                    <div
                      className="absolute top-0.5 w-3 h-3 rounded-full bg-white transition-fast"
                      style={{ left: enabled ? "calc(100% - 14px)" : "2px", boxShadow: "0 1px 3px rgba(0,0,0,0.4)" }}
                    />
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={() => handleSourceToggle(key)}
                      className="sr-only"
                    />
                  </div>
                </label>
              );
            })}
          </div>
        </div>

        {/* Advanced section */}
        <div>
          <button
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-1.5 w-full text-xs transition-fast"
            style={{ color: "var(--text-muted)" }}
          >
            {showAdvanced ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            <span className="font-medium">Advanced</span>
            <span className="ml-auto text-[10px] uppercase tracking-wider" style={{ color: "var(--border)" }}>
              Budget guardrails
            </span>
          </button>

          {showAdvanced && (
            <div className="mt-3 space-y-2.5">
              {budgetFields.map(({ key, label }) => (
                <div key={key}>
                  <label className="block text-[11px] mb-1" style={{ color: "var(--text-muted)" }}>
                    {label}
                  </label>
                  <input
                    type="number"
                    value={settings[key] as number}
                    onChange={(e) => handleBudgetChange(key, e.target.value)}
                    className="w-full px-2.5 py-1.5 text-xs"
                    style={inputStyle}
                  />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Run button */}
        <button
          onClick={onRun}
          disabled={isRunning || !ticker.trim()}
          className="w-full py-2.5 rounded-md text-sm font-semibold transition-fast disabled:opacity-40 disabled:cursor-not-allowed"
          style={{
            background: isRunning ? "var(--bg-hover)" : "var(--accent-blue)",
            color: isRunning ? "var(--text-muted)" : "white",
            boxShadow: !isRunning && ticker.trim() ? "0 0 12px rgba(59,130,246,0.25)" : "none",
          }}
        >
          {isRunning ? (
            <span className="flex items-center justify-center gap-2">
              <span
                className="inline-block w-3.5 h-3.5 rounded-full border-2 animate-spin"
                style={{ borderColor: "var(--border)", borderTopColor: "var(--accent-blue)" }}
              />
              Analyzing...
            </span>
          ) : (
            "Run Analysis"
          )}
        </button>
      </div>
    </div>
  );
}
