// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
import * as React from "react"
import { mergeProps } from "@base-ui/react/merge-props"
import { useRender } from "@base-ui/react/use-render"
import { ChevronRightIcon } from "lucide-react"

import { cn } from "@/lib/utils"

/**
 * Breadcrumb — 헤더 밴드의 위치 표기(13.5px secondary). 링크는 밑줄 없이 hover 시 잉크가
 * 짙어지고, 현재 페이지만 500 ink. `BreadcrumbLink`는 `render`로 next/link를 받을 수 있다.
 */
function Breadcrumb({ ...props }: React.ComponentProps<"nav">) {
  return <nav aria-label="breadcrumb" data-slot="breadcrumb" {...props} />
}

function BreadcrumbList({ className, ...props }: React.ComponentProps<"ol">) {
  return (
    <ol
      data-slot="breadcrumb-list"
      className={cn(
        "flex flex-wrap items-center gap-1.5 text-xs break-words text-text-secondary",
        className
      )}
      {...props}
    />
  )
}

function BreadcrumbItem({ className, ...props }: React.ComponentProps<"li">) {
  return (
    <li
      data-slot="breadcrumb-item"
      className={cn("inline-flex items-center gap-1.5", className)}
      {...props}
    />
  )
}

function BreadcrumbLink({
  className,
  render,
  ...props
}: useRender.ComponentProps<"a">) {
  return useRender({
    defaultTagName: "a",
    props: mergeProps<"a">(
      {
        className: cn(
          // 전환 속성 열거(v4 `transition-colors`는 `outline-color` 포함 → 포커스 링이 페이드인).
          "rounded-control no-underline transition-[color,background-color,border-color] hover:text-text-primary hover:no-underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus active:text-text-primary",
          className
        ),
      },
      props
    ),
    render,
    state: { slot: "breadcrumb-link" },
  })
}

function BreadcrumbPage({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      aria-current="page"
      data-slot="breadcrumb-page"
      className={cn("font-medium text-text-primary", className)}
      {...props}
    />
  )
}

function BreadcrumbSeparator({
  children,
  className,
  ...props
}: React.ComponentProps<"li">) {
  return (
    <li
      aria-hidden="true"
      data-slot="breadcrumb-separator"
      role="presentation"
      className={cn("text-text-tertiary [&>svg]:size-3.5", className)}
      {...props}
    >
      {children ?? <ChevronRightIcon />}
    </li>
  )
}

export {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
}
