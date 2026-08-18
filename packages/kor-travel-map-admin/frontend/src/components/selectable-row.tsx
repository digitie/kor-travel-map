"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * SelectableRow — 목록에서 하나를 고르는 행의 유일한 idiom(m7). 테두리 없는 행: hover는 배경만,
 * 선택은 `bg-brand-tint` + 좌측 2px brand 마크(색 1채널이 아니게 형태를 더한다), 키보드는 option처럼
 * (Enter/Space 선택, 그룹 안에서 ↑/↓·Home/End 이동). 안쪽 버튼/링크는 stopPropagation 한다.
 *
 *   <SelectableRowGroup aria-label="컬렉션">
 *     <SelectableRow selected={id === current} onSelect={() => setCurrent(id)}>…</SelectableRow>
 *   </SelectableRowGroup>
 */

type SelectableRowProps = Omit<
  React.ComponentProps<"div">,
  "role" | "onSelect" | "aria-selected" | "aria-disabled"
> & {
  selected: boolean;
  onSelect: () => void;
  /** 선택 불가 — 사유(`disabledReason`)를 inline note + title로 함께 보여 준다. */
  disabled?: boolean;
  disabledReason?: string;
  /** 우측 정렬 보조 슬롯(배지/카운트). */
  trailing?: React.ReactNode;
  /** 밀도. */
  size?: "default" | "sm";
};

function SelectableRow({
  selected,
  onSelect,
  disabled = false,
  disabledReason,
  trailing,
  size = "default",
  className,
  children,
  onClick,
  onKeyDown,
  title,
  ...props
}: SelectableRowProps) {
  const activate = () => {
    if (disabled) return;
    onSelect();
  };
  return (
    <div
      aria-disabled={disabled || undefined}
      aria-selected={selected}
      className={cn(
        "group/row relative flex w-full cursor-pointer items-start gap-3 rounded-control text-left text-sm text-text-primary transition-colors outline-none select-none",
        size === "default" ? "px-3 py-2" : "px-2 py-1.5",
        "hover:bg-surface-subtle focus-visible:bg-surface-subtle focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus active:bg-surface-muted",
        "aria-selected:bg-brand-tint aria-selected:hover:bg-brand-tint aria-selected:focus-visible:bg-brand-tint aria-selected:before:absolute aria-selected:before:inset-y-2 aria-selected:before:left-0 aria-selected:before:w-0.5 aria-selected:before:rounded-full aria-selected:before:bg-brand aria-selected:before:content-['']",
        "aria-disabled:cursor-not-allowed aria-disabled:opacity-55 aria-disabled:hover:bg-transparent",
        className,
      )}
      data-slot="selectable-row"
      data-state={selected ? "selected" : undefined}
      role="option"
      tabIndex={disabled ? -1 : 0}
      title={disabled && disabledReason ? disabledReason : title}
      onClick={(event) => {
        onClick?.(event);
        if (event.defaultPrevented) return;
        activate();
      }}
      onKeyDown={(event) => {
        onKeyDown?.(event);
        if (event.defaultPrevented) return;
        if (event.target !== event.currentTarget) return;
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          activate();
        }
      }}
      {...props}
    >
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        {children}
        {disabled && disabledReason ? (
          <span className="text-2xs text-text-secondary">{disabledReason}</span>
        ) : null}
      </div>
      {trailing ? (
        <div className="flex shrink-0 items-center gap-1 self-center text-xs text-text-secondary">
          {trailing}
        </div>
      ) : null}
    </div>
  );
}

/** 행의 1차 텍스트(이름) — 500 ink, 한 줄 말줄임. */
function SelectableRowTitle({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      className={cn("truncate font-medium text-text-primary", className)}
      data-slot="selectable-row-title"
      {...props}
    />
  );
}

/** 행의 2차 텍스트(식별자·요약) — 13.5px secondary. 식별자면 `font-mono`를 더한다. */
function SelectableRowDescription({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      className={cn("truncate text-xs text-text-secondary", className)}
      data-slot="selectable-row-description"
      {...props}
    />
  );
}

type SelectableRowGroupProps = Omit<React.ComponentProps<"div">, "role"> & {
  /** 행 사이 hairline. */
  divided?: boolean;
};

const OPTION_SELECTOR = '[role="option"]:not([aria-disabled="true"])';

/**
 * listbox 컨테이너 — ↑/↓·Home/End로 행 사이 포커스를 옮긴다(roving). `aria-label` 또는
 * `aria-labelledby`를 반드시 준다.
 */
function SelectableRowGroup({
  divided = false,
  className,
  onKeyDown,
  ...props
}: SelectableRowGroupProps) {
  return (
    <div
      className={cn("flex flex-col", divided && "divide-y divide-border", className)}
      data-slot="selectable-row-group"
      role="listbox"
      onKeyDown={(event) => {
        onKeyDown?.(event);
        if (event.defaultPrevented) return;
        const keys = ["ArrowDown", "ArrowUp", "Home", "End"];
        if (!keys.includes(event.key)) return;
        const options = Array.from(
          event.currentTarget.querySelectorAll<HTMLElement>(OPTION_SELECTOR),
        );
        if (options.length === 0) return;
        const current = options.indexOf(document.activeElement as HTMLElement);
        let next = current;
        if (event.key === "ArrowDown") next = current < 0 ? 0 : Math.min(current + 1, options.length - 1);
        if (event.key === "ArrowUp") next = current < 0 ? 0 : Math.max(current - 1, 0);
        if (event.key === "Home") next = 0;
        if (event.key === "End") next = options.length - 1;
        if (next === current) return;
        event.preventDefault();
        options[next]?.focus();
      }}
      {...props}
    />
  );
}

export { SelectableRow, SelectableRowDescription, SelectableRowGroup, SelectableRowTitle };
export type { SelectableRowGroupProps, SelectableRowProps };
