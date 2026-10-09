import React from "react";
import { cn } from "@/lib/utils";

export interface SegmentedOption<T extends string | number> {
  value: T;
  label: React.ReactNode;
  icon?: React.ReactNode;
}

export function Segmented<T extends string | number>({
  value,
  onChange,
  options,
  size = "md",
  className,
}: {
  value: T;
  onChange: (value: T) => void;
  options: SegmentedOption<T>[];
  size?: "sm" | "md";
  className?: string;
}) {
  return (
    <div
      role="radiogroup"
      className={cn(
        "inline-flex max-w-full flex-wrap items-center gap-1 rounded-xl border border-hairline bg-surface-2 p-1 dark:bg-surface",
        size === "sm" && "p-0.5 rounded-lg",
        className
      )}
    >
      {options.map((opt) => {
        const isSelected = opt.value === value;
        return (
          <label
            key={String(opt.value)}
            className={cn(
              "inline-flex items-center justify-center gap-1.5 rounded-control font-semibold transition-all cursor-pointer select-none",
              size === "sm" ? "h-6 px-2 text-[0.75rem]" : "h-8 px-3.5 text-[0.8125rem]",
              isSelected
                ? "bg-ink text-surface shadow-sm"
                : "text-ink-2 hover:text-ink hover:bg-surface/50"
            )}
          >
            <input
              type="radio"
              className="sr-only"
              checked={isSelected}
              onChange={() => onChange(opt.value)}
            />
            {opt.icon}
            <span>{opt.label}</span>
          </label>
        );
      })}
    </div>
  );
}

export function Chip({
  active = false,
  onClick,
  style,
  children,
  className,
  ...props
}: {
  active?: boolean;
  onClick?: () => void;
  children: React.ReactNode;
  className?: string;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      style={style}
      className={cn(
        "inline-flex h-8 items-center justify-center gap-1.5 rounded-full border px-3.5 text-xs font-semibold transition-colors cursor-pointer select-none",
        active
          ? "border-accent bg-accent-soft text-accent"
          : "border-hairline bg-surface text-ink-2 hover:border-hairline-strong hover:text-ink dark:bg-surface-2",
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}
