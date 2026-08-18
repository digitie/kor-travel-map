"use client"
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import { Tabs as TabsPrimitive } from "@base-ui/react/tabs"
import { type VariantProps } from "class-variance-authority"

import { tabsListVariants } from "@/components/ui/tabs-variants"
import { cn } from "@/lib/utils"

/**
 * Tabs — 두 variant, 한 높이(`h-control` 36px):
 * - `default`(segmented): view 토글(지도/테이블)용. 트랙 `bg-surface-subtle`, 활성 = `bg-card` + hairline
 *   (그림자 없음).
 * - `line`(underline): 콘텐츠 탭용. hairline 베이스라인 + 활성은 ink 텍스트 + 2px brand 바(opacity만
 *   전환). 전환 속성은 색/배경/테두리로 한정(M1) — 바는 `transition-opacity`.
 * TabsList recipe(`tabsListVariants`)는 `tabs-variants.ts`가 정본이다.
 */
function Tabs({
  className,
  orientation = "horizontal",
  ...props
}: TabsPrimitive.Root.Props) {
  return (
    <TabsPrimitive.Root
      data-slot="tabs"
      data-orientation={orientation}
      className={cn(
        "group/tabs flex gap-2 data-horizontal:flex-col",
        className
      )}
      {...props}
    />
  )
}

function TabsList({
  className,
  variant = "default",
  ...props
}: TabsPrimitive.List.Props & VariantProps<typeof tabsListVariants>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      data-variant={variant}
      className={cn(tabsListVariants({ variant }), className)}
      {...props}
    />
  )
}

function TabsTrigger({ className, ...props }: TabsPrimitive.Tab.Props) {
  return (
    <TabsPrimitive.Tab
      data-slot="tabs-trigger"
      className={cn(
        "relative inline-flex h-full flex-1 items-center justify-center gap-1.5 rounded-control border border-transparent px-2.5 text-sm font-medium whitespace-nowrap text-text-secondary transition-[color,background-color,border-color] duration-fast ease-out select-none",
        "group-data-vertical/tabs:h-control group-data-vertical/tabs:w-full group-data-vertical/tabs:justify-start",
        "hover:text-text-primary",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        "disabled:cursor-not-allowed disabled:opacity-55 aria-disabled:cursor-not-allowed aria-disabled:opacity-55",
        "has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2",
        "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        // segmented(default): 활성 = card 표면 + hairline, 그림자 없음
        "group-data-[variant=default]/tabs-list:data-active:border-border group-data-[variant=default]/tabs-list:data-active:bg-card group-data-[variant=default]/tabs-list:data-active:text-text-primary",
        // line: 배경 없음, 활성 = ink 텍스트 + brand 바
        "group-data-[variant=line]/tabs-list:rounded-none group-data-[variant=line]/tabs-list:border-0 group-data-[variant=line]/tabs-list:px-1 group-data-[variant=line]/tabs-list:data-active:text-text-primary",
        "after:pointer-events-none after:absolute after:bg-brand after:opacity-0 after:transition-opacity after:duration-fast group-data-horizontal/tabs:after:inset-x-0 group-data-horizontal/tabs:after:-bottom-px group-data-horizontal/tabs:after:h-0.5 group-data-vertical/tabs:after:inset-y-0 group-data-vertical/tabs:after:-right-px group-data-vertical/tabs:after:w-0.5 group-data-[variant=line]/tabs-list:data-active:after:opacity-100",
        className
      )}
      {...props}
    />
  )
}

function TabsContent({ className, ...props }: TabsPrimitive.Panel.Props) {
  return (
    <TabsPrimitive.Panel
      data-slot="tabs-content"
      className={cn(
        "flex-1 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        className
      )}
      {...props}
    />
  )
}

export { Tabs, TabsList, TabsTrigger, TabsContent }
