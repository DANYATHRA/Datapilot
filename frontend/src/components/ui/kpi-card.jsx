import React, { useState } from "react";
import { TrendingUp, TrendingDown, Minus, Info, Code2, Copy, Check } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "./dialog";
import { SimpleTooltip } from "./tooltip";
import { formatNumber, formatCurrency, formatPercent } from "../../lib/formatters";
import { cn } from "../../lib/utils";
import { toast } from "sonner";

export function KpiCard({
  title,
  value,
  format = "auto", // "number" | "currency" | "percent" | "auto"
  delta = null, // e.g. { label: "+12.4%", direction: "up", percent: 12.4 } or number
  deltaLabel = "vs prior period",
  definition = "",
  sql = "",
  sparklineData = null,
  className = "",
}) {
  const [showSqlModal, setShowSqlModal] = useState(false);
  const [copied, setCopied] = useState(false);

  // Format main number
  const formattedValue = React.useMemo(() => {
    if (value === null || value === undefined) return "—";
    if (typeof value === "string" && isNaN(Number(value))) return value;
    const num = Number(value);

    if (format === "currency") {
      return formatCurrency(num);
    }
    if (format === "percent") {
      return formatPercent(num);
    }
    return formatNumber(num);
  }, [value, format]);

  // Delta parsing
  const deltaObj = React.useMemo(() => {
    if (!delta) return null;
    if (typeof delta === "object") return delta;
    const num = Number(delta);
    if (isNaN(num)) return { label: String(delta), direction: "neutral" };
    return {
      label: `${num > 0 ? "+" : ""}${num.toFixed(1)}%`,
      direction: num > 0 ? "up" : num < 0 ? "down" : "neutral",
    };
  }, [delta]);

  const handleCopySql = () => {
    if (!sql) return;
    navigator.clipboard.writeText(sql);
    setCopied(true);
    toast.success("SQL query copied to clipboard");
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <>
      <div
        className={cn(
          "dash-kpi-card dashboard-kpi-card rounded-lg border border-border bg-card p-5 shadow-xs transition-all hover:shadow-md hover:border-border/80 flex flex-col justify-between",
          className
        )}
      >
        {/* Top Header: Title & Info Actions */}
        <div className="flex items-center justify-between gap-2 mb-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <span className="text-xs font-semibold tracking-wider uppercase text-muted-foreground truncate">
              {title}
            </span>
            {definition && (
              <SimpleTooltip content={definition}>
                <button
                  type="button"
                  className="text-muted-foreground/60 hover:text-foreground transition-colors p-0.5 rounded"
                  aria-label={`Definition of ${title}`}
                >
                  <Info className="w-3.5 h-3.5" strokeWidth={1.75} />
                </button>
              </SimpleTooltip>
            )}
          </div>

          {sql && (
            <SimpleTooltip content="Show compiled SQL">
              <button
                type="button"
                onClick={() => setShowSqlModal(true)}
                className="text-muted-foreground/60 hover:text-primary transition-colors p-1 rounded hover:bg-secondary"
                aria-label="Inspect SQL query"
              >
                <Code2 className="w-3.5 h-3.5" strokeWidth={1.75} />
              </button>
            </SimpleTooltip>
          )}
        </div>

        {/* Big Tabular Number */}
        <div className="flex items-baseline justify-between gap-3 my-1">
          <div className="text-2xl font-bold tracking-tight text-foreground tabular-nums font-mono">
            {formattedValue}
          </div>

          {/* Sparkline miniature if provided */}
          {sparklineData && sparklineData.length > 1 && (
            <div className="w-20 h-6 shrink-0 opacity-80" aria-hidden="true">
              <svg className="w-full h-full overflow-visible" viewBox="0 0 100 30">
                <path
                  d={generateSparklinePath(sparklineData, 100, 30)}
                  fill="none"
                  stroke="hsl(var(--primary))"
                  strokeWidth="2"
                  strokeLinecap="round"
                />
              </svg>
            </div>
          )}
        </div>

        {/* Delta with Lucide Trend Icon & Comparison Caption */}
        {deltaObj && (
          <div className="flex items-center gap-1.5 text-xs mt-2 pt-2 border-t border-border/40">
            {deltaObj.direction === "up" ? (
              <span className="inline-flex items-center gap-1 text-success font-semibold tabular-nums">
                <TrendingUp className="w-3.5 h-3.5" strokeWidth={1.75} aria-hidden="true" />
                <span>{deltaObj.label}</span>
              </span>
            ) : deltaObj.direction === "down" ? (
              <span className="inline-flex items-center gap-1 text-destructive font-semibold tabular-nums">
                <TrendingDown className="w-3.5 h-3.5" strokeWidth={1.75} aria-hidden="true" />
                <span>{deltaObj.label}</span>
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-muted-foreground font-semibold tabular-nums">
                <Minus className="w-3.5 h-3.5" strokeWidth={1.75} aria-hidden="true" />
                <span>{deltaObj.label}</span>
              </span>
            )}
            <span className="text-muted-foreground truncate">{deltaLabel}</span>
          </div>
        )}
      </div>

      {/* SQL Inspection Dialog */}
      {sql && (
        <Dialog open={showSqlModal} onOpenChange={setShowSqlModal}>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2 text-base">
                <Code2 className="w-5 h-5 text-primary" strokeWidth={1.75} />
                <span>Compiled DuckDB Query — {title}</span>
              </DialogTitle>
              <DialogDescription>
                Live read-only SQL query executed against the sandboxed database engine.
              </DialogDescription>
            </DialogHeader>

            <div className="relative mt-2">
              <pre className="rounded-lg bg-secondary p-4 text-xs font-mono overflow-x-auto text-foreground border border-border leading-relaxed">
                {sql}
              </pre>
              <button
                type="button"
                onClick={handleCopySql}
                className="absolute right-3 top-3 inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-card/80 hover:bg-card border border-border text-xs font-medium text-foreground shadow-xs transition-colors"
                aria-label="Copy SQL"
              >
                {copied ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-success" strokeWidth={1.75} />
                    <span>Copied</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5 text-muted-foreground" strokeWidth={1.75} />
                    <span>Copy</span>
                  </>
                )}
              </button>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </>
  );
}

function generateSparklinePath(values, width, height) {
  if (!values || values.length < 2) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const padding = 2;
  const usableHeight = height - padding * 2;

  const points = values.map((val, idx) => {
    const x = (idx / (values.length - 1)) * width;
    const y = height - padding - ((val - min) / range) * usableHeight;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  return `M ${points.join(" L ")}`;
}

export default KpiCard;
