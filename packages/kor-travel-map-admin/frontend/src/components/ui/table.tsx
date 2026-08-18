"use client"
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * Table — dense list의 기본 표면. 컨테이너는 Table 자신의 hairline(`rounded-panel border-border`)
 * 하나뿐이다: 바깥에 다른 bordered box를 두지 않는다(C3). Card/SectionCard *안*에 놓이면
 * 자동으로 flush(테두리·모서리·배경 제거)가 되어 containment이 1층으로 유지된다.
 * 숫자 정렬을 위해 table 전체가 `tabular-nums`(M24), 헤더는 12px/600 secondary
 * (uppercase·tracking 없음, m3). 긴 본문 셀(message 등)은 `whitespace-normal`을 주어
 * clamp/wrap이 동작하게 한다(M38).
 */
function Table({
  className,
  containerClassName,
  ...props
}: React.ComponentProps<"table"> & {
  /** 스크롤 컨테이너(div) className — 높이 제한/스크롤 축 조정용. */
  containerClassName?: string
}) {
  return (
    <div
      data-slot="table-container"
      className={cn(
        "relative w-full overflow-x-auto rounded-panel border border-border bg-card group-data-[slot=card]/card:rounded-none group-data-[slot=card]/card:border-0 group-data-[slot=card]/card:bg-transparent",
        containerClassName
      )}
    >
      <table
        data-slot="table"
        className={cn("w-full caption-bottom text-sm tabular-nums", className)}
        {...props}
      />
    </div>
  )
}

function TableHeader({ className, ...props }: React.ComponentProps<"thead">) {
  return (
    <thead
      data-slot="table-header"
      className={cn("bg-surface-subtle [&_tr]:border-b", className)}
      {...props}
    />
  )
}

function TableBody({ className, ...props }: React.ComponentProps<"tbody">) {
  return (
    <tbody
      data-slot="table-body"
      className={cn("[&_tr:last-child]:border-0", className)}
      {...props}
    />
  )
}

function TableFooter({ className, ...props }: React.ComponentProps<"tfoot">) {
  return (
    <tfoot
      data-slot="table-footer"
      className={cn(
        "border-t border-border bg-surface-subtle font-medium [&>tr]:last:border-b-0",
        className
      )}
      {...props}
    />
  )
}

function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return (
    <tr
      data-slot="table-row"
      className={cn(
        // 전환 속성은 열거한다: v4 `transition-colors`는 `outline-color`까지 포함해
        // 클릭 가능한 행(`tabIndex=0`)의 포커스 링이 100ms 페이드인 된다(design.md §Focus).
        "border-b border-border transition-[color,background-color,border-color] hover:bg-surface-subtle has-aria-expanded:bg-surface-subtle data-[state=selected]:bg-brand-tint",
        className
      )}
      {...props}
    />
  )
}

function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return (
    <th
      data-slot="table-head"
      className={cn(
        "h-9 px-3 text-left align-middle text-2xs leading-none font-semibold whitespace-nowrap text-text-secondary [&:has([role=checkbox])]:pr-0",
        className
      )}
      {...props}
    />
  )
}

function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return (
    <td
      data-slot="table-cell"
      className={cn(
        "px-3 py-2 align-middle whitespace-nowrap text-text-primary [&:has([role=checkbox])]:pr-0",
        className
      )}
      {...props}
    />
  )
}

function TableCaption({
  className,
  ...props
}: React.ComponentProps<"caption">) {
  return (
    <caption
      data-slot="table-caption"
      className={cn("mt-3 text-xs text-text-secondary", className)}
      {...props}
    />
  )
}

export {
  Table,
  TableHeader,
  TableBody,
  TableFooter,
  TableHead,
  TableRow,
  TableCell,
  TableCaption,
}
