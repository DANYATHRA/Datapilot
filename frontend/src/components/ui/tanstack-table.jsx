import React, { useMemo, useState } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  flexRender,
} from "@tanstack/react-table";
import {
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Download,
  Copy,
  Check,
  Search,
  SlidersHorizontal,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from "lucide-react";
import { Button } from "./button";
import { Input } from "./input";
import { DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuTrigger } from "./dropdown-menu";
import { SimpleTooltip } from "./tooltip";
import { isNumeric, formatNumber } from "../../lib/formatters";
import { cn } from "../../lib/utils";
import { toast } from "sonner";

export function TanStackTable({
  columns: rawColumns = [],
  data: rawData = [],
  pageSize = 20,
  enablePagination = true,
  enableGlobalFilter = true,
  enableColumnVisibility = true,
  enableExport = true,
  className = "",
  maxHeight = "520px",
}) {
  const [sorting, setSorting] = useState([]);
  const [globalFilter, setGlobalFilter] = useState("");
  const [columnVisibility, setColumnVisibility] = useState({});
  const [copiedCell, setCopiedCell] = useState(null);

  // Normalize column definitions and detect numeric columns for right-alignment
  const columns = useMemo(() => {
    return rawColumns.map((colName) => {
      // Determine if majority of values are numeric
      let isColNumeric = false;
      if (rawData.length > 0) {
        let sampleCount = 0;
        let numericCount = 0;
        for (let i = 0; i < Math.min(rawData.length, 25); i++) {
          const row = rawData[i];
          const val = Array.isArray(row)
            ? row[rawColumns.indexOf(colName)]
            : row[colName];
          if (val != null && val !== "") {
            sampleCount++;
            if (isNumeric(val)) numericCount++;
          }
        }
        if (sampleCount > 0 && numericCount / sampleCount >= 0.7) {
          isColNumeric = true;
        }
      }

      return {
        id: colName,
        accessorKey: colName,
        header: ({ column }) => {
          const isSorted = column.getIsSorted();
          return (
            <div
              className={cn(
                "flex items-center gap-1.5 cursor-pointer select-none font-semibold text-xs tracking-wider uppercase text-muted-foreground hover:text-foreground",
                isColNumeric ? "justify-end" : "justify-start"
              )}
              onClick={() => column.toggleSorting(column.getIsSorted() === "asc")}
            >
              <span className="truncate">{colName}</span>
              {isSorted === "asc" ? (
                <ArrowUp className="w-3.5 h-3.5 text-primary shrink-0" strokeWidth={1.75} />
              ) : isSorted === "desc" ? (
                <ArrowDown className="w-3.5 h-3.5 text-primary shrink-0" strokeWidth={1.75} />
              ) : (
                <ArrowUpDown className="w-3.5 h-3.5 opacity-40 hover:opacity-100 shrink-0" strokeWidth={1.75} />
              )}
            </div>
          );
        },
        cell: ({ getValue }) => {
          const val = getValue();
          if (val === null || val === undefined) {
            return <span className="text-muted-foreground/50 italic text-xs">null</span>;
          }
          if (isColNumeric && typeof val === "number") {
            return (
              <span className="tabular-nums font-mono text-xs">
                {formatNumber(val)}
              </span>
            );
          }
          return <span className="text-xs truncate block max-w-xs">{String(val)}</span>;
        },
        meta: {
          isNumeric: isColNumeric,
        },
      };
    });
  }, [rawColumns, rawData]);

  // Normalize data array
  const tableData = useMemo(() => {
    if (!rawData || rawData.length === 0) return [];
    if (!Array.isArray(rawData[0])) return rawData;
    // Map 2D array to objects
    return rawData.map((rowArr) => {
      const obj = {};
      rawColumns.forEach((c, idx) => {
        obj[c] = rowArr[idx];
      });
      return obj;
    });
  }, [rawData, rawColumns]);

  const table = useReactTable({
    data: tableData,
    columns,
    state: {
      sorting,
      globalFilter,
      columnVisibility,
    },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    onColumnVisibilityChange: setColumnVisibility,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: enablePagination ? getPaginationRowModel() : undefined,
    initialState: {
      pagination: {
        pageSize,
      },
    },
  });

  const handleCopyCell = (val, rowIdx, colId) => {
    const text = val == null ? "" : String(val);
    navigator.clipboard.writeText(text);
    const key = `${rowIdx}_${colId}`;
    setCopiedCell(key);
    toast.success("Cell value copied to clipboard");
    setTimeout(() => setCopiedCell(null), 1500);
  };

  const handleExportVisible = () => {
    const visibleCols = table.getVisibleLeafColumns().map((c) => c.id);
    const rows = table.getFilteredRowModel().rows;
    if (rows.length === 0) return;

    const csvLines = [
      visibleCols.join(","),
      ...rows.map((r) =>
        visibleCols
          .map((colId) => {
            const v = r.getValue(colId);
            return `"${String(v ?? "").replace(/"/g, '""')}"`;
          })
          .join(",")
      ),
    ];

    const blob = new Blob([csvLines.join("\n")], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `table_export_${Date.now()}.csv`;
    link.click();
    URL.revokeObjectURL(url);
    toast.success(`Exported ${rows.length} rows to CSV`);
  };

  if (!rawColumns.length) {
    return (
      <div className="p-8 text-center text-sm text-muted-foreground border border-border rounded-lg bg-card">
        No columns or data available.
      </div>
    );
  }

  return (
    <div className={cn("flex flex-col space-y-3", className)}>
      {/* Table Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        {enableGlobalFilter && (
          <div className="relative flex-1 min-w-[200px] max-w-sm">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" strokeWidth={1.75} />
            <Input
              placeholder="Search table records..."
              value={globalFilter ?? ""}
              onChange={(e) => setGlobalFilter(e.target.value)}
              className="pl-8 h-9 text-xs"
            />
          </div>
        )}

        <div className="flex items-center gap-2">
          {enableColumnVisibility && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm" className="h-9 gap-1.5 text-xs">
                  <SlidersHorizontal className="h-3.5 w-3.5" strokeWidth={1.75} />
                  <span>Columns</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48 max-h-64 overflow-y-auto">
                {table.getAllLeafColumns().map((col) => (
                  <DropdownMenuCheckboxItem
                    key={col.id}
                    checked={col.getIsVisible()}
                    onCheckedChange={(val) => col.toggleVisibility(!!val)}
                  >
                    <span className="truncate">{col.id}</span>
                  </DropdownMenuCheckboxItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}

          {enableExport && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleExportVisible}
              className="h-9 gap-1.5 text-xs"
              title="Export visible rows and columns to CSV"
            >
              <Download className="h-3.5 w-3.5" strokeWidth={1.75} />
              <span>Export CSV</span>
            </Button>
          )}
        </div>
      </div>

      {/* TanStack Table Container */}
      <div
        className="rounded-lg border border-border bg-card shadow-xs overflow-auto relative"
        style={{ maxHeight }}
      >
        <table className="w-full text-left border-collapse text-xs">
          <thead className="sticky top-0 z-10 bg-secondary/95 backdrop-blur-xs border-b border-border shadow-xs">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    className="p-3 font-semibold text-muted-foreground whitespace-nowrap"
                  >
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody className="divide-y divide-border">
            {table.getRowModel().rows.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
                  className="h-24 text-center text-sm text-muted-foreground"
                >
                  No matching records found.
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row, rowIdx) => (
                <tr
                  key={row.id}
                  className="transition-colors hover:bg-muted/10 group"
                >
                  {row.getVisibleCells().map((cell) => {
                    const isColNumeric = cell.column.columnDef.meta?.isNumeric;
                    const cellKey = `${rowIdx}_${cell.column.id}`;
                    const isCopied = copiedCell === cellKey;
                    return (
                      <td
                        key={cell.id}
                        className={cn(
                          "p-2.5 px-3 whitespace-nowrap relative group/cell",
                          isColNumeric ? "text-right tabular-nums font-mono" : "text-left"
                        )}
                        onClick={() => handleCopyCell(cell.getValue(), rowIdx, cell.column.id)}
                        title="Click to copy cell value"
                      >
                        <div className="flex items-center gap-1.5 justify-between">
                          <span className={cn("truncate", isColNumeric ? "w-full text-right" : "")}>
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </span>
                          <span
                            className={cn(
                              "opacity-0 group-hover/cell:opacity-100 transition-opacity p-0.5 rounded hover:bg-secondary cursor-pointer shrink-0",
                              isCopied && "opacity-100 text-success"
                            )}
                          >
                            {isCopied ? (
                              <Check className="w-3 h-3 text-success" strokeWidth={1.75} />
                            ) : (
                              <Copy className="w-3 h-3 text-muted-foreground" strokeWidth={1.75} />
                            )}
                          </span>
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Controls */}
      {enablePagination && (
        <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground px-1">
          <div>
            Showing{" "}
            <span className="font-semibold text-foreground tabular-nums">
              {table.getState().pagination.pageIndex * table.getState().pagination.pageSize + 1}
            </span>{" "}
            to{" "}
            <span className="font-semibold text-foreground tabular-nums">
              {Math.min(
                (table.getState().pagination.pageIndex + 1) * table.getState().pagination.pageSize,
                table.getFilteredRowModel().rows.length
              )}
            </span>{" "}
            of{" "}
            <span className="font-semibold text-foreground tabular-nums">
              {table.getFilteredRowModel().rows.length}
            </span>{" "}
            records
          </div>

          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="icon-sm"
              onClick={() => table.setPageIndex(0)}
              disabled={!table.getCanPreviousPage()}
              aria-label="First page"
            >
              <ChevronsLeft className="w-3.5 h-3.5" strokeWidth={1.75} />
            </Button>
            <Button
              variant="outline"
              size="icon-sm"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
              aria-label="Previous page"
            >
              <ChevronLeft className="w-3.5 h-3.5" strokeWidth={1.75} />
            </Button>
            <span className="px-2 tabular-nums">
              Page {table.getState().pagination.pageIndex + 1} of{" "}
              {Math.max(1, table.getPageCount())}
            </span>
            <Button
              variant="outline"
              size="icon-sm"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
              aria-label="Next page"
            >
              <ChevronRight className="w-3.5 h-3.5" strokeWidth={1.75} />
            </Button>
            <Button
              variant="outline"
              size="icon-sm"
              onClick={() => table.setPageIndex(table.getPageCount() - 1)}
              disabled={!table.getCanNextPage()}
              aria-label="Last page"
            >
              <ChevronsRight className="w-3.5 h-3.5" strokeWidth={1.75} />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

export default TanStackTable;
