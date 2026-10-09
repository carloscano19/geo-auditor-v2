import React from "react";
import { cn } from "@/lib/utils";

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
  elevated?: boolean;
}

export function Card({
  className,
  elevated = false,
  children,
  ...props
}: CardProps) {
  return (
    <div
      className={cn(
        "rounded-card border border-hairline bg-surface transition-colors",
        elevated && "shadow-card",
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export interface CardHeaderProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  icon?: React.ReactNode;
  title: React.ReactNode;
  hint?: React.ReactNode;
  action?: React.ReactNode;
}

export function CardHeader({
  icon,
  title,
  hint,
  action,
  className,
  children,
  ...props
}: CardHeaderProps) {
  return (
    <div
      className={cn(
        "flex min-h-12 flex-wrap items-center justify-between gap-3 px-5 pt-5 pb-4",
        className
      )}
      {...props}
    >
      <div className="flex min-w-0 items-center gap-3">
        {icon}
        <div className="min-w-0">
          <h2 className="text-[0.9375rem] font-semibold tracking-[-0.01em] text-ink truncate">
            {title}
          </h2>
          {hint && <p className="mt-0.5 text-xs text-ink-3">{hint}</p>}
        </div>
      </div>
      {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
      {children}
    </div>
  );
}

export interface CardBodyProps extends React.HTMLAttributes<HTMLDivElement> {
  noPadding?: boolean;
}

export function CardBody({
  noPadding = false,
  className,
  children,
  ...props
}: CardBodyProps) {
  return (
    <div className={cn(!noPadding && "p-5 pt-1", className)} {...props}>
      {children}
    </div>
  );
}

export function CardFooter({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "border-t border-hairline px-5 py-3.5 flex items-center justify-between text-xs text-ink-3",
        className
      )}
      {...props}
    >
      {children}
    </div>
  );
}
