import React from "react";
interface BadgeProps {
  label: string;
  variant?: "green" | "amber" | "red" | "blue" | "muted";
  size?: "sm" | "md";
}

interface ColorConfig {
  bg: string;
  color: string;
  border: string;
}

const colorMap: Record<NonNullable<BadgeProps["variant"]>, ColorConfig> = {
  green: {
    bg: "rgba(16,185,129,0.1)",
    color: "var(--accent-green)",
    border: "rgba(16,185,129,0.25)",
  },
  amber: {
    bg: "rgba(245,158,11,0.1)",
    color: "var(--accent-amber)",
    border: "rgba(245,158,11,0.25)",
  },
  red: {
    bg: "rgba(239,68,68,0.1)",
    color: "var(--accent-red)",
    border: "rgba(239,68,68,0.25)",
  },
  blue: {
    bg: "rgba(59,130,246,0.1)",
    color: "var(--accent-blue)",
    border: "rgba(59,130,246,0.25)",
  },
  muted: {
    bg: "var(--bg-hover)",
    color: "var(--text-secondary)",
    border: "var(--border-subtle)",
  },
};

export function Badge({ label, variant = "muted", size = "md" }: BadgeProps): React.ReactElement {
  const c = colorMap[variant];
  const sizeClass = size === "sm" ? "px-1.5 py-px text-[10px]" : "px-2.5 py-0.5 text-xs";

  return (
    <span
      className={`inline-flex items-center ${sizeClass} rounded-full font-semibold tracking-wide`}
      style={{
        background: c.bg,
        color: c.color,
        border: `1px solid ${c.border}`,
      }}
    >
      {label}
    </span>
  );
}
