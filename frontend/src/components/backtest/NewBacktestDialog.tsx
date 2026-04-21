import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import type { BacktestConfig, ModalRunRequest } from "../../api/types";

export type NewBacktestSubmission =
  | { kind: "legacy"; config: BacktestConfig }
  | { kind: "modal"; config: ModalRunRequest };

interface NewBacktestDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmit: (submission: NewBacktestSubmission) => void;
  isRunning: boolean;
}

// Inline universe strings for the legacy/tickers flow. For Modal, we pass
// `universe` through to the backend so the server-side `quant.universe`
// lookup stays the single source of truth and we don't drift.
const UNIVERSES: Record<string, string> = {
  LIQUID_10: "AAPL,MSFT,GOOGL,AMZN,JPM,JNJ,XOM,PG,HD,CAT",
  LIQUID_20:
    "AAPL,MSFT,GOOGL,AMZN,META,JPM,JNJ,UNH,XOM,PG,HD,CAT,NEE,AMT,LIN,BA,KO,GS,PFE,NVDA",
  Custom: "",
};

const MODAL_UNIVERSES: Array<{ key: string; label: string }> = [
  { key: "liquid_10", label: "Liquid 10" },
  { key: "liquid_20", label: "Liquid 20" },
  { key: "liquid_50", label: "Liquid 50" },
];

