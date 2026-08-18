"use client"
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import * as React from "react"

import { AlertDialog as AlertDialogPrimitive } from "@base-ui/react/alert-dialog"

import { cn } from "@/lib/utils"

/** Same overlay recipe as `dialog.tsx` (design.md §Motion): scrim `bg-overlay`, panel opacity+scale .98. */
const ALERT_BACKDROP_CLASS =
  "fixed inset-0 z-50 bg-overlay transition-opacity duration-base ease-out data-[starting-style]:opacity-0 data-[ending-style]:opacity-0 data-[ending-style]:duration-fast data-[ending-style]:ease-in"

const ALERT_POPUP_MOTION_CLASS =
  "transition-[opacity,scale] duration-base ease-out data-[starting-style]:scale-98 data-[starting-style]:opacity-0 data-[ending-style]:scale-98 data-[ending-style]:opacity-0 data-[ending-style]:duration-fast data-[ending-style]:ease-in"

function AlertDialog({ ...props }: AlertDialogPrimitive.Root.Props) {
  return <AlertDialogPrimitive.Root data-slot="alert-dialog" {...props} />
}

function AlertDialogTrigger({ ...props }: AlertDialogPrimitive.Trigger.Props) {
  return <AlertDialogPrimitive.Trigger data-slot="alert-dialog-trigger" {...props} />
}

function AlertDialogContent({
  className,
  children,
  ...props
}: AlertDialogPrimitive.Popup.Props) {
  return (
    <AlertDialogPrimitive.Portal>
      <AlertDialogPrimitive.Backdrop
        data-slot="alert-dialog-backdrop"
        className={ALERT_BACKDROP_CLASS}
      />
      <AlertDialogPrimitive.Viewport
        data-slot="alert-dialog-viewport"
        className="fixed inset-0 z-50 flex items-center justify-center overflow-auto p-4"
      >
        <AlertDialogPrimitive.Popup
          data-slot="alert-dialog-content"
          data-motion="crossfade"
          className={cn(
            "w-full max-w-md rounded-panel border border-border bg-card p-5 text-text-primary shadow-modal outline-none",
            ALERT_POPUP_MOTION_CLASS,
            className
          )}
          {...props}
        >
          {children}
        </AlertDialogPrimitive.Popup>
      </AlertDialogPrimitive.Viewport>
    </AlertDialogPrimitive.Portal>
  )
}

function AlertDialogTitle({
  className,
  ...props
}: AlertDialogPrimitive.Title.Props) {
  return (
    <AlertDialogPrimitive.Title
      data-slot="alert-dialog-title"
      className={cn("text-md font-semibold text-text-primary", className)}
      {...props}
    />
  )
}

function AlertDialogDescription({
  className,
  ...props
}: AlertDialogPrimitive.Description.Props) {
  return (
    <AlertDialogPrimitive.Description
      data-slot="alert-dialog-description"
      className={cn("mt-2 text-sm text-text-secondary", className)}
      {...props}
    />
  )
}

function AlertDialogFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-dialog-footer"
      className={cn("mt-5 flex flex-wrap items-center justify-end gap-2", className)}
      {...props}
    />
  )
}

function AlertDialogClose({ ...props }: AlertDialogPrimitive.Close.Props) {
  return <AlertDialogPrimitive.Close data-slot="alert-dialog-close" {...props} />
}

export {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogTrigger,
}
