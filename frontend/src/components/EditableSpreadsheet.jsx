import React, { useState, useEffect, useRef, useMemo, useCallback } from "react";
import {
  FileSpreadsheet,
  Download,
  Play,
  CheckCircle2,
  AlertCircle,
  AlertOctagon,
  TrendingUp,
  Type,
  Copy,
  ShieldAlert,
  AlertTriangle,
  RotateCcw,
  Undo2,
  Redo2,
  ChevronLeft,
  ChevronRight,
  Search,
  MoreVertical,
  Check,
  X,
  Key,
  Hash,
  Calendar,
  Mail,
  Phone,
  ArrowRight,
  ChevronDown,
  Loader2,
  SlidersHorizontal,
} from "lucide-react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { Input } from "./ui/input";
import { Checkbox } from "./ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "./ui/dialog";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuSubContent,
} from "./ui/dropdown-menu";
import { api, downloadFile } from "../api";
import { toast } from "sonner";
import { cn } from "../lib/utils";

// ── Issue styling configuration ─────────────────────────────────────────────
const ISSUE_CONFIG = {
  missing: {
    color: "amber",
    bg: "bg-amber-500/15",
    text: "text-amber-800 dark:text-amber-300",
    border: "border-amber-400",
    icon: AlertCircle,
    label: "Missing",
  },
  invalid_format: {
    color: "red",
    bg: "bg-red-500/15",
    text: "text-red-800 dark:text-red-300",
    border: "border-red-400",
    icon: AlertOctagon,
    label: "Invalid",
  },
  outlier: {
    color: "orange",
    bg: "bg-orange-500/15",
    text: "text-orange-800 dark:text-orange-300",
    border: "border-orange-400",
    icon: TrendingUp,
    label: "Outlier",
  },
  typo: {
    color: "yellow",
    bg: "bg-yellow-500/15",
    text: "text-yellow-800 dark:text-yellow-300",
    border: "border-yellow-400",
    icon: Type,
    label: "Typo",
  },
  wrong_type: {
    color: "blue",
    bg: "bg-blue-500/15",
    text: "text-blue-800 dark:text-blue-300",
    border: "border-blue-400",
    icon: AlertTriangle,
    label: "Wrong type",
  },
  duplicate: {
    color: "grey",
    bg: "bg-zinc-500/15",
    text: "text-zinc-700 dark:text-zinc-300",
    border: "border-zinc-400",
    icon: Copy,
    label: "Duplicate",
  },
  personal_data: {
    color: "purple",
    bg: "bg-purple-500/15",
    text: "text-purple-800 dark:text-purple-300",
    border: "border-purple-400",
    icon: ShieldAlert,
    label: "Personal data",
  },
};

const EMAIL_RE = /^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$/;

// Get column type icon
function getColumnTypeIcon(category) {
  switch (category) {
    case "id":
      return <Key className="w-3.5 h-3.5 text-muted-foreground shrink-0" />;
    case "money":
    case "number":
      return <Hash className="w-3.5 h-3.5 text-muted-foreground shrink-0" />;
    case "date":
      return <Calendar className="w-3.5 h-3.5 text-muted-foreground shrink-0" />;
    case "email":
      return <Mail className="w-3.5 h-3.5 text-muted-foreground shrink-0" />;
    case "phone":
      return <Phone className="w-3.5 h-3.5 text-muted-foreground shrink-0" />;
    default:
      return <Type className="w-3.5 h-3.5 text-muted-foreground shrink-0" />;
  }
}

// Client-side validation matching backend semantics
function validateInput(value, colMeta) {
  const valClean = String(value ?? "").trim();
  if (valClean === "") return { isValid: true, error: "" };

  const semType = colMeta?.semantic_type || "";
  const typeCat = colMeta?.type_category || "";

  if (typeCat === "number" || typeCat === "money") {
    const cleaned = valClean.replace(/[^0-9.-]/g, "");
    if (cleaned === "" || isNaN(Number(cleaned))) {
      return { isValid: false, error: "Must be a valid number" };
    }
  } else if (typeCat === "date" || semType === "date") {
    const parsed = Date.parse(valClean);
    if (isNaN(parsed)) {
      return { isValid: false, error: "Must be a valid date (YYYY-MM-DD)" };
    }
  } else if (typeCat === "email" || semType === "email") {
    if (!EMAIL_RE.test(valClean)) {
      return { isValid: false, error: "Must be a valid email (user@domain.com)" };
    }
  } else if (typeCat === "phone" || semType === "phone") {
    const digits = valClean.replace(/\D/g, "");
    if (digits.length < 7 || digits.length > 15) {
      return { isValid: false, error: "Must contain 7 to 15 digits" };
    }
  }

  return { isValid: true, error: "" };
}

