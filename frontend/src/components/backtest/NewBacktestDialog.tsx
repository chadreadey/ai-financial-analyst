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
  LIQUID_10: "AAPL,MSFT,GOOGL,AMZN,JPM,JNJ,XOM,PG,HD,CAT",
  LIQUID_20:
    "AAPL,MSFT,GOOGL,AMZN,META,JPM,JNJ,UNH,XOM,PG,HD,CAT,NEE,AMT,LIN,BA,KO,GS,PFE,NVDA",
  Custom: "",
};

export function NewBacktestDialog({
  open,
  onOpenChange,
  onSubmit,
  isRunning,
}: NewBacktestDialogProps) {
  const [universe, setUniverse] = useState("LIQUID_10");
  const [customTickers, setCustomTickers] = useState("");
  const [startDate, setStartDate] = useState("2020-01-01");
  const [endDate, setEndDate] = useState(new Date().toISOString().split("T")[0]);

  const handleSubmit = () => {
    const tickerStr = universe === "Custom" ? customTickers : UNIVERSES[universe];
    const tickers = tickerStr
      .split(",")
      .map((t) => t.trim().toUpperCase())
      .filter(Boolean);
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
        </div>
        <DialogFooter>
          <Button variant="secondary" size="sm" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button size="sm" onClick={handleSubmit} disabled={isRunning}>
            {isRunning ? "Running..." : "Run Backtest"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
