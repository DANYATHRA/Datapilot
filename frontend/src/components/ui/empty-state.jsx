import React from "react";
import { Button } from "./button";
import { ArrowRight, Upload } from "lucide-react";
import { cn } from "../../lib/utils";

export function EmptyIllustration({ className = "w-24 h-24" }) {
  return (
    <svg
      viewBox="0 0 120 120"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn("mx-auto text-primary/40", className)}
      aria-hidden="true"
    >
      <rect
        x="20"
        y="25"
        width="80"
        height="70"
        rx="8"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeDasharray="4 4"
      />
      <path
        d="M35 50H85M35 65H65M35 80H75"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
      />
      <circle cx="60" cy="60" r="18" fill="hsl(var(--card))" stroke="currentColor" strokeWidth="1.75" />
      <path
        d="M60 52V68M52 60L60 52L68 60"
        stroke="hsl(var(--primary))"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function EmptyState({
  title = "No dataset active",
  description = "Upload an Excel, CSV, or Parquet file to unlock automated cleaning, query analytics, and visual studios.",
  actionLabel = "Upload an Excel file",
  onAction,
  icon: Icon = Upload,
  actionIcon: ActionIcon = ArrowRight,
  className = "",
  children,
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-dashed border-border bg-card p-10 text-center shadow-xs max-w-xl mx-auto my-10",
        className
      )}
    >
      <EmptyIllustration className="w-20 h-20 mb-4" />
      <h3 className="text-base font-semibold text-foreground mb-1.5">{title}</h3>
      <p className="text-sm text-muted-foreground leading-relaxed max-w-md mx-auto mb-6">
        {description}
      </p>

      {onAction && (
        <Button onClick={onAction} className="inline-flex items-center gap-2">
          {Icon && <Icon className="w-4 h-4" strokeWidth={1.75} aria-hidden="true" />}
          <span>{actionLabel}</span>
          {ActionIcon && <ActionIcon className="w-4 h-4" strokeWidth={1.75} aria-hidden="true" />}
        </Button>
      )}

      {children && <div className="mt-6">{children}</div>}
    </div>
  );
}

export default EmptyState;
