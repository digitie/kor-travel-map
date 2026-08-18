// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
import * as React from "react"
import { Input as InputPrimitive } from "@base-ui/react/input"

import { cn } from "@/lib/utils"

type InputProps = Omit<React.ComponentProps<"input">, "size"> & {
  /** 컨트롤 높이 2종만: `default` = `h-control`(36px, 15px) · `sm` = `h-control-sm`(30px, 13.5px). */
  size?: "sm" | "default"
}

/**
 * 텍스트 입력 recipe (interaction-and-states §Input field states):
 * border 1px 고정(모든 상태) · hover는 배경만 · focus는 불투명 outline(즉시) · disabled/read-only는
 * opacity + cursor + 배경 3채널 · aria-invalid는 border 색 + 메시지 슬롯(FormField) 병행.
 */
function Input({ className, type, size = "default", ...props }: InputProps) {
  return (
    <InputPrimitive
      type={type}
      data-slot="input"
      data-size={size}
      className={cn(
        "w-full min-w-0 rounded-control border border-input bg-card px-3 text-text-primary transition-[color,background-color,border-color] duration-fast ease-out",
        "h-control text-sm data-[size=sm]:h-control-sm data-[size=sm]:px-2.5 data-[size=sm]:text-xs",
        "file:inline-flex file:h-6 file:border-0 file:bg-transparent file:text-xs file:font-medium file:text-text-primary placeholder:text-text-tertiary",
        "hover:bg-surface-subtle focus-visible:border-text-secondary focus-visible:bg-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        "disabled:cursor-not-allowed disabled:bg-surface-subtle disabled:opacity-55 read-only:cursor-default read-only:bg-surface-subtle read-only:text-text-secondary",
        "aria-invalid:border-destructive",
        className
      )}
      {...props}
    />
  )
}

export { Input }
export type { InputProps }
