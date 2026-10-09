import React from "react";
import { cn } from "@/lib/utils";

export type BadgeTone =
  | "neutral"
  | "good"
  | "warn"
  | "critical"
  | "info"
  | "spoofed"
  | "outline";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
  children: React.ReactNode;
}

export function Badge({
  tone = "neutral",
  className,
  children,
  ...props
}: BadgeProps) {
  const toneClasses: Record<BadgeTone, string> = {
    neutral: "border-hairline bg-surface-2 text-ink-2",
    good: "border-good/30 bg-good-soft text-good",
    warn: "border-warn/30 bg-warn-soft text-warn",
    critical: "border-critical/25 bg-critical-soft text-critical",
    info: "border-info/25 bg-info-soft text-info",
    spoofed: "border-spoofed/30 bg-spoofed-soft text-spoofed",
    outline: "border-hairline-strong text-ink-2",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-micro leading-4 font-semibold tracking-[0.2px]",
        toneClasses[tone],
        className
      )}
      {...props}
    >
      {children}
    </span>
  );
}
