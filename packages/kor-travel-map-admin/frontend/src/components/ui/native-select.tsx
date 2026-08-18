// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
import * as React from "react"

import { cn } from "@/lib/utils"
import { ChevronDownIcon } from "lucide-react"

type NativeSelectProps = Omit<React.ComponentPropsWithRef<"select">, "size"> & {
  /** 컨트롤 높이 2종만: `default` = `h-control`(36px) · `sm` = `h-control-sm`(30px). */
  size?: "sm" | "default"
}

/**
 * Native `<select>` + styled wrapper (a11y는 브라우저 것 그대로). Input과 같은 recipe:
 * border 1px 고정 · hover 배경만 · 불투명 focus outline · disabled 3채널(opacity/cursor/배경).
 * 우측 chevron 슬롯(`pr-9`)은 항상 예약.
 */
function NativeSelect({
  className,
  size = "default",
  ref,
  ...props
}: NativeSelectProps) {
  return (
    <div
      className={cn(
        "group/native-select relative w-fit has-[select:disabled]:opacity-55",
        className
      )}
      data-slot="native-select-wrapper"
      data-size={size}
    >
      <select
        data-slot="native-select"
        data-size={size}
        ref={ref}
        className={cn(
          "w-full min-w-0 appearance-none rounded-control border border-input bg-card pr-9 pl-3 text-text-primary transition-[color,background-color,border-color] duration-fast ease-out outline-none select-none",
          "h-control text-sm data-[size=sm]:h-control-sm data-[size=sm]:pl-2.5 data-[size=sm]:text-xs",
          "selection:bg-brand selection:text-brand-foreground placeholder:text-text-tertiary",
          "hover:bg-surface-subtle focus-visible:border-text-secondary focus-visible:bg-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
          "disabled:cursor-not-allowed disabled:bg-surface-subtle",
          "aria-invalid:border-destructive"
        )}
        {...props}
      />
      <ChevronDownIcon
        className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-icon-default select-none group-data-[size=sm]/native-select:right-2.5 group-data-[size=sm]/native-select:size-3.5"
        aria-hidden="true"
        data-slot="native-select-icon"
      />
    </div>
  )
}

export { NativeSelect }
export type { NativeSelectProps }
