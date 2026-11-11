"use client";
import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";
export {
  AlertTitle,
  AlertDescription,
  AlertAction,
} from "@kor-travel/ui/alert";

export function AlertActions({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-actions"
      className={cn("mt-3 flex flex-wrap items-center gap-2", className)}
      {...props}
    />
  );
}

import { Alert as CommonAlert } from "@kor-travel/ui/alert";

/** 오류는 assertive, 일반 작업 결과는 polite로 알리는 기존 Map 계약. */
export function Alert({
  variant,
  role,
  "aria-live": live,
  ...props
}: ComponentProps<typeof CommonAlert>) {
  const resolvedRole = role ?? (variant === "destructive" ? "alert" : "status");
  return (
    <CommonAlert
      data-variant={variant ?? "default"}
      variant={variant}
      role={resolvedRole}
      aria-live={live ?? (resolvedRole === "alert" ? "assertive" : "polite")}
      {...props}
    />
  );
}
