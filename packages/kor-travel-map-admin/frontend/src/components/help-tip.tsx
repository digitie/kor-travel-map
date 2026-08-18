"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import * as React from "react";
import { CircleHelpIcon } from "lucide-react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

type HelpTipProps = {
  /** 도움말 대상 필드/항목 이름 — 접근성 이름 `도움말: {label}`을 만든다. */
  label: string;
  children: React.ReactNode;
  className?: string;
};

/**
 * 필드 옆 도움말 아이콘 버튼 (§3/§5-6).
 * hover(800ms) / focus(0ms) = Tooltip(빠른 훑기), click = Popover(터치 기기 안전 + 긴 내용).
 * 본문 상세 설명을 인라인 hint 대신 여기로 옮긴다.
 *
 * Hit target: 24px visible box + `before:` pseudo-element extending the pointer target to 40px
 * (design.md §Microinteractions ≥ 24px) without changing the 14px glyph or inline layout.
 * States: rest ink-2 · hover/open ink on paper-2 · active paper-3 · focus = one outline recipe.
 */
function HelpTip({ label, children, className }: HelpTipProps) {
  const [popoverOpen, setPopoverOpen] = React.useState(false);

  const trigger = (
    <button
      aria-label={`도움말: ${label}`}
      className={cn(
        "relative inline-flex size-6 shrink-0 items-center justify-center rounded-control text-text-secondary transition-[color,background-color] duration-fast ease-out",
        "before:absolute before:-inset-2",
        "hover:bg-surface-subtle hover:text-text-primary active:bg-surface-muted aria-expanded:bg-surface-subtle aria-expanded:text-text-primary",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        "disabled:pointer-events-none disabled:text-text-disabled",
        className,
      )}
      type="button"
    >
      <CircleHelpIcon aria-hidden className="size-3.5" />
    </button>
  );

  return (
    <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger
            render={<PopoverTrigger render={trigger} />}
          />
          {popoverOpen ? null : <TooltipContent>{children}</TooltipContent>}
        </Tooltip>
      </TooltipProvider>
      <PopoverContent align="start" className="leading-relaxed">
        {children}
      </PopoverContent>
    </Popover>
  );
}

export { HelpTip };
export type { HelpTipProps };
