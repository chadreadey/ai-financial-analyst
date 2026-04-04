import React from "react";
import { NavLink } from "react-router-dom";
import { BarChart3, Newspaper, Building2, TrendingUp, LayoutGrid, FlaskConical, Wallet } from "lucide-react";

interface NavItem {
  to: string;
  label: string;
  icon: React.ComponentType<{ size?: number; className?: string }>;
}

const links: NavItem[] = [
  { to: "/analysis", label: "Analysis", icon: BarChart3 },
  { to: "/portfolio", label: "Watchlist", icon: LayoutGrid },
  { to: "/news", label: "News", icon: Newspaper },
  { to: "/industry", label: "Industry", icon: Building2 },
  { to: "/backtest", label: "Backtest", icon: FlaskConical },
  { to: "/paper-trading", label: "Paper Trading", icon: Wallet },
];

export function TopNav(): React.ReactElement {
  return (
    <nav
      className="sticky top-0 z-50"
      style={{
        background: "var(--bg-secondary)",
        borderBottom: "1px solid var(--border)",
        boxShadow: "0 1px 0 rgba(0,0,0,0.4)",
      }}
    >
      <div className="max-w-7xl mx-auto px-4 flex items-center h-14">
        {/* Brand */}
        <div className="flex items-center gap-2 mr-8">
          <div
            className="flex items-center justify-center w-7 h-7 rounded"
            style={{ background: "var(--accent-blue-dim)", border: "1px solid rgba(59,130,246,0.25)" }}
          >
            <TrendingUp size={14} style={{ color: "var(--accent-blue)" }} />
          </div>
          <div className="flex flex-col leading-none">
            <span className="font-bold text-sm tracking-tight" style={{ color: "var(--text-primary)" }}>
              AI Analyst
            </span>
            <span className="text-[10px] tracking-widest uppercase" style={{ color: "var(--text-muted)" }}>
              Equity Research
            </span>
          </div>
        </div>

        {/* Divider */}
        <div className="w-px h-5 mr-6" style={{ background: "var(--border)" }} />

        {/* Nav links */}
        <div className="flex items-center gap-1">
          {links.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className="relative flex items-center gap-1.5 px-3 py-2 text-sm font-medium rounded-md transition-fast"
              style={({ isActive }) => ({
                color: isActive ? "var(--text-primary)" : "var(--text-secondary)",
                background: isActive ? "var(--bg-hover)" : "transparent",
              })}
            >
              {({ isActive }) => (
                <>
                  <Icon size={15} />
                  {label}
                  {isActive && (
                    <span
                      className="absolute bottom-0 left-3 right-3 h-0.5 rounded-full"
                      style={{ background: "var(--accent-blue)" }}
                    />
                  )}
                </>
              )}
            </NavLink>
          ))}
        </div>
      </div>
    </nav>
  );
}
