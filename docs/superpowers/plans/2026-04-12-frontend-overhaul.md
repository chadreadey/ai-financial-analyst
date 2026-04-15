# Frontend Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Overhaul the frontend from a vibecoded prototype into a polished, Koyfin-inspired portfolio management interface using shadcn/ui on a zinc + cyan design system.

**Architecture:** React + Vite + Tailwind 3 stays. Add shadcn/ui (Radix-based component library). Replace flat TopNav with labeled sidebar. Replace broken NL backtest with structured Backtest Explorer. Re-skin all pages with new design tokens. No backend API changes.

**Tech Stack:** React 19, Vite 6, Tailwind CSS 3, shadcn/ui (New York style, zinc theme), Radix UI, lightweight-charts, recharts, lucide-react

**Spec:** `docs/superpowers/specs/2026-04-12-frontend-overhaul-design.md`

---

## File Map

### New Files
- `frontend/components.json` — shadcn config
- `frontend/src/lib/utils.ts` — `cn()` utility (shadcn standard)
- `frontend/src/components/ui/*` — shadcn-generated components (Button, Input, Badge, Card, Tabs, Table, Dialog, Sheet, Separator, Tooltip, ScrollArea, DropdownMenu, Collapsible)
- `frontend/src/components/layout/AppSidebar.tsx` — new labeled sidebar nav
- `frontend/src/components/layout/AppLayout.tsx` — sidebar + main content wrapper
- `frontend/src/components/layout/SettingsDrawer.tsx` — settings Sheet (moved from old Sidebar)
- `frontend/src/components/analysis/SignalCards.tsx` — 4-card metric grid
- `frontend/src/components/analysis/AgentReportTabs.tsx` — tabbed agent reports (reused in deep dive)
- `frontend/src/components/backtest/RunSelector.tsx` — backtest run picker
- `frontend/src/components/backtest/PerformanceTab.tsx` — metrics + equity curve
- `frontend/src/components/backtest/TradeDetailRow.tsx` — expandable trade row
- `frontend/src/components/backtest/NewBacktestDialog.tsx` — structured backtest form
- `frontend/src/components/deepdive/AnalysisAccordion.tsx` — expandable analysis history rows

### Modified Files
- `frontend/src/index.css` — replace all CSS variables with new zinc palette
- `frontend/tailwind.config.js` — add shadcn color tokens to `extend`
- `frontend/tsconfig.app.json` — add `@/` path alias for shadcn imports
- `frontend/vite.config.ts` — add path alias resolution
- `frontend/src/App.tsx` — replace TopNav with AppLayout, remove deleted page routes
- `frontend/src/pages/AnalysisPage.tsx` — remove Sidebar, use new layout + components
- `frontend/src/pages/BacktestPage.tsx` — full rewrite as Backtest Explorer
- `frontend/src/pages/PaperTradingPage.tsx` — re-skin with shadcn components
- `frontend/src/pages/StockDeepDivePage.tsx` — add analysis accordion, re-skin
- `frontend/src/components/charts/PriceChart.tsx` — update colors
- `frontend/src/components/charts/EquityCurveChart.tsx` — update colors
- `frontend/src/components/charts/SparklineChart.tsx` — update colors

### Deleted Files
- `frontend/src/pages/WatchlistPage.tsx`
- `frontend/src/pages/NewsPage.tsx`
- `frontend/src/pages/IndustryPage.tsx`
- `frontend/src/pages/PortfolioPage.tsx`
- `frontend/src/components/layout/TopNav.tsx`
- `frontend/src/components/layout/Sidebar.tsx`
- `frontend/src/components/common/Card.tsx` (replaced by shadcn Card)
- `frontend/src/components/common/Badge.tsx` (replaced by shadcn Badge)
- `frontend/src/components/watchlist/*` (no longer needed)

---

### Task 1: Setup shadcn/ui and Design System Foundation

**Files:**
- Modify: `frontend/tsconfig.app.json`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/tailwind.config.js`
- Modify: `frontend/src/index.css`
- Create: `frontend/src/lib/utils.ts`
- Create: `frontend/components.json`

- [ ] **Step 1: Add path alias to tsconfig.app.json**

Add `baseUrl` and `paths` to the existing `compilerOptions`:

```json
{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"]
    }
  }
}
```

Keep all existing compiler options — just add these two fields.

- [ ] **Step 2: Add path alias to vite.config.ts**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
})
```

- [ ] **Step 3: Create the cn() utility**

Create `frontend/src/lib/utils.ts`:

```typescript
import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
```

- [ ] **Step 4: Install shadcn/ui**

```bash
cd frontend && npx shadcn@latest init
```

When prompted:
- Style: **New York**
- Base color: **Zinc**
- CSS variables: **Yes**

This will create `components.json` and update `tailwind.config.js` and `index.css`.

- [ ] **Step 5: Override index.css with the approved palette**

Replace the entire `:root` block and body styles in `frontend/src/index.css` with:

```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: 240 10% 3.9%;
    --foreground: 0 0% 98%;
    --card: 240 6% 10%;
    --card-foreground: 0 0% 98%;
    --popover: 240 6% 10%;
    --popover-foreground: 0 0% 98%;
    --primary: 187 72% 43%;
    --primary-foreground: 240 10% 3.9%;
    --secondary: 240 4% 16%;
    --secondary-foreground: 0 0% 98%;
    --muted: 240 4% 16%;
    --muted-foreground: 240 5% 65%;
    --accent: 187 72% 43%;
    --accent-foreground: 240 10% 3.9%;
    --destructive: 0 84% 60%;
    --destructive-foreground: 0 0% 98%;
    --border: 240 4% 16%;
    --input: 240 4% 16%;
    --ring: 187 72% 43%;
    --radius: 0.5rem;

    /* Semantic financial colors (non-shadcn, used directly) */
    --positive: #22c55e;
    --negative: #ef4444;
    --warning: #f59e0b;
    --sidebar-bg: #0f0f11;
    --card-elevated: #141416;
  }

  * {
    border-color: hsl(var(--border));
  }

  body {
    margin: 0;
    background: hsl(var(--background));
    color: hsl(var(--foreground));
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    -webkit-font-smoothing: antialiased;
    font-size: 13px;
    line-height: 1.5;
  }
}

::-webkit-scrollbar {
  width: 5px;
  height: 5px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: hsl(var(--border));
  border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover {
  background: hsl(var(--muted-foreground));
}

/* Prose styles for markdown agent reports */
.prose {
  color: hsl(var(--muted-foreground));
  line-height: 1.7;
}
.prose h1, .prose h2, .prose h3 {
  color: hsl(var(--foreground));
  font-weight: 600;
  margin-top: 1.5em;
  margin-bottom: 0.5em;
}
.prose h1 { font-size: 1.25rem; }
.prose h2 { font-size: 1.1rem; }
.prose h3 { font-size: 1rem; }
.prose p { margin: 0.75em 0; }
.prose ul, .prose ol { padding-left: 1.5em; margin: 0.75em 0; }
.prose li { margin: 0.25em 0; }
.prose strong { color: hsl(var(--foreground)); font-weight: 600; }
.prose code {
  background: hsl(var(--secondary));
  padding: 0.1em 0.4em;
  border-radius: 4px;
  font-size: 0.85em;
  color: hsl(var(--primary));
}
.prose blockquote {
  border-left: 3px solid hsl(var(--primary));
  padding-left: 1em;
  color: hsl(var(--muted-foreground));
  margin: 1em 0;
  font-style: italic;
}
.prose table { width: 100%; border-collapse: collapse; }
.prose th {
  background: hsl(var(--secondary));
  padding: 0.5em 0.75em;
  text-align: left;
  font-weight: 600;
  color: hsl(var(--foreground));
  border-bottom: 1px solid hsl(var(--border));
}
.prose td {
  padding: 0.5em 0.75em;
  border-bottom: 1px solid hsl(var(--border));
  color: hsl(var(--muted-foreground));
}
.prose hr {
  border: none;
  border-top: 1px solid hsl(var(--border));
  margin: 1.5em 0;
}
```

