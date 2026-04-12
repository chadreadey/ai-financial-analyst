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
