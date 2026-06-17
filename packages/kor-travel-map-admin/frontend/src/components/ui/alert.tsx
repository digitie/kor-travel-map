import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const alertVariants = cva(
  "group/alert relative grid w-full gap-1 rounded-2xl border px-6 py-5 text-left text-[14px] shadow-[var(--shadow-card)] has-data-[slot=alert-action]:relative has-data-[slot=alert-action]:pr-18 has-[>svg]:grid-cols-[auto_1fr] has-[>svg]:gap-x-3 *:[svg]:row-span-2 *:[svg]:translate-y-0.5 *:[svg]:text-current *:[svg:not([class*='size-'])]:size-5",
  {
    variants: {
      variant: {
        default: "border-surface-muted bg-card text-card-foreground",
        destructive:
          "border-destructive/20 bg-card text-destructive *:data-[slot=alert-description]:text-destructive/90 *:[svg]:text-current",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Alert({
  className,
  variant,
  role,
  "aria-live": ariaLive,
  ...props
}: React.ComponentProps<"div"> & VariantProps<typeof alertVariants>) {
  // 에러(destructive)는 즉시 안내해야 하므로 role=alert(assertive),
  // 성공/정보(default)는 작업 흐름을 끊지 않도록 role=status(polite)로 안내한다.
  // 호출부가 role/aria-live를 명시하면 그 값을 우선한다. (T-218e)
  const resolvedRole = role ?? (variant === "destructive" ? "alert" : "status")
  const resolvedAriaLive =
    ariaLive ?? (resolvedRole === "alert" ? "assertive" : "polite")
  return (
    <div
      data-slot="alert"
      role={resolvedRole}
      aria-live={resolvedAriaLive}
      className={cn(alertVariants({ variant }), className)}
      {...props}
    />
  )
}

function AlertTitle({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-title"
      className={cn(
        "text-[14px] font-bold group-has-[>svg]/alert:col-start-2 [&_a]:underline [&_a]:underline-offset-3 [&_a]:hover:text-text-primary",
        className
      )}
      {...props}
    />
  )
}

function AlertDescription({
  className,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-description"
      className={cn(
        "text-[13px] text-balance text-text-secondary md:text-pretty [&_a]:underline [&_a]:underline-offset-3 [&_a]:hover:text-text-primary [&_p:not(:last-child)]:mb-4",
        className
      )}
      {...props}
    />
  )
}

function AlertAction({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-action"
      className={cn("absolute top-2 right-2", className)}
      {...props}
    />
  )
}

export { Alert, AlertTitle, AlertDescription, AlertAction }
