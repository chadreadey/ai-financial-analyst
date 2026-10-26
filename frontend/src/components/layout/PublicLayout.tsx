import { Link, NavLink, Outlet } from "react-router-dom";
import { cn } from "@/lib/utils";

const REPO_URL = "https://github.com/chadreadey/ai-financial-analyst";

const navClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    "text-sm transition-colors hover:text-foreground",
    isActive ? "text-foreground font-medium" : "text-muted-foreground"
  );

export function PublicLayout() {
  return (
    <div className="min-h-screen flex flex-col bg-background text-foreground">
      <header className="border-b border-border">
        <div className="mx-auto max-w-5xl px-4 py-3 flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
          <Link to="/" className="text-sm font-bold tracking-tight">
            AI Financial Analyst
          </Link>
          <nav className="flex items-center gap-4 sm:gap-6">
            <NavLink to="/" end className={navClass}>
              Examples
            </NavLink>
            <NavLink to="/evidence" className={navClass}>
              How it performs
            </NavLink>
            <a
              href={REPO_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              View code
            </a>
          </nav>
        </div>
      </header>
      <main className="flex-1 mx-auto w-full max-w-5xl px-4 py-8">
        <Outlet />
      </main>
      <footer className="border-t border-border">
        <p className="mx-auto max-w-5xl px-4 py-4 text-xs text-muted-foreground">
          Research demo, not investment advice.
        </p>
      </footer>
    </div>
  );
}
