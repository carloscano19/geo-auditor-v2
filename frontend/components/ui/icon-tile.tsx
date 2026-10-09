import React from "react";
import { cn } from "@/lib/utils";

export type IconTileTone =
  | "brand"
  | "neutral"
  | "good"
  | "warn"
  | "critical"
  | "info"
  | "verified"
  | "spoofed"
  | "series-1"
  | "series-2"
  | "series-3"
  | "series-4"
  | "series-7";

export type IconTileSize = "sm" | "md" | "lg";

export function IconTile({
  tone = "neutral",
  size = "md",
  className,
  children,
}: {
  tone?: IconTileTone;
  size?: IconTileSize;
  className?: string;
  children: React.ReactNode;
}) {
  const sizeClasses: Record<IconTileSize, string> = {
    sm: "size-8 rounded-control", // 32px for card headers
    md: "size-11 rounded-tile",   // 44px for stat cards
    lg: "size-12 rounded-tile",   // 48px for banners
  };

  const toneClasses: Record<IconTileTone, string> = {
    brand: "bg-accent-soft text-accent",
    neutral: "bg-surface-2 text-ink-2",
    good: "bg-good-soft text-good",
    warn: "bg-warn-soft text-warn",
    critical: "bg-critical-soft text-critical",
    info: "bg-info-soft text-info",
    verified: "bg-[#f0f2f5] text-verified dark:bg-[#1a1f26]",
    spoofed: "bg-spoofed-soft text-spoofed",
    "series-1": "bg-blue-50 text-[var(--series-1)] dark:bg-blue-950/40",
    "series-2": "bg-orange-50 text-[var(--series-2)] dark:bg-orange-950/40",
    "series-3": "bg-emerald-50 text-[var(--series-3)] dark:bg-emerald-950/40",
    "series-4": "bg-amber-50 text-[var(--series-4)] dark:bg-amber-950/40",
    "series-7": "bg-indigo-50 text-[var(--series-7)] dark:bg-indigo-950/40",
  };

  return (
    <div
      className={cn(
        "grid place-items-center shrink-0 border border-hairline/60 transition-colors",
        sizeClasses[size],
        toneClasses[tone],
        className
      )}
    >
      {children}
    </div>
  );
}