- [ ] **Step 6: Install shadcn components**

Run each command from `frontend/`:

```bash
npx shadcn@latest add button input badge card tabs table dialog sheet separator tooltip scroll-area dropdown-menu collapsible
```

- [ ] **Step 7: Verify the build compiles**

```bash
cd frontend && npm run build
```

Expected: Build succeeds with no errors. shadcn components are in `src/components/ui/`.

- [ ] **Step 8: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): setup shadcn/ui with zinc + cyan design system"
```

---

### Task 2: App Layout — Sidebar Navigation

**Files:**
- Create: `frontend/src/components/layout/AppSidebar.tsx`
- Create: `frontend/src/components/layout/AppLayout.tsx`
- Modify: `frontend/src/App.tsx`
- Delete: `frontend/src/components/layout/TopNav.tsx`

- [ ] **Step 1: Create AppSidebar.tsx**

Create `frontend/src/components/layout/AppSidebar.tsx`:

```tsx
import { NavLink } from "react-router-dom";
import { Search, FlaskConical, Wallet, Settings } from "lucide-react";
import { cn } from "@/lib/utils";
import { Separator } from "@/components/ui/separator";

const navSections = [
  {
    label: "Research",
    items: [
      { to: "/analysis", label: "Analysis", icon: Search },
      { to: "/backtest", label: "Backtest Lab", icon: FlaskConical },
    ],
  },
  {
    label: "Trading",
    items: [
      { to: "/paper-trading", label: "Paper Trading", icon: Wallet },
    ],
  },
];

interface AppSidebarProps {
  onSettingsOpen: () => void;
}