export default function EditableSpreadsheet({
  ds,
  onRefresh,
  onRunCompleteClean,
  cleaning = false,
  onDownloadExcel,
  onFinishCleaning,
}) {
  // Grid data state
  const [loading, setLoading] = useState(true);
  const [columns, setColumns] = useState([]);
  const [rows, setRows] = useState([]);
  const [totalRows, setTotalRows] = useState(0);

  // Issues and stats
  const [issuesData, setIssuesData] = useState({
    total: 0,
    counts_by_type: {},
    counts_by_column: {},
    ordered_issues: [],
    resolved_count: 0,
    initial_total: 0,
  });
  const [currentIssueIdx, setCurrentIssueIdx] = useState(-1);

  // View state: "cleaned" | "original" | "changes_only"
  const [activeView, setActiveView] = useState("cleaned");
  const [searchQuery, setSearchQuery] = useState("");
  const [activeIssueFilter, setActiveIssueFilter] = useState(null);
  const [activeColumnFilter, setActiveColumnFilter] = useState(null);

  // Versioning & Undo/Redo
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);

  // Column width state in pixels
  const [colWidths, setColWidths] = useState({});

  // Active cell & Keyboard selection
  const [selectedCell, setSelectedCell] = useState(null); // { rowIdx, colName }
  const [editingCell, setEditingCell] = useState(null); // { rowIdx, colName, value, error }

  // Hover / Focus Popover state
  const [popoverState, setPopoverState] = useState(null);
  // { row, col, issueType, anchorRect, isMobile }
  const [suggestionData, setSuggestionData] = useState(null);
  const [loadingSuggestion, setLoadingSuggestion] = useState(false);
  const [popoverScope, setPopoverScope] = useState("cell"); // "cell" | "column"
  const [customInputValue, setCustomInputValue] = useState("");
  const [showCustomInput, setShowCustomInput] = useState(false);

  // Confirm "Fix All" popover
  const [showFixAllConfirm, setShowFixAllConfirm] = useState(false);
  const [fixingAll, setFixingAll] = useState(false);

  // Download Excel Dialog
  const [showDownloadDialog, setShowDownloadDialog] = useState(false);
  const [downloadFormat, setDownloadFormat] = useState("xlsx");
  const [includeChangeLog, setIncludeChangeLog] = useState(true);
  const [highlightChanges, setHighlightChanges] = useState(false);
  const [downloading, setDownloading] = useState(false);

  // Finish Cleaning Confirm Dialog & Clean Check
  const [showFinishConfirm, setShowFinishConfirm] = useState(false);
  const [cleanCheck, setCleanCheck] = useState(null);
  const [showDecisionDrawer, setShowDecisionDrawer] = useState(false);
  const [autoFixedCount, setAutoFixedCount] = useState(0);
  const [autoFixedBreakdown, setAutoFixedBreakdown] = useState({});

  // Refs
  const gridContainerRef = useRef(null);
  const hoverTimerRef = useRef(null);
  const popoverRef = useRef(null);

  // Column Resizing Refs
  const resizingColRef = useRef(null);
  const startXRef = useRef(0);
  const startWidthRef = useRef(0);

  // Load grid rows from backend
  const fetchGridData = useCallback(async () => {
    if (!ds?.id) return;
    try {
      setLoading(true);
      const res = await api.getGrid(ds.id, {
        limit: 500,
        view: activeView,
        search: searchQuery || undefined,
        issueFilter: activeIssueFilter || undefined,
        columnFilter: activeColumnFilter || undefined,
      });

      if (res) {
        setColumns(res.columns || []);
        setRows(res.rows || []);
        setTotalRows(res.total_rows || 0);
        setCanUndo(res.can_undo || false);
        setCanRedo(res.can_redo || false);
      }
    } catch (err) {
      toast.error(err.message || "Failed to load spreadsheet grid");
    } finally {
      setLoading(false);
    }
  }, [ds?.id, activeView, searchQuery, activeIssueFilter, activeColumnFilter]);

  // Load issues list & summary
  const fetchIssuesData = useCallback(async () => {
    if (!ds?.id) return;
    try {
      const res = await api.getIssues(ds.id);
      if (res) {
        setIssuesData(res);
      }
    } catch {
      // non-blocking
    }
  }, [ds?.id]);

  // Load Clean Check state
  const fetchCleanCheckData = useCallback(async () => {
    if (!ds?.id) return;
    try {
      const res = await api.getCleanCheck(ds.id);
      if (res) {
        setCleanCheck(res);
      }
    } catch {
      // non-blocking
    }
  }, [ds?.id]);

  useEffect(() => {
    fetchGridData();
    fetchIssuesData();
    fetchCleanCheckData();
  }, [fetchGridData, fetchIssuesData, fetchCleanCheckData, ds?.current_version]);

  // Virtualizer for 50k+ rows
  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => gridContainerRef.current,
    estimateSize: () => 36,
    overscan: 10,
  });

  // Global Keyboard shortcuts: Ctrl+Z, Ctrl+Y, Esc
  useEffect(() => {
    const handleKeyDown = async (e) => {
      // Undo: Ctrl+Z (without shift)
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !e.shiftKey) {
        e.preventDefault();
        if (canUndo && ds?.id) {
          try {
            await api.undoGrid(ds.id);
            toast.success("Action undone");
            if (onRefresh) await onRefresh();
            fetchGridData();
            fetchIssuesData();
          } catch (err) {
            toast.error(err.message || "Undo failed");
          }
        }
      }
      // Redo: Ctrl+Y or Ctrl+Shift+Z
      if (
        ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") ||
        ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === "z")
      ) {
        e.preventDefault();
        if (canRedo && ds?.id) {
          try {
            await api.redoGrid(ds.id);
            toast.success("Action redone");
            if (onRefresh) await onRefresh();
            fetchGridData();
            fetchIssuesData();
          } catch (err) {
            toast.error(err.message || "Redo failed");
          }
        }
      }
      // Close popover on Esc
      if (e.key === "Escape") {
        if (editingCell) {
          setEditingCell(null);
        } else if (popoverState) {
          closePopover();
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [canUndo, canRedo, ds?.id, onRefresh, fetchGridData, fetchIssuesData, editingCell, popoverState]);

  // Close popover when clicked outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target) &&
        !e.target.closest("[data-popover-trigger]")
      ) {
        closePopover();
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const closePopover = () => {
    setPopoverState(null);
    setSuggestionData(null);
    setShowCustomInput(false);
    setCustomInputValue("");
    if (hoverTimerRef.current) {
      clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }
  };

  // Open Popover for an issue cell
  const openPopover = async (rowIdx, colName, issueType, rect) => {
    if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current);
    const isMobile = window.innerWidth < 640;
    setPopoverState({
      row: rowIdx,
      col: colName,
      issueType,
      anchorRect: rect,
      isMobile,
    });
    setPopoverScope("cell");
    setShowCustomInput(false);
    setLoadingSuggestion(true);

    try {
      const sug = await api.getSuggest(ds.id, colName, issueType, rowIdx);
      setSuggestionData(sug);
    } catch {
      toast.error("Could not load suggestion");
      closePopover();
    } finally {
      setLoadingSuggestion(false);
    }
  };

  // Hover trigger with 300ms delay
  const handleCellMouseEnter = (rowIdx, colName, issues, e) => {
    if (editingCell || (popoverState && popoverState.row === rowIdx && popoverState.col === colName)) {
      return;
    }
    if (!issues || issues.length === 0) return;

    if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current);
    const rect = e.currentTarget.getBoundingClientRect();
    const primaryIssue = issues[0].type;

    hoverTimerRef.current = setTimeout(() => {
      openPopover(rowIdx, colName, primaryIssue, rect);
    }, 300);
  };

  const handleCellMouseLeave = () => {
    if (hoverTimerRef.current) {
      clearTimeout(hoverTimerRef.current);
      hoverTimerRef.current = null;
    }
  };

  // Apply suggestion or alternative option
  const handleApplyFix = async (strategy, value = null) => {
    if (!popoverState || !ds?.id) return;
    const { row, col, issueType } = popoverState;
    const targetVal = value !== null ? value : suggestionData?.suggested_value;

    try {
      const res = await api.applyFix(ds.id, {
        issue_type: issueType,
        column: col,
        row: popoverScope === "cell" ? row : undefined,
        strategy,
        value: targetVal,
        scope: popoverScope,
      });

      const changedCount = res.affected_count || 1;
      closePopover();

      // Toast with single-click Undo action!
      toast.success(`Applied fix to ${changedCount} cell${changedCount > 1 ? "s" : ""}`, {
        action: {
          label: "Undo",
          onClick: async () => {
            try {
              await api.undoGrid(ds.id);
              toast.success("Fix undone");
              if (onRefresh) await onRefresh();
              fetchGridData();
              fetchIssuesData();
            } catch {
              toast.error("Failed to undo fix");
            }
          },
        },
      });

      if (onRefresh) await onRefresh();
      fetchGridData();
      fetchIssuesData();
    } catch (err) {
      toast.error(err.message || "Failed to apply fix");
    }
  };

  // Revert single cell to original upload value
  const handleRevertCell = async (row, column) => {
    if (!ds?.id) return;
    try {
      await api.revertCell(ds.id, row, column);
      toast.success(`Reverted row ${row + 1}, column "${column}" to original upload`);
      if (onRefresh) await onRefresh();
      fetchGridData();
      fetchIssuesData();
    } catch (err) {
      toast.error(err.message || "Failed to revert cell");
    }
  };

  // Save manual cell edit
  const handleCommitCellEdit = async () => {
    if (!editingCell || !ds?.id) return;
    const { rowIdx, colName, value } = editingCell;
    const colMeta = columns.find((c) => c.name === colName);
    const validation = validateInput(value, colMeta);

    if (!validation.isValid) {
      setEditingCell((prev) => ({ ...prev, error: validation.error }));
      return;
    }

    try {
      await api.batchUpdateCells(ds.id, [
        { row: rowIdx, column: colName, value },
      ]);

      toast.success(`Updated row ${rowIdx + 1}, column "${colName}"`);
      setEditingCell(null);
      if (onRefresh) await onRefresh();
      fetchGridData();
      fetchIssuesData();
    } catch (err) {
      setEditingCell((prev) => ({ ...prev, error: err.message || "Failed to save" }));
    }
  };

  // Fill Down: Copies value of selected cell to next row(s)
  const handleFillDown = async () => {
    if (!selectedCell || !ds?.id) return;
    const { rowIdx, colName } = selectedCell;
    const sourceRow = rows.find((r) => r._row_index === rowIdx);
    if (!sourceRow) return;

    const sourceVal = sourceRow._cells?.[colName]?.val;
    const nextRow = rows.find((r) => r._row_index === rowIdx + 1);
    if (!nextRow) {
      toast.info("No row below to fill down");
      return;
    }

    try {
      await api.batchUpdateCells(ds.id, [
        { row: rowIdx + 1, column: colName, value: sourceVal },
      ]);
      toast.success(`Filled down to row ${rowIdx + 2}`);
      if (onRefresh) await onRefresh();
      fetchGridData();
      fetchIssuesData();
    } catch (err) {
      toast.error(err.message || "Fill down failed");
    }
  };

  // Paste from Excel handler
  const handlePaste = async (e) => {
    if (!selectedCell || !ds?.id) return;
    const text = e.clipboardData.getData("text/plain");
    if (!text) return;

    e.preventDefault();
    const pasteRows = text.split(/\r?\n/).filter((r) => r.length > 0);
    const startRowIdx = selectedCell.rowIdx;
    const startColIdx = columns.findIndex((c) => c.name === selectedCell.colName);
    if (startColIdx === -1) return;

    const edits = [];
    pasteRows.forEach((rowStr, rOffset) => {
      const cellValues = rowStr.split("\t");
      cellValues.forEach((val, cOffset) => {
        const targetCol = columns[startColIdx + cOffset];
        const targetRowIdx = startRowIdx + rOffset;
        if (targetCol && targetRowIdx < totalRows) {
          edits.push({
            row: targetRowIdx,
            column: targetCol.name,
            value: val.trim(),
          });
        }
      });
    });

    if (edits.length === 0) return;

    try {
      await api.batchUpdateCells(ds.id, edits);
      toast.success(`Pasted ${edits.length} cell(s) from clipboard`);
      if (onRefresh) await onRefresh();
      fetchGridData();
      fetchIssuesData();
    } catch (err) {
      toast.error(err.message || "Failed to paste cells");
    }
  };

  // Next / Previous Issue Navigation
  const navigateToIssue = (direction) => {
    const list = issuesData.ordered_issues || [];
    if (list.length === 0) return;

    let nextIdx = direction === "next" ? currentIssueIdx + 1 : currentIssueIdx - 1;
    if (nextIdx >= list.length) nextIdx = 0;
    if (nextIdx < 0) nextIdx = list.length - 1;

    setCurrentIssueIdx(nextIdx);
    const targetIssue = list[nextIdx];
    if (targetIssue) {
      setSelectedCell({ rowIdx: targetIssue.row, colName: targetIssue.column });
      // Scroll into view
      rowVirtualizer.scrollToIndex(Math.max(0, targetIssue.row - 2), { align: "start" });
    }
  };

  // Fix All Suggested handler
  const handleExecuteFixAll = async () => {
    if (!ds?.id) return;
    setFixingAll(true);
    try {
      const res = await api.fixAllSuggested(ds.id);
      setShowFixAllConfirm(false);
      setAutoFixedCount((prev) => prev + (res.total_resolved || 0));
      if (res.changes_by_rule) {
        setAutoFixedBreakdown(res.changes_by_rule);
      }
      if (res.clean_check) {
        setCleanCheck(res.clean_check);
      }
      toast.success(`Resolved ${res.total_resolved || 0} issues across automated passes!`, {
        action: {
          label: "Undo",
          onClick: async () => {
            await api.undoGrid(ds.id);
            if (onRefresh) await onRefresh();
            fetchGridData();
            fetchIssuesData();
          },
        },
      });
      if (onRefresh) await onRefresh();
      fetchGridData();
      fetchIssuesData();
    } catch (err) {
      toast.error(err.message || "Fix all failed");
    } finally {
      setFixingAll(false);
    }
  };

  // Column Action handler (header menu)
  const handleColumnAction = async (colName, action, params = {}) => {
    if (!ds?.id) return;
    try {
      await api.columnAction(ds.id, { column: colName, action, params });
      toast.success(`Applied ${action} to "${colName}"`);
      if (onRefresh) await onRefresh();
      fetchGridData();
      fetchIssuesData();
    } catch (err) {
      toast.error(err.message || "Column action failed");
    }
  };

  // Download Excel / CSV submission
  const handleExecuteDownload = async () => {
    if (!ds?.id) return;
    setDownloading(true);
    try {
      const p = new URLSearchParams({
        format: downloadFormat,
        include_change_log: String(includeChangeLog),
        highlight_changes: String(highlightChanges),
      });

      const endpoint = `/datasets/${ds.id}/download-excel?${p.toString()}`;
      const ext = downloadFormat === "csv" ? "csv" : "xlsx";
      await downloadFile(endpoint, `${ds.name || "dataset"}_cleaned.${ext}`);
      toast.success(`Downloaded ${downloadFormat.toUpperCase()} file`);
      setShowDownloadDialog(false);
    } catch (err) {
      toast.error(err.message || "Download failed");
    } finally {
      setDownloading(false);
    }
  };

  // Column resizing mouse event handlers
  const onResizeMouseDown = (colName, e) => {
    e.stopPropagation();
    resizingColRef.current = colName;
    startXRef.current = e.clientX;
    startWidthRef.current = colWidths[colName] || 150;

    const onMouseMove = (moveEvt) => {
      if (!resizingColRef.current) return;
      const delta = moveEvt.clientX - startXRef.current;
      const newWidth = Math.max(80, startWidthRef.current + delta);
      setColWidths((prev) => ({ ...prev, [resizingColRef.current]: newWidth }));
    };

    const onMouseUp = () => {
      resizingColRef.current = null;
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  };

  // Progress meter ratio
  const progressRatio = useMemo(() => {
    const total = issuesData.initial_total || (issuesData.total + issuesData.resolved_count);
    if (!total || total === 0) return 100;
    return Math.min(100, Math.round((issuesData.resolved_count / total) * 100));
  }, [issuesData]);

  return (
    <div className="space-y-3" onPaste={handlePaste}>
      {/* ── 1. MAIN TOOLBAR (Controls, Views, Fix All, Download) ─────── */}
      <div className="bg-card border border-border rounded-xl p-3.5 shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-3">
        {/* Left: Dataset info + Undo/Redo + View Switch */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0">
              <FileSpreadsheet className="w-4 h-4" strokeWidth={1.75} />
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <span className="font-semibold text-xs sm:text-sm text-foreground truncate max-w-[160px] sm:max-w-[220px]">
                  {ds?.name || "Active Sheet"}
                </span>
                <Badge variant="secondary" className="text-[10px] font-mono h-4 px-1.5">
                  v{ds?.current_version || 1}
                </Badge>
              </div>
              <p className="text-[11px] text-muted-foreground font-mono">
                {totalRows.toLocaleString()} rows · {columns.length} columns
              </p>
            </div>
          </div>

          <div className="h-6 w-px bg-border hidden sm:block" />

          {/* Undo / Redo controls */}
          <div className="flex items-center gap-1">
            <Button
              size="icon"
              variant="outline"
              className="w-7 h-7"
              disabled={!canUndo}
              onClick={async () => {
                await api.undoGrid(ds.id);
                toast.success("Action undone");
                if (onRefresh) await onRefresh();
                fetchGridData();
                fetchIssuesData();
              }}
              title="Undo (Ctrl+Z)"
              aria-label="Undo"
            >
              <Undo2 className="w-3.5 h-3.5" />
            </Button>
            <Button
              size="icon"
              variant="outline"
              className="w-7 h-7"
              disabled={!canRedo}
              onClick={async () => {
                await api.redoGrid(ds.id);
                toast.success("Action redone");
                if (onRefresh) await onRefresh();
                fetchGridData();
                fetchIssuesData();
              }}
              title="Redo (Ctrl+Y)"
              aria-label="Redo"
            >
              <Redo2 className="w-3.5 h-3.5" />
            </Button>
          </div>

          <div className="h-6 w-px bg-border hidden sm:block" />

          {/* View Switch: Original | Cleaned | Changes only */}
          <div className="inline-flex rounded-lg border border-border p-0.5 bg-muted/40 text-[11px] font-medium">
            <button
              type="button"
              id="btn-view-original"
              onClick={() => setActiveView("original")}
              className={cn(
                "px-2.5 py-1 rounded-md transition-all select-none",
                activeView === "original"
                  ? "bg-background text-foreground shadow-xs font-semibold"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              Original
            </button>
            <button
              type="button"
              id="btn-view-cleaned"
              onClick={() => setActiveView("cleaned")}
              className={cn(
                "px-2.5 py-1 rounded-md transition-all select-none",
                activeView === "cleaned"
                  ? "bg-background text-foreground shadow-xs font-semibold"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              Cleaned
            </button>
            <button
              type="button"
              id="btn-view-changes"
              onClick={() => setActiveView("changes_only")}
              className={cn(
                "px-2.5 py-1 rounded-md transition-all select-none",
                activeView === "changes_only"
                  ? "bg-background text-foreground shadow-xs font-semibold"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              Changes only
            </button>
          </div>
        </div>

        {/* Right: Fix All Suggested & Download Excel */}
        <div className="flex items-center gap-2">
          {/* Fix all suggested */}
          <DropdownMenu open={showFixAllConfirm} onOpenChange={setShowFixAllConfirm}>
            <DropdownMenuTrigger asChild>
              <Button
                size="sm"
                id="btn-fix-all-suggested"
                disabled={issuesData.total === 0 || fixingAll}
                className="gap-1.5 h-8 text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90"
              >
                {fixingAll ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <CheckCircle2 className="w-3.5 h-3.5" />
                )}
                <span>Fix all suggested</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-64 p-3 space-y-2.5 text-xs">
              <div className="font-semibold text-foreground">Confirm batch clean</div>
              <p className="text-muted-foreground text-[11px] leading-relaxed">
                Applies high-confidence suggestions according to semantic rules. Low-confidence and restricted cells (IDs, PII) stay highlighted.
              </p>
              <div className="space-y-1 bg-muted/40 p-2 rounded border border-border text-[11px] font-mono">
                {Object.entries(issuesData.counts_by_type || {}).map(([t, count]) => {
                  if (count === 0) return null;
                  return (
                    <div key={t} className="flex justify-between items-center text-muted-foreground">
                      <span>{t.replace("_", " ")}:</span>
                      <span className="font-semibold text-foreground">{count}</span>
                    </div>
                  );
                })}
              </div>
              <Button
                size="sm"
                id="btn-confirm-fix-all"
                onClick={handleExecuteFixAll}
                disabled={fixingAll}
                className="w-full text-xs h-7 font-medium"
              >
                Apply all suggestions
              </Button>
            </DropdownMenuContent>
          </DropdownMenu>

          {/* Full Auto-clean pipeline trigger */}
          <Button
            size="sm"
            variant="outline"
            id="btn-run-auto-clean"
            onClick={onRunCompleteClean}
            disabled={cleaning}
            className="h-8 text-xs font-medium gap-1.5"
            title="Run 10-stage automated cleaning pipeline"
          >
            <Play className={`w-3.5 h-3.5 ${cleaning ? "animate-spin" : ""}`} />
            <span className="hidden sm:inline">Auto-clean</span>
          </Button>

          {/* Download Excel Dialog trigger */}
          <Button
            size="sm"
            variant="outline"
            id="btn-open-download-dialog"
            onClick={() => setShowDownloadDialog(true)}
            className="h-8 text-xs font-medium gap-1.5 border-primary/30 text-primary hover:bg-primary/10"
            title="Download Excel with Raw_Data and Processed_Data tabs"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Download Excel</span>
          </Button>

          {/* Primary Action: Finish Cleaning */}
          {onFinishCleaning && (
            <Button
              size="sm"
              id="btn-finish-cleaning"
              onClick={async () => {
                try {
                  const check = await api.getCleanCheck(ds.id);
                  if (check) setCleanCheck(check);
                } catch (e) {
                  // Fallback to local issues data
                }
                setShowFinishConfirm(true);
              }}
              className="h-8 text-xs font-semibold gap-1.5 bg-[#0B7A75] text-white hover:bg-[#085854]"
            >
              <span>Finish cleaning</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </Button>
          )}
        </div>
      </div>

      {/* ── 1.5 CLEAN CHECK BANNER (A1 Completeness Contract) ───────── */}
      {cleanCheck && (autoFixedCount > 0 || cleanCheck.auto_fixable_count === 0) && (
        <div
          id="clean-check-banner"
          className="p-3 rounded-xl border bg-white border-[#E4E7EC] shadow-xs flex flex-wrap items-center justify-between gap-2.5 text-xs"
        >
          <div className="flex items-center gap-2.5">
            <div className="w-5 h-5 rounded-full bg-[#0B7A75]/10 text-[#0B7A75] flex items-center justify-center font-bold text-xs">
              <Check className="w-3.5 h-3.5" />
            </div>
            <div>
              <span className="font-semibold text-[#101828]">
                {cleanCheck.banner_message}
              </span>
              {cleanCheck.needs_decision_count > 0 && (
                <span className="text-[#475467] ml-2 hidden sm:inline">
                  (Only items requiring a human choice remain highlighted below)
                </span>
              )}
            </div>
          </div>
          {cleanCheck.decision_items?.length > 0 && (
            <button
              type="button"
              id="btn-toggle-decisions"
              onClick={() => setShowDecisionDrawer(!showDecisionDrawer)}
              className="text-[#0B7A75] font-medium hover:underline text-[11px]"
            >
              {showDecisionDrawer ? "Hide decision items" : `View ${cleanCheck.decision_items.length} decision items`}
            </button>
          )}
        </div>
      )}

      {/* Decision items quick drawer */}
      {cleanCheck && showDecisionDrawer && cleanCheck.decision_items?.length > 0 && (
        <div className="p-3 rounded-xl border border-[#E4E7EC] bg-[#F8FAFC] space-y-2 text-xs">
          <span className="font-semibold text-[#101828] block">Items requiring human decision:</span>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
            {cleanCheck.decision_items.map((it, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => {
                  setSelectedCell({ rowIdx: it.row, colName: it.column });
                  rowVirtualizer.scrollToIndex(Math.max(0, it.row - 2), { align: "start" });
                }}
                className="text-left p-2 rounded-lg bg-white border border-[#E4E7EC] hover:border-[#0B7A75] transition-all"
              >
                <div className="font-mono text-[10px] text-[#0B7A75] font-semibold">Row {it.row + 1} · {it.column}</div>
                <div className="text-[11px] text-[#101828] truncate">{it.reason}</div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ── 2. SLIM ISSUE TOOLBAR & FILTER CHIPS ────────────────────── */}
      <div className="bg-card/70 border border-border rounded-xl px-3 py-2 flex flex-wrap items-center justify-between gap-2.5 text-xs">
        {/* Filter chips with counts */}
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] font-medium text-muted-foreground mr-1">Issues:</span>
          {Object.entries(issuesData.counts_by_type || {}).map(([typeKey, count]) => {
            if (count === 0) return null;
            const cfg = ISSUE_CONFIG[typeKey] || ISSUE_CONFIG.missing;
            const Icon = cfg.icon;
            const isSelected = activeIssueFilter === typeKey;

            return (
              <button
                key={typeKey}
                type="button"
                id={`chip-issue-${typeKey}`}
                onClick={() => {
                  setActiveIssueFilter(isSelected ? null : typeKey);
                }}
                className={cn(
                  "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium border transition-all cursor-pointer select-none",
                  isSelected
                    ? "bg-foreground text-background border-foreground shadow-xs font-semibold"
                    : `${cfg.bg} ${cfg.text} ${cfg.border} hover:opacity-90`
                )}
              >
                <Icon className="w-3 h-3 shrink-0" />
                <span>
                  {cfg.label} {count}
                </span>
              </button>
            );
          })}

          {activeIssueFilter && (
            <button
              onClick={() => setActiveIssueFilter(null)}
              className="text-[10px] text-muted-foreground hover:text-foreground underline ml-1"
            >
              Clear filter
            </button>
          )}
        </div>

        {/* Right: Next / Previous issue + Progress Meter */}
        <div className="flex items-center gap-3 shrink-0 ml-auto">
          {/* Progress meter */}
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-muted-foreground">
              <span className="font-mono font-medium text-foreground">
                {issuesData.resolved_count}
              </span>{" "}
              of{" "}
              <span className="font-mono font-medium text-foreground">
                {issuesData.initial_total || (issuesData.total + issuesData.resolved_count)}
              </span>{" "}
              resolved
            </span>
            <div className="w-16 h-1.5 rounded-full bg-muted overflow-hidden">
              <div
                className="h-full bg-emerald-500 transition-all duration-300"
                style={{ width: `${progressRatio}%` }}
              />
            </div>
          </div>

          <div className="h-4 w-px bg-border" />

          {/* Next / Previous issue controls */}
          <div className="flex items-center gap-1">
            <Button
              size="icon"
              variant="ghost"
              className="w-6 h-6 text-muted-foreground hover:text-foreground"
              onClick={() => navigateToIssue("prev")}
              disabled={(issuesData.ordered_issues || []).length === 0}
              title="Previous issue"
              aria-label="Previous issue"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
            </Button>
            <span className="text-[10px] font-mono text-muted-foreground min-w-[32px] text-center">
              {currentIssueIdx >= 0 ? `${currentIssueIdx + 1}/${issuesData.ordered_issues.length}` : "Issues"}
            </span>
            <Button
              size="icon"
              variant="ghost"
              className="w-6 h-6 text-muted-foreground hover:text-foreground"
              onClick={() => navigateToIssue("next")}
              disabled={(issuesData.ordered_issues || []).length === 0}
              title="Next issue"
              aria-label="Next issue"
            >
              <ChevronRight className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>
      </div>

      {/* ── 3. SEARCH & COLUMN FILTER STRIP ─────────────────────────── */}
      <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground px-1">
        <div className="relative w-full sm:w-64">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            id="input-grid-search"
            placeholder="Search all cells..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-8 pr-3 py-1 rounded-md border border-border bg-card text-xs text-foreground placeholder:text-muted-foreground focus:outline-hidden focus:ring-1 focus:ring-primary"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              <X className="w-3 h-3" />
            </button>
          )}
        </div>

        {activeColumnFilter && (
          <div className="flex items-center gap-1.5 text-xs text-foreground font-medium">
            <span>Filtered to column: "{activeColumnFilter}"</span>
            <button
              onClick={() => setActiveColumnFilter(null)}
              className="text-muted-foreground hover:text-foreground"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        <div className="text-[11px] text-muted-foreground hidden sm:block">
          Double-click to edit cell · Tab/Enter to navigate · Esc to close
        </div>
      </div>

      {/* ── 4. SPREADSHEET VIRTUALIZED GRID ─────────────────────────── */}
      <div className="relative bg-card border border-border rounded-xl shadow-xs overflow-hidden">
        {loading ? (
          <div className="p-16 text-center text-sm text-muted-foreground space-y-3">
            <Loader2 className="w-6 h-6 animate-spin text-primary mx-auto" />
            <p>Loading editable data grid...</p>
          </div>
        ) : columns.length === 0 ? (
          <div className="p-12 text-center text-sm text-muted-foreground">
            No columns or data available in this sheet.
          </div>
        ) : (
          <div
            ref={gridContainerRef}
            className="overflow-auto h-[580px] max-h-[580px] border-collapse text-xs select-none"
          >
            <div style={{ minWidth: "100%", width: "max-content" }}>
              {/* Sticky Table Header */}
              <div className="sticky top-0 z-20 flex bg-muted/60 border-b border-border font-semibold text-foreground select-none backdrop-blur-xs">
                {/* Row Number Header */}
                <div className="sticky left-0 z-30 w-12 shrink-0 px-2 py-2 text-center font-mono text-[11px] text-muted-foreground border-r border-border bg-muted/80 flex items-center justify-center">
                  #
                </div>

                {/* Column Headers */}
                {columns.map((col) => {
                  const width = colWidths[col.name] || 150;
                  const hasIssues = (col.issue_count || 0) > 0;

                  return (
                    <div
                      key={col.name}
                      style={{ width, minWidth: 80 }}
                      className="relative shrink-0 px-2.5 py-1.5 border-r border-border flex items-center justify-between group"
                    >
                      <div className="flex items-center gap-1.5 truncate">
                        {getColumnTypeIcon(col.type_category)}
                        <span className="truncate text-xs font-semibold" title={col.name}>
                          {col.name}
                        </span>
                      </div>

                      {/* Header Actions: Issue Badge & 3-Dot Menu */}
                      <div className="flex items-center gap-1 shrink-0">
                        {hasIssues && (
                          <button
                            type="button"
                            onClick={() =>
                              setActiveColumnFilter(
                                activeColumnFilter === col.name ? null : col.name
                              )
                            }
                            className={cn(
                              "text-[10px] font-mono px-1.5 py-0.2 rounded border transition-colors cursor-pointer",
                              activeColumnFilter === col.name
                                ? "bg-amber-500 text-white border-amber-600 font-bold"
                                : "bg-amber-500/15 border-amber-500/30 text-amber-700 dark:text-amber-300 hover:bg-amber-500/25"
                            )}
                            title={`Filter issues in ${col.name} (${col.issue_count})`}
                          >
                            {col.issue_count}
                          </button>
                        )}

                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <button
                              type="button"
                              className="opacity-0 group-hover:opacity-100 p-0.5 text-muted-foreground hover:text-foreground rounded transition-opacity"
                              aria-label="Column menu"
                            >
                              <MoreVertical className="w-3.5 h-3.5" />
                            </button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="start" className="w-48 text-xs">
                            <DropdownMenuSub>
                              <DropdownMenuSubTrigger>Change type</DropdownMenuSubTrigger>
                              <DropdownMenuSubContent className="text-xs">
                                <DropdownMenuItem onClick={() => handleColumnAction(col.name, "change_type", { target_type: "number" })}>
                                  Number
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => handleColumnAction(col.name, "change_type", { target_type: "text" })}>
                                  Text
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => handleColumnAction(col.name, "change_type", { target_type: "date" })}>
                                  Date
                                </DropdownMenuItem>
                              </DropdownMenuSubContent>
                            </DropdownMenuSub>
                            <DropdownMenuItem onClick={() => handleColumnAction(col.name, "trim")}>
                              Trim whitespace
                            </DropdownMenuItem>
                            <DropdownMenuSub>
                              <DropdownMenuSubTrigger>Change case</DropdownMenuSubTrigger>
                              <DropdownMenuSubContent className="text-xs">
                                <DropdownMenuItem onClick={() => handleColumnAction(col.name, "change_case", { case: "upper" })}>
                                  UPPERCASE
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => handleColumnAction(col.name, "change_case", { case: "lower" })}>
                                  lowercase
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={() => handleColumnAction(col.name, "change_case", { case: "title" })}>
                                  Title Case
                                </DropdownMenuItem>
                              </DropdownMenuSubContent>
                            </DropdownMenuSub>
                            <DropdownMenuItem onClick={() => handleColumnAction(col.name, "standardise")}>
                              Standardise values
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              onClick={() => {
                                const newName = prompt(`Enter new name for column "${col.name}":`, col.name);
                                if (newName && newName.trim()) {
                                  handleColumnAction(col.name, "rename", { new_name: newName.trim() });
                                }
                              }}
                            >
                              Rename column
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onClick={() => {
                                if (confirm(`Are you sure you want to remove column "${col.name}"?`)) {
                                  handleColumnAction(col.name, "remove");
                                }
                              }}
                              className="text-red-600 focus:text-red-600"
                            >
                              Remove column
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>

                      {/* Resize Handle */}
                      <div
                        onMouseDown={(e) => onResizeMouseDown(col.name, e)}
                        className="absolute right-0 top-0 bottom-0 w-1.5 cursor-col-resize hover:bg-primary/50 transition-colors"
                      />
                    </div>
                  );
                })}
              </div>

              {/* Virtualized Body Container */}
              <div
                style={{
                  height: `${rowVirtualizer.getTotalSize()}px`,
                  position: "relative",
                }}
              >
                {rowVirtualizer.getVirtualItems().map((virtualRow) => {
                  const rowData = rows[virtualRow.index];
                  if (!rowData) return null;
                  const rowIdx = rowData._row_index;
                  const isDuplicateRow = rowData._is_duplicate;

                  return (
                    <div
                      key={rowIdx}
                      style={{
                        position: "absolute",
                        top: 0,
                        left: 0,
                        width: "100%",
                        height: `${virtualRow.size}px`,
                        transform: `translateY(${virtualRow.start}px)`,
                      }}
                      className={cn(
                        "flex border-b border-border/50 hover:bg-muted/20 transition-colors font-mono text-xs",
                        isDuplicateRow && "bg-zinc-500/10"
                      )}
                    >
                      {/* Sticky Row Number */}
                      <div className="sticky left-0 z-10 w-12 shrink-0 px-2 py-1.5 text-center text-muted-foreground border-r border-border bg-card font-mono text-[11px] flex items-center justify-center select-none">
                        {isDuplicateRow ? (
                          <span title="Duplicate row" className="flex items-center gap-0.5 text-zinc-500">
                            <Copy className="w-3 h-3" />
                            <span>{rowIdx + 1}</span>
                          </span>
                        ) : (
                          <span>{rowIdx + 1}</span>
                        )}
                      </div>

                      {/* Row Cells */}
                      {columns.map((col) => {
                        const width = colWidths[col.name] || 150;
                        const cellData = rowData._cells?.[col.name] || {};
                        const val = cellData.val;
                        const issues = cellData.issues || [];
                        const hasIssue = issues.length > 0;
                        const isChanged = cellData.is_changed;

                        const isSelected =
                          selectedCell?.rowIdx === rowIdx && selectedCell?.colName === col.name;
                        const isEditingThis =
                          editingCell?.rowIdx === rowIdx && editingCell?.colName === col.name;

                        // Issue styling
                        const primaryIssue = hasIssue ? issues[0] : null;
                        const issueCfg = primaryIssue
                          ? ISSUE_CONFIG[primaryIssue.type] || ISSUE_CONFIG.missing
                          : null;
                        const IssueIcon = issueCfg ? issueCfg.icon : null;

                        return (
                          <div
                            key={col.name}
                            style={{ width, minWidth: 80 }}
                            data-popover-trigger={hasIssue ? "true" : undefined}
                            className={cn(
                              "relative shrink-0 px-2.5 py-1.5 border-r border-border/40 flex items-center justify-between transition-all cursor-cell select-text",
                              isSelected && "ring-2 ring-primary ring-inset z-10",
                              hasIssue && `${issueCfg.bg} ${issueCfg.text} font-medium`,
                              isChanged && !hasIssue && "bg-emerald-500/10 border-emerald-500/30"
                            )}
                            onClick={(e) => {
                              setSelectedCell({ rowIdx, colName: col.name });
                              if (hasIssue) {
                                openPopover(rowIdx, col.name, primaryIssue.type, e.currentTarget.getBoundingClientRect());
                              }
                            }}
                            onDoubleClick={() => {
                              setEditingCell({
                                rowIdx,
                                colName: col.name,
                                value: val ?? "",
                                error: "",
                              });
                            }}
                            onMouseEnter={(e) => handleCellMouseEnter(rowIdx, col.name, issues, e)}
                            onMouseLeave={handleCellMouseLeave}
                          >
                            {isEditingThis ? (
                              <div className="w-full flex flex-col z-30">
                                <div className="flex items-center gap-1">
                                  <input
                                    type="text"
                                    autoFocus
                                    value={editingCell.value}
                                    onChange={(e) =>
                                      setEditingCell((prev) => ({
                                        ...prev,
                                        value: e.target.value,
                                        error: "",
                                      }))
                                    }
                                    onKeyDown={(e) => {
                                      if (e.key === "Enter") handleCommitCellEdit();
                                      if (e.key === "Escape") setEditingCell(null);
                                    }}
                                    className="w-full px-1.5 py-0.5 rounded border border-primary bg-background text-xs font-mono text-foreground focus:outline-hidden"
                                  />
                                  <button
                                    type="button"
                                    onClick={handleCommitCellEdit}
                                    className="p-1 rounded bg-primary text-primary-foreground hover:bg-primary/90"
                                    aria-label="Save cell edit"
                                  >
                                    <Check className="w-3 h-3" />
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => setEditingCell(null)}
                                    className="p-1 rounded text-muted-foreground hover:text-foreground"
                                    aria-label="Cancel edit"
                                  >
                                    <X className="w-3 h-3" />
                                  </button>
                                </div>
                                {editingCell.error && (
                                  <span className="text-[10px] text-red-500 font-sans mt-0.5">
                                    {editingCell.error}
                                  </span>
                                )}
                              </div>
                            ) : hasIssue ? (
                              <div className="flex items-center justify-between w-full gap-1">
                                <span className="inline-flex items-center gap-1 truncate" title={primaryIssue.message}>
                                  <IssueIcon className="w-3 h-3 shrink-0" />
                                  <span>{val !== "" ? String(val) : primaryIssue.label}</span>
                                </span>
                                <span className="text-[9px] opacity-75 font-sans">Fix</span>
                              </div>
                            ) : (
                              <div className="flex items-center justify-between w-full group/cell">
                                <span className="truncate" title={String(val ?? "")}>
                                  {val !== "" && val !== null && val !== undefined ? (
                                    String(val)
                                  ) : (
                                    <span className="text-muted-foreground/40 italic">blank</span>
                                  )}
                                </span>

                                {isChanged && (
                                  <button
                                    type="button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleRevertCell(rowIdx, col.name);
                                    }}
                                    className="opacity-0 group-hover/cell:opacity-100 p-0.5 text-muted-foreground hover:text-foreground"
                                    title="Revert to original upload value"
                                    aria-label="Revert cell"
                                  >
                                    <RotateCcw className="w-3 h-3" />
                                  </button>
                                )}
                              </div>
                            )}

                            {/* Fill down square handle on selected cell */}
                            {isSelected && !isEditingThis && (
                              <div
                                onDoubleClick={handleFillDown}
                                title="Double click to fill down"
                                className="absolute -bottom-1 -right-1 w-2.5 h-2.5 bg-primary border border-background cursor-crosshair z-20"
                              />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── 5. HOVER / FOCUS POPOVER (Small, Simple, Strict 2-Line) ─── */}
      {popoverState && (
        <div
          ref={popoverRef}
          className={cn(
            "fixed z-50 rounded-xl border border-border bg-card shadow-xl p-3 text-xs space-y-2.5 animate-in fade-in zoom-in-95",
            popoverState.isMobile
              ? "inset-x-3 bottom-4 max-w-sm mx-auto"
              : "w-80"
          )}
          style={
            !popoverState.isMobile && popoverState.anchorRect
              ? {
                  top: Math.min(
                    window.innerHeight - 280,
                    Math.max(10, popoverState.anchorRect.bottom + 6)
                  ),
                  left: Math.min(
                    window.innerWidth - 340,
                    Math.max(10, popoverState.anchorRect.left - 10)
                  ),
                }
              : undefined
          }
        >
          {loadingSuggestion ? (
            <div className="py-4 text-center text-muted-foreground flex items-center justify-center gap-2">
              <Loader2 className="w-4 h-4 animate-spin text-primary" />
              <span>Checking suggestion...</span>
            </div>
          ) : suggestionData ? (
            <>
              {/* Header: Line 1 (What is wrong) & Close */}
              <div className="flex items-start justify-between gap-2 border-b border-border/60 pb-1.5">
                <div className="font-semibold text-foreground text-xs leading-snug">
                  {suggestionData.line1}
                </div>
                <button
                  type="button"
                  onClick={closePopover}
                  className="p-0.5 text-muted-foreground hover:text-foreground shrink-0"
                  aria-label="Close"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>

              {/* Line 2: The suggested fix with one-line reason */}
              <div className="text-[11px] text-muted-foreground leading-snug">
                {suggestionData.line2}
              </div>

              {/* Scope Switch: Only this cell | All N in this column */}
              <div className="flex items-center gap-4 text-[11px] font-medium pt-1 text-foreground">
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="radio"
                    name="scope"
                    value="cell"
                    checked={popoverScope === "cell"}
                    onChange={() => setPopoverScope("cell")}
                    className="accent-primary"
                  />
                  <span>Only this cell</span>
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="radio"
                    name="scope"
                    value="column"
                    checked={popoverScope === "column"}
                    onChange={() => setPopoverScope("column")}
                    className="accent-primary"
                  />
                  <span>
                    All {suggestionData.scope_counts?.column || 1} in column
                  </span>
                </label>
              </div>

              {/* Primary Apply Button */}
              <div>
                <Button
                  size="sm"
                  id="btn-popover-apply-primary"
                  onClick={() =>
                    handleApplyFix(
                      suggestionData.primary_strategy,
                      suggestionData.suggested_value
                    )
                  }
                  className="w-full text-xs h-7.5 font-medium bg-primary text-primary-foreground hover:bg-primary/90"
                >
                  <span>
                    {suggestionData.suggested_label || "Apply suggestion"} (
                    {popoverScope === "cell"
                      ? "1 cell"
                      : `${suggestionData.scope_counts?.column || 1} cells`}
                    )
                  </span>
                </Button>
              </div>

              {/* Compact "Other options" Dropdown (at most 4 entries) */}
              {suggestionData.options && suggestionData.options.length > 0 && (
                <div className="pt-0.5 flex items-center justify-between">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button
                        type="button"
                        id="btn-popover-other-options"
                        className="text-[11px] text-muted-foreground hover:text-foreground flex items-center gap-1 font-medium"
                      >
                        <span>Other options</span>
                        <ChevronDown className="w-3 h-3" />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start" className="w-56 text-xs">
                      {suggestionData.options.slice(0, 4).map((opt, i) => (
                        <DropdownMenuItem
                          key={i}
                          onClick={() => {
                            if (opt.needs_input) {
                              setShowCustomInput(true);
                            } else {
                              handleApplyFix(opt.strategy, opt.value);
                            }
                          }}
                        >
                          {opt.label}
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>

                  {/* Cell source note */}
                  <span className="text-[10px] text-muted-foreground/60 font-mono">
                    Row {popoverState.row + 1}
                  </span>
                </div>
              )}

              {/* Inline Custom Input if selected from Other Options */}
              {showCustomInput && (
                <div className="flex items-center gap-1.5 pt-1 border-t border-border">
                  <input
                    type="text"
                    placeholder="Enter value..."
                    value={customInputValue}
                    onChange={(e) => setCustomInputValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && customInputValue.trim()) {
                        handleApplyFix("enter_value", customInputValue.trim());
                      }
                    }}
                    className="w-full px-2 py-1 text-xs rounded border border-border bg-background text-foreground focus:outline-hidden"
                  />
                  <Button
                    size="sm"
                    onClick={() => handleApplyFix("enter_value", customInputValue.trim())}
                    disabled={!customInputValue.trim()}
                    className="h-7 text-xs px-2 shrink-0"
                  >
                    Save
                  </Button>
                </div>
              )}
            </>
          ) : null}
        </div>
      )}

      {/* ── 6. DOWNLOAD EXCEL DIALOG (Clean & Minimal Specification) ── */}
      <Dialog open={showDownloadDialog} onOpenChange={setShowDownloadDialog}>
        <DialogContent className="sm:max-w-md p-6">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">
              Download dataset
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-2 text-xs">
            {/* Format choice */}
            <div className="space-y-2">
              <span className="font-medium text-foreground">File format</span>
              <div className="grid grid-cols-2 gap-2">
                <label
                  className={cn(
                    "flex items-center gap-2 p-2.5 rounded-lg border cursor-pointer transition-all",
                    downloadFormat === "xlsx"
                      ? "border-primary bg-primary/5 text-foreground font-semibold"
                      : "border-border text-muted-foreground hover:text-foreground"
                  )}
                >
                  <input
                    type="radio"
                    name="dl_format"
                    value="xlsx"
                    checked={downloadFormat === "xlsx"}
                    onChange={() => setDownloadFormat("xlsx")}
                    className="accent-primary"
                  />
                  <span>Excel (.xlsx)</span>
                </label>

                <label
                  className={cn(
                    "flex items-center gap-2 p-2.5 rounded-lg border cursor-pointer transition-all",
                    downloadFormat === "csv"
                      ? "border-primary bg-primary/5 text-foreground font-semibold"
                      : "border-border text-muted-foreground hover:text-foreground"
                  )}
                >
                  <input
                    type="radio"
                    name="dl_format"
                    value="csv"
                    checked={downloadFormat === "csv"}
                    onChange={() => setDownloadFormat("csv")}
                    className="accent-primary"
                  />
                  <span>Cleaned CSV</span>
                </label>
              </div>
            </div>

            {/* Checkbox Options (Excel only) */}
            {downloadFormat === "xlsx" && (
              <div className="space-y-2.5 pt-1">
                <label className="flex items-center gap-2 cursor-pointer text-foreground">
                  <Checkbox
                    id="chk-include-changelog"
                    checked={includeChangeLog}
                    onCheckedChange={(checked) => setIncludeChangeLog(!!checked)}
                  />
                  <span>Include change log tab</span>
                </label>

                <label className="flex items-center gap-2 cursor-pointer text-foreground">
                  <Checkbox
                    id="chk-highlight-changes"
                    checked={highlightChanges}
                    onCheckedChange={(checked) => setHighlightChanges(!!checked)}
                  />
                  <span>Highlight changed cells</span>
                </label>
              </div>
            )}

            {/* Structure info text */}
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              The Excel workbook contains <span className="font-mono font-medium">Raw_Data</span> (unmodified upload) followed by <span className="font-mono font-medium">Processed_Data</span> (cleaned, typed cells with frozen headers).
            </p>
          </div>

          <DialogFooter className="gap-2 sm:gap-0 pt-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowDownloadDialog(false)}
              className="text-xs"
            >
              Cancel
            </Button>
            <Button
              size="sm"
              id="btn-dialog-download-submit"
              onClick={handleExecuteDownload}
              disabled={downloading}
              className="text-xs font-medium gap-1.5 bg-primary text-primary-foreground hover:bg-primary/90"
            >
              {downloading ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Download className="w-3.5 h-3.5" />
              )}
              <span>Download</span>
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── 7. FINISH CLEANING / CLEANING SUMMARY DIALOG ───────────── */}
      <Dialog open={showFinishConfirm} onOpenChange={setShowFinishConfirm}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold text-foreground">Cleaning summary</DialogTitle>
            <DialogDescription className="text-xs text-muted-foreground">
              Review automated fixes and remaining human decision items before generating the dashboard.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 py-2 text-xs">
            {/* Auto-fixed summary */}
            <div className="p-3 rounded-lg bg-[#0B7A75]/5 border border-[#0B7A75]/20 space-y-1.5">
              <div className="flex items-center justify-between font-medium text-[#0B7A75]">
                <span className="flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  Issues fixed automatically
                </span>
                <span className="font-semibold tabular-nums text-sm">{autoFixedCount}</span>
              </div>
              {Object.keys(autoFixedBreakdown).length > 0 && (
                <div className="text-[11px] text-muted-foreground pt-1 border-t border-[#0B7A75]/15 space-y-0.5">
                  {Object.entries(autoFixedBreakdown).slice(0, 4).map(([rule, count]) => (
                    <div key={rule} className="flex justify-between">
                      <span className="capitalize">{rule.replace(/_/g, " ")}:</span>
                      <span className="font-medium text-foreground tabular-nums">{count}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Human decision items */}
            <div className="p-3 rounded-lg bg-muted/40 border border-border space-y-2">
              <div className="flex items-center justify-between font-medium text-foreground">
                <span className="flex items-center gap-1.5">
                  <AlertCircle className="w-3.5 h-3.5 text-amber-600" />
                  Issues needing human decision
                </span>
                <span className="font-semibold tabular-nums text-sm">
                  {cleanCheck?.human_decision_count ?? issuesData.total}
                </span>
              </div>

              {(cleanCheck?.human_decisions && cleanCheck.human_decisions.length > 0) ? (
                <div className="max-h-36 overflow-y-auto space-y-1.5 pr-1 divide-y divide-border/50 text-[11px]">
                  {cleanCheck.human_decisions.slice(0, 5).map((item, i) => (
                    <div key={i} className="pt-1.5 first:pt-0 flex items-start justify-between gap-2">
                      <span className="font-medium text-foreground truncate">{item.column}</span>
                      <span className="text-muted-foreground text-right">{item.reason}</span>
                    </div>
                  ))}
                  {cleanCheck.human_decisions.length > 5 && (
                    <div className="text-[10px] text-muted-foreground text-center pt-1">
                      +{cleanCheck.human_decisions.length - 5} more highlighted in grid
                    </div>
                  )}
                </div>
              ) : issuesData.total === 0 ? (
                <p className="text-[11px] text-muted-foreground">
                  Zero issues remaining. Dataset is verified completely clean.
                </p>
              ) : (
                <p className="text-[11px] text-muted-foreground">
                  {issuesData.total} cell{issuesData.total > 1 ? "s" : ""} flagged for review (IDs or PII restricted from auto-filling).
                </p>
              )}
            </div>
          </div>

          <DialogFooter className="flex justify-end gap-2 pt-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowFinishConfirm(false)}
            >
              Keep cleaning
            </Button>
            <Button
              size="sm"
              id="btn-confirm-proceed-dashboard"
              onClick={() => {
                setShowFinishConfirm(false);
                if (onFinishCleaning) onFinishCleaning();
              }}
              className="bg-[#0B7A75] text-white hover:bg-[#085854]"
            >
              Proceed to Dashboard
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
