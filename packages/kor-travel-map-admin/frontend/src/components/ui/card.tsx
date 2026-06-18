import * as React from "react"

import { cn } from "@/lib/utils"

function Card({
  className,
  size = "default",
  ...props
}: React.ComponentProps<"div"> & { size?: "default" | "sm" }) {
  return (
    <div
      data-slot="card"
      data-size={size}
      className={cn(
        "group/card flex flex-col gap-5 overflow-hidden rounded-2xl bg-card p-6 text-[14px] leading-normal text-card-foreground shadow-[var(--shadow-card)] ring-1 ring-border/70 transition-shadow has-data-[slot=card-footer]:pb-0 hover:shadow-[var(--shadow-card-hover)] has-[>img:first-child]:pt-0 data-[size=sm]:gap-4 data-[size=sm]:p-5 data-[size=sm]:has-data-[slot=card-footer]:pb-0 *:[img:first-child]:rounded-t-2xl *:[img:last-child]:rounded-b-2xl",
        className
      )}
      {...props}
    />
  )
}

function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-header"
      className={cn(
        "group/card-header @container/card-header grid auto-rows-min items-start gap-1.5 rounded-t-2xl group-data-[size=sm]/card:gap-1 has-data-[slot=card-action]:grid-cols-[1fr_auto] has-data-[slot=card-description]:grid-rows-[auto_auto] [.border-b]:pb-5 group-data-[size=sm]/card:[.border-b]:pb-4",
        className
      )}
      {...props}
    />
  )
}

function CardTitle({
  className,
  role = "heading",
  "aria-level": ariaLevel = 2,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      aria-level={ariaLevel}
      data-slot="card-title"
      role={role}
      className={cn(
        "font-heading text-[18px] leading-snug font-bold text-text-primary group-data-[size=sm]/card:text-[14px]",
        className
      )}
      {...props}
    />
  )
}

function CardDescription({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-description"
      className={cn("text-[13px] leading-normal text-text-secondary", className)}
      {...props}
    />
  )
}

function CardAction({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-action"
      className={cn(
        "col-start-2 row-span-2 row-start-1 self-start justify-self-end text-icon-default [&_svg:not([class*='size-'])]:size-5",
        className
      )}
      {...props}
    />
  )
}

function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-content"
      className={cn("min-w-0", className)}
      {...props}
    />
  )
}

function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-footer"
      className={cn(
        "-mx-6 -mb-6 mt-1 flex items-center rounded-b-2xl border-t border-surface-muted bg-surface-subtle px-6 py-4 group-data-[size=sm]/card:-mx-5 group-data-[size=sm]/card:-mb-5 group-data-[size=sm]/card:px-5 group-data-[size=sm]/card:py-3",
        className
      )}
      {...props}
    />
  )
}

export {
  Card,
  CardHeader,
  CardFooter,
  CardTitle,
  CardAction,
  CardDescription,
  CardContent,
}
