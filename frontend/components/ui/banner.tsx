import React from "react";
import { cn } from "@/lib/utils";

export interface PageBannerProps
  extends Omit<React.HTMLAttributes<HTMLElement>, "title"> {
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  icon?: React.ReactNode;
  actions?: React.ReactNode;
  figures?: React.ReactNode;
}

export function PageBanner({
  eyebrow,
  title,
  description,
  icon,
  actions,
  figures,
  className,
  ...props
}: PageBannerProps) {
  return (
    <section
      className={cn(
        "relative isolate overflow-hidden rounded-panel border border-white/10 px-5 py-6 sm:px-8 sm:py-7 text-white shadow-banner",
        className
      )}
      style={{ background: "var(--banner)" }}
      {...props}
    >
      {/* Dot field pattern fading towards the right */}
      <span
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-10 opacity-40 [background-image:radial-gradient(rgb(255_255_255/0.22)_1px,transparent_1px)] [background-size:14px_14px] [mask-image:linear-gradient(100deg,transparent_35%,black_90%)]"
      />

      <div className="flex flex-wrap items-center justify-between gap-5">
        <div className="flex min-w-0 items-start gap-4">
          {icon && (
            <span className="hidden sm:grid size-12 place-items-center rounded-tile border border-white/15 bg-[#ffffff]/10 shrink-0">
              {icon}
            </span>
          )}
          <div>
            {eyebrow && (
              <p className="text-micro font-semibold tracking-[1.2px] text-brand-lilac uppercase">
                {eyebrow}
              </p>
            )}
            <h1 className="mt-0.5 font-display text-2xl leading-8 font-bold tracking-[-0.02em] sm:text-[1.75rem] sm:leading-9">
              {title}
            </h1>
            {description && (
              <p className="mt-1.5 max-w-[80ch] text-[0.84375rem] text-white/75">
                {description}
              </p>
            )}
          </div>
        </div>

        {actions && (
          <div className="flex flex-wrap items-center gap-2.5">{actions}</div>
        )}
      </div>

      {figures && (
        <div className="mt-6 pt-5 border-t border-white/10 flex flex-wrap gap-3">
          {figures}
        </div>
      )}
    </section>
  );
}

export function BannerFigure({
  label,
  value,
  className,
}: {
  label: string;
  value: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "rounded-tile border border-white/10 bg-[#ffffff]/[0.06] px-4 py-3 shrink-0",
        className
      )}
    >
      <div className="text-micro font-semibold tracking-[0.6px] text-white/60 uppercase">
        {label}
      </div>
      <div className="mt-0.5 text-xl leading-7 font-bold text-white tabular-nums">
        {value}
      </div>
    </div>
  );
}

export function BannerButton({
  variant = "outline",
  className,
  children,
  ...props
}: {
  variant?: "solid" | "outline";
  className?: string;
  children: React.ReactNode;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 h-9 rounded-control px-3.5 text-[0.8125rem] font-semibold transition-colors cursor-pointer select-none",
        variant === "solid"
          ? "bg-[#ffffff] text-night shadow-sm hover:bg-[#ffffff]/90"
          : "border border-white/20 bg-[#ffffff]/10 text-white hover:bg-[#ffffff]/15",
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}

export function ViewHeader({
  title,
  description,
  actions,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "flex flex-wrap items-end justify-between gap-4",
        className
      )}
    >
      <div className="min-w-0">
        <h1 className="font-display text-2xl leading-8 font-bold tracking-[-0.02em] text-ink">
          {title}
        </h1>
        {description && (
          <p className="mt-1 max-w-[90ch] text-[0.84375rem] text-ink-2">
            {description}
          </p>
        )}
      </div>
      {actions && (
        <div className="flex shrink-0 items-center gap-2.5">{actions}</div>
      )}
    </header>
  );
}
