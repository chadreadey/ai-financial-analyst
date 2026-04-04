import { useState, useEffect } from "react";
import { Card } from "../components/common/Card";
import { Badge } from "../components/common/Badge";
import { api } from "../api/client";
import type { NewsItem } from "../api/types";
import { ExternalLink } from "lucide-react";

export function NewsPage() {
  const [items, setItems] = useState<NewsItem[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);

  const fetchNews = (ticker?: string) => {
    setLoading(true);
    api.getNews({ ticker, limit: 15 })
      .then((d) => setItems(d.items))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchNews(); }, []);

  const handleSearch = () => {
    if (search.trim()) fetchNews(search.trim().toUpperCase());
    else fetchNews();
  };

  const inputStyle = {
    background: "var(--bg-primary)",
    border: "1px solid var(--border)",
    color: "var(--text-primary)",
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>News</h1>
        <div className="flex gap-2">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            placeholder="Filter by ticker..."
            className="rounded px-3 py-1.5 text-sm w-40"
            style={inputStyle}
          />
          <button onClick={handleSearch}
            className="px-3 py-1.5 rounded text-sm"
            style={{ background: "var(--accent-blue)", color: "white" }}>
            Search
          </button>
        </div>
      </div>

      {loading ? (
        <p style={{ color: "var(--text-muted)" }}>Loading news...</p>
      ) : items.length === 0 ? (
        <Card>
          <p className="text-center py-8" style={{ color: "var(--text-muted)" }}>
            No news articles found. Configure TAVILY_API_KEY to enable news.
          </p>
        </Card>
      ) : (
        <div className="grid gap-4">
          {items.map((item, i) => (
            <Card key={i}>
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-semibold text-sm hover:underline flex items-center gap-1.5"
                    style={{ color: "var(--text-primary)" }}
                  >
                    {item.title}
                    <ExternalLink size={12} style={{ color: "var(--text-muted)" }} />
                  </a>
                  <p className="mt-1 text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                    {item.snippet}
                  </p>
                  <div className="mt-2 flex items-center gap-2">
                    {item.source && <Badge label={item.source} />}
                    {item.sector && <Badge label={item.sector} variant="blue" />}
                  </div>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
