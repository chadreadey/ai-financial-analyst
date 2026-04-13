import React from "react";
import { useState, useEffect } from "react";
import { Eye, EyeOff, ChevronDown, ChevronRight, Key, Database, Cpu } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Separator } from "@/components/ui/separator";
import { api } from "@/api/client";

export interface Settings {
  provider: string;
  api_key: string;
  enable_tiingo: boolean;
  enable_fmp: boolean;
  enable_yahoo: boolean;
  enable_tavily: boolean;
  max_agent_context_chars: number;
  max_agent_output_tokens: number;
  synthesis_report_max_chars: number;
  synthesis_input_max_chars: number;
  max_synthesis_output_tokens: number;
}

const STORAGE_KEY = "atis_settings";

const DEFAULT_SETTINGS: Settings = {
  provider: "openai",
  api_key: "",
  enable_tiingo: true,
  enable_fmp: true,
  enable_yahoo: true,
  enable_tavily: true,
  max_agent_context_chars: 12000,
  max_agent_output_tokens: 1200,
  synthesis_report_max_chars: 4500,
  synthesis_input_max_chars: 22000,
  max_synthesis_output_tokens: 1500,
};

function loadFromStorage(): Settings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
    }
  } catch {
    // ignore parse errors
  }
  return { ...DEFAULT_SETTINGS };
}

function saveToStorage(s: Settings): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
  } catch {
    // ignore storage errors
  }
}

/** Read current settings from localStorage without prop drilling */
export function getSettings(): Settings {
  return loadFromStorage();
}

interface DataSource {
  key: keyof Pick<Settings, "enable_tiingo" | "enable_fmp" | "enable_yahoo" | "enable_tavily">;
  label: string;
  description: string;
}

const DATA_SOURCES: DataSource[] = [
  { key: "enable_tiingo", label: "Tiingo", description: "Price & fundamentals" },
  { key: "enable_fmp", label: "FMP", description: "Financial statements" },
  { key: "enable_yahoo", label: "Yahoo Finance", description: "Fallback data source" },
  { key: "enable_tavily", label: "Tavily Research", description: "News & web search" },
];

const BUDGET_FIELDS: Array<{ key: keyof Settings; label: string }> = [
  { key: "max_agent_context_chars", label: "Agent context chars" },
  { key: "max_agent_output_tokens", label: "Agent output tokens" },
  { key: "synthesis_report_max_chars", label: "Report max chars" },
  { key: "synthesis_input_max_chars", label: "Synthesis input chars" },
  { key: "max_synthesis_output_tokens", label: "Synthesis output tokens" },
];

function SectionHeader({
  icon: Icon,
  label,
}: {
  icon: React.ComponentType<{ size?: number }>;
  label: string;
}): React.ReactElement {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon size={13} />
      <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
    </div>
  );
}

interface SettingsDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function SettingsDrawer({ open, onOpenChange }: SettingsDrawerProps): React.ReactElement {
  const [settings, setSettings] = useState<Settings>(loadFromStorage);
  const [showKey, setShowKey] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Load backend defaults on mount (only fills fields not already persisted)
  useEffect(() => {
    api
      .getDefaults()
      .then((d) => {
        setSettings((prev) => {
          // Only apply backend defaults if localStorage had no saved copy
          const hasStored = localStorage.getItem(STORAGE_KEY) !== null;
          if (hasStored) return prev;
          const next: Settings = {
            ...prev,
            enable_tiingo: d.enable_tiingo,
            enable_fmp: d.enable_fmp,
            enable_yahoo: d.enable_yahoo,
            enable_tavily: d.enable_tavily,
            max_agent_context_chars: d.max_agent_context_chars,
            max_agent_output_tokens: d.max_agent_output_tokens,
            synthesis_report_max_chars: d.synthesis_report_max_chars,
            synthesis_input_max_chars: d.synthesis_input_max_chars,
            max_synthesis_output_tokens: d.max_synthesis_output_tokens,
          };
          saveToStorage(next);
          return next;
        });
      })
      .catch(() => {});
  }, []);

  function update(partial: Partial<Settings>): void {
    setSettings((prev) => {
      const next = { ...prev, ...partial };
      saveToStorage(next);
      return next;
    });
  }

  function handleKeyChange(value: string): void {
    update({ api_key: value });
  }

  function handleProviderChange(provider: string): void {
    update({ provider });
  }

  function handleSourceToggle(
    key: keyof Pick<Settings, "enable_tiingo" | "enable_fmp" | "enable_yahoo" | "enable_tavily">
  ): void {
    update({ [key]: !settings[key] });
  }

  function handleBudgetChange(key: keyof Settings, value: string): void {
    const num = parseInt(value, 10);
    if (!isNaN(num) && num > 0) {
      update({ [key]: num });
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-80 bg-card border-border flex flex-col overflow-y-auto">
        <SheetHeader className="pb-2">
          <SheetTitle>Settings</SheetTitle>
        </SheetHeader>

        <div className="space-y-5 pt-2 flex-1">
          {/* API Key */}
          <div>
            <SectionHeader icon={Key} label="API Key" />
            <div className="relative">
              <input
                type={showKey ? "text" : "password"}
                value={settings.api_key}
                onChange={(e) => handleKeyChange(e.target.value)}
                placeholder={`${settings.provider === "anthropic" ? "Anthropic" : "OpenAI"} API key`}
                className="w-full px-3 py-2 text-sm pr-9 rounded-md bg-background border border-input text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                spellCheck={false}
                autoComplete="off"
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                title={showKey ? "Hide key" : "Show key"}
              >
                {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
            <p className="mt-1.5 text-[11px] text-muted-foreground">
              Saved locally in your browser
            </p>
          </div>

          <Separator />

          {/* LLM Provider */}
          <div>
            <SectionHeader icon={Cpu} label="Provider" />
            <div className="grid grid-cols-2 gap-1.5">
              {(["openai", "anthropic"] as const).map((p) => {
                const active = settings.provider === p;
                return (
                  <button
                    key={p}
                    onClick={() => handleProviderChange(p)}
                    className={[
                      "py-1.5 px-2 rounded text-xs font-medium transition-colors border",
                      active
                        ? "bg-blue-500/10 text-blue-400 border-blue-500/35"
                        : "bg-muted text-muted-foreground border-transparent hover:bg-muted/80",
                    ].join(" ")}
                  >
                    {p === "openai" ? "OpenAI" : "Anthropic"}
                  </button>
                );
              })}
            </div>
          </div>

          <Separator />

          {/* Data Sources */}
          <div>
            <SectionHeader icon={Database} label="Data Sources" />
            <div className="space-y-1.5">
              {DATA_SOURCES.map(({ key, label, description }) => {
                const enabled = settings[key] as boolean;
                return (
                  <label
                    key={key}
                    className={[
                      "flex items-center justify-between gap-3 px-2.5 py-2 rounded cursor-pointer transition-colors border",
                      enabled
                        ? "bg-blue-500/5 border-blue-500/15"
                        : "bg-muted/50 border-transparent hover:bg-muted",
                    ].join(" ")}
                  >
                    <div className="flex-1 min-w-0">
                      <div
                        className={[
                          "text-xs font-medium",
                          enabled ? "text-foreground" : "text-muted-foreground",
                        ].join(" ")}
                      >
                        {label}
                      </div>
                      <div className="text-[11px] text-muted-foreground">{description}</div>
                    </div>
                    {/* Custom toggle switch */}
                    <div
                      className={[
                        "relative flex-shrink-0 w-8 h-4 rounded-full transition-colors cursor-pointer",
                        enabled ? "bg-blue-500" : "bg-border",
                      ].join(" ")}
                      onClick={() => handleSourceToggle(key)}
                    >
                      <div
                        className="absolute top-0.5 w-3 h-3 rounded-full bg-white shadow transition-all duration-150"
                        style={{ left: enabled ? "calc(100% - 14px)" : "2px" }}
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

          {/* Advanced / Budget guardrails */}
          <div>
            <button
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex items-center gap-1.5 w-full text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              {showAdvanced ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
              <span className="font-medium">Advanced</span>
              <span className="ml-auto text-[10px] uppercase tracking-wider text-muted-foreground/50">
                Budget guardrails
              </span>
            </button>

            {showAdvanced && (
              <div className="mt-3 space-y-2.5">
                {BUDGET_FIELDS.map(({ key, label }) => (
                  <div key={key}>
                    <label className="block text-[11px] mb-1 text-muted-foreground">
                      {label}
                    </label>
                    <input
                      type="number"
                      value={settings[key] as number}
                      onChange={(e) => handleBudgetChange(key, e.target.value)}
                      className="w-full px-2.5 py-1.5 text-xs rounded-md bg-background border border-input text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                    />
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}
