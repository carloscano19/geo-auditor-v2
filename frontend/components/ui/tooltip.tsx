"use client";

import React, { useState, useRef, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

export interface TooltipProps {
  content?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  align?: "left" | "center" | "right";
}

export function Tooltip({
  content,
  children,
  className = "",
}: TooltipProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [coords, setCoords] = useState<{
    top: number;
    left: number;
    placement: "top" | "bottom";
    arrowLeft: number;
  } | null>(null);
  const triggerRef = useRef<HTMLSpanElement>(null);
  const tooltipRef = useRef<HTMLSpanElement>(null);

  const updatePosition = useCallback(() => {
    if (!triggerRef.current) return;
    const triggerRect = triggerRef.current.getBoundingClientRect();
    const tooltipEl = tooltipRef.current;
    const tooltipWidth = tooltipEl ? tooltipEl.offsetWidth : 200;
    const tooltipHeight = tooltipEl ? tooltipEl.offsetHeight : 36;
    const gap = 8;
    const margin = 10;

    // Determine top vs bottom placement
    const fitsTop = triggerRect.top - tooltipHeight - gap >= margin;
    const placement: "top" | "bottom" = fitsTop ? "top" : "bottom";

    const top =
      placement === "top"
        ? triggerRect.top - tooltipHeight - gap
        : triggerRect.bottom + gap;

    // Center horizontally on trigger, clamped to viewport bounds
    const triggerCenter = triggerRect.left + triggerRect.width / 2;
    let left = triggerCenter - tooltipWidth / 2;
    if (left < margin) {
      left = margin;
    } else if (left + tooltipWidth > window.innerWidth - margin) {
      left = window.innerWidth - margin - tooltipWidth;
    }

    // Relative arrow position inside tooltip
    const arrowLeft = Math.max(12, Math.min(tooltipWidth - 12, triggerCenter - left));

    setCoords({ top, left, placement, arrowLeft });
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    updatePosition();
    const handleScrollOrResize = () => updatePosition();
    window.addEventListener("scroll", handleScrollOrResize, true);
    window.addEventListener("resize", handleScrollOrResize);
    return () => {
      window.removeEventListener("scroll", handleScrollOrResize, true);
      window.removeEventListener("resize", handleScrollOrResize);
    };
  }, [isOpen, updatePosition]);

  if (!content) return <>{children}</>;

  return (
    <span
      ref={triggerRef}
      onMouseEnter={() => {
        setIsOpen(true);
        updatePosition();
      }}
      onMouseLeave={() => setIsOpen(false)}
      onFocus={() => {
        setIsOpen(true);
        updatePosition();
      }}
      onBlur={() => setIsOpen(false)}
      className={cn("relative inline-flex items-center", className)}
    >
      {children}
      {isOpen &&
        typeof document !== "undefined" &&
        createPortal(
          <span
            ref={tooltipRef}
            role="tooltip"
            style={{
              position: "fixed",
              top: coords ? coords.top : -9999,
              left: coords ? coords.left : -9999,
              opacity: coords ? 1 : 0,
              zIndex: 99999,
            }}
            className="pointer-events-none select-none transition-opacity duration-75"
          >
            <span className="block max-w-[320px] w-max whitespace-normal rounded-control border border-hairline bg-surface p-2 text-center font-sans text-xs font-medium leading-snug text-ink shadow-pop dark:bg-surface-2 dark:border-hairline-strong">
              {content}
            </span>
            {coords && (
              <span
                style={{ left: coords.arrowLeft }}
                className={cn(
                  "absolute -translate-x-1/2 w-2 h-2 rotate-45 border-hairline bg-surface dark:bg-surface-2 dark:border-hairline-strong",
                  coords.placement === "top"
                    ? "top-full -mt-1 border-b border-r"
                    : "bottom-full -mb-1 border-t border-l"
                )}
                aria-hidden="true"
              />
            )}
          </span>,
          document.body
        )}
    </span>
  );
}

export function InfoTooltip({
  text,
  align = "center",
}: {
  text: string;
  align?: "left" | "center" | "right";
}) {
  return (
    <Tooltip content={text} align={align}>
      <span
        tabIndex={0}
        aria-label={text}
        className="inline-flex items-center justify-center size-3.5 rounded-full text-[10px] font-bold text-ink-3 hover:text-ink focus:text-ink bg-surface-2 hover:bg-hairline focus:bg-hairline border border-hairline cursor-help transition-colors select-none focus:outline-none"
      >
        ?
      </span>
    </Tooltip>
  );
}
