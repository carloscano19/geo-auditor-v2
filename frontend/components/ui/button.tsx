import React from "react";
import { cn } from "@/lib/utils";

export type ButtonVariant = "primary" | "default" | "ghost" | "danger";
export type ButtonSize = "sm" | "xs" | "icon";

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  children: React.ReactNode;
}

export function Button({
  variant = "default",
  size = "sm",
  className,
  children,
  ...props
}: ButtonProps) {
  const variantClasses: Record<ButtonVariant, string> = {
    primary:
      "bg-accent text-accent-on shadow-sm hover:bg-accent-hover focus-visible:outline-accent",
    default:
      "border border-hairline bg-surface text-ink hover:border-hairline-strong hover:bg-surface-2 dark:bg-surface-2 focus-visible:outline-accent",
    ghost:
      "text-ink-2 hover:bg-surface-2 hover:text-ink focus-visible:outline-accent",
    danger:
      "border border-critical/40 bg-critical-soft text-critical hover:border-critical focus-visible:outline-critical",
  };

  const sizeClasses: Record<ButtonSize, string> = {
    sm: "h-9 px-4 text-[0.8125rem]",
    xs: "h-7 px-2.5 text-xs",
    icon: "size-9 p-0",
  };

  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-control font-semibold whitespace-nowrap transition-colors cursor-pointer select-none disabled:pointer-events-none disabled:opacity-50",
        variantClasses[variant],
        sizeClasses[size],
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}
