"use client";

import { CopyIcon } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";

type CopyButtonProps = {
  value: string;
  /** 접근성 이름·토스트 문구에 쓰는 값 이름(예: "feature ID"). */
  label?: string;
  className?: string;
};

/**
 * 클립보드 복사 버튼 (§3). settings-client의 secure-context fallback 규약을 따른다:
 * 비보안 컨텍스트/미지원 브라우저에서는 실패 대신 직접 선택 안내를 띄운다.
 */
function CopyButton({ value, label = "값", className }: CopyButtonProps) {
  const copy = async () => {
    if (!window.isSecureContext || !navigator.clipboard?.writeText) {
      toast.info("자동 복사를 사용할 수 없습니다. 값을 직접 선택해 복사하세요.");
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
      toast.success(`${label}을(를) 클립보드에 복사했습니다.`);
    } catch {
      toast.error("클립보드 복사에 실패했습니다. 값을 직접 선택해 복사하세요.");
    }
  };
  return (
    <button
      aria-label={`${label} 복사`}
      className={cn(
        "inline-flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none",
        className,
      )}
      title={`${label} 복사`}
      type="button"
      onClick={() => void copy()}
    >
      <CopyIcon aria-hidden className="size-3.5" />
    </button>
  );
}

export { CopyButton };
export type { CopyButtonProps };
