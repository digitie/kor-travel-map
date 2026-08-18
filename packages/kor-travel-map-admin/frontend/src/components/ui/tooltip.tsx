"use client"
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import { Tooltip as TooltipPrimitive } from "@base-ui/react/tooltip"

import { cn } from "@/lib/utils"

/**
 * Tooltip timing (design.md §Microinteractions): hover opens after 800ms so casual pointer
 * travel never flashes tooltips; keyboard focus opens at 0ms (Base UI's focus interaction has
 * no delay — only the hover path reads `delay`). Popups stay hoverable (WCAG 1.4.13) and close
 * on Escape. Wrap a screen's tooltips in one Provider so adjacent tooltips skip the delay.
 */
function TooltipProvider({
  delay = 800,
  ...props
}: TooltipPrimitive.Provider.Props) {
  return (
    <TooltipPrimitive.Provider data-slot="tooltip-provider" delay={delay} {...props} />
  )
}

function Tooltip({ ...props }: TooltipPrimitive.Root.Props) {
  return <TooltipPrimitive.Root data-slot="tooltip" {...props} />
}

function TooltipTrigger({ ...props }: TooltipPrimitive.Trigger.Props) {
  return <TooltipPrimitive.Trigger data-slot="tooltip-trigger" {...props} />
}

/**
 * Ink-on-paper inversion (`bg-text-primary` / `text-surface-page`) so the tip reads as a label,
 * not a panel. Motion = opacity only, 150ms in / 100ms out; `data-instant` (focus / grouped
 * hover / dismiss) renders without transition; `data-motion="crossfade"` keeps the opacity-only
 * crossfade under reduced motion.
 */
function TooltipContent({
  className,
  sideOffset = 6,
  children,
  ...props
}: TooltipPrimitive.Popup.Props & { sideOffset?: number }) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Positioner sideOffset={sideOffset} className="z-50">
        <TooltipPrimitive.Popup
          data-slot="tooltip-content"
          data-motion="crossfade"
          className={cn(
            "max-w-xs rounded-control bg-text-primary px-3 py-1.5 text-2xs leading-normal text-surface-page shadow-elevated",
            "transition-opacity duration-base ease-out data-[starting-style]:opacity-0 data-[ending-style]:opacity-0 data-[ending-style]:duration-fast data-[ending-style]:ease-in data-[instant]:duration-0",
            className
          )}
          {...props}
        >
          {children}
        </TooltipPrimitive.Popup>
      </TooltipPrimitive.Positioner>
    </TooltipPrimitive.Portal>
  )
}

export { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger }
