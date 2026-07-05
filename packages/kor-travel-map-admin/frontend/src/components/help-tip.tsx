"use client";

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
 * hover/focus = Tooltip(빠른 훑기), click = Popover(터치 기기 안전 + 긴 내용).
 * 본문 상세 설명을 인라인 hint 대신 여기로 옮긴다.
 */
function HelpTip({ label, children, className }: HelpTipProps) {
  const [popoverOpen, setPopoverOpen] = React.useState(false);

  const trigger = (
    <button
      aria-label={`도움말: ${label}`}
      className={cn(
        "inline-flex size-5 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
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
      <PopoverContent align="start" className="text-[13px] leading-relaxed">
        {children}
      </PopoverContent>
    </Popover>
  );
}

export { HelpTip };
export type { HelpTipProps };
