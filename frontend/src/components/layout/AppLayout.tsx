import { useState } from "react";
import { AppSidebar } from "./AppSidebar";
import { SettingsDrawer } from "./SettingsDrawer";

export function AppLayout({ children }: { children: React.ReactNode }) {
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <div className="min-h-screen bg-background">
      <AppSidebar onSettingsOpen={() => setSettingsOpen(true)} />
      <main className="ml-48 min-h-screen">
        {children}
      </main>
      <SettingsDrawer open={settingsOpen} onOpenChange={setSettingsOpen} />
    </div>
  );
}
