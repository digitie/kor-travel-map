"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench (detail) · design-system: design.md · designed-as-app

import { CircleHelpIcon } from "lucide-react";
import { useState } from "react";

import { statusLabel, toneFor } from "@/lib/status-label";
import { toneBadgeVariant } from "@/components/status-badge-variants";
import { Badge } from "@/components/ui/badge";
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
 * 무슨 일이 생기는지"를 한 줄에서 읽게 한다. 칩은 상태 필터 버튼을 겸한다
 * (`onSelectStatus`가 있으면 클릭 시 해당 상태로 필터). 톤은 단일 tone 테이블에서 읽는다
 * (candidate=info · curated=success · rejected=destructive · archived=neutral).
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
      className="flex flex-col gap-2 text-sm"
      data-testid="curated-lifecycle-strip"
    >
      {!compact ? (
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-medium text-text-secondary">큐레이션 흐름</span>
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
        <div className={cn("flex flex-wrap items-center gap-2", compact && "gap-1")}>
          {statuses.map((status) => {
            const active = activeStatus === status;
            const chip = (
              <Badge
                className={cn("gap-1.5", !active && "text-text-secondary")}
                variant={active ? toneBadgeVariant(toneFor(status)) : "outline"}
              >
                {active ? (
                  <span aria-hidden="true" className="size-1.5 shrink-0 rounded-full bg-current" />
                ) : null}
                {statusLabel(status)}
              </Badge>
            );
            const trigger = onSelectStatus ? (
              <button
                aria-pressed={active}
                className="rounded-control outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
                type="button"
                onClick={() => onSelectStatus(status)}
              >
                {chip}
              </button>
            ) : (
              <span className="inline-flex rounded-control">{chip}</span>
            );
            return (
              <Tooltip key={status}>
                <TooltipTrigger render={trigger} />
                <TooltipContent>{STATUS_CONSEQUENCES[status]}</TooltipContent>
              </Tooltip>
            );
          })}
          {compact && activeStatus && activeStatus in STATUS_CONSEQUENCES ? (
            <span className="text-xs text-text-secondary">
              {STATUS_CONSEQUENCES[activeStatus]}
            </span>
          ) : null}
        </div>
      </TooltipProvider>
      {!compact ? (
        <Dialog open={helpOpen} onOpenChange={setHelpOpen}>
          <DialogContent aria-label="큐레이션 흐름 도움말">
            <DialogHeader>
              <DialogTitle>이 화면의 동작 방식</DialogTitle>
            </DialogHeader>
            <ul className="grid list-disc gap-2 pl-5 text-sm text-text-secondary">
              <li>큐레이션 항목은 원본 feature 위의 overlay입니다.</li>
              <li>
                채택·해제·보관은 이 화면이 아니라 컬렉션 관리(canonical)에서 합니다
                (T-VN-40A: legacy 쓰기 봉인).
              </li>
              <li>거절·보관된 항목은 규칙 재적용으로 되살아나지 않습니다.</li>
            </ul>
            <div className="flex justify-end">
              <Button
                size="sm"
                type="button"
                variant="outline"
                onClick={() => setHelpOpen(false)}
              >
                닫기
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      ) : null}
    </div>
  );
}
