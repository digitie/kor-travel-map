import * as React from "react"

import { cn } from "@/lib/utils"
import { ChevronDownIcon } from "lucide-react"

type NativeSelectProps = Omit<React.ComponentPropsWithRef<"select">, "size"> & {
  size?: "sm" | "default"
}

function NativeSelect({
  className,
  size = "default",
  ref,
  ...props
}: NativeSelectProps) {
  return (
    <div
      className={cn(
        "group/native-select relative w-fit has-[select:disabled]:opacity-50",
        className
      )}
      data-slot="native-select-wrapper"
      data-size={size}
    >
      <select
        data-slot="native-select"
        data-size={size}
        ref={ref}
        className="h-10 w-full min-w-0 appearance-none rounded-md border border-input bg-card py-2 pr-9 pl-3 text-[14px] transition-colors outline-none select-none selection:bg-brand selection:text-brand-foreground placeholder:text-text-tertiary focus-visible:border-brand focus-visible:ring-3 focus-visible:ring-brand/20 disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-text-disabled aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 data-[size=sm]:h-9 data-[size=sm]:py-1.5 data-[size=sm]:text-[13px] dark:bg-card dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40"
        {...props}
      />
      <ChevronDownIcon className="pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 text-icon-default select-none" aria-hidden="true" data-slot="native-select-icon" />
    </div>
  )
}

export { NativeSelect }
export type { NativeSelectProps }
