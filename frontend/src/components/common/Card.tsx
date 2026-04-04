import React from "react";
import type { ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  className?: string;
  padding?: "sm" | "md" | "lg";
  elevated?: boolean;
}

const paddingMap: Record<NonNullable<CardProps["padding"]>, string> = {
  sm: "p-3",
  md: "p-4",
  lg: "p-6",
};

export function Card({ children, className = "", padding = "md", elevated = false }: CardProps): React.ReactElement {
  return (
    <div
      className={`rounded-lg ${paddingMap[padding]} ${className}`}
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border)",
        boxShadow: elevated ? "var(--shadow-md)" : "var(--shadow-sm)",
      }}
    >
      {children}
    </div>
  );
}
