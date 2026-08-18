"use client";

import { CircleHelpIcon } from "lucide-react";
import { useState } from "react";

import { statusLabel } from "@/lib/status-label";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { STATUS_CONSEQUENCES } from "@/lib/curated-labels";
import { cn } from "@/lib/utils";

/**
 * 큐레이션 라이프사이클 스트립 — 처음 온 운영자가 "후보가 어디서 오고, 채택하면
 * 무슨 일이 생기는지"를 한 카드에서 읽게 한다. 칩은 상태 필터 버튼을 겸한다
 * (`onSelectStatus`가 있으면 클릭 시 해당 상태로 필터).
 *
 * compact: DETAIL 화면용 — 현재 상태와 그 결과 한 줄만 강조.
 */

export type CuratedLifecycleStatus =
  | "candidate"
  | "curated"
  | "rejected"
  | "archived";

const LIFECYCLE_STATUSES: readonly CuratedLifecycleStatus[] = [
  "candidate",
  "curated",
  "rejected",
  "archived",
];

function chipTone(status: CuratedLifecycleStatus, active: boolean): string {
  if (status === "curated") {
    return active
      ? "border-primary bg-primary text-primary-foreground"
      : "border-primary/40 bg-primary/10 text-foreground";
  }
  if (status === "candidate") {
    return active
      ? "border-foreground bg-secondary text-secondary-foreground ring-1 ring-foreground"
      : "border-border bg-secondary text-secondary-foreground";
  }
  return active
    ? "border-foreground bg-muted text-foreground ring-1 ring-foreground"
    : "border-border bg-muted text-muted-foreground";
}

export function CuratedLifecycleStrip({
  activeStatus,
  onSelectStatus,
  compact = false,
}: {
  activeStatus: string | null;
  onSelectStatus?: (status: CuratedLifecycleStatus) => void;
  compact?: boolean;
}) {
  const [helpOpen, setHelpOpen] = useState(false);
  const statuses = compact
    ? LIFECYCLE_STATUSES.filter((status) => status === activeStatus)
    : LIFECYCLE_STATUSES;

  return (
    <div
      className="rounded-lg border bg-muted/40 px-3 py-2 text-sm"
      data-testid="curated-lifecycle-strip"
    >
      {!compact ? (
        <div className="mb-2 flex items-center gap-1.5">
          <span className="font-medium">큐레이션 흐름</span>
          <Button
            aria-label="이 화면의 동작 방식"
            size="icon-sm"
            title="이 화면의 동작 방식"
            type="button"
            variant="ghost"
            onClick={() => setHelpOpen(true)}
          >
            <CircleHelpIcon />
          </Button>
        </div>
      ) : null}
      <TooltipProvider>
        <div className={cn("flex flex-wrap gap-2", compact && "gap-1")}>
          {statuses.map((status) => {
            const active = activeStatus === status;
            const chip = (
              <span
                className={cn(
                  "inline-flex h-6 items-center rounded-full border px-2.5 text-xs font-medium",
                  chipTone(status, active),
                )}
              >
                {statusLabel(status)}
              </span>
            );
            const trigger = onSelectStatus ? (
              <button
                aria-pressed={active}
                className="rounded-full outline-offset-2 focus-visible:outline-2"
                type="button"
                onClick={() => onSelectStatus(status)}
              >
                {chip}
              </button>
            ) : (
              <span className="inline-flex rounded-full">{chip}</span>
            );
            return (
              <Tooltip key={status}>
                <TooltipTrigger render={trigger} />
                <TooltipContent>{STATUS_CONSEQUENCES[status]}</TooltipContent>
              </Tooltip>
            );
          })}
        </div>
      </TooltipProvider>
      {!compact ? (
        <Dialog open={helpOpen} onOpenChange={setHelpOpen}>
          <DialogContent aria-label="큐레이션 흐름 도움말">
            <DialogHeader>
              <DialogTitle>이 화면의 동작 방식</DialogTitle>
              <Button
                size="sm"
                type="button"
                variant="ghost"
                onClick={() => setHelpOpen(false)}
              >
                닫기
              </Button>
            </DialogHeader>
            <ul className="grid list-disc gap-2 p-4 pl-8 text-sm text-muted-foreground">
              <li>큐레이션 항목은 원본 feature 위의 overlay입니다.</li>
              <li>
                채택·해제·보관은 이 화면이 아니라 컬렉션 관리(canonical)에서 합니다
                (T-VN-40A: legacy 쓰기 봉인).
              </li>
              <li>거절·보관된 항목은 규칙 재적용으로 되살아나지 않습니다.</li>
            </ul>
          </DialogContent>
        </Dialog>
      ) : null}
    </div>
  );
}
