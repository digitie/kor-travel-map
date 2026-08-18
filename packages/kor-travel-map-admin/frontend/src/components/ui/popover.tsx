"use client"
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import { Popover as PopoverPrimitive } from "@base-ui/react/popover"

import { cn } from "@/lib/utils"

function Popover({ ...props }: PopoverPrimitive.Root.Props) {
  return <PopoverPrimitive.Root data-slot="popover" {...props} />
}

function PopoverTrigger({ ...props }: PopoverPrimitive.Trigger.Props) {
  return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />
}

/**
 * Elevated surface: `bg-card` + hairline + `rounded-panel` + `shadow-elevated` (popover/menu tier;
 * dialogs use `shadow-modal`). Motion = design.md overlay recipe (opacity + scale .98, 150ms in /
 * 100ms out); `data-motion="crossfade"` keeps an opacity-only crossfade under reduced motion.
 *
 * `focus-visible:outline-0` — 패널은 `tabIndex=-1`로 프로그램적 포커스만 받는 컨테이너다(키보드로
 * 열면 base-ui가 여기로 포커스를 옮긴다). 링을 그리면 팝오버 전체가 2px 테를 두르는데, 조작
 * 가능한 요소가 아니라 등장 자체가 상태 변화를 알린다. `outline-none` 대신 폭만 0인 `outline-0`을
 * 쓴다 — `--tw-outline-style: none` 오염이 없어야 안의 컨트롤이 base 레시피 링을 받는다.
 */
function PopoverContent({
  className,
  sideOffset = 8,
  align = "center",
  children,
  ...props
}: PopoverPrimitive.Popup.Props & {
  sideOffset?: number
  align?: PopoverPrimitive.Positioner.Props["align"]
}) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Positioner
        align={align}
        sideOffset={sideOffset}
        className="z-50"
      >
        <PopoverPrimitive.Popup
          data-slot="popover-content"
          data-motion="crossfade"
          className={cn(
            "w-72 rounded-panel border border-border bg-card p-4 text-xs leading-normal text-text-primary shadow-elevated focus-visible:outline-0",
            "transition-[opacity,scale] duration-base ease-out data-[starting-style]:scale-98 data-[starting-style]:opacity-0 data-[ending-style]:scale-98 data-[ending-style]:opacity-0 data-[ending-style]:duration-fast data-[ending-style]:ease-in",
            className
          )}
          {...props}
        >
          {children}
        </PopoverPrimitive.Popup>
      </PopoverPrimitive.Positioner>
    </PopoverPrimitive.Portal>
  )
}

function PopoverClose({ ...props }: PopoverPrimitive.Close.Props) {
  return <PopoverPrimitive.Close data-slot="popover-close" {...props} />
}

export { Popover, PopoverClose, PopoverContent, PopoverTrigger }
