// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * Card — 패널 표면의 유일한 chrome(design.md §Spacing·shape·size §Depth).
 * rest = hairline(`border-border`) + `rounded-panel`, 그림자 없음, hover 상승 없음(M8/C3).
 * `min-w-0` — Card 가 flex/grid item 일 때 자동 최소 크기(min-content)를 끈다. 이게 없으면
 * nowrap 헤더 행이나 표를 품은 카드가 좁은 뷰포트에서 트랙을 밀어내 문서 가로 스크롤이 생긴다
 * (홈 `grid gap-6 xl:grid-cols-[…]`가 390px에서 445px 트랙이 되던 원인). 예전 카드는
 * `overflow-hidden`이 우연히 같은 효과를 냈지만, 그건 포커스 링·팝오버까지 잘라 쓰지 않는다.
 * 실제로 클릭되는 카드만 `data-interactive` opt-in: hover 배경 + focus-visible outline.
 * Card 안에 Card/SectionCard/bordered box를 넣지 않는다 — containment은 region당 1층.
 */
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
        "group/card flex min-w-0 flex-col gap-4 rounded-panel border border-border bg-card p-6 text-sm text-text-primary has-data-[slot=card-footer]:pb-0 has-[>img:first-child]:pt-0 data-[size=sm]:gap-3 data-[size=sm]:p-4 data-[size=sm]:has-data-[slot=card-footer]:pb-0 *:[img:first-child]:rounded-t-panel *:[img:last-child]:rounded-b-panel",
        // 전환 속성 열거(v4 `transition-colors`는 `outline-color` 포함 → 포커스 링이 페이드인).
        "data-interactive:cursor-pointer data-interactive:transition-[color,background-color,border-color] data-interactive:hover:bg-surface-subtle data-interactive:focus-visible:outline-2 data-interactive:focus-visible:outline-offset-2 data-interactive:focus-visible:outline-focus data-interactive:active:bg-surface-muted",
        className
      )}
      {...props}
    />
  )
}

/**
 * 제목 행. `border-b`를 주면 카드 패딩 밖까지 뻗는 hairline이 아래에 그어진다
 * (SectionCard가 이 형태를 쓴다 — 제목 밴드 + flat body).
 */
function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-header"
      className={cn(
        "group/card-header @container/card-header grid auto-rows-min items-start gap-1 has-data-[slot=card-action]:grid-cols-[1fr_auto] has-data-[slot=card-description]:grid-rows-[auto_auto] group-data-[size=sm]/card:gap-0.5",
        "[.border-b]:-mx-6 [.border-b]:border-border [.border-b]:px-6 [.border-b]:pb-4 group-data-[size=sm]/card:[.border-b]:-mx-4 group-data-[size=sm]/card:[.border-b]:px-4 group-data-[size=sm]/card:[.border-b]:pb-3",
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
        "text-md leading-snug font-semibold text-text-primary group-data-[size=sm]/card:text-sm",
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
      className={cn("text-xs text-text-secondary", className)}
      {...props}
    />
  )
}

function CardAction({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-action"
      className={cn(
        "col-start-2 row-span-2 row-start-1 flex items-center gap-2 self-start justify-self-end text-icon-default",
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

/**
 * 카드 하단 행 — hairline 위에 flat(틴트 밴드 없음). 저장 행/요약 행에 쓴다.
 * 좌우로만 bleed한다(`-mx-*` + 같은 값의 `px-*`): 아래쪽 여백은 Card의
 * `has-data-[slot=card-footer]:pb-0`가 이미 걷어내므로 음수 `-mb-*`를 더하면 footer가 카드
 * 테두리 밖으로 넘쳐 밑줄이 두 겹으로 보인다(drift-P1-4).
 */
function CardFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-footer"
      className={cn(
        "-mx-6 mt-1 flex flex-wrap items-center gap-2 rounded-b-panel border-t border-border px-6 py-3 group-data-[size=sm]/card:-mx-4 group-data-[size=sm]/card:px-4 group-data-[size=sm]/card:py-3",
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
