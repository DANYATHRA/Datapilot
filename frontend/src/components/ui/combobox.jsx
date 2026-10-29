import * as React from "react";
import { Check, ChevronsUpDown, Search } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";
import { Button } from "./button";
import { cn } from "../../lib/utils";

export function Combobox({
  options = [],
  value,
  onChange,
  placeholder = "Select option...",
  searchPlaceholder = "Search columns...",
  emptyText = "No column found.",
  className = "",
  disabled = false,
}) {
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");

  const filteredOptions = React.useMemo(() => {
    if (!search.trim()) return options;
    const term = search.toLowerCase();
    return options.filter((opt) => {
      const label = typeof opt === "string" ? opt : opt.label || opt.name || opt.value;
      return String(label).toLowerCase().includes(term);
    });
  }, [options, search]);

  const selectedLabel = React.useMemo(() => {
    if (!value) return placeholder;
    const match = options.find((opt) => (typeof opt === "string" ? opt === value : opt.value === value));
    if (match) {
      return typeof match === "string" ? match : match.label || match.name || match.value;
    }
    return value;
  }, [options, value, placeholder]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          disabled={disabled}
          className={cn("w-full justify-between font-normal text-left truncate h-9", className)}
        >
          <span className="truncate">{selectedLabel}</span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" strokeWidth={1.75} />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[var(--radix-popover-trigger-width)] min-w-[200px] p-0" align="start">
        <div className="flex items-center border-b border-border px-3 py-2">
          <Search className="mr-2 h-4 w-4 shrink-0 text-muted-foreground" strokeWidth={1.75} />
          <input
            className="flex h-7 w-full rounded-md bg-transparent text-sm outline-none placeholder:text-muted-foreground text-foreground"
            placeholder={searchPlaceholder}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="max-h-60 overflow-y-auto p-1">
          {filteredOptions.length === 0 ? (
            <div className="py-4 text-center text-xs text-muted-foreground">{emptyText}</div>
          ) : (
            filteredOptions.map((opt) => {
              const optVal = typeof opt === "string" ? opt : opt.value;
              const optLabel = typeof opt === "string" ? opt : opt.label || opt.name || opt.value;
              const isSelected = value === optVal;
              return (
                <div
                  key={optVal}
                  className={cn(
                    "relative flex cursor-pointer select-none items-center rounded-sm px-2 py-1.5 text-sm outline-none hover:bg-accent hover:text-accent-foreground transition-colors",
                    isSelected ? "bg-accent/60 font-medium" : ""
                  )}
                  onClick={() => {
                    onChange(optVal);
                    setOpen(false);
                    setSearch("");
                  }}
                >
                  <Check
                    className={cn(
                      "mr-2 h-4 w-4 text-primary shrink-0",
                      isSelected ? "opacity-100" : "opacity-0"
                    )}
                    strokeWidth={1.75}
                  />
                  <span className="truncate">{optLabel}</span>
                </div>
              );
            })
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
