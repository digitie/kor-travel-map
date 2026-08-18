// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Textarea recipe = Input recipe + `resize-y` + `min-h-24` (interaction-and-states §Specific
 * control overrides). border 1px 고정, focus는 불투명 outline(즉시), disabled는 3채널.
 */
function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "min-h-24 w-full min-w-0 resize-y rounded-control border border-input bg-card px-3 py-1.5 text-sm text-text-primary transition-[color,background-color,border-color] duration-fast ease-out",
        "placeholder:text-text-tertiary hover:bg-surface-subtle focus-visible:border-text-secondary focus-visible:bg-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        "disabled:cursor-not-allowed disabled:bg-surface-subtle disabled:opacity-55 read-only:cursor-default read-only:bg-surface-subtle read-only:text-text-secondary",
        "aria-invalid:border-destructive",
        className,
      )}
      {...props}
    />
  );
}

export { Textarea };
