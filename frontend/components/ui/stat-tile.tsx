import React from "react";
import { cn } from "@/lib/utils";
import { IconTile, IconTileTone } from "./icon-tile";

export type StatTileTone =
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

export interface StatTileProps extends React.HTMLAttributes<HTMLDivElement> {
  hero?: boolean;
  tone?: StatTileTone;
  icon?: React.ReactNode;
  figure: React.ReactNode;
  label: string;
  hint?: React.ReactNode;
  change?: {
    value: string | number;
    direction?: "up" | "down" | "flat";
  };
  share?: {
    current: number;
    total: number;
    label?: string;
  };
}

export function StatTile({
  hero = false,
  tone = "neutral",
  icon,
  figure,
  label,
  hint,
  change,
  share,
  className,
  ...props
}: StatTileProps) {
  const figureToneClasses: Record<StatTileTone, string> = {
    neutral: "text-ink",
    good: "text-good",
    warn: "text-warn",
    critical: "text-critical",
    info: "text-info",
    verified: "text-verified",
    spoofed: "text-spoofed",
    "series-1": "text-[var(--series-1)]",
    "series-2": "text-[var(--series-2)]",
    "series-3": "text-[var(--series-3)]",
    "series-4": "text-[var(--series-4)]",
    "series-7": "text-[var(--series-7)]",
  };

  const sharePercent =
    share && share.total > 0
      ? Math.min(100, Math.max(0, (share.current / share.total) * 100))
      : 0;

  return (
    <div
      className={cn(
        "relative flex flex-col overflow-hidden rounded-card border border-hairline bg-surface p-5 transition-colors",
        hero &&
          "bg-[linear-gradient(135deg,color-mix(in_srgb,var(--brand-lilac)_14%,var(--surface))_0%,var(--surface)_70%)]",
        className
      )}
      {...props}
    >
      {/* Top row: Icon tile & Change pill */}
      <div className="flex items-center justify-between gap-3 mb-3.5">
        {icon ? (
          <IconTile tone={tone as IconTileTone} size="md">
            {icon}
          </IconTile>
        ) : (
          <div />
        )}

        {change && (
          <span
            className={cn(
              "rounded-full px-2.5 py-0.5 text-micro font-semibold tabular-nums shrink-0",
              change.direction === "up" && "bg-good-soft text-good",
              change.direction === "down" && "bg-critical-soft text-critical",
              change.direction === "flat" && "bg-surface-2 text-ink-3"
            )}
          >
            {change.direction === "up" && "▲ "}
            {change.direction === "down" && "▼ "}
            {change.value}
          </span>
        )}
      </div>

      {/* KPI figure */}
      <div
        className={cn(
          "text-[1.75rem] leading-8 font-extrabold tracking-[-0.03em] tabular-nums",
          figureToneClasses[tone]
        )}
      >
        {figure}
      </div>

      {/* Label (Eyebrow) */}
      <div className="mt-1 text-xs font-medium uppercase tracking-[0.5px] text-ink-2">
        {label}
      </div>

      {/* Hint */}
      {hint && <div className="mt-0.5 text-xs text-ink-3">{hint}</div>}

      {/* Optional share bar */}
      {share && (
        <div className="mt-4 pt-1">
          <div className="h-1 rounded-full bg-surface-2 overflow-hidden">
            <div
              className={cn(
                "h-full rounded-full transition-all duration-500",
                tone === "neutral"
                  ? "bg-[linear-gradient(90deg,var(--brand),var(--brand-lilac))]"
                  : tone === "good"
                  ? "bg-good"
                  : tone === "warn"
                  ? "bg-warn"
                  : tone === "critical"
                  ? "bg-critical"
                  : tone === "series-1"
                  ? "bg-[var(--series-1)]"
                  : tone === "series-2"
                  ? "bg-[var(--series-2)]"
                  : tone === "series-3"
                  ? "bg-[var(--series-3)]"
                  : tone === "series-4"
                  ? "bg-[var(--series-4)]"
                  : tone === "series-7"
                  ? "bg-[var(--series-7)]"
                  : "bg-accent"
              )}
              style={{ width: `${sharePercent}%` }}
            />
          </div>
          {share.label && (
            <div className="mt-1 flex justify-between text-micro text-ink-3 font-mono">
              <span>{share.label}</span>
              <span>{Math.round(sharePercent)}%</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
