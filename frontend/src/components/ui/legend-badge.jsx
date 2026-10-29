import React from "react";
import { cn } from "../../lib/utils";

export const STAGE_CONFIG = {
  structure: {
    label: "Structure",
    code: "STR",
    bg: "bg-slate-100 dark:bg-slate-800",
    text: "text-slate-700 dark:text-slate-300",
    border: "border-slate-300 dark:border-slate-600",
    dot: "#94a3b8",
  },
  column_names: {
    label: "Column Name",
    code: "COL",
    bg: "bg-slate-100 dark:bg-slate-800",
    text: "text-slate-700 dark:text-slate-300",
    border: "border-slate-300 dark:border-slate-600",
    dot: "#64748b",
  },
  text_hygiene: {
    label: "Text Cleaned",
    code: "TXT",
    bg: "bg-amber-50 dark:bg-amber-950/40",
    text: "text-amber-800 dark:text-amber-300",
    border: "border-amber-300 dark:border-amber-800",
    dot: "#eab308",
  },
  data_types: {
    label: "Type Converted",
    code: "TYP",
    bg: "bg-blue-50 dark:bg-blue-950/40",
    text: "text-blue-800 dark:text-blue-300",
    border: "border-blue-300 dark:border-blue-800",
    dot: "#3b82f6",
  },
  value_standardisation: {
    label: "Standardised",
    code: "STD",
    bg: "bg-cyan-50 dark:bg-cyan-950/40",
    text: "text-cyan-800 dark:text-cyan-300",
    border: "border-cyan-300 dark:border-cyan-800",
    dot: "#06b6d4",
  },
  missing_values: {
    label: "Missing Filled",
    code: "MIS",
    bg: "bg-emerald-50 dark:bg-emerald-950/40",
    text: "text-emerald-800 dark:text-emerald-300",
    border: "border-emerald-300 dark:border-emerald-800",
    dot: "#10b981",
  },
  duplicates: {
    label: "Row Removed",
    code: "DEL",
    bg: "bg-rose-50 dark:bg-rose-950/40",
    text: "text-rose-800 dark:text-rose-300",
    border: "border-rose-300 dark:border-rose-800",
    dot: "#ef4444",
  },
  outliers: {
    label: "Outlier Clipped",
    code: "OUT",
    bg: "bg-orange-50 dark:bg-orange-950/40",
    text: "text-orange-800 dark:text-orange-300",
    border: "border-orange-300 dark:border-orange-800",
    dot: "#f97316",
  },
  pii: {
    label: "PII Masked",
    code: "PII",
    bg: "bg-purple-50 dark:bg-purple-950/40",
    text: "text-purple-800 dark:text-purple-300",
    border: "border-purple-300 dark:border-purple-800",
    dot: "#a855f7",
  },
  validation: {
    label: "Validation",
    code: "VAL",
    bg: "bg-slate-50 dark:bg-slate-900",
    text: "text-slate-600 dark:text-slate-400",
    border: "border-slate-200 dark:border-slate-700",
    dot: "#94a3b8",
  },
  review: {
    label: "Needs review",
    code: "?",
    bg: "bg-pink-50 dark:bg-pink-950/40",
    text: "text-pink-800 dark:text-pink-300",
    border: "border-pink-300 dark:border-pink-800",
    dot: "#ec4899",
  },
};

export function LegendBadge({ stage, showLabel = true, className = "" }) {
  const cfg = STAGE_CONFIG[stage] || STAGE_CONFIG.validation;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-semibold border select-none tabular-nums",
        cfg.bg,
        cfg.text,
        cfg.border,
        className
      )}
      title={`${cfg.label} stage modification`}
    >
      <span
        className="w-1.5 h-1.5 rounded-full shrink-0"
        style={{ backgroundColor: cfg.dot }}
        aria-hidden="true"
      />
      <span className="font-mono tracking-wider">{cfg.code}</span>
      {showLabel && <span className="opacity-80 font-normal">{cfg.label}</span>}
    </span>
  );
}

export function StageMarkerDot({ stage, className = "" }) {
  const cfg = STAGE_CONFIG[stage] || STAGE_CONFIG.validation;
  return (
    <span
      className={cn("inline-block w-2.5 h-2.5 rounded-xs shrink-0 border border-black/10 dark:border-white/20", className)}
      style={{ backgroundColor: cfg.dot }}
      title={cfg.label}
      aria-label={cfg.label}
    />
  );
}

export default LegendBadge;
