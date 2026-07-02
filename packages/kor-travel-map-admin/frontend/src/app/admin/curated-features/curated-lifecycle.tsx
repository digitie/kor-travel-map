"use client";

import { statusLabel } from "@/components/status-badge";
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

/** 상태에서 나가는 전환 동사 — 칩 옆에 작은 라벨로 노출. */
const TRANSITION_VERBS: Partial<Record<CuratedLifecycleStatus, string>> = {
  candidate: "채택 →",
  curated: "채택 해제 →",
};

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
  const statuses = compact
    ? LIFECYCLE_STATUSES.filter((status) => status === activeStatus)
    : LIFECYCLE_STATUSES;

  return (
    <div
      className="rounded-lg border bg-muted/40 p-3 text-sm"
      data-testid="curated-lifecycle-strip"
    >
      {!compact ? (
        <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="font-medium">큐레이션 흐름</span>
          <span className="text-xs text-muted-foreground">
            후보는 &lsquo;소스 규칙&rsquo; 적용 또는 새로고침 job으로
            만들어집니다 · 수동 등록은 아직 API 전용입니다
          </span>
        </div>
      ) : null}
      <div
        className={cn(
          "grid gap-3",
          compact ? "grid-cols-1" : "sm:grid-cols-2 xl:grid-cols-4",
        )}
      >
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
          return (
            <div className="flex flex-col gap-1" key={status}>
              <div className="flex items-center gap-2">
                {onSelectStatus ? (
                  <button
                    aria-pressed={active}
                    className="rounded-full outline-offset-2 focus-visible:outline-2"
                    type="button"
                    onClick={() => onSelectStatus(status)}
                  >
                    {chip}
                  </button>
                ) : (
                  chip
                )}
                {!compact && TRANSITION_VERBS[status] ? (
                  <span className="text-xs text-muted-foreground">
                    {TRANSITION_VERBS[status]}
                  </span>
                ) : null}
              </div>
              <span className="text-xs leading-relaxed text-muted-foreground">
                {STATUS_CONSEQUENCES[status]}
              </span>
            </div>
          );
        })}
      </div>
      {!compact ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
            이 화면의 동작 방식
          </summary>
          <ul className="mt-2 grid list-disc gap-1 pl-5 text-xs text-muted-foreground">
            <li>
              큐레이션 항목은 원본 feature 위의 overlay입니다 — 원본은 수정되지
              않습니다.
            </li>
            <li>
              &lsquo;채택&rsquo;하면 공개 API 기본 목록에 노출되고 배포 스냅샷이
              생성됩니다.
            </li>
            <li>
              거절·보관된 항목은 규칙 재적용·재적재로 되살아나지 않습니다.
            </li>
          </ul>
        </details>
      ) : null}
    </div>
  );
}
