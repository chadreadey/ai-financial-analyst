import type { AlpacaOrder } from "../../api/types";

interface Props {
  orders: AlpacaOrder[];
}

const statusColor: Record<string, string> = {
  filled: "text-[--positive]",
  partially_filled: "text-amber-500",
  canceled: "text-muted-foreground",
  rejected: "text-[--negative]",
  accepted: "text-primary",
  new: "text-primary",
};

export function OrderHistoryTable({ orders }: Props) {
  if (orders.length === 0) {
    return <div className="p-4 text-xs text-muted-foreground text-center">No orders yet</div>;
  }

  return (
    <div>
      <div className="px-4 py-2.5 border-b">
        <span className="text-xs font-medium text-muted-foreground">Alpaca Orders</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b text-muted-foreground">
              <th className="px-4 py-2 text-left font-medium">Symbol</th>
              <th className="px-4 py-2 text-left font-medium">Side</th>
              <th className="px-4 py-2 text-right font-medium">Qty</th>
              <th className="px-4 py-2 text-right font-medium">Fill Price</th>
              <th className="px-4 py-2 text-left font-medium">Status</th>
              <th className="px-4 py-2 text-left font-medium">Submitted</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.order_id} className="border-b last:border-0 hover:bg-muted/50">
                <td className="px-4 py-2 font-medium text-foreground">{o.symbol}</td>
                <td className="px-4 py-2">
                  <span className={o.side === "buy" ? "text-[--positive]" : "text-[--negative]"}>
                    {o.side.toUpperCase()}
                  </span>
                </td>
                <td className="px-4 py-2 text-right">{o.qty}</td>
                <td className="px-4 py-2 text-right">
                  {o.filled_avg_price != null ? `$${o.filled_avg_price.toFixed(2)}` : "\u2014"}
                </td>
                <td className={`px-4 py-2 ${statusColor[o.status] || "text-foreground"}`}>
                  {o.status}
                </td>
                <td className="px-4 py-2 text-muted-foreground">
                  {o.submitted_at ? new Date(o.submitted_at).toLocaleDateString() : "\u2014"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
