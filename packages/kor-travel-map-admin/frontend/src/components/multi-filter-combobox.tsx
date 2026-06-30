"use client";

import { useMemo, useState } from "react";

import { XIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface MultiFilterComboboxProps {
  ariaLabel: string;
  className?: string;
  onChange: (values: string[]) => void;
  options: string[];
  placeholder: string;
  values: string[];
}

function uniqueSorted(values: string[]): string[] {
  return Array.from(
    new Set(values.map((value) => value.trim()).filter(Boolean)),
  ).sort((left, right) => left.localeCompare(right));
}

function MultiFilterCombobox({
  ariaLabel,
  className,
  onChange,
  options,
  placeholder,
  values,
}: MultiFilterComboboxProps) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const normalizedQuery = query.trim().toLowerCase();
  const selected = useMemo(() => uniqueSorted(values), [values]);
  const selectableOptions = useMemo(
    () =>
      uniqueSorted([...options, ...selected]).filter(
        (option) =>
          !selected.includes(option) &&
          (normalizedQuery.length === 0 ||
            option.toLowerCase().includes(normalizedQuery)),
      ),
    [normalizedQuery, options, selected],
  );

  const addValue = (value: string) => {
    const next = value.trim();
    if (!next || selected.includes(next)) return;
    onChange(uniqueSorted([...selected, next]));
    setQuery("");
    setOpen(false);
  };

  const removeValue = (value: string) => {
    onChange(selected.filter((item) => item !== value));
  };

  return (
    <div
      className={cn("relative flex min-w-0 flex-col gap-1", className)}
      onBlur={(event) => {
        const nextFocus = event.relatedTarget;
        if (!nextFocus || !event.currentTarget.contains(nextFocus as Node)) {
          setOpen(false);
        }
      }}
      onFocus={() => setOpen(true)}
    >
      <div className="flex min-h-10 flex-wrap items-center gap-1 rounded-md border bg-card px-2 py-1">
        {selected.map((value) => (
          <Badge className="gap-1 pr-1" key={value} variant="outline">
            <span className="max-w-36 truncate">{value}</span>
            <Button
              aria-label={`${value} 제거`}
              className="size-4 p-0"
              size="icon-xs"
              type="button"
              variant="ghost"
              onClick={() => removeValue(value)}
            >
              <XIcon className="size-3" />
            </Button>
          </Badge>
        ))}
        <Input
          aria-label={ariaLabel}
          className="h-7 min-w-28 flex-1 border-0 bg-transparent px-1 py-0 shadow-none focus-visible:ring-0"
          placeholder={selected.length === 0 ? placeholder : "추가"}
          role="combobox"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              addValue(query);
            }
            if (
              event.key === "Backspace" &&
              query.length === 0 &&
              selected.length > 0
            ) {
              removeValue(selected[selected.length - 1] ?? "");
            }
          }}
        />
      </div>
      {open && (query.trim().length > 0 || selectableOptions.length > 0) ? (
        <div className="absolute top-full right-0 left-0 z-20 mt-1 max-h-56 overflow-auto rounded-md border bg-popover p-1 shadow-md">
          {query.trim().length > 0 &&
          !selected.includes(query.trim()) &&
          !selectableOptions.includes(query.trim()) ? (
            <button
              className="w-full rounded-sm px-2 py-1.5 text-left text-sm hover:bg-muted focus-visible:bg-muted focus-visible:outline-none"
              type="button"
              onClick={() => addValue(query)}
            >
              추가: {query.trim()}
            </button>
          ) : null}
          {selectableOptions.slice(0, 12).map((option) => (
            <button
              className="w-full rounded-sm px-2 py-1.5 text-left text-sm hover:bg-muted focus-visible:bg-muted focus-visible:outline-none"
              key={option}
              type="button"
              onClick={() => addValue(option)}
            >
              {option}
            </button>
          ))}
          {selectableOptions.length === 0 && query.trim().length === 0 ? (
            <div className="px-2 py-1.5 text-sm text-muted-foreground">
              선택지가 없습니다.
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export { MultiFilterCombobox, uniqueSorted };
