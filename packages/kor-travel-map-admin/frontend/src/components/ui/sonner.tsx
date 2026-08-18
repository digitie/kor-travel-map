"use client"
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import type { CSSProperties } from "react"

import { Toaster as Sonner, type ToasterProps } from "sonner"
import { CircleCheckIcon, InfoIcon, TriangleAlertIcon, OctagonXIcon, Loader2Icon } from "lucide-react"

type ToastClassNames = NonNullable<NonNullable<ToasterProps["toastOptions"]>["classNames"]>

/**
 * Sonner injects its own stylesheet at runtime (unlayered `<style>` appended to <head>), so it
 * outranks Tailwind's `@layer utilities` regardless of specificity. Surface colours therefore go
 * through Sonner's CSS variables (`--normal-*`, `--border-radius`, set in `style` below), and the
 * few properties Sonner hard-codes on the toast (font, shadow, size, gap, focus halo, description
 * colour, action buttons) are overridden with `!` utilities. No `richColors`: tone is carried by
 * the icon shape + status token colour only (design.md §Status colour semantics), the surface
 * stays `bg-card` + hairline.
 */
const TOAST_CLASS_NAMES: ToastClassNames = {
  toast:
    "text-xs! gap-2! shadow-elevated! focus-visible:shadow-elevated! focus-visible:outline-2! focus-visible:outline-offset-2 focus-visible:outline-focus!",
  title: "font-medium text-text-primary",
  description: "text-text-secondary!",
  content: "min-w-0",
  icon: "shrink-0",
  success: "[&_[data-icon]]:text-success",
  info: "[&_[data-icon]]:text-info",
  warning: "[&_[data-icon]]:text-warning",
  error: "[&_[data-icon]]:text-destructive",
  loading: "[&_[data-icon]]:text-text-secondary",
  actionButton:
    "rounded-control! bg-brand! font-medium text-brand-foreground! hover:bg-brand-hover! focus-visible:shadow-none! focus-visible:outline-2! focus-visible:outline-offset-2 focus-visible:outline-focus!",
  cancelButton:
    "rounded-control! bg-surface-subtle! font-medium text-text-primary! hover:bg-surface-muted! focus-visible:shadow-none! focus-visible:outline-2! focus-visible:outline-offset-2 focus-visible:outline-focus!",
  closeButton:
    "border-border! bg-card! text-text-secondary! hover:border-border! hover:bg-surface-subtle! hover:text-text-primary! focus-visible:shadow-none! focus-visible:outline-2! focus-visible:outline-offset-2 focus-visible:outline-focus!",
}

const TOASTER_STYLE = {
  "--normal-bg": "var(--card)",
  "--normal-text": "var(--text-primary)",
  "--normal-border": "var(--border)",
  "--border-radius": "var(--radius-panel)",
} as CSSProperties

/**
 * App toaster (mounted once in `app/layout.tsx`). Toasts are for cross-page / invisible async
 * effects only — a mutation that re-renders its own region stays silent (design.md
 * §Microinteractions). Theme follows the CSS tokens (`.dark` swaps them); no theme-provider hook
 * is used because no ThemeProvider is mounted (audit M16).
 */
const Toaster = ({ toastOptions, ...props }: ToasterProps) => {
  return (
    <Sonner
      className="toaster group font-sans!"
      icons={{
        success: <CircleCheckIcon aria-hidden className="size-4" />,
        info: <InfoIcon aria-hidden className="size-4" />,
        warning: <TriangleAlertIcon aria-hidden className="size-4" />,
        error: <OctagonXIcon aria-hidden className="size-4" />,
        loading: <Loader2Icon aria-hidden className="size-4 animate-spin" />,
      }}
      style={TOASTER_STYLE}
      toastOptions={{
        ...toastOptions,
        classNames: { ...TOAST_CLASS_NAMES, ...toastOptions?.classNames },
      }}
      {...props}
    />
  )
}

export { Toaster }
