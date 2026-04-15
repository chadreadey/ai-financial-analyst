# Frontend Overhaul Design Spec

**Date:** 2026-04-12
**Scope:** Full Phase A — design system, page cleanup, backtest rebuild, analysis + deep dive polish
**Reference:** Koyfin (data density, equity research aesthetic)

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Color palette | Neutral Zinc | Modern, minimal, no blue tint. Linear/Vercel aesthetic. |
| Primary accent | Cyan (#06b6d4) | Technical HUD feel, high contrast on dark zinc, distinct from generic fintech blue |
| Navigation | Labeled sidebar with grouped sections | Scales for future pages (Dashboard, Trade Review, Opportunity Radar). Koyfin pattern. |
| Settings | Modal/drawer via gear icon in sidebar footer | Rarely changed mid-session, keeps analysis page focused |
| Component library | shadcn/ui (Radix + Tailwind) | Already have Radix. Zinc dark theme matches palette. Fastest path to polished components. |
| Design reference | Koyfin | Dark theme, data density, equity research professional quality |
| Target | Desktop only | No mobile for now. Optimize for wide screens with dense financial data. |

---

## 1. Design System Foundation

### Color Palette (CSS variables + Tailwind theme)

**Backgrounds:**
- `--background`: #09090b (page base)
- `--sidebar`: #0f0f11 (sidebar surface)
- `--card`: #18181b (card / elevated surface)
- `--card-elevated`: #141416 (nested surface inside cards)

**Borders:**
- `--border`: #27272a (default)
- `--border-hover`: #3f3f46 (hover / focus)

**Text:**
- `--foreground`: #fafafa (primary)
- `--muted-foreground`: #a1a1aa (secondary)
- `--muted`: #71717a (labels, placeholders)
- `--disabled`: #3f3f46 (disabled text, faintest)

**Accent:**
- `--accent`: #06b6d4 (cyan — interactive elements, active states)
- `--accent-hover`: #0891b2 (cyan hover)
- `--accent-dim`: rgba(6,182,212,0.1) (cyan background tint)

**Semantic:**
- `--positive`: #22c55e (green — gains, BUY, success)
- `--negative`: #ef4444 (red — losses, SELL, errors)
- `--warning`: #f59e0b (amber — HOLD, caution, alerts)

### Typography

- **Font:** Inter (already loaded) — 400, 500, 600 weights
- **Scale:**
  - 10px — badges, uppercase labels (letter-spacing: +0.8px)
  - 11px — captions, secondary labels, table metadata
  - 12px — body small, table cells, nav items
  - 13px — body default, input text
  - 14px — body large, card values
  - 16px — page titles
  - 18-20px — section headers, ticker names
  - 24-28px — hero numbers (portfolio value, stock price)
- **Letter-spacing:** -0.3px on headings 16px+, +1px on uppercase labels

### Tailwind Config

Move all CSS variables into `extend.colors` using shadcn's naming convention:

```
colors: {
  background: "hsl(var(--background))",
  foreground: "hsl(var(--foreground))",
  card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
  muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
  accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
  destructive: { DEFAULT: "hsl(var(--destructive))", foreground: ... },
  positive: "hsl(var(--positive))",
  warning: "hsl(var(--warning))",
  border: "hsl(var(--border))",
}
```

### shadcn/ui Setup

- Initialize: `npx shadcn@latest init` — zinc theme, dark mode, New York style
- Override generated CSS variables with the palette above
- Install components: Button, Input, Select, Table, Tabs, Dialog, Badge, Card, Separator, Tooltip, ScrollArea, DropdownMenu, Sheet (for settings drawer), Collapsible (for accordion rows)

---

## 2. Navigation — Labeled Sidebar

### Structure

```
┌─────────────────────┐
│ [icon] ATIS          │
│                      │
│ RESEARCH             │  ← section label (10px, uppercase, #3f3f46)
│ [icon] Analysis      │  ← active: cyan bg tint + cyan text
│ [icon] Backtest Lab  │
│                      │
│ TRADING              │
│ [icon] Paper Trading │
│                      │
│ ─────────────────── │  ← separator
│ [regime badge]       │  ← BULLISH VIX 18.3 (green bg tint)
│ [gear] Settings      │  ← opens Sheet drawer
└─────────────────────┘
```

### Specs

- Width: 192px fixed
- Background: #0f0f11
- Border-right: 1px solid #27272a
- Brand: 24px icon (cyan tint bg) + "ATIS" 14px weight-700
- Section labels: 10px uppercase, #3f3f46, letter-spacing 1.2px
- Nav items: 12px, #a1a1aa default, padding 7px 10px, border-radius 6px
- Active state: background rgba(6,182,212,0.08), color #06b6d4, icon bg rgba(6,182,212,0.15)
- Regime badge: bottom of sidebar, green/amber/red bg tint depending on regime level
- Settings button: #18181b bg, #27272a border, gear icon + "Settings" text, opens Sheet component

### Settings Drawer

- Opens from the right as a shadcn Sheet
- Contains everything currently in the Analysis page sidebar:
  - LLM provider selector
  - API key input
  - Data source toggles (Yahoo, Tavily, Tiingo, FMP)
  - Context budget sliders (agent chars, output tokens, synthesis limits)
- Persists settings to localStorage (same as current behavior)
- Accessible from any page via the sidebar gear icon

---

## 3. Pages

### 3.1 Analysis Page (`/analysis`)

The flagship single-stock analysis experience.

**Layout:**
- Page header: "Analysis" title (left) + ticker input with inline "Analyze" button (right)
- Input: shadcn Input, 280px wide, cyan focus ring
- When no result: centered empty state with large input prompt
- When result loaded:

**Result view:**
- **Header row:** Ticker (20px bold) + company name (13px muted) | BUY/SELL/HOLD badge + conviction badge
- **Price row:** Current price (24px) + day change (positive/negative colored)
- **Signal cards:** 4-column grid of metric cards
  - Weighted Score, OBV Signal, ERM Score, ATR Regime
  - Each card: #18181b bg, 10px uppercase label, 14px colored value
- **Agent tabs:** shadcn Tabs component
  - Tabs: Synthesis, DCF, Risk, Earnings, Competitive, Pattern, Macro
  - Active tab: cyan underline
  - Content: markdown-rendered agent report in a Card
  - Trade parameters bar below synthesis: Entry, Target, Stop, Horizon as muted badges

**Progress state:**
- While analysis runs: progress stream component showing step-by-step agent status
- Each agent gets a line: `[icon] Earnings Agent ● Running...` → `[icon] Earnings Agent ✓ Complete`

**Past analyses:**
- Below the main result, collapsible section: "Past Analyses"
- Shows previous runs for this ticker if available
- Click to load that analysis result into the main view

### 3.2 Backtest Explorer (`/backtest`)

Replaces the broken natural language backtest. Structured investigation tool.

**Layout:**
- Page header: "Backtest Lab" title | "Export CSV" outline button + "New Backtest" primary button
- Run selector: Card at top showing currently selected run config as text + Sharpe/PBO badges
  - Dropdown or side list to switch between past runs

**Tabs:**
1. **Performance** (default)
   - Metric cards (4-column grid): Sharpe, Total Return, Max Drawdown, Alpha
   - Equity curve chart (recharts AreaChart, cyan gradient fill, #0f0f11 bg)
   - Benchmark overlay line in muted gray

2. **Trade Log**
   - shadcn Table: Date, Ticker, Direction, Entry, Exit, Return, Regime, Signals
   - Sortable and filterable (column header clicks)
   - Ticker column is clickable → navigates to /stock/:ticker
   - **Row click expands** to show:
     - Signal scores at entry (OBV, ERM, SUE, dispersion, inst flow, ATR)
     - Regime state at entry (VIX level, SPY vs SMA, turbulence score, macro overlay)
     - Entry reason (why this stock ranked high enough)
     - Exit trigger (stop loss, rebalance, signal degradation)

3. **Regime Timeline**
   - Horizontal timeline spanning backtest period
   - Color-coded segments: green (bullish), amber (cautious), red (risk-off)
   - Trade entries/exits overlaid as markers on the timeline
   - Click a regime transition → popover showing VIX level, turbulence score, macro state at that date

4. **CPCV Results** (if run with --cpcv flag)
   - OOS Sharpe distribution histogram (recharts BarChart)
   - PBO badge (large, prominent), DSR badge
   - Scatter plot: IS Sharpe (x) vs OOS Sharpe (y) per combination

**"New Backtest" flow:**
- Dialog (shadcn Dialog) with structured form fields:
  - Universe selector (dropdown: LIQUID_10/20/50/100/200, SP500)
  - Date range (start + end date inputs)
  - Rebalance frequency (monthly/weekly radio)
  - Regime filter toggle
  - Enable CPCV toggle + group count
  - Signal overlay toggles (earnings, institutional flow, sentiment)
- No natural language parsing. Structured inputs only.

### 3.3 Paper Trading (`/paper-trading`)

Existing functionality, redesigned with new component library.

**Layout:**
- Page header: "Paper Trading" title | "Add Position" primary button
- Summary cards (4-column grid): Portfolio Value, Total P&L ($ + %), Open Positions count, Win Rate (with trade count subtitle)
- Equity curve chart (recharts, same style as backtest)
- Tabs: Open Positions | Closed Trades
  - shadcn Table for each
  - Open: Ticker, Direction, Entry, Current, P&L, Days Held, Conviction
  - Closed: Ticker, Direction, Entry, Exit, P&L, Days Held, Conviction, Exit Reason
  - Ticker column clickable → /stock/:ticker

**"Add Position" flow:**
- Dialog with: Ticker input, Entry Price, Direction (BUY/SELL), Conviction (optional)

### 3.4 Stock Deep Dive (`/stock/:ticker`)

Reached by clicking any ticker anywhere in the app.

**Layout:**
- Page header: Ticker (18px bold) + company name + verdict badge | "View Analysis" outline + "Re-analyze" primary buttons
- **Price hero:** Large price (28px), day change with color, inline with stat grid
- **Stat grid:** 3x2 grid of small metric cards
  - 52W High, 52W Low, Mkt Cap, P/E (FWD), ERM Score, OBV Signal
- **Price chart:** lightweight-charts candlestick with recommendation markers (keep existing chart component, restyle colors to match palette)
- **Tabs:** Analysis History | Trade History | Fundamentals

**Analysis History tab (primary):**
- Accordion list of past analysis runs, sorted newest first
- **Collapsed row:** Date | Verdict badge | Conviction | Score | one-line key driver
- **Expanded row (click to toggle):**
  - Agent tabs: Synthesis, DCF, Risk, Earnings, Competitive, Pattern, Macro
  - Each tab shows the full agent report from that analysis run (markdown rendered)
  - Signal scores bar at bottom: OBV, ERM, SUE, Dispersion, Inst Flow, ATR values at that point in time
  - Trade parameters: Entry, Target, Stop, Horizon badges

**Trade History tab:**
- Table of trades involving this ticker from paper trading
- Same columns as Paper Trading closed trades table

**Fundamentals tab:**
- Key financial data from FMP/WRDS (income statement, balance sheet highlights)
- Display whatever is available in cached_fundamentals

---

## 4. Pages to Remove

Remove from the router and sidebar nav:

- **WatchlistPage** (`/portfolio`) — ugly placeholder, will be replaced by Opportunity Radar in Phase C
- **NewsPage** (`/news`) — ugly placeholder, news will be integrated into Deep Dive and Dashboard alerts
- **IndustryPage** (`/industry`) — ugly placeholder, sector view will be part of Opportunity Radar

Delete the page files and their imports from App.tsx. Keep the components if any are reusable (WatchlistCard sparklines may be useful later).

---

## 5. Data Flow

No changes to the backend API. All data fetching stays the same:

- **Analysis:** POST `/api/analysis/run` with streaming progress → GET `/api/analysis/:id` for results
- **Backtest:** POST `/api/backtest/run` → GET `/api/backtest/history` for past runs
- **Paper Trading:** CRUD via `/api/paper-trading/` endpoints
- **Deep Dive:** GET `/api/watchlist/summary/:ticker` + GET `/api/recommendations/:ticker`

The frontend refactor is purely presentational. API client layer (`src/api/`) and custom hooks stay intact — they just feed into restyled components.

---

## 6. Chart Styling Updates

Both chart libraries get restyled to match the palette:

**lightweight-charts (PriceChart):**
- Background: #0f0f11
- Grid lines: #1a1a1e
- Candle up: #22c55e, candle down: #ef4444
- Crosshair: #3f3f46
- Text: #71717a

**recharts (EquityCurveChart, SparklineChart):**
- Background: transparent (inside #0f0f11 container)
- Area fill: cyan gradient (rgba(6,182,212,0.3) → rgba(6,182,212,0.02))
- Stroke: #06b6d4
- Axis text: #71717a, 10px
- Grid: #1a1a1e
- Negative area fill: red gradient (rgba(239,68,68,0.3) → transparent)

---

## 7. What This Does NOT Include

- No new backend endpoints or API changes
- No Dashboard home page (Phase B)
- No Trade Review page (Phase B)
- No Opportunity Radar (Phase C)
- No real-time updates / WebSocket (Phase C)
- No auth or multi-user support
- No mobile responsiveness
