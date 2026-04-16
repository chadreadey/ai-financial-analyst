import { Card } from "@/components/ui/card";
import type { AlpacaAccount } from "../../api/types";

interface Props {
  account: AlpacaAccount | null;
}

function AccountStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] font-medium uppercase tracking-[0.8px] text-muted-foreground">
        {label}
      </div>
      <div className="text-sm font-semibold mt-0.5 text-foreground">{value}</div>
    </div>
  );
}

export function AccountPanel({ account }: Props) {
  if (!account || account.error) {
    return (
      <Card className="p-4">
        <div className="text-xs text-muted-foreground">
          {account?.error || "Alpaca account not connected"}
        </div>
      </Card>
    );
  }

  const fmt = (n: number) =>
    n.toLocaleString("en-US", { style: "currency", currency: "USD" });

  return (
    <Card className="p-4">
      <div className="text-xs font-medium text-muted-foreground mb-3">Alpaca Paper Account</div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <AccountStat label="Equity" value={fmt(account.equity)} />
        <AccountStat label="Cash" value={fmt(account.cash)} />
        <AccountStat label="Buying Power" value={fmt(account.buying_power)} />
        <AccountStat label="Portfolio Value" value={fmt(account.portfolio_value)} />
      </div>
    </Card>
  );
}
