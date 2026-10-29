import React, { Suspense, useMemo, useState, useRef, useEffect } from "react";
import { useTheme } from "../../lib/theme";
import { getPlotlyTheme, PLOTLY_CONFIG } from "../../lib/plotly-theme";
import { Skeleton } from "./skeleton";
import { Button } from "./button";
import { Table, Eye, EyeOff, AlertCircle, Info } from "lucide-react";
import { cn } from "../../lib/utils";

// Lazy-load Plotly bundle on demand so initial application bundle stays light
const LazyPlot = React.lazy(async () => {
  const [createPlotlyFactory, Plotly] = await Promise.all([
    import("react-plotly.js/factory"),
    import("plotly.js-dist-min"),
  ]);
  const factory = createPlotlyFactory.default || createPlotlyFactory;
  const plotlyLib = Plotly.default || Plotly;
  return { default: factory(plotlyLib) };
});

export function ChartSkeleton({ height = 320 }) {
  return (
    <div
      style={{ height }}
      className="w-full flex flex-col justify-between p-4 rounded-lg border border-border/60 bg-muted/5 animate-pulse"
    >
      <div className="flex justify-between items-center">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-4 w-16" />
      </div>
      <div className="flex items-end gap-2 h-48 w-full pt-6">
        {Array.from({ length: 8 }).map((_, i) => (
          <Skeleton
            key={i}
            className="flex-1"
            style={{ height: `${25 + ((i * 37) % 65)}%` }}
          />
        ))}
      </div>
      <div className="flex justify-between pt-2">
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-3 w-16" />
        <Skeleton className="h-3 w-16" />
      </div>
    </div>
  );
}

