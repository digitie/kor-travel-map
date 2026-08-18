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

/**
 * 라벨 래퍼 — `disabled`/`aria-disabled`의 흐림(`opacity-55`)을 **root가 아니라 이 자식에** 건다.
 * `opacity`는 요소 전체를 합성하므로 root에 걸면 자기 focus outline까지 55 %로 흐려진다
 * (light page 6.66 → 2.57:1 · card 6.93 → 2.61 / dark 10.26 → 3.89 — WCAG 2.4.11의 3:1 미달).
 * 특히 `aria-disabled`는 **포커스를 유지하는** 상태라 1.4.11의 "비활성 컴포넌트" 면제 대상이
 * 아니다(design.md §Focus/§States). 같은 레시피가 `button.tsx`(`[data-slot="button-label"]`)와
 * `selectable-row.tsx`(content/trailing)에 있다. `gap-[inherit]`이라 아이콘+라벨 간격은 트리거의
 * `gap-1.5`를 그대로 물려받고, `after:` brand 바와 테두리·링은 항상 100 %로 남는다.
 */
const TABS_TRIGGER_LABEL_CLASS =
  "inline-flex items-center justify-center gap-[inherit] group-disabled/tabs-trigger:opacity-55 group-aria-disabled/tabs-trigger:opacity-55"

function TabsTrigger({ className, children, ...props }: TabsPrimitive.Tab.Props) {
  return (
    <TabsPrimitive.Tab
      data-slot="tabs-trigger"
      className={cn(
        "group/tabs-trigger relative inline-flex h-full flex-1 items-center justify-center gap-1.5 rounded-control border border-transparent px-2.5 text-sm font-medium whitespace-nowrap text-text-secondary transition-[color,background-color,border-color] duration-fast ease-out select-none",
        "group-data-vertical/tabs:h-control group-data-vertical/tabs:w-full group-data-vertical/tabs:justify-start",
        "hover:text-text-primary",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        // 흐림은 위 라벨 래퍼가 맡는다 — root `opacity`는 링까지 함께 흐린다.
        "disabled:cursor-not-allowed aria-disabled:cursor-not-allowed",
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
    >
      <span className={TABS_TRIGGER_LABEL_CLASS} data-slot="tabs-trigger-label">
        {children}
      </span>
    </TabsPrimitive.Tab>
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
