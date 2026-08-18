"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import * as React from "react";
import { CheckIcon, CopyIcon } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";

type CopyButtonProps = {
  value: string;
  /** 접근성 이름·안내 문구에 쓰는 값 이름(예: "feature ID"). */
  label?: string;
  className?: string;
};

/** Copied glyph dwell before reverting to the copy icon (design.md: silent success, icon swap). */
const COPIED_RESET_MS = 1200;

/**
 * 클립보드 복사 버튼 (§3). settings-client의 secure-context fallback 규약을 따른다:
 * 비보안 컨텍스트/미지원 브라우저에서는 실패 대신 직접 선택 안내를 띄운다.
 *
 * Success is silent (audit M15): the icon swaps to a check for {@link COPIED_RESET_MS} and a
 * visually-hidden `aria-live` region announces `복사됨`; toasts remain for the failure /
 * unsupported branches only. Hit target: 24px box + `before:` extension to 40px (audit M23).
 */
function CopyButton({ value, label = "값", className }: CopyButtonProps) {
  const [copied, setCopied] = React.useState(false);
  const resetTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(() => {
    return () => {
      if (resetTimer.current !== null) clearTimeout(resetTimer.current);
    };
  }, []);

  const copy = async () => {
    if (!window.isSecureContext || !navigator.clipboard?.writeText) {
      toast.info("자동 복사를 사용할 수 없습니다. 값을 직접 선택해 복사하세요.");
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      toast.error("클립보드 복사에 실패했습니다. 값을 직접 선택해 복사하세요.");
      return;
    }
    setCopied(true);
    if (resetTimer.current !== null) clearTimeout(resetTimer.current);
    resetTimer.current = setTimeout(() => {
      resetTimer.current = null;
      setCopied(false);
    }, COPIED_RESET_MS);
  };

  return (
    <button
      aria-label={`${label} 복사`}
      className={cn(
        "relative inline-flex size-6 shrink-0 items-center justify-center rounded-control text-text-secondary transition-[color,background-color] duration-fast ease-out",
        "before:absolute before:-inset-2",
        "hover:bg-surface-subtle hover:text-text-primary active:bg-surface-muted",
        "outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        "disabled:pointer-events-none disabled:text-text-disabled",
        "data-[state=copied]:text-success",
        className,
      )}
      data-state={copied ? "copied" : undefined}
      title={`${label} 복사`}
      type="button"
      onClick={() => void copy()}
    >
      {copied ? (
        <CheckIcon aria-hidden className="size-3.5" />
      ) : (
        <CopyIcon aria-hidden className="size-3.5" />
      )}
      <span aria-live="polite" className="sr-only">
        {copied ? "복사됨" : ""}
      </span>
    </button>
  );
}

export { CopyButton };
export type { CopyButtonProps };