export function ChartWrapper({
  data = [],
  layout = {},
  config = {},
  height = 320,
  className = "",
  ariaLabel = "",
  summary = "",
  caption = "",
  excludedRows = 0,
  excludedReason = "",
  error = null,
  emptyMessage = "No rows match these filters. Clear a filter.",
  tableData = null,
  showTableToggle = true,
  onPlotClick = null,
}) {
  const { theme } = useTheme();
  const isDark = theme === "dark";
  const [viewAsTable, setViewAsTable] = useState(false);
  const containerRef = useRef(null);
  const [containerWidth, setContainerWidth] = useState(null);

  // ResizeObserver to track container width changes cleanly
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect.width > 0) {
          setContainerWidth(Math.floor(entry.contentRect.width));
        }
      }
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  const themeLayout = useMemo(() => {
    const baseTheme = getPlotlyTheme(isDark);

    // Single series legend hiding logic
    const traceCount = Array.isArray(data) ? data.length : 0;
    const hideLegendForSingle = traceCount <= 1 && !layout.showlegend;

    return {
      ...baseTheme,
      ...layout,
      // NO title inside the figure (card header carries title and subtitle)
      title: { text: "" },
      autosize: true,
      height,
      showlegend: hideLegendForSingle ? false : (layout.showlegend ?? traceCount > 1),
      font: {
        ...baseTheme.font,
        ...(layout.font || {}),
      },
      margin: {
        ...baseTheme.margin,
        ...(layout.margin || {}),
      },
      xaxis: {
        ...baseTheme.xaxis,
        ...(layout.xaxis || {}),
      },
      yaxis: {
        ...baseTheme.yaxis,
        ...(layout.yaxis || {}),
      },
    };
  }, [isDark, layout, height, data]);

  const mergedConfig = useMemo(() => {
    return {
      ...PLOTLY_CONFIG,
      ...config,
    };
  }, [config]);

  // Derive tabular data fallback if not provided explicitly
  const tabularRows = useMemo(() => {
    if (tableData && Array.isArray(tableData)) return tableData;
    if (!data || !data.length) return [];
    const firstTrace = data[0];
    if (firstTrace.x && firstTrace.y) {
      return firstTrace.x.map((xVal, idx) => ({
        Category: String(xVal),
        Value: firstTrace.y[idx],
      }));
    }
    return [];
  }, [tableData, data]);

  // Auto-generate aria description if not passed
  const effectiveAria = useMemo(() => {
    if (ariaLabel) return ariaLabel;
    if (summary) return summary;
    if (data && data.length > 0) {
      const trace = data[0];
      const count = trace.x?.length || trace.values?.length || trace.y?.length || 0;
      return `Chart displaying ${count} data points across categories.`;
    }
    return "Data visualization chart";
  }, [ariaLabel, summary, data]);

  // Error State
  if (error) {
    return (
      <div
        style={{ height }}
        className={cn(
          "w-full rounded-lg border border-border/80 bg-card p-6 flex flex-col items-center justify-center text-center space-y-2",
          className
        )}
      >
        <AlertCircle className="w-6 h-6 text-destructive/80" strokeWidth={1.75} />
        <div className="text-xs font-semibold text-foreground">Unable to render chart</div>
        <p className="text-[11px] text-muted-foreground max-w-sm">
          {String(error)}
        </p>
      </div>
    );
  }

  // Empty State
  const hasData = Array.isArray(data) && data.length > 0 && (
    (data[0].x && data[0].x.length > 0) ||
    (data[0].values && data[0].values.length > 0) ||
    (data[0].y && data[0].y.length > 0) ||
    data[0].value !== undefined
  );

  if (!hasData) {
    return (
      <div
        style={{ height }}
        className={cn(
          "w-full rounded-lg border border-dashed border-border bg-card p-6 flex flex-col items-center justify-center text-center space-y-2",
          className
        )}
      >
        <Info className="w-5 h-5 text-muted-foreground" strokeWidth={1.75} />
        <div className="text-xs font-semibold text-foreground">No data points</div>
        <p className="text-[11px] text-muted-foreground max-w-sm">
          {emptyMessage}
        </p>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className={cn("w-full relative select-none flex flex-col", className)}
      role="region"
      aria-label={effectiveAria}
    >
      {/* Top right "View as table" helper toggle */}
      {showTableToggle && tabularRows.length > 0 && (
        <div className="absolute top-1 right-2 z-10">
          <button
            type="button"
            onClick={() => setViewAsTable((v) => !v)}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors border border-transparent hover:border-border/60"
            title={viewAsTable ? "Switch back to chart" : "View data as table"}
          >
            {viewAsTable ? (
              <>
                <Eye className="w-3 h-3" strokeWidth={1.75} />
                <span>Chart</span>
              </>
            ) : (
              <>
                <Table className="w-3 h-3" strokeWidth={1.75} />
                <span>Table</span>
              </>
            )}
          </button>
        </div>
      )}

      {/* Main Plot or Table view */}
      {viewAsTable ? (
        <div
          style={{ height }}
          className="w-full overflow-auto rounded-md border border-border/60 bg-card text-xs p-2 font-mono"
        >
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-border/80 text-[11px] text-muted-foreground uppercase">
                {Object.keys(tabularRows[0] || {}).map((col) => (
                  <th key={col} className="p-2 font-semibold">{col}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border/60">
              {tabularRows.slice(0, 50).map((row, rIdx) => (
                <tr key={rIdx} className="hover:bg-muted/20">
                  {Object.values(row).map((val, cIdx) => (
                    <td key={cIdx} className="p-2 tabular-nums">
                      {val === null || val === undefined ? "—" : String(val)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {tabularRows.length > 50 && (
            <div className="p-2 text-center text-[10px] text-muted-foreground font-sans">
              Showing first 50 rows of {tabularRows.length} total.
            </div>
          )}
        </div>
      ) : (
        <Suspense fallback={<ChartSkeleton height={height} />}>
          <LazyPlot
            data={data}
            layout={themeLayout}
            config={mergedConfig}
            style={{ width: "100%", height }}
            useResizeHandler
            onClick={(event) => {
              if (onPlotClick) onPlotClick(event);
            }}
          />
        </Suspense>
      )}

      {/* Honest Data Caption: Rows excluded indicator */}
      {(excludedRows > 0 || excludedReason || caption) && (
        <div className="pt-1.5 px-1 text-[11px] text-muted-foreground flex items-center justify-between">
          <span className="truncate">
            {caption || (excludedRows > 0 ? `${excludedRows} rows excluded (${excludedReason || "missing required field"})` : "")}
          </span>
          {summary && (
            <span className="text-[10px] opacity-75 hidden sm:inline ml-2 truncate max-w-xs" title={summary}>
              {summary}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

export default ChartWrapper;
