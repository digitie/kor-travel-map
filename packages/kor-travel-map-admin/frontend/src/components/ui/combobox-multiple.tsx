"use client";

import { CheckIcon, ChevronsUpDownIcon, SearchIcon, XIcon } from "lucide-react";
import * as React from "react";

import { Badge } from "@/components/ui/badge";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
} from "@/components/ui/field";
import {
  describedBy,
  type FieldShellProps,
  requiredFieldAriaLabel,
  useFieldIds,
} from "@/components/ui/form-field-shared";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export interface ComboboxMultipleOption {
  value: string;
  label: string;
  description?: string;
}

type ComboboxMultipleProps = FieldShellProps & {
  id?: string;
  value: string[];
  options: ComboboxMultipleOption[];
  placeholder?: string;
  searchPlaceholder?: string;
  emptyMessage?: string;
  disabled?: boolean;
  onChange: (value: string[]) => void;
};

function ComboboxMultiple({
  label,
  hint,
  error,
  required,
  className,
  labelClassName,
  id,
  value,
  options,
  placeholder = "선택",
  searchPlaceholder = "검색",
  emptyMessage = "선택할 항목이 없습니다.",
  disabled,
  onChange,
}: ComboboxMultipleProps) {
  const { fieldId, hintId, errorId } = useFieldIds(id);
  const listboxId = `${fieldId}-listbox`;
  const accessibleLabel =
    typeof label === "string"
      ? required
        ? `${label} 필수`
        : label
      : undefined;
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const rootRef = React.useRef<HTMLDivElement | null>(null);
  const searchRef = React.useRef<HTMLInputElement | null>(null);
  const selected = React.useMemo(() => new Set(value), [value]);
  const selectedOptions = value.map(
    (selectedValue) =>
      options.find((option) => option.value === selectedValue) ?? {
        label: selectedValue,
        value: selectedValue,
      },
  );
  const filteredOptions = options.filter((option) => {
    const keyword = query.trim().toLowerCase();
    if (keyword.length === 0) return true;
    return (
      option.label.toLowerCase().includes(keyword) ||
      option.value.toLowerCase().includes(keyword)
    );
  });

  React.useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, []);

  React.useEffect(() => {
    if (!open) return;
    const frame = window.requestAnimationFrame(() => searchRef.current?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [open]);

  const toggleValue = (nextValue: string) => {
    if (selected.has(nextValue)) {
      onChange(value.filter((item) => item !== nextValue));
    } else {
      onChange([...value, nextValue]);
    }
  };

  const removeValue = (nextValue: string) => {
    onChange(value.filter((item) => item !== nextValue));
  };

  return (
    <Field
      className={className}
      data-disabled={disabled ? true : undefined}
      data-invalid={error ? true : undefined}
      data-slot="combobox-multiple-field"
    >
      <FieldLabel className={labelClassName} htmlFor={fieldId}>
        {label}
        {required ? <span aria-hidden="true"> *</span> : null}
      </FieldLabel>
      <div className="relative" ref={rootRef}>
        <div
          aria-controls={listboxId}
          aria-describedby={describedBy(
            undefined,
            hint ? hintId : undefined,
            error ? errorId : undefined,
          )}
          aria-expanded={open}
          aria-haspopup="listbox"
          aria-invalid={error ? true : undefined}
          aria-label={accessibleLabel ?? requiredFieldAriaLabel(label, required)}
          aria-required={required || undefined}
          className={cn(
            "flex min-h-10 w-full min-w-0 cursor-pointer items-center justify-between gap-2 rounded-md border border-input bg-card px-2 py-1.5 text-[14px] transition-colors outline-none focus-within:border-brand focus-within:ring-3 focus-within:ring-brand/20",
            disabled &&
              "pointer-events-none cursor-not-allowed bg-surface-muted text-text-disabled",
            error && "border-destructive ring-3 ring-destructive/20",
          )}
          data-slot="combobox-multiple-trigger"
          id={fieldId}
          role="combobox"
          tabIndex={disabled ? -1 : 0}
          onClick={() => {
            if (!disabled) setOpen((current) => !current);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              setOpen((current) => !current);
            }
            if (event.key === "Escape") setOpen(false);
          }}
        >
          <div className="flex min-w-0 flex-1 flex-wrap gap-1.5">
            {selectedOptions.length === 0 ? (
              <span className="px-1 text-text-tertiary">{placeholder}</span>
            ) : (
              selectedOptions.map((option) => (
                <Badge
                  className="h-7 max-w-full gap-1 normal-case"
                  key={option.value}
                  variant="secondary"
                >
                  <span className="truncate">{option.label}</span>
                  <button
                    aria-label={`${option.label} 제거`}
                    className="rounded-sm p-0.5 hover:bg-brand/10"
                    type="button"
                    onClick={(event) => {
                      event.stopPropagation();
                      removeValue(option.value);
                    }}
                  >
                    <XIcon className="size-3" />
                  </button>
                </Badge>
              ))
            )}
          </div>
          <ChevronsUpDownIcon className="size-4 shrink-0 text-icon-default" />
        </div>

        {open && !disabled ? (
          <div
            className="absolute z-50 mt-1 w-full overflow-hidden rounded-md border bg-card shadow-lg"
            data-slot="combobox-multiple-content"
          >
            <div className="relative border-b p-2" data-slot="combobox-multiple-search">
              <SearchIcon className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-text-tertiary" />
              <Input
                aria-label={`${typeof label === "string" ? label : "항목"} 검색`}
                className="pl-8"
                placeholder={searchPlaceholder}
                ref={searchRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Escape") setOpen(false);
                }}
              />
            </div>
            <div
              aria-multiselectable="true"
              className="max-h-72 overflow-auto p-1"
              id={listboxId}
              role="listbox"
            >
              {filteredOptions.length === 0 ? (
                <div
                  className="px-2 py-3 text-sm text-text-secondary"
                  data-slot="combobox-multiple-empty"
                >
                  {emptyMessage}
                </div>
              ) : (
                filteredOptions.map((option) => {
                  const active = selected.has(option.value);
                  return (
                    <button
                      aria-selected={active}
                      className={cn(
                        "flex w-full items-start gap-2 rounded-sm px-2 py-2 text-left text-sm hover:bg-surface-subtle",
                        active && "bg-brand-tint text-brand",
                      )}
                      data-slot="combobox-multiple-option"
                      key={option.value}
                      role="option"
                      type="button"
                      onClick={() => toggleValue(option.value)}
                    >
                      <CheckIcon
                        className={cn(
                          "mt-0.5 size-4 shrink-0",
                          active ? "opacity-100" : "opacity-0",
                        )}
                      />
                      <span className="min-w-0">
                        <span className="block truncate font-medium">
                          {option.label}
                        </span>
                        {option.description ? (
                          <span className="block truncate text-xs text-text-secondary">
                            {option.description}
                          </span>
                        ) : null}
                      </span>
                    </button>
                  );
                })
              )}
            </div>
          </div>
        ) : null}
      </div>
      {hint ? <FieldDescription id={hintId}>{hint}</FieldDescription> : null}
      {error ? <FieldError id={errorId}>{error}</FieldError> : null}
    </Field>
  );
}

export { ComboboxMultiple };
