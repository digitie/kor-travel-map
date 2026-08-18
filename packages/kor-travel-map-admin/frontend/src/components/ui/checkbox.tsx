"use client"
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import { Checkbox as CheckboxPrimitive } from "@base-ui/react/checkbox"

import { cn } from "@/lib/utils"
import { CheckIcon, MinusIcon } from "lucide-react"

/**
 * Checkbox: 16px 시각 크기 + `::after` 확장으로 32×32 hit target(design.md §Microinteractions —
 * hit target ≥ 24px). 44×44까지 키우면 표 안에서 확장 영역이 이웃 셀(이름 링크)과 위아래 행을
 * 덮어 오클릭이 난다 — 확장은 선택 열 폭(36px)과 행 높이(≈33px) 안으로 제한한다.
 * 상태 8종: rest(hairline) · hover(border 진해짐) · focus-visible(불투명 outline) ·
 * checked(brand fill + check 글리프) · disabled(opacity + cursor) · aria-invalid(destructive
 * border) · indeterminate(brand fill + minus 글리프 — check와 형태로 구분) · loading 없음.
 */
function Checkbox({
  className,
  indeterminate,
  ...props
}: CheckboxPrimitive.Root.Props) {
  return (
    <CheckboxPrimitive.Root
      data-slot="checkbox"
      indeterminate={indeterminate}
      className={cn(
        "peer relative flex size-4 shrink-0 items-center justify-center rounded-control border border-input bg-card text-brand-foreground transition-[color,background-color,border-color] duration-fast ease-out",
        "after:absolute after:-inset-2 after:content-['']",
        "data-[unchecked]:hover:border-text-secondary data-[unchecked]:hover:bg-surface-subtle",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        "disabled:cursor-not-allowed disabled:opacity-55 group-has-disabled/field:opacity-55",
        "aria-invalid:border-destructive",
        "data-checked:border-brand data-checked:bg-brand data-checked:text-brand-foreground data-[checked]:hover:border-brand-hover data-[checked]:hover:bg-brand-hover",
        "data-[indeterminate]:border-brand data-[indeterminate]:bg-brand data-[indeterminate]:text-brand-foreground",
        className
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator
        data-slot="checkbox-indicator"
        className="grid place-content-center text-current transition-none [&>svg]:size-3.5"
      >
        {/* base-ui Indicator는 checked · indeterminate 양쪽에서 렌더된다 — 두 상태가
            같은 글리프면 구분이 색뿐이라(M4) indeterminate는 minus로 갈라 놓는다. */}
        {indeterminate ? <MinusIcon /> : <CheckIcon />}
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  )
}

export { Checkbox }