export function NewBacktestDialog({
  open,
  onOpenChange,
  onSubmit,
  isRunning,
}: NewBacktestDialogProps) {
  const [mode, setMode] = useState<"legacy" | "modal">("modal");

  // Shared state
  const [startDate, setStartDate] = useState("2020-01-01");
  const [endDate, setEndDate] = useState(new Date().toISOString().split("T")[0]);

  // Legacy-only
  const [universe, setUniverse] = useState("LIQUID_10");
  const [customTickers, setCustomTickers] = useState("");

  // Modal-only
  const [modalUniverse, setModalUniverse] = useState("liquid_10");
  const [nGroups, setNGroups] = useState(16);
  const [nTestGroups, setNTestGroups] = useState(8);
  const [maxCombos, setMaxCombos] = useState<number | "">(50);
  const [purgeMonths, setPurgeMonths] = useState(1);
  const [embargoMonths, setEmbargoMonths] = useState(1);
  const [seed, setSeed] = useState(42);

  const handleSubmit = () => {
    if (mode === "legacy") {
      const tickerStr = universe === "Custom" ? customTickers : UNIVERSES[universe];
      const tickers = tickerStr.split(",").map((t) => t.trim().toUpperCase()).filter(Boolean);
      if (tickers.length === 0) return;
      onSubmit({
        kind: "legacy",
        config: { tickers, start_date: startDate, end_date: endDate },
      });
    } else {
      onSubmit({
        kind: "modal",
        config: {
          universe: modalUniverse,
          start_date: startDate,
          end_date: endDate,
          n_groups: nGroups,
          n_test_groups: nTestGroups,
          purge_months: purgeMonths,
          embargo_months: embargoMonths,
          max_combos: maxCombos === "" ? undefined : Number(maxCombos),
          seed,
        },
      });
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-card border-border max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-sm flex items-center gap-2">
            New Backtest
            {mode === "modal" && (
              <Badge variant="outline" className="text-primary border-primary/20 bg-primary/10 text-[9px]">
                Modal CPCV
              </Badge>
            )}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 mt-2">
          {/* Mode toggle */}
          <div className="flex items-center gap-1 bg-secondary/50 rounded-md p-0.5 w-fit">
            <button
              type="button"
              onClick={() => setMode("modal")}
              className={
                "px-3 py-1 rounded text-[11px] font-medium transition-colors " +
                (mode === "modal"
                  ? "bg-primary/15 text-primary"
                  : "text-muted-foreground hover:text-foreground")
              }
            >
              Run on Modal (CPCV)
            </button>
            <button
              type="button"
              onClick={() => setMode("legacy")}
              className={
                "px-3 py-1 rounded text-[11px] font-medium transition-colors " +
                (mode === "legacy"
                  ? "bg-primary/15 text-primary"
                  : "text-muted-foreground hover:text-foreground")
              }
            >
              Legacy (in-process)
            </button>
          </div>

          {/* Universe */}
          {mode === "legacy" ? (
            <>
              <div>
                <label className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">
                  Universe
                </label>
                <select
                  value={universe}
                  onChange={(e) => setUniverse(e.target.value)}
                  className="mt-1 w-full bg-secondary border border-border rounded-md px-3 py-2 text-xs text-foreground"
                >
                  {Object.keys(UNIVERSES).map((k) => (
                    <option key={k} value={k}>
                      {k}
                    </option>
                  ))}
                </select>
              </div>
              {universe === "Custom" && (
                <div>
                  <label className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">
                    Tickers (comma-separated)
                  </label>
                  <Input
                    value={customTickers}
                    onChange={(e) => setCustomTickers(e.target.value)}
                    placeholder="AAPL, MSFT, NVDA"
                    className="mt-1 text-xs"
                  />
                </div>
              )}
            </>
          ) : (
            <div>
              <label className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">
                Universe
              </label>
              <select
                value={modalUniverse}
                onChange={(e) => setModalUniverse(e.target.value)}
                className="mt-1 w-full bg-secondary border border-border rounded-md px-3 py-2 text-xs text-foreground"
              >
                {MODAL_UNIVERSES.map((u) => (
                  <option key={u.key} value={u.key}>
                    {u.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Dates */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">
                Start Date
              </label>
              <Input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="mt-1 text-xs"
              />
            </div>
            <div>
              <label className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">
                End Date
              </label>
              <Input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="mt-1 text-xs"
              />
            </div>
          </div>

          {/* Modal-only CPCV knobs */}
          {mode === "modal" && (
            <div className="space-y-3 rounded-md border border-border bg-secondary/20 p-3">
              <div className="text-[10px] font-semibold uppercase tracking-[1px] text-muted-foreground/50">
                CPCV Parameters
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="text-[9px] uppercase tracking-wider text-muted-foreground/50">
                    Groups (N)
                  </label>
                  <Input
                    type="number"
                    min={2}
                    max={24}
                    value={nGroups}
                    onChange={(e) => setNGroups(Number(e.target.value))}
                    className="mt-1 text-xs"
                  />
                </div>
                <div>
                  <label className="text-[9px] uppercase tracking-wider text-muted-foreground/50">
                    Test Groups (k)
                  </label>
                  <Input
                    type="number"
                    min={1}
                    max={12}
                    value={nTestGroups}
                    onChange={(e) => setNTestGroups(Number(e.target.value))}
                    className="mt-1 text-xs"
                  />
                </div>
                <div>
                  <label className="text-[9px] uppercase tracking-wider text-muted-foreground/50">
                    Max Combos
                  </label>
                  <Input
                    type="number"
                    min={1}
                    value={maxCombos}
                    onChange={(e) => {
                      const v = e.target.value;
                      setMaxCombos(v === "" ? "" : Number(v));
                    }}
                    placeholder="All"
                    className="mt-1 text-xs"
                  />
                </div>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="text-[9px] uppercase tracking-wider text-muted-foreground/50">
                    Purge (months)
                  </label>
                  <Input
                    type="number"
                    min={0}
                    max={12}
                    value={purgeMonths}
                    onChange={(e) => setPurgeMonths(Number(e.target.value))}
                    className="mt-1 text-xs"
                  />
                </div>
                <div>
                  <label className="text-[9px] uppercase tracking-wider text-muted-foreground/50">
                    Embargo (months)
                  </label>
                  <Input
                    type="number"
                    min={0}
                    max={12}
                    value={embargoMonths}
                    onChange={(e) => setEmbargoMonths(Number(e.target.value))}
                    className="mt-1 text-xs"
                  />
                </div>
                <div>
                  <label className="text-[9px] uppercase tracking-wider text-muted-foreground/50">
                    Seed
                  </label>
                  <Input
                    type="number"
                    value={seed}
                    onChange={(e) => setSeed(Number(e.target.value))}
                    className="mt-1 text-xs"
                  />
                </div>
              </div>
              <p className="text-[10px] text-muted-foreground/70 leading-relaxed">
                With C(N, k) combinations, large values fan out across many Modal workers. Use
                <span className="text-foreground"> Max Combos</span> to cap fan-out while iterating.
              </p>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="secondary" size="sm" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button size="sm" onClick={handleSubmit} disabled={isRunning}>
            {isRunning ? "Dispatching..." : mode === "modal" ? "Queue on Modal" : "Run Backtest"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
