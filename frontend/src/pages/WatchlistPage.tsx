import { useState } from "react";
import { useWatchlist } from "../hooks/useWatchlist";
import { WatchlistCard } from "../components/watchlist/WatchlistCard";
import { Card } from "../components/common/Card";

export function WatchlistPage() {
  const { entries, isLoading, error, add, remove } = useWatchlist();
  const [newTicker, setNewTicker] = useState("");

  const handleAdd = () => {
    if (newTicker.trim()) {
      add(newTicker.trim());
      setNewTicker("");
    }
  };

  const inputStyle = {
    background: "var(--bg-primary)",
    border: "1px solid var(--border)",
    color: "var(--text-primary)",
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
          Watchlist
        </h1>
        <div className="flex gap-2">
          <input
            value={newTicker}
            onChange={(e) => setNewTicker(e.target.value.toUpperCase())}
            onKeyDown={(e) => e.key === "Enter" && handleAdd()}
            placeholder="Add ticker..."
            className="rounded px-3 py-1.5 text-sm w-28"
            style={inputStyle}
          />
          <button
            onClick={handleAdd}
            className="px-3 py-1.5 rounded text-sm font-medium"
            style={{ background: "var(--accent-blue)", color: "white" }}
          >
            Add
          </button>
        </div>
      </div>

      {error && (
        <div className="text-sm" style={{ color: "var(--accent-red)" }}>{error}</div>
      )}

      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="rounded-lg h-40 animate-pulse"
              style={{ background: "var(--bg-card)" }}
            />
          ))}
        </div>
      ) : entries.length === 0 ? (
        <Card>
          <p className="text-center py-8" style={{ color: "var(--text-muted)" }}>
            Your watchlist is empty. Add a ticker to get started.
          </p>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {entries.map((e) => (
            <div key={e.ticker} className="relative group">
              <WatchlistCard entry={e} />
              <button
                onClick={() => remove(e.ticker)}
                className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity text-xs px-2 py-1 rounded"
                style={{ background: "var(--bg-hover)", color: "var(--accent-red)" }}
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
