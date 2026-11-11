"use client";
import type { ComponentProps } from "react";
import { Badge as CommonBadge } from "@kor-travel/ui/badge";
import { badgeVariants, type BadgeVariant } from "./badge-variants";
import { cn } from "@/lib/utils";
export type { BadgeVariant } from "./badge-variants";

/** 상태색은 기존 Map 토큰을 유지하고 합성은 공통 shadcn 부품을 사용한다. */
export function Badge({
  variant = "default",
  className,
  ...props
}: Omit<ComponentProps<typeof CommonBadge>, "variant"> & {
  variant?: BadgeVariant;
}) {
  return (
    <CommonBadge
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  );
}
