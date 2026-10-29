import React, { useState, useEffect, useCallback, useMemo } from "react";
import {
  Download,
  FileSpreadsheet,
  FileText,
  Filter,
  Plus,
  Info,
  MoreVertical,
  Check,
  X,
  TrendingUp,
  TrendingDown,
  Loader2,
  Trash2,
  RotateCcw,
  Maximize2,
  Table as TableIcon,
  Calendar,
  ChevronDown,
  ChevronUp,
  Search,
  ChevronRight,
} from "lucide-react";
import { api } from "../api";
import ChartWrapper from "../components/ui/chart-wrapper";
import { Button } from "../components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuSubContent,
} from "../components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "../components/ui/dialog";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "../components/ui/popover";
import { Checkbox } from "../components/ui/checkbox";
import { toast } from "sonner";
import { cn } from "../lib/utils";

export default function DashboardPage({ ds, onOpenClean }) {
  const [loading, setLoading] = useState(true);
  const [dashboardData, setDashboardData] = useState(null);
  const [charts, setCharts] = useState([]);

  // Active report tab
  const [activeTab, setActiveTab] = useState("Overview");

  // Active slicers
  const [filters, setFilters] = useState({
    date_min: "",
    date_max: "",
    date_grain: "month",
    cat1_col: "",
    cat1_vals: [],
    cat2_col: "",
    cat2_vals: [],
    cat3_col: "",
    cat3_vals: [],
    cross_dim: "",
    cross_val: "",
  });

  // UI state
  const [highlightedChartId, setHighlightedChartId] = useState(null);
  const [showDownloadExcelDialog, setShowDownloadExcelDialog] = useState(false);
  const [excelFormat, setExcelFormat] = useState("xlsx");
  const [includeChangeLog, setIncludeChangeLog] = useState(true);
  const [highlightChanges, setHighlightChanges] = useState(false);
  const [downloadingExcel, setDownloadingExcel] = useState(false);
  const [downloadingPdf, setDownloadingPdf] = useState(false);

  // Per-visual interactive state: table view toggle & focus mode
  const [tableViews, setTableViews] = useState({}); // chartId -> boolean
  const [focusedChart, setFocusedChart] = useState(null); // chart object

  // Category slicer search state
  const [slicerSearches, setSlicerSearches] = useState({});

  // Fetch dashboard data from shared calculation layer
  const loadDashboard = useCallback(
    async (appliedFilters = filters) => {
      if (!ds?.id) return;
      try {
        setLoading(true);
        const res = await api.getDashboardData(ds.id, appliedFilters);
        if (res) {
          setDashboardData(res);
          setCharts(res.charts || []);
        }
      } catch (err) {
        toast.error(err.message || "Failed to load dashboard data");
      } finally {
        setLoading(false);
      }
    },
    [ds?.id]
  );

  useEffect(() => {
    loadDashboard(filters);
  }, [loadDashboard]);

  // Handle cross-filtering by clicking a data point or category
  const handleCrossFilter = (dim, val) => {
    if (!dim || !val) return;
    setFilters((prev) => {
      const isAlreadyFiltered = prev.cross_dim === dim && prev.cross_val === String(val);
      const nextFilters = {
        ...prev,
        cross_dim: isAlreadyFiltered ? "" : dim,
        cross_val: isAlreadyFiltered ? "" : String(val),
      };
      loadDashboard(nextFilters);
      return nextFilters;
    });
  };

  const handleClearCrossFilter = () => {
    setFilters((prev) => {
      const nextFilters = { ...prev, cross_dim: "", cross_val: "" };
      loadDashboard(nextFilters);
      return nextFilters;
    });
  };

  // Handle Slicer Toggle
  const handleToggleSlicerVal = (colIndex, colName, val) => {
    setFilters((prev) => {
      const keyCol = `cat${colIndex}_col`;
      const keyVals = `cat${colIndex}_vals`;
      const curVals = prev[keyVals] || [];
      const nextVals = curVals.includes(val)
        ? curVals.filter((v) => v !== val)
        : [...curVals, val];

      const next = {
        ...prev,
        [keyCol]: nextVals.length > 0 ? colName : "",
        [keyVals]: nextVals,
      };
      loadDashboard(next);
      return next;
    });
  };

  const handleClearAllSlicers = () => {
    const cleared = {
      date_min: "",
      date_max: "",
      date_grain: "month",
      cat1_col: "",
      cat1_vals: [],
      cat2_col: "",
      cat2_vals: [],
      cat3_col: "",
      cat3_vals: [],
      cross_dim: "",
      cross_val: "",
    };
    setFilters(cleared);
    loadDashboard(cleared);
    toast.success("All slicers and filters cleared");
  };

  // Date drill-down handler
  const handleDateDrill = (chartId, direction) => {
    const grains = ["year", "quarter", "month", "day"];
    const curGrain = filters.date_grain || "month";
    const curIdx = grains.indexOf(curGrain);
    let nextIdx = curIdx;
    if (direction === "down" && curIdx < grains.length - 1) {
      nextIdx = curIdx + 1;
    } else if (direction === "up" && curIdx > 0) {
      nextIdx = curIdx - 1;
    }
    const nextGrain = grains[nextIdx];
    if (nextGrain !== curGrain) {
      setFilters((prev) => {
        const next = { ...prev, date_grain: nextGrain };
        loadDashboard(next);
        return next;
      });
    }
  };

  // Export CSV of visual's aggregated data
  const handleExportChartCsv = (chart) => {
    const tableData = chart.table_data;
    if (!tableData || !tableData.rows || !tableData.rows.length) {
      toast.error("No aggregated data to export");
      return;
    }
    const cols = tableData.columns || [];
    const headerRow = cols.map((c) => `"${c.label}"`).join(",");
    const dataRows = tableData.rows.map((r) =>
      cols.map((c) => `"${r[c.key] ?? ""}"`).join(",")
    );
    const totalRow = cols.map((c) => `"${tableData.total?.[c.key] ?? ""}"`).join(",");
    const csvContent = [headerRow, ...dataRows, totalRow].join("\n");

    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${chart.title.replace(/[^a-zA-Z0-9_-]/g, "_")}_data.csv`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("Visual data exported to CSV");
  };

  // Change chart type
  const handleChangeChartType = (chartId, newType) => {
    setCharts((prev) =>
      prev.map((ch) => {
        if (ch.id !== chartId) return ch;
        const updatedFig = JSON.parse(JSON.stringify(ch.figure));
        if (updatedFig.data && updatedFig.data[0]) {
          if (newType === "bar") {
            updatedFig.data[0].type = "bar";
            updatedFig.data[0].orientation = "h";
            if (ch.x_vals && ch.y_vals) {
              updatedFig.data[0].x = [...ch.y_vals].reverse();
              updatedFig.data[0].y = [...ch.x_vals].reverse();
            }
          } else if (newType === "column") {
            updatedFig.data[0].type = "bar";
            updatedFig.data[0].orientation = "v";
            if (ch.x_vals && ch.y_vals) {
              updatedFig.data[0].x = ch.x_vals;
              updatedFig.data[0].y = ch.y_vals;
            }
          } else if (newType === "line") {
            updatedFig.data[0].type = "scatter";
            updatedFig.data[0].mode = "lines+markers";
            delete updatedFig.data[0].fill;
          } else if (newType === "area") {
            updatedFig.data[0].type = "scatter";
            updatedFig.data[0].mode = "lines";
            updatedFig.data[0].fill = "tozeroy";
          } else if (newType === "pie" || newType === "donut") {
            updatedFig.data[0].type = "pie";
            updatedFig.data[0].hole = newType === "donut" ? 0.55 : 0;
            if (ch.x_vals && ch.y_vals) {
              updatedFig.data[0].labels = ch.x_vals;
              updatedFig.data[0].values = ch.y_vals;
            }
          }
        }
        return {
          ...ch,
          chart_type: newType,
          figure: updatedFig,
        };
      })
    );
    toast.success(`Visual updated to ${newType}`);
  };

  // Remove chart
  const handleRemoveChart = (chartId) => {
    setCharts((prev) => prev.filter((ch) => ch.id !== chartId));
    toast.success("Visual removed");
  };

  // Handle Insight click: scrolls to and highlights corresponding chart
  const handleInsightClick = (chartId) => {
    if (!chartId) return;
    setHighlightedChartId(chartId);
    const el = document.getElementById(`chart-card-${chartId}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    setTimeout(() => {
      setHighlightedChartId(null);
    }, 2800);
  };

  // Download PDF Report
  const handleDownloadPdf = async () => {
    if (!ds?.id) return;
    try {
      setDownloadingPdf(true);
      await api.downloadReportPdf(
        ds.id,
        filters,
        `${(ds.name || "dataset").replace(/\.[^.]+$/, "")}_report.pdf`
      );
      toast.success("Executive report downloaded");
    } catch (err) {
      toast.error(err.message || "Failed to download PDF report");
    } finally {
      setDownloadingPdf(false);
    }
  };

  // Download Excel
  const handleExecuteExcelDownload = async () => {
    if (!ds?.id) return;
    try {
      setDownloadingExcel(true);
      const url = `/api/datasets/${ds.id}/download-excel?format=${excelFormat}&include_change_log=${includeChangeLog}&highlight_changes=${highlightChanges}`;
      const token = localStorage.getItem("dp_token");
      const headers = token ? { Authorization: `Bearer ${token}` } : {};
      const res = await fetch(url, { headers });
      if (!res.ok) throw new Error("Excel download failed");
      const blob = await res.blob();
      const objUrl = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = objUrl;
      a.download = `${(ds.name || "dataset").replace(/\.[^.]+$/, "")}_cleaned.${excelFormat}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(objUrl);
      setShowDownloadExcelDialog(false);
      toast.success("Workbook downloaded (Raw_Data & Processed_Data tabs)");
    } catch (err) {
      toast.error(err.message || "Failed to download file");
    } finally {
      setDownloadingExcel(false);
    }
  };

  // Total active slicer count
  const activeSlicersCount =
    (filters.date_min || filters.date_max ? 1 : 0) +
    (filters.cat1_vals.length > 0 ? 1 : 0) +
    (filters.cat2_vals.length > 0 ? 1 : 0) +
    (filters.cat3_vals.length > 0 ? 1 : 0) +
    (filters.cross_val ? 1 : 0);

  const kpis = dashboardData?.kpis || [];
  const insights = dashboardData?.insights || [];
  const availFilters = dashboardData?.available_filters || {};

  // Check if ratings exist
  const hasRatings = charts.some((c) => c.section === "Ratings");

  // Filter tabs
  const tabNames = useMemo(() => {
    const list = ["Overview", "Trends", "Breakdown", "Distributions"];
    if (hasRatings) list.push("Ratings");
    return list;
  }, [hasRatings]);

  // Scoped charts for active tab
  const displayCharts = useMemo(() => {
    if (activeTab === "Overview") {
      // Top 4 most impactful charts on overview
      return charts.slice(0, 4);
    }
    return charts.filter((c) => c.section === activeTab);
  }, [charts, activeTab]);

  if (loading && !dashboardData) {
    return (
      <div className="flex flex-col items-center justify-center h-full py-28 text-muted-foreground">
        <Loader2 className="w-6 h-6 animate-spin text-[#0B7A75] mb-2.5" />
        <span className="text-sm font-medium">Preparing dashboard...</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col min-h-full bg-[#f8fafc] text-foreground">
      {/* ── 1. REPORT HEADER ────────────────────────────────────────── */}
      <div className="px-6 py-3.5 bg-white border-b border-border flex flex-wrap items-center justify-between gap-3 shrink-0">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold tracking-tight text-foreground">Dashboard</h1>
          <span
            id="dashboard-dataset-name"
            className="text-xs font-semibold text-muted-foreground bg-muted/60 px-2.5 py-1 rounded-md truncate max-w-xs"
            title={dashboardData?.dataset_name || ds?.name}
          >
            {dashboardData?.dataset_name || ds?.name}
          </span>
          <span className="text-xs text-muted-foreground tabular-nums">
            {dashboardData?.filtered_rows?.toLocaleString()} / {dashboardData?.total_rows?.toLocaleString()} records
          </span>
          {dashboardData?.last_updated_at && (
            <span className="text-[11px] text-muted-foreground/80 pl-1 border-l border-border hidden sm:inline">
              Data as of {dashboardData.last_updated_at}
            </span>
          )}
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2">
          {/* Download Report (PDF) */}
          <Button
            size="sm"
            variant="outline"
            id="btn-download-pdf"
            onClick={handleDownloadPdf}
            disabled={downloadingPdf}
            className="h-8 text-xs font-medium gap-1.5 border-border text-foreground hover:bg-muted/50"
          >
            {downloadingPdf ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <FileText className="w-3.5 h-3.5 text-[#0B7A75]" />
            )}
            <span>Download report</span>
          </Button>

          {/* Download Excel */}
          <Button
            size="sm"
            id="btn-download-excel"
            onClick={() => setShowDownloadExcelDialog(true)}
            className="h-8 text-xs font-semibold gap-1.5 bg-[#0B7A75] text-white hover:bg-[#085854]"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Download Excel</span>
          </Button>
        </div>
      </div>

      {/* ── 2. REPORT PAGE TABS ─────────────────────────────────────── */}
      <div className="px-6 bg-white border-b border-border flex items-center justify-between shrink-0">
        <div className="flex items-center gap-1 -mb-px">
          {tabNames.map((tab) => {
            const isActive = activeTab === tab;
            return (
              <button
                key={tab}
                type="button"
                onClick={() => setActiveTab(tab)}
                className={cn(
                  "px-4 py-2.5 text-xs font-medium border-b-2 transition-colors",
                  isActive
                    ? "border-[#0B7A75] text-[#0B7A75] font-semibold"
                    : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
                )}
              >
                {tab}
              </button>
            );
          })}
        </div>

        {activeSlicersCount > 0 && (
          <button
            type="button"
            onClick={handleClearAllSlicers}
            className="text-[11px] font-medium text-[#0B7A75] hover:underline flex items-center gap-1"
          >
            <RotateCcw className="w-3 h-3" />
            <span>Clear all slicers ({activeSlicersCount})</span>
          </button>
        )}
      </div>

      {/* ── 3. SLICER BAR (POWER BI / TABLEAU STYLE) ────────────────── */}
      <div className="px-6 py-2.5 bg-muted/20 border-b border-border flex flex-wrap items-center gap-3 text-xs shrink-0">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
          <Filter className="w-3.5 h-3.5" />
          Slicers:
        </span>

        {/* Date Range Slicer */}
        {availFilters.date_filter && (
          <div className="flex items-center gap-1.5 bg-white border border-border rounded-md px-2.5 py-1 text-xs shadow-2xs">
            <Calendar className="w-3.5 h-3.5 text-muted-foreground" />
            <input
              type="date"
              value={filters.date_min || availFilters.date_filter.min}
              min={availFilters.date_filter.min}
              max={availFilters.date_filter.max}
              onChange={(e) => {
                const val = e.target.value;
                setFilters((prev) => {
                  const next = { ...prev, date_min: val };
                  loadDashboard(next);
                  return next;
                });
              }}
              className="border-none bg-transparent text-foreground text-xs focus:outline-none"
            />
            <span className="text-muted-foreground">to</span>
            <input
              type="date"
              value={filters.date_max || availFilters.date_filter.max}
              min={availFilters.date_filter.min}
              max={availFilters.date_filter.max}
              onChange={(e) => {
                const val = e.target.value;
                setFilters((prev) => {
                  const next = { ...prev, date_max: val };
                  loadDashboard(next);
                  return next;
                });
              }}
              className="border-none bg-transparent text-foreground text-xs focus:outline-none"
            />
          </div>
        )}

        {/* Categorical Slicers (up to 3) */}
        {availFilters.category_filters?.map((catSlicer, idx) => {
          const colIndex = idx + 1;
          const keyVals = `cat${colIndex}_vals`;
          const selectedVals = filters[keyVals] || [];
          const searchKey = `cat_${idx}`;
          const curSearch = (slicerSearches[searchKey] || "").toLowerCase();

          const filteredOptions = catSlicer.options.filter((opt) =>
            opt.label.toLowerCase().includes(curSearch)
          );

          return (
            <Popover key={catSlicer.column}>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  className={cn(
                    "flex items-center gap-1.5 bg-white border rounded-md px-2.5 py-1 text-xs shadow-2xs transition-colors",
                    selectedVals.length > 0
                      ? "border-[#0B7A75] text-[#0B7A75] font-semibold bg-[#0B7A75]/5"
                      : "border-border text-foreground hover:bg-muted/30"
                  )}
                >
                  <span>{catSlicer.label}</span>
                  {selectedVals.length > 0 && (
                    <span className="w-4 h-4 rounded-full bg-[#0B7A75] text-white text-[10px] flex items-center justify-center font-bold">
                      {selectedVals.length}
                    </span>
                  )}
                  <ChevronDown className="w-3 h-3 text-muted-foreground ml-0.5" />
                </button>
              </PopoverTrigger>
              <PopoverContent align="start" className="w-56 p-2 text-xs space-y-2">
                <div className="flex items-center gap-1.5 px-2 py-1 rounded border border-border bg-muted/20">
                  <Search className="w-3 h-3 text-muted-foreground" />
                  <input
                    type="text"
                    placeholder={`Search ${catSlicer.label}...`}
                    value={slicerSearches[searchKey] || ""}
                    onChange={(e) =>
                      setSlicerSearches((prev) => ({ ...prev, [searchKey]: e.target.value }))
                    }
                    className="w-full bg-transparent text-xs focus:outline-none"
                  />
                </div>
                <div className="max-h-48 overflow-y-auto space-y-1 pr-1">
                  {filteredOptions.length === 0 ? (
                    <div className="text-[11px] text-muted-foreground text-center py-2">
                      No matching values
                    </div>
                  ) : (
                    filteredOptions.map((opt) => {
                      const isChecked = selectedVals.includes(opt.value);
                      return (
                        <label
                          key={opt.value}
                          className="flex items-center justify-between p-1.5 rounded hover:bg-muted/40 cursor-pointer text-xs"
                        >
                          <div className="flex items-center gap-2 truncate">
                            <Checkbox
                              checked={isChecked}
                              onCheckedChange={() =>
                                handleToggleSlicerVal(colIndex, catSlicer.column, opt.value)
                              }
                            />
                            <span className="truncate">{opt.label}</span>
                          </div>
                          <span className="text-[10px] text-muted-foreground tabular-nums">
                            {opt.count}
                          </span>
                        </label>
                      );
                    })
                  )}
                </div>
              </PopoverContent>
            </Popover>
          );
        })}

        {/* Cross-Filter Indicator Pill */}
        {filters.cross_val && (
          <div className="flex items-center gap-1.5 bg-[#0B7A75]/10 border border-[#0B7A75]/30 rounded-md px-2.5 py-1 text-xs text-[#0B7A75] font-semibold">
            <span>Filtered: {filters.cross_val}</span>
            <button
              type="button"
              onClick={handleClearCrossFilter}
              className="hover:bg-[#0B7A75]/20 rounded p-0.5"
              title="Clear cross-filter"
            >
              <X className="w-3 h-3" />
            </button>
          </div>
        )}
      </div>

      {/* ── 4. MAIN CONTENT AREA ────────────────────────────────────── */}
      <div className="flex-1 p-6 space-y-6 max-w-7xl w-full mx-auto">
        {/* KPI Row (Always visible on Overview, or top of dashboard) */}
        {activeTab === "Overview" && (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            {kpis.map((kpi) => (
              <div
                key={kpi.id}
                className="bg-white border border-border rounded-xl p-3.5 shadow-2xs flex flex-col justify-between"
              >
                <div className="text-xs font-medium text-muted-foreground truncate mb-1">
                  {kpi.label}
                </div>
                <div className="text-[26px] font-bold text-foreground tracking-tight leading-tight tabular-nums">
                  {kpi.value}
                </div>
                <div className="mt-1 text-[11px] flex items-center justify-between text-muted-foreground">
                  <span>{kpi.subtext}</span>
                  {kpi.delta !== null && (
                    <span
                      className={cn(
                        "font-semibold tabular-nums inline-flex items-center gap-0.5",
                        kpi.is_positive ? "text-emerald-600" : "text-rose-600"
                      )}
                    >
                      {kpi.is_positive ? (
                        <TrendingUp className="w-3 h-3" />
                      ) : (
                        <TrendingDown className="w-3 h-3" />
                      )}
                      {kpi.delta > 0 ? `+${kpi.delta}%` : `${kpi.delta}%`}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Visual Cards Layout */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* Visuals Grid (col-span-8 or 12) */}
          <div
            className={cn(
              "space-y-6",
              activeTab === "Overview" ? "lg:col-span-8 order-2 lg:order-1" : "lg:col-span-12"
            )}
          >
            {displayCharts.length === 0 ? (
              <div className="bg-white border border-border rounded-xl p-12 text-center text-muted-foreground">
                <p className="text-sm">No visuals found for {activeTab}.</p>
                <button
                  type="button"
                  onClick={handleClearAllSlicers}
                  className="mt-3 text-xs font-semibold text-[#0B7A75] hover:underline"
                >
                  Reset slicers
                </button>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {displayCharts.map((ch) => {
                  const isHighlighted = highlightedChartId === ch.id;
                  const isTableView = !!tableViews[ch.id];
                  const hasDateDrill = !!ch.date_drill;

                  return (
                    <div
                      key={ch.id}
                      id={`chart-card-${ch.id}`}
                      className={cn(
                        "group bg-white border rounded-xl p-4 shadow-2xs transition-all duration-300 flex flex-col justify-between relative",
                        isHighlighted
                          ? "border-[#0B7A75] ring-3 ring-[#0B7A75]/30 shadow-md"
                          : "border-border hover:shadow-xs"
                      )}
                    >
                      {/* Visual Card Header */}
                      <div className="flex items-center justify-between gap-2 mb-2 pb-1.5 border-b border-border/40">
                        <div className="flex items-center gap-1.5 truncate">
                          <h3
                            className="text-sm font-semibold text-foreground truncate"
                            title={ch.title}
                          >
                            {ch.title}
                          </h3>
                        </div>

                        {/* Hover Toolbar (Focus, Filters, Table toggle, Export CSV, More) */}
                        <div className="flex items-center gap-1 opacity-90 sm:opacity-0 group-hover:opacity-100 transition-opacity">
                          {/* Date Drill Controls */}
                          {hasDateDrill && (
                            <div className="flex items-center border border-border rounded px-1 py-0.5 bg-muted/20 mr-1 text-[10px]">
                              <button
                                type="button"
                                onClick={() => handleDateDrill(ch.id, "up")}
                                className="p-0.5 hover:text-[#0B7A75]"
                                title="Drill Up (Grain)"
                              >
                                <ChevronUp className="w-3 h-3" />
                              </button>
                              <span className="px-1 font-medium capitalize text-muted-foreground">
                                {filters.date_grain || "Month"}
                              </span>
                              <button
                                type="button"
                                onClick={() => handleDateDrill(ch.id, "down")}
                                className="p-0.5 hover:text-[#0B7A75]"
                                title="Drill Down (Grain)"
                              >
                                <ChevronDown className="w-3 h-3" />
                              </button>
                            </div>
                          )}

                          {/* Focus Mode */}
                          <button
                            type="button"
                            data-action="focus-mode"
                            onClick={() => setFocusedChart(ch)}
                            className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
                            title="Focus mode (full screen)"
                          >
                            <Maximize2 className="w-3.5 h-3.5" />
                          </button>

                          {/* Active Filters Popover */}
                          <Popover>
                            <PopoverTrigger asChild>
                              <button
                                type="button"
                                data-action="visual-filters"
                                className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
                                title="Visual filters"
                              >
                                <Filter className="w-3.5 h-3.5" />
                              </button>
                            </PopoverTrigger>
                            <PopoverContent align="end" className="w-56 p-2.5 text-xs space-y-1.5">
                              <div className="font-semibold text-foreground">Active Filters</div>
                              <div className="text-[11px] text-muted-foreground space-y-1">
                                <div>• Metric: {ch.fields?.y || "Count"}</div>
                                <div>• Dimension: {ch.fields?.x || "None"}</div>
                                {filters.cross_val && <div>• Cross-filtered: {filters.cross_val}</div>}
                                {activeSlicersCount === 0 && <div>• All records included</div>}
                              </div>
                            </PopoverContent>
                          </Popover>

                          {/* Show as Table Toggle */}
                          <button
                            type="button"
                            data-action="toggle-table"
                            onClick={() =>
                              setTableViews((prev) => ({ ...prev, [ch.id]: !prev[ch.id] }))
                            }
                            className={cn(
                              "p-1 rounded transition-colors",
                              isTableView
                                ? "text-[#0B7A75] bg-[#0B7A75]/10 font-bold"
                                : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                            )}
                            title={isTableView ? "Show as visual" : "Show as table"}
                          >
                            <TableIcon className="w-3.5 h-3.5" />
                          </button>

                          {/* Export CSV */}
                          <button
                            type="button"
                            data-action="export-csv"
                            onClick={() => handleExportChartCsv(ch)}
                            className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
                            title="Export data (CSV)"
                          >
                            <Download className="w-3.5 h-3.5" />
                          </button>

                          {/* More dropdown */}
                          <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                              <button
                                type="button"
                                className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
                                aria-label="More visual options"
                              >
                                <MoreVertical className="w-3.5 h-3.5" />
                              </button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="end" className="w-44 text-xs">
                              {ch.compatible_types?.length > 1 && (
                                <DropdownMenuSub>
                                  <DropdownMenuSubTrigger className="text-xs">
                                    Change chart type
                                  </DropdownMenuSubTrigger>
                                  <DropdownMenuSubContent className="w-36 text-xs">
                                    {ch.compatible_types.map((t) => (
                                      <DropdownMenuItem
                                        key={t}
                                        onClick={() => handleChangeChartType(ch.id, t)}
                                        className="capitalize text-xs"
                                      >
                                        {t === ch.chart_type && (
                                          <Check className="w-3 h-3 mr-1 text-[#0B7A75]" />
                                        )}
                                        {t}
                                      </DropdownMenuItem>
                                    ))}
                                  </DropdownMenuSubContent>
                                </DropdownMenuSub>
                              )}
                              <DropdownMenuItem
                                onClick={() => handleRemoveChart(ch.id)}
                                className="text-rose-600 focus:text-rose-600 text-xs gap-1.5"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                                <span>Remove visual</span>
                              </DropdownMenuItem>
                            </DropdownMenuContent>
                          </DropdownMenu>
                        </div>
                      </div>

                      {/* Visual Graphic or Table View */}
                      <div className="h-64 w-full">
                        {isTableView ? (
                          <div className="h-full w-full overflow-auto rounded border border-border/60 bg-white text-xs">
                            <table className="w-full text-left border-collapse">
                              <thead>
                                <tr className="border-b border-border text-[11px] text-muted-foreground uppercase bg-muted/20">
                                  {ch.table_data?.columns?.map((col) => (
                                    <th key={col.key} className="p-2 font-semibold">
                                      {col.label}
                                    </th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody className="divide-y divide-border/40">
                                {ch.table_data?.rows?.map((row, rIdx) => (
                                  <tr
                                    key={rIdx}
                                    onClick={() => handleCrossFilter(ch.fields?.x, row.category)}
                                    className="hover:bg-[#0B7A75]/5 cursor-pointer relative group/row"
                                  >
                                    <td className="p-2 font-medium truncate max-w-xs">{row.category}</td>
                                    <td className="p-2 tabular-nums relative">
                                      {/* Conditional Data Bar */}
                                      <div
                                        style={{ width: `${row.percent_of_max || 0}%` }}
                                        className="absolute inset-y-1 left-0 bg-[#0B7A75]/15 rounded-sm pointer-events-none"
                                      />
                                      <span className="relative z-10 font-semibold text-foreground">
                                        {row.formatted_value}
                                      </span>
                                    </td>
                                    <td className="p-2 tabular-nums text-muted-foreground">
                                      {row.percent_of_total}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                              {ch.table_data?.total && (
                                <tfoot>
                                  <tr className="border-t-2 border-border font-bold bg-muted/10 text-foreground">
                                    <td className="p-2">{ch.table_data.total.category}</td>
                                    <td className="p-2 tabular-nums">{ch.table_data.total.formatted_value}</td>
                                    <td className="p-2 tabular-nums">{ch.table_data.total.percent_of_total}</td>
                                  </tr>
                                </tfoot>
                              )}
                            </table>
                          </div>
                        ) : (
                          <ChartWrapper
                            data={ch.figure?.data || []}
                            layout={ch.figure?.layout || {}}
                            height={256}
                            showTableToggle={false}
                            onPlotClick={(e) => {
                              if (e && e.points && e.points[0]) {
                                const pt = e.points[0];
                                const clickedVal = pt.x !== undefined ? pt.x : pt.label;
                                if (clickedVal && ch.fields?.x) {
                                  handleCrossFilter(ch.fields.x, clickedVal);
                                }
                              }
                            }}
                          />
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Key Insights Card (Right column on Overview) */}
          {activeTab === "Overview" && (
            <div className="lg:col-span-4 order-1 lg:order-2 space-y-4">
              <div className="bg-white border border-border rounded-xl p-5 shadow-2xs">
                <div className="flex items-center justify-between pb-3 border-b border-border">
                  <div className="flex items-center gap-2">
                    <Info className="w-4 h-4 text-[#0B7A75]" />
                    <h2 className="text-sm font-semibold text-foreground">Key insights</h2>
                  </div>
                  <span className="text-[11px] text-muted-foreground font-medium">
                    {insights.length} observations
                  </span>
                </div>

                <div className="divide-y divide-border/60">
                  {insights.map((ins, idx) => (
                    <div
                      key={ins.id || idx}
                      onClick={() => handleInsightClick(ins.chart_id)}
                      className="py-3 cursor-pointer group transition-colors"
                      title={ins.calculation_info ? `Calculation: ${ins.calculation_info}` : "Click to view chart"}
                    >
                      <div className="flex items-start gap-2.5">
                        <span className="text-xs font-bold text-[#0B7A75] tabular-nums mt-0.5">
                          {idx + 1}.
                        </span>
                        <div className="flex-1 text-xs text-foreground group-hover:text-[#0B7A75] transition-colors leading-relaxed">
                          {ins.text}
                        </div>
                        <ChevronRight className="w-3.5 h-3.5 text-muted-foreground/50 group-hover:text-[#0B7A75] shrink-0 mt-0.5 opacity-0 group-hover:opacity-100 transition-opacity" />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── 5. FOCUS MODE FULL-SCREEN MODAL ─────────────────────────── */}
      <Dialog open={!!focusedChart} onOpenChange={(open) => !open && setFocusedChart(null)}>
        <DialogContent className="max-w-5xl w-[95vw] h-[85vh] flex flex-col p-6">
          <DialogHeader className="flex flex-row items-center justify-between pb-2 border-b border-border">
            <div>
              <DialogTitle className="text-lg font-bold">{focusedChart?.title}</DialogTitle>
              <DialogDescription className="text-xs text-muted-foreground">
                Section: {focusedChart?.section} · Interactive Focus Mode
              </DialogDescription>
            </div>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => focusedChart && handleExportChartCsv(focusedChart)}
                className="h-8 text-xs gap-1.5"
              >
                <Download className="w-3.5 h-3.5" />
                <span>Export CSV</span>
              </Button>
            </div>
          </DialogHeader>

          <div className="flex-1 w-full py-4 min-h-0">
            {focusedChart && (
              <ChartWrapper
                data={focusedChart.figure?.data || []}
                layout={{
                  ...(focusedChart.figure?.layout || {}),
                  margin: { l: 60, r: 30, t: 40, b: 60 },
                }}
                height={520}
                showTableToggle={true}
                onPlotClick={(e) => {
                  if (e && e.points && e.points[0]) {
                    const pt = e.points[0];
                    const clickedVal = pt.x !== undefined ? pt.x : pt.label;
                    if (clickedVal && focusedChart.fields?.x) {
                      handleCrossFilter(focusedChart.fields.x, clickedVal);
                    }
                  }
                }}
              />
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* ── 6. DOWNLOAD EXCEL DIALOG ─────────────────────────────────── */}
      <Dialog open={showDownloadExcelDialog} onOpenChange={setShowDownloadExcelDialog}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">Download Excel Workbook</DialogTitle>
            <DialogDescription className="text-xs text-muted-foreground">
              Contains Raw_Data tab first, Processed_Data tab second.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2 text-xs">
            <div className="space-y-2">
              <label className="font-semibold text-foreground">File format</label>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => setExcelFormat("xlsx")}
                  className={cn(
                    "p-2.5 rounded-lg border text-left flex items-center justify-between",
                    excelFormat === "xlsx"
                      ? "border-[#0B7A75] bg-[#0B7A75]/5 text-[#0B7A75] font-semibold"
                      : "border-border text-foreground hover:bg-muted/40"
                  )}
                >
                  <div>
                    <div className="font-medium">.xlsx</div>
                    <div className="text-[10px] text-muted-foreground">Excel Workbook</div>
                  </div>
                  {excelFormat === "xlsx" && <Check className="w-4 h-4 text-[#0B7A75]" />}
                </button>

                <button
                  type="button"
                  onClick={() => setExcelFormat("csv")}
                  className={cn(
                    "p-2.5 rounded-lg border text-left flex items-center justify-between",
                    excelFormat === "csv"
                      ? "border-[#0B7A75] bg-[#0B7A75]/5 text-[#0B7A75] font-semibold"
                      : "border-border text-foreground hover:bg-muted/40"
                  )}
                >
                  <div>
                    <div className="font-medium">.csv</div>
                    <div className="text-[10px] text-muted-foreground">Cleaned Data Only</div>
                  </div>
                  {excelFormat === "csv" && <Check className="w-4 h-4 text-[#0B7A75]" />}
                </button>
              </div>
            </div>

            {excelFormat === "xlsx" && (
              <div className="space-y-2.5 pt-1">
                <label className="flex items-center gap-2 cursor-pointer">
                  <Checkbox
                    checked={includeChangeLog}
                    onCheckedChange={(c) => setIncludeChangeLog(!!c)}
                  />
                  <span className="text-xs text-foreground font-medium">
                    Include Change_Log tab (audit trail)
                  </span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <Checkbox
                    checked={highlightChanges}
                    onCheckedChange={(c) => setHighlightChanges(!!c)}
                  />
                  <span className="text-xs text-foreground font-medium">
                    Highlight modified cells in yellow tint
                  </span>
                </label>
              </div>
            )}
          </div>

          <DialogFooter className="flex justify-end gap-2 pt-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowDownloadExcelDialog(false)}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={handleExecuteExcelDownload}
              disabled={downloadingExcel}
              className="bg-[#0B7A75] text-white hover:bg-[#085854]"
            >
              {downloadingExcel ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" />
              ) : (
                <Download className="w-3.5 h-3.5 mr-1.5" />
              )}
              <span>Download</span>
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
