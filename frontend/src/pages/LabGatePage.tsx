import { useState } from "react";
import { Link } from "react-router-dom";
import { getAdminKey, setAdminKey } from "@/lib/adminKey";

export function LabGatePage() {
  const [value, setValue] = useState("");
  const [unlocked, setUnlocked] = useState(() => getAdminKey() !== null);

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!value.trim()) return;
    setAdminKey(value.trim());
    setValue("");
    setUnlocked(true);
  };

  return (
    <div className="mx-auto max-w-sm space-y-4 px-4 py-16">
      <h1 className="text-xl font-bold tracking-tight">Research lab</h1>
      <p className="text-sm text-muted-foreground">
        The lab is the author's private workbench. Enter the access key to unlock it.
      </p>
      <form onSubmit={onSubmit} className="flex gap-2">
        <input
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Access key"
          aria-label="Access key"
          autoComplete="off"
          className="flex-1 min-w-0 rounded-md border border-border bg-secondary px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
        />
        <button
          type="submit"
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          Save
        </button>
      </form>
      {unlocked && (
        <Link to="/lab/analysis" className="inline-block text-sm text-primary hover:underline">
          Enter the lab
        </Link>
      )}
      <div>
        <Link to="/" className="text-xs text-muted-foreground hover:text-foreground">
          Back to the public site
        </Link>
      </div>
    </div>
  );
}
