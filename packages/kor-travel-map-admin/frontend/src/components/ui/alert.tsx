"use client";
import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";
export { Alert, AlertTitle, AlertDescription, AlertAction } from "@kor-travel/ui/alert";

export function AlertActions({ className, ...props }: ComponentProps<"div">) {
  return <div data-slot="alert-actions" className={cn("mt-3 flex flex-wrap items-center gap-2", className)} {...props} />;
}
