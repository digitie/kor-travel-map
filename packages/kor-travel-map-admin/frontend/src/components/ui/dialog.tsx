"use client"
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import * as React from "react"

import { Dialog as DialogPrimitive } from "@base-ui/react/dialog"

import { cn } from "@/lib/utils"

/**
 * Overlay motion recipe (design.md §Motion): enter = opacity + scale .98, `--duration-base`
 * 150ms `--ease-out`; exit = 100ms `--ease-in`. Scrim is the only alpha colour (`bg-overlay`).
 * `data-motion="crossfade"` keeps a ≤150ms opacity-only crossfade under
 * `prefers-reduced-motion` (globals.css global rule); the scale step then snaps.
 */
const OVERLAY_BACKDROP_CLASS =
  "fixed inset-0 z-50 bg-overlay transition-opacity duration-base ease-out data-[starting-style]:opacity-0 data-[ending-style]:opacity-0 data-[ending-style]:duration-fast data-[ending-style]:ease-in"

const OVERLAY_POPUP_MOTION_CLASS =
  "transition-[opacity,scale] duration-base ease-out data-[starting-style]:scale-98 data-[starting-style]:opacity-0 data-[ending-style]:scale-98 data-[ending-style]:opacity-0 data-[ending-style]:duration-fast data-[ending-style]:ease-in"

function Dialog({ ...props }: DialogPrimitive.Root.Props) {
  return <DialogPrimitive.Root data-slot="dialog" {...props} />
}

function DialogTrigger({ ...props }: DialogPrimitive.Trigger.Props) {
  return <DialogPrimitive.Trigger data-slot="dialog-trigger" {...props} />
}

function DialogClose({ ...props }: DialogPrimitive.Close.Props) {
  return <DialogPrimitive.Close data-slot="dialog-close" {...props} />
}

/**
 * 화면 중앙(상단 정렬) 팝업. 스크롤은 backdrop(viewport) 영역에서. panel 표면은 다른
 * elevated surface와 같은 `bg-card` + hairline + `rounded-panel`, 그림자는 `shadow-modal`만.
 */
function DialogContent({
  className,
  children,
  ...props
}: DialogPrimitive.Popup.Props) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Backdrop
        data-slot="dialog-backdrop"
        className={OVERLAY_BACKDROP_CLASS}
      />
      <DialogPrimitive.Viewport
        data-slot="dialog-viewport"
        className="fixed inset-0 z-50 flex items-start justify-center overflow-auto p-4"
      >
        <DialogPrimitive.Popup
          data-slot="dialog-content"
          data-motion="crossfade"
          className={cn(
            "w-full max-w-lg rounded-panel border border-border bg-card text-text-primary shadow-modal outline-none",
            OVERLAY_POPUP_MOTION_CLASS,
            className
          )}
          {...props}
        >
          {children}
        </DialogPrimitive.Popup>
      </DialogPrimitive.Viewport>
    </DialogPrimitive.Portal>
  )
}

function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-header"
      className={cn(
        "flex flex-wrap items-start justify-between gap-3 border-b border-border px-4 py-3",
        className
      )}
      {...props}
    />
  )
}

function DialogTitle({ className, ...props }: DialogPrimitive.Title.Props) {
  return (
    <DialogPrimitive.Title
      data-slot="dialog-title"
      className={cn("text-md font-semibold text-text-primary", className)}
      {...props}
    />
  )
}

function DialogDescription({
  className,
  ...props
}: DialogPrimitive.Description.Props) {
  return (
    <DialogPrimitive.Description
      data-slot="dialog-description"
      className={cn("text-sm text-text-secondary", className)}
      {...props}
    />
  )
}

function DialogFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="dialog-footer"
      className={cn(
        "flex flex-wrap items-center justify-end gap-2 border-t border-border px-4 py-3",
        className
      )}
      {...props}
    />
  )
}

export {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
}