export function AppSidebar({ onSettingsOpen }: AppSidebarProps) {
  return (
    <aside
      className="fixed left-0 top-0 bottom-0 w-48 flex flex-col border-r border-border z-40"
      style={{ background: "var(--sidebar-bg)" }}
    >
      {/* Brand */}
      <div className="flex items-center gap-2 px-4 py-4">
        <div className="w-6 h-6 rounded-md flex items-center justify-center bg-primary/10">
          <div className="w-3 h-3 rounded-sm bg-primary" />
        </div>
        <span className="text-sm font-bold tracking-tight">ATIS</span>
      </div>

      {/* Nav sections */}
      <nav className="flex-1 px-2 space-y-4 mt-2">
        {navSections.map((section) => (
          <div key={section.label}>
            <div className="px-3 mb-1 text-[10px] font-semibold uppercase tracking-[1.2px] text-muted-foreground/50">
              {section.label}
            </div>
            <div className="space-y-0.5">
              {section.items.map(({ to, label, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-2.5 px-3 py-[7px] rounded-md text-xs font-medium transition-colors",
                      isActive
                        ? "bg-primary/[0.08] text-primary"
                        : "text-muted-foreground hover:text-foreground hover:bg-secondary"
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      <div
                        className={cn(
                          "w-4 h-4 rounded flex items-center justify-center",
                          isActive ? "bg-primary/15 text-primary" : "bg-secondary text-muted-foreground"
                        )}
                      >
                        <Icon size={10} />
                      </div>
                      {label}
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-2 pb-3 space-y-2">
        <Separator />
        {/* Regime badge — placeholder, will be dynamic later */}
        <div className="mx-1 px-3 py-1.5 rounded-md bg-[--positive]/[0.08] border border-[--positive]/15 flex items-center justify-between">
          <span className="text-[10px] font-semibold tracking-wide" style={{ color: "var(--positive)" }}>
            BULLISH
          </span>
          <span className="text-[10px] text-muted-foreground">VIX 18.3</span>
        </div>
        <button
          onClick={onSettingsOpen}
          className="w-full mx-1 px-3 py-1.5 rounded-md bg-secondary border border-border flex items-center gap-2 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
        >
          <Settings size={12} />
          Settings
        </button>
      </div>
    </aside>
  );
}
```

- [ ] **Step 2: Create AppLayout.tsx**

Create `frontend/src/components/layout/AppLayout.tsx`:

```tsx
import { useState } from "react";
import { AppSidebar } from "./AppSidebar";
import { SettingsDrawer } from "./SettingsDrawer";

export function AppLayout({ children }: { children: React.ReactNode }) {
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <div className="min-h-screen bg-background">
      <AppSidebar onSettingsOpen={() => setSettingsOpen(true)} />
      <main className="ml-48 min-h-screen">
        {children}
      </main>
      <SettingsDrawer open={settingsOpen} onOpenChange={setSettingsOpen} />
    </div>
  );
}
```

- [ ] **Step 3: Create SettingsDrawer.tsx stub**

Create `frontend/src/components/layout/SettingsDrawer.tsx` — we'll fill it in Task 3, but need it to exist for AppLayout:

```tsx
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";

interface SettingsDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function SettingsDrawer({ open, onOpenChange }: SettingsDrawerProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-80 bg-card border-border">
        <SheetHeader>
          <SheetTitle>Settings</SheetTitle>
        </SheetHeader>
        <p className="text-sm text-muted-foreground mt-4">Settings will be moved here from the old sidebar.</p>
      </SheetContent>
    </Sheet>
  );
}
```

- [ ] **Step 4: Update App.tsx — replace TopNav with AppLayout, remove deleted routes**

Replace the entire `frontend/src/App.tsx`:

```tsx
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AppLayout } from "./components/layout/AppLayout";
import { AnalysisPage } from "./pages/AnalysisPage";
import { StockDeepDivePage } from "./pages/StockDeepDivePage";
import { BacktestPage } from "./pages/BacktestPage";
import { PaperTradingPage } from "./pages/PaperTradingPage";

export default function App() {
  return (
    <BrowserRouter>
      <AppLayout>
        <Routes>
          <Route path="/analysis" element={<AnalysisPage />} />
          <Route path="/stock/:ticker" element={<StockDeepDivePage />} />
          <Route path="/backtest" element={<BacktestPage />} />
          <Route path="/paper-trading" element={<PaperTradingPage />} />
          <Route path="*" element={<Navigate to="/analysis" replace />} />
        </Routes>
      </AppLayout>
    </BrowserRouter>
  );
}
```

- [ ] **Step 5: Delete removed files**

```bash
cd frontend/src
rm pages/WatchlistPage.tsx pages/NewsPage.tsx pages/IndustryPage.tsx pages/PortfolioPage.tsx
rm components/layout/TopNav.tsx
rm -rf components/watchlist
```

- [ ] **Step 6: Verify build**

```bash
cd frontend && npm run build
```

Expected: Build succeeds. App renders with sidebar nav on left, content on right. Removed pages return 404 → redirect to /analysis.

- [ ] **Step 7: Commit**

```bash
git add -A frontend/src/
git commit -m "feat(frontend): replace TopNav with labeled sidebar, remove placeholder pages"
```

---

### Task 3: Settings Drawer (Full Implementation)

**Files:**
- Modify: `frontend/src/components/layout/SettingsDrawer.tsx`
- Modify: `frontend/src/pages/AnalysisPage.tsx`
- Delete: `frontend/src/components/layout/Sidebar.tsx`

- [ ] **Step 1: Implement SettingsDrawer with all config fields**

Replace `frontend/src/components/layout/SettingsDrawer.tsx`:

```tsx
import { useState, useEffect } from "react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Eye, EyeOff } from "lucide-react";
import { api } from "@/api/client";

interface SettingsDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface Settings {
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

const DEFAULTS: Settings = {
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

const DATA_SOURCES = [
  { key: "enable_tiingo" as const, label: "Tiingo", desc: "Price & fundamentals" },
  { key: "enable_fmp" as const, label: "FMP", desc: "Financial statements" },
  { key: "enable_yahoo" as const, label: "Yahoo Finance", desc: "Fallback data" },
  { key: "enable_tavily" as const, label: "Tavily Research", desc: "News & web" },
];

const BUDGET_FIELDS = [
  { key: "max_agent_context_chars" as const, label: "Agent context chars" },
  { key: "max_agent_output_tokens" as const, label: "Agent output tokens" },
  { key: "synthesis_report_max_chars" as const, label: "Report max chars" },
  { key: "synthesis_input_max_chars" as const, label: "Synthesis input chars" },
  { key: "max_synthesis_output_tokens" as const, label: "Synthesis output tokens" },
];

// Persist to localStorage so AnalysisPage can read it
const STORAGE_KEY = "atis_settings";

export function getSettings(): Settings {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) return { ...DEFAULTS, ...JSON.parse(saved) };
  } catch {}
  return DEFAULTS;
}

function saveSettings(s: Settings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
}

export function SettingsDrawer({ open, onOpenChange }: SettingsDrawerProps) {
  const [settings, setSettings] = useState<Settings>(getSettings);
  const [showKey, setShowKey] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    api.getDefaults().then((d) => {
      setSettings((prev) => {
        const merged = {
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
        saveSettings(merged);
        return merged;
      });
    }).catch(() => {});
  }, []);

  const update = (partial: Partial<Settings>) => {
    setSettings((prev) => {
      const next = { ...prev, ...partial };
      saveSettings(next);
      return next;
    });
  };

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-80 bg-card border-border overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="text-sm">Settings</SheetTitle>
        </SheetHeader>

        <div className="mt-6 space-y-6">
          {/* API Key */}
          <div>
            <label className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">API Key</label>
            <div className="relative mt-1.5">
              <Input
                type={showKey ? "text" : "password"}
                value={settings.api_key}
                onChange={(e) => update({ api_key: e.target.value })}
                placeholder={`${settings.provider === "anthropic" ? "Anthropic" : "OpenAI"} API key`}
                className="pr-9 text-xs"
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
              >
                {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
            <p className="mt-1 text-[10px] text-muted-foreground">Saved locally in your browser</p>
          </div>

          <Separator />

          {/* Provider */}
          <div>
            <label className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">Provider</label>
            <div className="grid grid-cols-2 gap-1.5 mt-1.5">
              {["openai", "anthropic"].map((p) => (
                <Button
                  key={p}
                  variant={settings.provider === p ? "default" : "secondary"}
                  size="sm"
                  className="text-xs h-8"
                  onClick={() => update({ provider: p })}
                >
                  {p === "openai" ? "OpenAI" : "Anthropic"}
                </Button>
              ))}
            </div>
          </div>

          <Separator />

          {/* Data Sources */}
          <div>
            <label className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">Data Sources</label>
            <div className="mt-1.5 space-y-1.5">
              {DATA_SOURCES.map(({ key, label, desc }) => {
                const enabled = settings[key];
                return (
                  <button
                    key={key}
                    onClick={() => update({ [key]: !enabled })}
                    className={`w-full flex items-center justify-between px-3 py-2 rounded-md border text-left transition-colors ${
                      enabled
                        ? "bg-primary/[0.05] border-primary/15"
                        : "bg-secondary border-transparent"
                    }`}
                  >
                    <div>
                      <div className={`text-xs font-medium ${enabled ? "text-foreground" : "text-muted-foreground"}`}>{label}</div>
                      <div className="text-[10px] text-muted-foreground">{desc}</div>
                    </div>
                    <div className={`w-8 h-4 rounded-full relative transition-colors ${enabled ? "bg-primary" : "bg-border"}`}>
                      <div className={`absolute top-0.5 w-3 h-3 rounded-full bg-white shadow-sm transition-all ${enabled ? "left-[calc(100%-14px)]" : "left-0.5"}`} />
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <Separator />

          {/* Advanced */}
          <div>
            <button
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              <span className="text-[10px]">{showAdvanced ? "▼" : "▶"}</span>
              <span className="font-medium">Advanced — Budget Guardrails</span>
            </button>
            {showAdvanced && (
              <div className="mt-3 space-y-2.5">
                {BUDGET_FIELDS.map(({ key, label }) => (
                  <div key={key}>
                    <label className="block text-[10px] mb-1 text-muted-foreground">{label}</label>
                    <Input
                      type="number"
                      value={settings[key]}
                      onChange={(e) => {
                        const num = parseInt(e.target.value, 10);
                        if (!isNaN(num) && num > 0) update({ [key]: num });
                      }}
                      className="text-xs h-8"
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
```

- [ ] **Step 2: Update AnalysisPage to use getSettings() instead of Sidebar**

Replace `frontend/src/pages/AnalysisPage.tsx`:

```tsx
import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useAnalysis } from "@/hooks/useAnalysis";
import { getSettings } from "@/components/layout/SettingsDrawer";
import { TickerInput } from "@/components/analysis/TickerInput";
import { ProgressStream } from "@/components/analysis/ProgressStream";
import { ResultView } from "@/components/analysis/ResultView";
import { PastAnalysesPanel } from "@/components/analysis/PastAnalysesPanel";
import { AlertTriangle } from "lucide-react";
import type { AnalysisResult } from "@/api/types";

export function AnalysisPage() {
  const [searchParams] = useSearchParams();
  const [ticker, setTicker] = useState(searchParams.get("ticker") || "");
  const [selectedPastResult, setSelectedPastResult] = useState<AnalysisResult | null>(null);

  useEffect(() => {
    const t = searchParams.get("ticker");
    if (t) setTicker(t.toUpperCase());
  }, [searchParams]);

  const { isRunning, progress, result, error, run } = useAnalysis();

  const handleRun = () => {
    if (!ticker.trim()) return;
    const s = getSettings();
    run({
      ticker: ticker.trim().toUpperCase(),
      provider: s.provider,
      api_key: s.api_key || undefined,
      enable_tiingo: s.enable_tiingo,
      enable_fmp: s.enable_fmp,
      enable_yahoo: s.enable_yahoo,
      enable_tavily: s.enable_tavily,
      max_agent_context_chars: s.max_agent_context_chars,
      max_agent_output_tokens: s.max_agent_output_tokens,
      synthesis_report_max_chars: s.synthesis_report_max_chars,
      synthesis_input_max_chars: s.synthesis_input_max_chars,
      max_synthesis_output_tokens: s.max_synthesis_output_tokens,
    });
    setSelectedPastResult(null);
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-4">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <h1 className="text-base font-semibold tracking-tight">Analysis</h1>
        <TickerInput
          ticker={ticker}
          onTickerChange={setTicker}
          onRun={handleRun}
          isRunning={isRunning}
        />
      </div>

      {isRunning && progress && <ProgressStream progress={progress} />}

      {error && (
        <div className="flex items-start gap-3 rounded-lg p-4 bg-destructive/10 border border-destructive/30 text-destructive text-sm">
          <AlertTriangle size={16} className="mt-0.5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {(result || selectedPastResult) && (
        <ResultView result={result || selectedPastResult!} />
      )}
      <PastAnalysesPanel onOpenResult={setSelectedPastResult} />
    </div>
  );
}
```

- [ ] **Step 3: Delete old Sidebar**

```bash
rm frontend/src/components/layout/Sidebar.tsx
```

- [ ] **Step 4: Verify build and test**

```bash
cd frontend && npm run build
```

Expected: Build succeeds. Analysis page renders without left sidebar config panel. Settings accessible via gear icon in nav sidebar.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/
git commit -m "feat(frontend): move settings to drawer, simplify analysis page layout"
```

---

### Task 4: Chart Restyling

**Files:**
- Modify: `frontend/src/components/charts/PriceChart.tsx`
- Modify: `frontend/src/components/charts/EquityCurveChart.tsx`
- Modify: `frontend/src/components/charts/SparklineChart.tsx`

- [ ] **Step 1: Update PriceChart colors**

In `frontend/src/components/charts/PriceChart.tsx`, find and replace the color values used in the chart configuration. The exact locations vary, but update these specific values wherever they appear:

- Chart background: change to `#0f0f11`
- Grid line color: change to `#1a1a1e`
- Candle up color: change to `#22c55e`
- Candle down color: change to `#ef4444`
- Crosshair color: change to `#3f3f46`
- Text/label color: change to `#71717a`
- Any blue accent (`#3b82f6`, `#818cf8`): change to `#06b6d4`
- Forecast area purple: change to `rgba(6,182,212,0.15)` (cyan instead of purple)

- [ ] **Step 2: Update EquityCurveChart colors**

In `frontend/src/components/charts/EquityCurveChart.tsx`, update:

- Positive stroke: change to `#06b6d4` (cyan)
- Positive fill gradient: `rgba(6,182,212,0.3)` → `rgba(6,182,212,0.02)`
- Negative stroke: keep `#ef4444`
- Negative fill gradient: `rgba(239,68,68,0.3)` → `transparent`
- Axis text: change to `#71717a`
- Grid lines: change to `#1a1a1e`
- Any remaining green (`#10b981`) for positive: change to `#06b6d4`

- [ ] **Step 3: Update SparklineChart colors**

In `frontend/src/components/charts/SparklineChart.tsx`, update:

- Up color: change to `#06b6d4` (cyan instead of green for sparklines)
- Down color: keep `#ef4444`
- Fill gradients: match equity curve approach

- [ ] **Step 4: Verify charts render**

```bash
cd frontend && npm run dev
```

Open http://localhost:5173/analysis, run an analysis, check that the price chart renders with the new colors. Check /paper-trading for equity curve.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/charts/
git commit -m "feat(frontend): restyle charts to zinc + cyan palette"
```

---

### Task 5: Delete Old Common Components

**Files:**
- Delete: `frontend/src/components/common/Card.tsx`
- Delete: `frontend/src/components/common/Badge.tsx`
- Modify: any files importing from `../common/Card` or `../common/Badge`

- [ ] **Step 1: Find all imports of old Card and Badge**

```bash
cd frontend && grep -rn "from.*common/Card\|from.*common/Badge" src/ --include="*.tsx" --include="*.ts"
```

- [ ] **Step 2: Replace each import**

For every file found, replace:
- `import { Card } from "../components/common/Card"` → `import { Card } from "@/components/ui/card"`
- `import { Badge } from "../components/common/Badge"` → `import { Badge } from "@/components/ui/badge"`

Note: shadcn's Card has different props than the old one — it doesn't take `padding` or `elevated` props. Replace `<Card padding="md" elevated>` with `<Card className="p-4">` (or appropriate padding class). Replace `<Badge label="BUY" variant="green">` with `<Badge variant="default" className="bg-[--positive]/10 text-[--positive] border-[--positive]/20">BUY</Badge>`.

- [ ] **Step 3: Delete old components**

```bash
rm frontend/src/components/common/Card.tsx frontend/src/components/common/Badge.tsx
```

- [ ] **Step 4: Verify build**

```bash
cd frontend && npm run build
```

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/
git commit -m "refactor(frontend): replace hand-rolled Card/Badge with shadcn components"
```

---

### Task 6: Analysis Page — Result View Polish

**Files:**
- Create: `frontend/src/components/analysis/SignalCards.tsx`
- Create: `frontend/src/components/analysis/AgentReportTabs.tsx`
- Modify: `frontend/src/components/analysis/ResultView.tsx`

- [ ] **Step 1: Create SignalCards component**

Create `frontend/src/components/analysis/SignalCards.tsx`:

```tsx
import { Card } from "@/components/ui/card";

interface SignalCardProps {
  label: string;
  value: string;
  colorClass?: string;
}

function SignalCard({ label, value, colorClass = "text-foreground" }: SignalCardProps) {
  return (
    <Card className="p-3">
      <div className="text-[10px] font-medium uppercase tracking-[0.8px] text-muted-foreground">{label}</div>
      <div className={`text-sm font-semibold mt-0.5 ${colorClass}`}>{value}</div>
    </Card>
  );
}

interface SignalCardsProps {
  verdict: Record<string, any> | null;
}

export function SignalCards({ verdict }: SignalCardsProps) {
  if (!verdict) return null;

  const score = verdict.weighted_score ?? verdict.composite_score;
  const scoreColor = score > 0.5 ? "text-[--positive]" : score > 0 ? "text-primary" : "text-[--negative]";

  return (
    <div className="grid grid-cols-4 gap-3">
      <SignalCard
        label="Weighted Score"
        value={score != null ? score.toFixed(2) : "—"}
        colorClass={scoreColor}
      />
      <SignalCard
        label="Conviction"
        value={verdict.conviction ?? "—"}
        colorClass="text-primary"
      />
      <SignalCard
        label="Verdict"
        value={verdict.verdict ?? "—"}
        colorClass={
          verdict.verdict === "BUY" ? "text-[--positive]" :
          verdict.verdict === "SELL" ? "text-[--negative]" :
          "text-[--warning]"
        }
      />
      <SignalCard
        label="Time Horizon"
        value={verdict.time_horizon ?? "—"}
      />
    </div>
  );
}
```

- [ ] **Step 2: Create AgentReportTabs component**

Create `frontend/src/components/analysis/AgentReportTabs.tsx`:

```tsx
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { MarkdownRenderer } from "@/components/common/MarkdownRenderer";
import type { AgentReport } from "@/api/types";

interface AgentReportTabsProps {
  synthesis: string;
  agentReports: AgentReport[];
  tradeParams?: Record<string, any> | null;
}

const AGENT_ORDER = ["Synthesis", "DCF", "Risk", "Earnings", "Competitive", "Pattern", "Macro"];

export function AgentReportTabs({ synthesis, agentReports, tradeParams }: AgentReportTabsProps) {
  // Build tab content map
  const reportMap: Record<string, string> = { Synthesis: synthesis };
  for (const r of agentReports) {
    const name = r.agent_name.replace(/Agent$/, "").replace(/Specialist$/, "");
    reportMap[name] = r.analysis;
  }

  const availableTabs = AGENT_ORDER.filter((name) => reportMap[name]);

  return (
    <Tabs defaultValue="Synthesis" className="mt-4">
      <TabsList className="bg-secondary border border-border h-8">
        {availableTabs.map((name) => (
          <TabsTrigger key={name} value={name} className="text-xs h-7 data-[state=active]:text-primary">
            {name}
          </TabsTrigger>
        ))}
      </TabsList>
      {availableTabs.map((name) => (
        <TabsContent key={name} value={name}>
          <div className="bg-card border border-border rounded-lg p-4">
            <div className="prose text-sm">
              <MarkdownRenderer content={reportMap[name]} />
            </div>
            {name === "Synthesis" && tradeParams && (
              <div className="mt-3 pt-3 border-t border-border flex gap-2 flex-wrap">
                {tradeParams.entry_price && (
                  <span className="px-2 py-0.5 rounded bg-secondary text-[10px] text-muted-foreground border border-border">
                    Entry: ${tradeParams.entry_price}
                  </span>
                )}
                {tradeParams.price_target && (
                  <span className="px-2 py-0.5 rounded bg-secondary text-[10px] text-muted-foreground border border-border">
                    Target: ${tradeParams.price_target}
                  </span>
                )}
                {tradeParams.stop_loss_value && (
                  <span className="px-2 py-0.5 rounded bg-secondary text-[10px] text-muted-foreground border border-border">
                    Stop: ${tradeParams.stop_loss_value}
                  </span>
                )}
                {tradeParams.time_horizon && (
                  <span className="px-2 py-0.5 rounded bg-secondary text-[10px] text-muted-foreground border border-border">
                    Horizon: {tradeParams.time_horizon}
                  </span>
                )}
              </div>
            )}
          </div>
        </TabsContent>
      ))}
    </Tabs>
  );
}
```

- [ ] **Step 3: Update ResultView to use new components**

Read the current `ResultView.tsx`, then update it to:
- Import and use `SignalCards` for the verdict metrics
- Import and use `AgentReportTabs` for the agent reports
- Use shadcn Badge for the verdict badge (BUY/SELL/HOLD)
- Use the new palette classes (`text-primary`, `text-[--positive]`, etc.)
- Remove any old `style={{ color: "var(--accent-blue)" }}` patterns — use Tailwind classes

The exact edit depends on the current ResultView structure, but the pattern is: replace inline styles with Tailwind classes, replace custom components with shadcn components, wrap agent reports in the new AgentReportTabs.

- [ ] **Step 4: Verify analysis page renders correctly**

```bash
cd frontend && npm run dev
```

Open http://localhost:5173/analysis, enter a ticker, verify the result view shows signal cards + agent tabs with new styling.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/
git commit -m "feat(frontend): polish analysis page with SignalCards and AgentReportTabs"
```

---

### Task 7: Backtest Explorer — Full Rebuild

**Files:**
- Create: `frontend/src/components/backtest/RunSelector.tsx`
- Create: `frontend/src/components/backtest/PerformanceTab.tsx`
- Create: `frontend/src/components/backtest/TradeDetailRow.tsx`
- Create: `frontend/src/components/backtest/NewBacktestDialog.tsx`
- Rewrite: `frontend/src/pages/BacktestPage.tsx`

- [ ] **Step 1: Create RunSelector**

Create `frontend/src/components/backtest/RunSelector.tsx`:

```tsx
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

interface BacktestRun {
  id: string;
  config_summary: string;
  sharpe: number | null;
  pbo?: number | null;
  date: string;
}

interface RunSelectorProps {
  runs: BacktestRun[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function RunSelector({ runs, selectedId, onSelect }: RunSelectorProps) {
  const selected = runs.find((r) => r.id === selectedId) ?? runs[0];
  if (!selected) return null;

  return (
    <Card className="p-3 flex items-center justify-between">
      <div className="flex items-center gap-3">
        <span className="text-xs text-muted-foreground">Run:</span>
        <select
          value={selected.id}
          onChange={(e) => onSelect(e.target.value)}
          className="bg-secondary border border-border rounded px-2 py-1 text-xs text-foreground"
        >
          {runs.map((r) => (
            <option key={r.id} value={r.id}>
              {r.date} — {r.config_summary}
            </option>
          ))}
        </select>
      </div>
      <div className="flex gap-2">
        {selected.sharpe != null && (
          <Badge variant="outline" className="text-primary border-primary/20 bg-primary/10">
            Sharpe {selected.sharpe.toFixed(2)}
          </Badge>
        )}
        {selected.pbo != null && (
          <Badge variant="outline" className={`${selected.pbo === 0 ? "text-[--positive] border-[--positive]/20 bg-[--positive]/10" : "text-[--warning] border-[--warning]/20 bg-[--warning]/10"}`}>
            PBO {(selected.pbo * 100).toFixed(0)}%
          </Badge>
        )}
      </div>
    </Card>
  );
}
```

- [ ] **Step 2: Create PerformanceTab**

Create `frontend/src/components/backtest/PerformanceTab.tsx`:

```tsx
import { Card } from "@/components/ui/card";
import { EquityCurveChart } from "@/components/charts/EquityCurveChart";

interface PerformanceTabProps {
  sharpe: number | null;
  totalReturn: number | null;
  maxDrawdown: number | null;
  alpha: number | null;
  equityCurve: { date: string; equity: number }[];
}

function MetricCard({ label, value, colorClass = "" }: { label: string; value: string; colorClass?: string }) {
  return (
    <Card className="p-3">
      <div className="text-[10px] font-medium uppercase tracking-[0.8px] text-muted-foreground">{label}</div>
      <div className={`text-sm font-semibold mt-0.5 ${colorClass}`}>{value}</div>
    </Card>
  );
}

export function PerformanceTab({ sharpe, totalReturn, maxDrawdown, alpha, equityCurve }: PerformanceTabProps) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-3">
        <MetricCard label="Sharpe Ratio" value={sharpe?.toFixed(2) ?? "—"} colorClass="text-primary" />
        <MetricCard
          label="Total Return"
          value={totalReturn != null ? `${totalReturn > 0 ? "+" : ""}${totalReturn.toFixed(1)}%` : "—"}
          colorClass={totalReturn != null && totalReturn > 0 ? "text-[--positive]" : "text-[--negative]"}
        />
        <MetricCard
          label="Max Drawdown"
          value={maxDrawdown != null ? `${maxDrawdown.toFixed(1)}%` : "—"}
          colorClass="text-[--negative]"
        />
        <MetricCard
          label="Alpha (ann.)"
          value={alpha != null ? `${alpha > 0 ? "+" : ""}${alpha.toFixed(1)}%` : "—"}
          colorClass={alpha != null && alpha > 0 ? "text-[--positive]" : "text-muted-foreground"}
        />
      </div>

      {equityCurve.length > 0 && (
        <div className="rounded-lg border border-border p-3" style={{ background: "#0f0f11" }}>
          <EquityCurveChart data={equityCurve} height={200} />
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Create TradeDetailRow**

Create `frontend/src/components/backtest/TradeDetailRow.tsx`:

```tsx
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface Trade {
  date: string;
  ticker: string;
  direction: string;
  entry_price: number;
  exit_price: number;
  return_pct: number;
  regime?: string;
  signals?: Record<string, number>;
  [key: string]: any;
}

export function TradeDetailRow({ trade }: { trade: Trade }) {
  const [open, setOpen] = useState(false);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <tr className="cursor-pointer hover:bg-secondary/50 transition-colors">
          <td className="px-3 py-2 text-xs text-muted-foreground">{trade.date}</td>
          <td className="px-3 py-2 text-xs font-medium text-foreground">{trade.ticker}</td>
          <td className="px-3 py-2">
            <Badge variant="outline" className={cn("text-[9px]", trade.direction === "LONG" ? "text-[--positive] border-[--positive]/20 bg-[--positive]/10" : "text-[--negative] border-[--negative]/20 bg-[--negative]/10")}>
              {trade.direction}
            </Badge>
          </td>
          <td className="px-3 py-2 text-xs text-muted-foreground">${trade.entry_price?.toFixed(2)}</td>
          <td className="px-3 py-2 text-xs text-muted-foreground">${trade.exit_price?.toFixed(2)}</td>
          <td className={cn("px-3 py-2 text-xs font-medium", trade.return_pct >= 0 ? "text-[--positive]" : "text-[--negative]")}>
            {trade.return_pct >= 0 ? "+" : ""}{trade.return_pct?.toFixed(1)}%
          </td>
          <td className="px-3 py-2 text-xs text-muted-foreground">{trade.regime ?? "—"}</td>
          <td className="px-3 py-2 text-xs">
            <ChevronRight size={12} className={cn("text-muted-foreground transition-transform", open && "rotate-90")} />
          </td>
        </tr>
      </CollapsibleTrigger>
      <CollapsibleContent asChild>
        <tr>
          <td colSpan={8} className="px-3 py-3 bg-card">
            <div className="grid grid-cols-2 gap-4 text-xs">
              {trade.signals && (
                <div>
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/50 mb-1">Signal Scores at Entry</div>
                  <div className="flex flex-wrap gap-3">
                    {Object.entries(trade.signals).map(([name, value]) => (
                      <div key={name}>
                        <span className="text-[9px] uppercase tracking-wider text-muted-foreground/50">{name}</span>
                        <span className={cn("ml-1 font-medium", Number(value) > 0 ? "text-primary" : Number(value) < 0 ? "text-[--negative]" : "text-muted-foreground")}>
                          {Number(value) > 0 ? "+" : ""}{Number(value).toFixed(2)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/50 mb-1">Regime at Entry</div>
                <span className="text-muted-foreground">{trade.regime ?? "Unknown"}</span>
                {trade.vix_level && <span className="ml-2 text-muted-foreground">VIX {trade.vix_level}</span>}
              </div>
            </div>
          </td>
        </tr>
      </CollapsibleContent>
    </Collapsible>
  );
}
```

- [ ] **Step 4: Create NewBacktestDialog**

Create `frontend/src/components/backtest/NewBacktestDialog.tsx`:

```tsx
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";

interface NewBacktestDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (config: { tickers: string[]; start_date: string; end_date: string }) => void;
  isRunning: boolean;
}

const UNIVERSES: Record<string, string> = {
  "LIQUID_10": "AAPL,MSFT,GOOGL,AMZN,JPM,JNJ,XOM,PG,HD,CAT",
  "LIQUID_20": "AAPL,MSFT,GOOGL,AMZN,META,JPM,JNJ,UNH,XOM,PG,HD,CAT,NEE,AMT,LIN,BA,KO,GS,PFE,NVDA",
  "LIQUID_50": "Top 50 liquid stocks across all GICS sectors",
  "Custom": "",
};

export function NewBacktestDialog({ open, onOpenChange, onSubmit, isRunning }: NewBacktestDialogProps) {
  const [universe, setUniverse] = useState("LIQUID_10");
  const [customTickers, setCustomTickers] = useState("");
  const [startDate, setStartDate] = useState("2020-01-01");
  const [endDate, setEndDate] = useState(new Date().toISOString().split("T")[0]);

  const handleSubmit = () => {
    const tickerStr = universe === "Custom" ? customTickers : UNIVERSES[universe];
    const tickers = tickerStr.split(",").map((t) => t.trim().toUpperCase()).filter(Boolean);
    if (tickers.length === 0) return;
    onSubmit({ tickers, start_date: startDate, end_date: endDate });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-card border-border max-w-md">
        <DialogHeader>
          <DialogTitle className="text-sm">New Backtest</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 mt-2">
          <div>
            <label className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">Universe</label>
            <select
              value={universe}
              onChange={(e) => setUniverse(e.target.value)}
              className="mt-1 w-full bg-secondary border border-border rounded-md px-3 py-2 text-xs text-foreground"
            >
              {Object.keys(UNIVERSES).map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
          </div>
          {universe === "Custom" && (
            <div>
              <label className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">Tickers (comma-separated)</label>
              <Input value={customTickers} onChange={(e) => setCustomTickers(e.target.value)} placeholder="AAPL, MSFT, NVDA" className="mt-1 text-xs" />
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">Start Date</label>
              <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="mt-1 text-xs" />
            </div>
            <div>
              <label className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">End Date</label>
              <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="mt-1 text-xs" />
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="secondary" size="sm" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button size="sm" onClick={handleSubmit} disabled={isRunning}>
            {isRunning ? "Running..." : "Run Backtest"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 5: Rewrite BacktestPage**

Replace `frontend/src/pages/BacktestPage.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { RunSelector } from "@/components/backtest/RunSelector";
import { PerformanceTab } from "@/components/backtest/PerformanceTab";
import { TradeDetailRow } from "@/components/backtest/TradeDetailRow";
import { NewBacktestDialog } from "@/components/backtest/NewBacktestDialog";
import { useBacktest } from "@/hooks/useBacktest";

export function BacktestPage() {
  const { isRunning, result, history, refreshHistory, run } = useBacktest();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  useEffect(() => { refreshHistory(); }, [refreshHistory]);

  const handleNewBacktest = (config: { tickers: string[]; start_date: string; end_date: string }) => {
    run(config);
    setDialogOpen(false);
  };

  // Build runs list from history
  const runs = (history ?? []).map((h: any, i: number) => ({
    id: h.id ?? String(i),
    config_summary: h.config_summary ?? `${h.tickers?.length ?? "?"} tickers`,
    sharpe: h.sharpe ?? null,
    pbo: h.pbo ?? null,
    date: h.date ?? "",
  }));

  // Use current result or selected historical run
  const activeResult = result;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-base font-semibold tracking-tight">Backtest Lab</h1>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" className="text-xs">Export CSV</Button>
          <Button size="sm" className="text-xs" onClick={() => setDialogOpen(true)}>New Backtest</Button>
        </div>
      </div>

      {runs.length > 0 && (
        <RunSelector runs={runs} selectedId={selectedRunId} onSelect={setSelectedRunId} />
      )}

      {activeResult && (
        <Tabs defaultValue="performance">
          <TabsList className="bg-secondary border border-border h-8">
            <TabsTrigger value="performance" className="text-xs h-7 data-[state=active]:text-primary">Performance</TabsTrigger>
            <TabsTrigger value="trades" className="text-xs h-7 data-[state=active]:text-primary">Trade Log</TabsTrigger>
            <TabsTrigger value="regime" className="text-xs h-7 data-[state=active]:text-primary">Regime Timeline</TabsTrigger>
          </TabsList>

          <TabsContent value="performance">
            <PerformanceTab
              sharpe={activeResult.sharpe}
              totalReturn={activeResult.equity_curve?.length ? ((activeResult.equity_curve[activeResult.equity_curve.length - 1].equity / activeResult.equity_curve[0].equity - 1) * 100) : null}
              maxDrawdown={activeResult.max_drawdown_pct}
              alpha={null}
              equityCurve={activeResult.equity_curve ?? []}
            />
          </TabsContent>

          <TabsContent value="trades">
            <div className="border border-border rounded-lg overflow-hidden">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-border bg-secondary">
                    <th className="px-3 py-2 text-left text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Date</th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Ticker</th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Dir</th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Entry</th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Exit</th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Return</th>
                    <th className="px-3 py-2 text-left text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Regime</th>
                    <th className="px-3 py-2 w-6"></th>
                  </tr>
                </thead>
                <tbody>
                  {(activeResult.trade_log ?? []).map((trade: any, i: number) => (
                    <TradeDetailRow key={i} trade={trade} />
                  ))}
                </tbody>
              </table>
              {(!activeResult.trade_log || activeResult.trade_log.length === 0) && (
                <div className="py-8 text-center text-xs text-muted-foreground">No trades in this backtest run.</div>
              )}
            </div>
          </TabsContent>

          <TabsContent value="regime">
            <div className="py-12 text-center text-xs text-muted-foreground">
              Regime timeline visualization — coming in Phase B.
            </div>
          </TabsContent>
        </Tabs>
      )}

      {!activeResult && !isRunning && (
        <div className="py-20 text-center">
          <p className="text-sm text-muted-foreground mb-4">No backtest results loaded. Run a new backtest or select a past run.</p>
          <Button size="sm" onClick={() => setDialogOpen(true)}>New Backtest</Button>
        </div>
      )}

      {isRunning && (
        <div className="py-12 text-center text-sm text-muted-foreground">
          Running backtest...
        </div>
      )}

      <NewBacktestDialog open={dialogOpen} onOpenChange={setDialogOpen} onSubmit={handleNewBacktest} isRunning={isRunning} />
    </div>
  );
}
```

- [ ] **Step 6: Delete old backtest components if unused**

Check if `BacktestConfigPanel.tsx` and `BacktestMetricsPanel.tsx` are still imported anywhere. If not:

```bash
rm frontend/src/components/backtest/BacktestConfigPanel.tsx frontend/src/components/backtest/BacktestMetricsPanel.tsx
```

- [ ] **Step 7: Verify build**

```bash
cd frontend && npm run build
```

- [ ] **Step 8: Commit**

```bash
git add -A frontend/src/
git commit -m "feat(frontend): rebuild backtest page as structured explorer"
```

---

### Task 8: Paper Trading Page — Re-skin

**Files:**
- Modify: `frontend/src/pages/PaperTradingPage.tsx`

- [ ] **Step 1: Re-skin PaperTradingPage**

Read the current file, then update to:
- Replace all `style={{ ... }}` inline styles with Tailwind classes using the new palette
- Replace `<Card>` imports with shadcn Card
- Replace any hand-built buttons with shadcn `<Button>`
- Use shadcn `<Badge>` for LONG/SHORT direction badges
- Use the new page layout pattern: `<div className="p-6 max-w-6xl mx-auto space-y-4">`
- Page header: title left, "Add Position" button right
- Summary cards: 4-column grid with the MetricCard pattern from PerformanceTab
- Tables: match the Trade Log table styling (header bg-secondary, 10px uppercase headers, 12px body text)

The data fetching hooks (`usePaperTrading`) stay unchanged — only the presentation changes.

- [ ] **Step 2: Verify build**

```bash
cd frontend && npm run build
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/PaperTradingPage.tsx
git commit -m "feat(frontend): re-skin paper trading page with new design system"
```

---

### Task 9: Stock Deep Dive — Analysis Accordion

**Files:**
- Create: `frontend/src/components/deepdive/AnalysisAccordion.tsx`
- Modify: `frontend/src/pages/StockDeepDivePage.tsx`

- [ ] **Step 1: Create AnalysisAccordion**

Create `frontend/src/components/deepdive/AnalysisAccordion.tsx`:

```tsx
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { AgentReportTabs } from "@/components/analysis/AgentReportTabs";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AnalysisResult, HistoryEntry } from "@/api/types";

interface AnalysisAccordionProps {
  entries: HistoryEntry[];
  getFullResult: (analysisId: string) => Promise<AnalysisResult | null>;
}

function AccordionRow({ entry, getFullResult }: { entry: HistoryEntry; getFullResult: (id: string) => Promise<AnalysisResult | null> }) {
  const [open, setOpen] = useState(false);
  const [fullResult, setFullResult] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);

  const handleToggle = async (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (nextOpen && !fullResult && !loading) {
      setLoading(true);
      const result = await getFullResult(entry.analysis_id);
      setFullResult(result);
      setLoading(false);
    }
  };

  const verdictColor = entry.verdict === "BUY" ? "text-[--positive] border-[--positive]/20 bg-[--positive]/10" :
                        entry.verdict === "SELL" ? "text-[--negative] border-[--negative]/20 bg-[--negative]/10" :
                        "text-[--warning] border-[--warning]/20 bg-[--warning]/10";

  const date = new Date(entry.run_at * 1000).toISOString().split("T")[0];

  return (
    <Collapsible open={open} onOpenChange={handleToggle}>
      <CollapsibleTrigger className="w-full">
        <div className="flex items-center justify-between px-4 py-3 hover:bg-secondary/50 transition-colors cursor-pointer">
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted-foreground">{date}</span>
            <Badge variant="outline" className={cn("text-[9px]", verdictColor)}>{entry.verdict}</Badge>
            <span className="text-xs text-primary">Conviction: {entry.conviction}</span>
            {entry.composite_score != null && (
              <span className="text-xs text-muted-foreground">Score: {entry.composite_score.toFixed(2)}</span>
            )}
          </div>
          <ChevronRight size={12} className={cn("text-muted-foreground transition-transform", open && "rotate-90")} />
        </div>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="px-4 pb-4 border-t border-border">
          {loading && <p className="text-xs text-muted-foreground py-4">Loading full analysis...</p>}
          {fullResult && (
            <AgentReportTabs
              synthesis={fullResult.synthesis}
              agentReports={fullResult.agent_reports}
              tradeParams={fullResult.structured_verdict}
            />
          )}
          {!loading && !fullResult && (
            <p className="text-xs text-muted-foreground py-4">Analysis data unavailable.</p>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

export function AnalysisAccordion({ entries, getFullResult }: AnalysisAccordionProps) {
  if (!entries.length) {
    return <p className="text-xs text-muted-foreground py-4">No past analyses for this ticker.</p>;
  }

  return (
    <div className="border border-border rounded-lg overflow-hidden divide-y divide-border">
      {entries.map((entry) => (
        <AccordionRow key={entry.analysis_id} entry={entry} getFullResult={getFullResult} />
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Update StockDeepDivePage**

Read the current `StockDeepDivePage.tsx`, then update to:
- Use the new page layout: `<div className="p-6 max-w-6xl mx-auto space-y-4">`
- Page header: ticker (18px bold) + company name + verdict badge | "Re-analyze" button
- Price hero: large price + day change + stat grid (3x2 metric cards)
- Replace existing tabs/content with shadcn Tabs: "Analysis History" | "Trade History" | "Fundamentals"
- Analysis History tab uses the new `<AnalysisAccordion>` component
- Wire `getFullResult` to `api.getAnalysis(analysisId)` or equivalent endpoint
- Trade History and Fundamentals tabs can show existing content or placeholder text ("Coming in Phase B")
- Re-skin all colors/styles to use the new Tailwind classes

- [ ] **Step 3: Verify build**

```bash
cd frontend && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add -A frontend/src/
git commit -m "feat(frontend): stock deep dive with analysis accordion and agent report tabs"
```

---

### Task 10: Final Cleanup and Verification

**Files:**
- Various — cleanup dead imports, unused files, verify complete build

- [ ] **Step 1: Find and fix dead imports**

```bash
cd frontend && npm run build 2>&1 | head -50
```

Fix any TypeScript errors from stale imports referencing deleted files (old Card, Badge, TopNav, Sidebar, removed pages).

- [ ] **Step 2: Check for remaining old CSS variable references**

```bash
cd frontend && grep -rn "var(--bg-\|var(--text-\|var(--accent-\|var(--border-subtle)" src/ --include="*.tsx" --include="*.ts" | head -20
```

Replace any remaining old variable references with the new Tailwind classes or shadcn variables.

- [ ] **Step 3: Delete empty directories**

```bash
rmdir frontend/src/components/common 2>/dev/null || true
rmdir frontend/src/components/watchlist 2>/dev/null || true
```

- [ ] **Step 4: Full build verification**

```bash
cd frontend && npm run build
```

Expected: Clean build, zero errors, zero warnings about missing modules.

- [ ] **Step 5: Visual smoke test**

```bash
cd frontend && npm run dev
```

Visit each route and verify:
- http://localhost:5173/analysis — sidebar nav, ticker input, run analysis works
- http://localhost:5173/backtest — new backtest dialog, past runs, trade log
- http://localhost:5173/paper-trading — positions table, equity curve
- http://localhost:5173/stock/AAPL — deep dive with analysis accordion
- Settings drawer opens from gear icon in sidebar
- All pages use zinc dark theme with cyan accents
- No old blue (#3b82f6) colors remaining
- No old purple (#818cf8) colors remaining

- [ ] **Step 6: Commit**

```bash
git add -A frontend/
git commit -m "chore(frontend): cleanup dead imports and stale references"
```
