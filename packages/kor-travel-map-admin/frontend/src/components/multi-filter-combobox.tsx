"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import { useId, useMemo, useState } from "react";

import { XIcon } from "lucide-react";

import { Input } from "@/components/ui/input";
import { uniqueSorted } from "@/lib/string-list";
import { cn } from "@/lib/utils";

interface MultiFilterComboboxProps {
  ariaLabel: string;
  className?: string;
  onChange: (values: string[]) => void;
  options: string[];
  placeholder: string;
  values: string[];
}

/** 팝업 항목 레시피 — 30px row, hover paper-2, focus 단일 outline, pressed rules 색. */
const optionRowClass =
  "flex h-control-sm w-full items-center rounded-control px-2 text-left text-xs text-text-primary transition-[color,background-color] duration-fast ease-out outline-none hover:bg-surface-subtle focus-visible:bg-surface-subtle focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus active:bg-surface-muted";

/**
 * 다중 선택 필터 콤보박스 — 선택값은 chip(hairline, 배지 아님 — M22), 입력은 chip 옆 인라인,
 * 컨테이너가 focus 를 대신 표시(`:has(input:focus-visible)`), 팝업은 `shadow-elevated` 한 층.
 */
function MultiFilterCombobox({
  ariaLabel,
  className,
  onChange,
  options,
  placeholder,
  values,
}: MultiFilterComboboxProps) {
  const listId = useId();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const normalizedQuery = query.trim().toLowerCase();
  const selected = useMemo(() => uniqueSorted(values), [values]);
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const selectableOptions = useMemo(
    () =>
      uniqueSorted([...options, ...selected]).filter(
        (option) =>
          !selectedSet.has(option) &&
          (normalizedQuery.length === 0 ||
            option.toLowerCase().includes(normalizedQuery)),
      ),
    [normalizedQuery, options, selected, selectedSet],
  );

  const addValue = (value: string) => {
    const next = value.trim();
    if (!next || selectedSet.has(next)) return;
    onChange(uniqueSorted([...selected, next]));
    setQuery("");
    setOpen(false);
  };

  const removeValue = (value: string) => {
    onChange(selected.filter((item) => item !== value));
  };

  const popupOpen =
    open && (query.trim().length > 0 || selectableOptions.length > 0);

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
      <div className="flex min-h-control flex-wrap items-center gap-1 rounded-control border border-input bg-card px-2 py-0.5 transition-[border-color,background-color] duration-fast ease-out has-[input:focus-visible]:outline-2 has-[input:focus-visible]:outline-offset-2 has-[input:focus-visible]:outline-focus">
        {selected.map((value) => (
          <span
            className="inline-flex h-6 max-w-full items-center gap-0.5 rounded-control border border-border bg-surface-subtle pl-2 pr-0.5 text-2xs text-text-primary"
            key={value}
          >
            <span className="max-w-36 truncate">{value}</span>
            <button
              aria-label={`${value} 제거`}
              className="relative inline-flex size-5 shrink-0 items-center justify-center rounded-control text-text-secondary transition-[color,background-color] duration-fast ease-out outline-none before:absolute before:-inset-1 hover:bg-surface-muted hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-focus active:bg-surface-muted"
              type="button"
              onClick={() => removeValue(value)}
            >
              <XIcon aria-hidden="true" className="size-3" />
            </button>
          </span>
        ))}
        <Input
          aria-autocomplete="list"
          aria-controls={popupOpen ? listId : undefined}
          aria-expanded={popupOpen}
          aria-label={ariaLabel}
          className="min-w-28 flex-1 border-0 bg-transparent px-1 shadow-none outline-none data-[size=sm]:px-1 hover:bg-transparent focus-visible:border-transparent focus-visible:bg-transparent focus-visible:ring-0 focus-visible:outline-none focus-visible:outline-transparent"
          placeholder={selected.length === 0 ? placeholder : "추가"}
          role="combobox"
          size="sm"
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
      {popupOpen ? (
        <div
          className="absolute top-full right-0 left-0 z-20 mt-1 max-h-56 overflow-auto rounded-panel border border-border bg-card p-1 shadow-elevated"
          id={listId}
        >
          {query.trim().length > 0 &&
          !selectedSet.has(query.trim()) &&
          !selectableOptions.includes(query.trim()) ? (
            <button
              className={optionRowClass}
              type="button"
              onClick={() => addValue(query)}
            >
              추가: {query.trim()}
            </button>
          ) : null}
          {selectableOptions.slice(0, 12).map((option) => (
            <button
              className={optionRowClass}
              key={option}
              type="button"
              onClick={() => addValue(option)}
            >
              {option}
            </button>
          ))}
          {selectableOptions.length === 0 && query.trim().length === 0 ? (
            <p className="px-2 py-1.5 text-xs text-text-secondary">
              선택지가 없습니다.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export { MultiFilterCombobox };
