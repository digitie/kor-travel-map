// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

/**
 * Alert — 인라인 피드백 밴드. 슬롯은 copy.md의 3부 구조를 그대로 따른다(M18):
 *   <AlertTitle>       무엇이 깨졌나(what)        — 한 문장, 과거형·사실
 *   <AlertDescription> 왜(why)                    — 알면 쓴다
 *   <AlertActions>     무엇을 할까(what to do)     — 버튼/링크 1–2개(`다시 시도`, `이전 화면`)
 *   <AlertAction>      우상단 보조 슬롯(닫기 등)
 * 톤은 status 토큰의 불투명 tint + hairline(rest 그림자 없음, M8). 성공 Alert는 두지 않는다
 * (silent success — design.md §Microinteractions).
 */
const alertVariants = cva(
  "group/alert relative grid w-full gap-1 rounded-panel border px-4 py-3 text-left text-sm has-data-[slot=alert-action]:pr-14 has-[>svg]:grid-cols-[auto_1fr] has-[>svg]:gap-x-3 *:[svg]:col-start-1 *:[svg]:row-start-1 *:[svg]:translate-y-0.5 *:[svg]:text-current *:[svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "border-border bg-card text-text-primary",
        destructive:
          "border-destructive bg-destructive-tint text-destructive *:data-[slot=alert-description]:text-text-primary",
        warning:
          "border-warning bg-warning-tint text-warning *:data-[slot=alert-description]:text-text-primary",
        info: "border-info bg-info-tint text-info *:data-[slot=alert-description]:text-text-primary",
        success:
          "border-success bg-success-tint text-success *:data-[slot=alert-description]:text-text-primary",
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
  // 그 외(default/warning/info/success)는 작업 흐름을 끊지 않도록 role=status(polite)로 안내한다.
  // 호출부가 role/aria-live를 명시하면 그 값을 우선한다. (T-218e)
  const resolvedRole = role ?? (variant === "destructive" ? "alert" : "status")
  const resolvedAriaLive =
    ariaLive ?? (resolvedRole === "alert" ? "assertive" : "polite")
  return (
    <div
      data-slot="alert"
      data-variant={variant ?? "default"}
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
        "text-sm font-semibold group-has-[>svg]/alert:col-start-2 [&_a]:underline [&_a]:underline-offset-4",
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
        "text-xs text-text-secondary group-has-[>svg]/alert:col-start-2 [&_a]:underline [&_a]:underline-offset-4 [&_p:not(:last-child)]:mb-2",
        className
      )}
      {...props}
    />
  )
}

/** what-to-do 슬롯 — 설명 아래 액션 행(버튼/링크 1–2개). */
function AlertActions({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-actions"
      className={cn(
        "mt-2 flex flex-wrap items-center gap-2 group-has-[>svg]/alert:col-start-2",
        className
      )}
      {...props}
    />
  )
}

/** 우상단 보조 슬롯(닫기 버튼 등). 주 액션은 AlertActions에 둔다. */
function AlertAction({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-action"
      className={cn("absolute top-2 right-2", className)}
      {...props}
    />
  )
}

export { Alert, AlertTitle, AlertDescription, AlertActions, AlertAction }
