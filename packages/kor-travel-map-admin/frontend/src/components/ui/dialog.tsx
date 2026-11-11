"use client";

export {
  Dialog,
  DialogClose,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@kor-travel/ui/dialog";

import type { ComponentProps } from "react";
import { DialogContent as CommonDialogContent } from "@kor-travel/ui/dialog";
import { cn } from "@/lib/utils";

/** 긴 비교 화면은 뷰포트 안에서 스크롤하고 앱의 명시적 닫기 동작을 유지한다. */
export function DialogContent({
  className,
  showCloseButton = false,
  ...props
}: ComponentProps<typeof CommonDialogContent>) {
  return (
    <CommonDialogContent
      showCloseButton={showCloseButton}
      className={cn(
        "max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg",
        className,
      )}
      {...props}
    />
  );
}
