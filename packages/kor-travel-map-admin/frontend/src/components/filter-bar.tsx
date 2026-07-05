import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * 목록 상단 필터 행 표준 (§3). 셀렉트/인풋/콤보박스를 `FilterField`로 감싸
 * 라벨-컨트롤 결합과 간격(§6 gap-3)을 통일한다.
 */
function FilterBar({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      className={cn("flex flex-wrap items-end gap-3", className)}
      data-slot="filter-bar"
      {...props}
    />
  );
}

function FilterField({
  label,
  htmlFor,
  className,
  children,
}: {
  label: string;
  htmlFor?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <label className={cn("flex flex-col gap-1", className)} htmlFor={htmlFor}>
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

export { FilterBar, FilterField };
