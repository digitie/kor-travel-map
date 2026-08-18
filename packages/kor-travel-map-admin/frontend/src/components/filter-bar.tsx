// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * 목록 상단 툴바의 유일한 필터 idiom(M26). 모든 컨트롤을 `FilterField`(가시 라벨 위·컨트롤 아래)로
 * 감싼다 — placeholder는 형식만 보여 주고 라벨을 대신하지 않는다. 행은 wrap(가로 스크롤 금지),
 * 정렬은 column header에만, page-size는 pager 쪽에 둔다.
 */
function FilterBar({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      className={cn("flex flex-wrap items-end gap-x-3 gap-y-2", className)}
      data-slot="filter-bar"
      {...props}
    />
  );
}

/**
 * 라벨 + 컨트롤 결합. 라벨은 12px/500 secondary. `htmlFor`를 주면 label이 컨트롤을 가리키고,
 * 생략하면 label이 컨트롤을 감싼다(native input/select에 적합).
 * `hint`는 컨트롤 아래 한 줄(형식 안내·disabled 사유 — 색만으로 알리지 않는다).
 */
function FilterField({
  label,
  htmlFor,
  hint,
  className,
  children,
}: {
  label: string;
  htmlFor?: string;
  /** 컨트롤 아래 한 줄 보조 문구(형식/사유). */
  hint?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <label
      className={cn("flex min-w-0 flex-col gap-1", className)}
      data-slot="filter-field"
      htmlFor={htmlFor}
    >
      <span className="text-2xs leading-none font-medium text-text-secondary">{label}</span>
      {children}
      {hint ? <span className="text-2xs text-text-tertiary">{hint}</span> : null}
    </label>
  );
}

/** 툴바 우측 액션 묶음(적용/초기화 등) — FilterBar 안에서 컨트롤과 baseline을 맞춘다. */
function FilterActions({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn("flex flex-wrap items-center gap-2 self-end", className)}
      data-slot="filter-actions"
      {...props}
    />
  );
}

export { FilterActions, FilterBar, FilterField };
