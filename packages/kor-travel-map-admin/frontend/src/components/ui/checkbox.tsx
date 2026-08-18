"use client"
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import { Checkbox as CheckboxPrimitive } from "@base-ui/react/checkbox"

import { cn } from "@/lib/utils"
import { CheckIcon } from "lucide-react"

/**
 * Checkbox: 16px 시각 크기 + `::after` 확장으로 44×44 hit target(M23). 상태 8종:
 * rest(hairline) · hover(border 진해짐) · focus-visible(불투명 outline) · checked(brand fill) ·
 * disabled(opacity + cursor) · aria-invalid(destructive border) · indeterminate(base-ui) · loading 없음.
 */
function Checkbox({ className, ...props }: CheckboxPrimitive.Root.Props) {
  return (
    <CheckboxPrimitive.Root
      data-slot="checkbox"
      className={cn(
        "peer relative flex size-4 shrink-0 items-center justify-center rounded-control border border-input bg-card text-brand-foreground transition-[color,background-color,border-color] duration-fast ease-out outline-none",
        "after:absolute after:-inset-3.5 after:content-['']",
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
        <CheckIcon />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  )
}

export { Checkbox }
