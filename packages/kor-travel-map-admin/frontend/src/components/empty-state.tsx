// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
import * as React from "react";

import { cn } from "@/lib/utils";

type EmptyStateProps = {
  /** 선택 — 제목 앞 16px 인라인 글리프(아이콘 타일 아님). */
  icon?: React.ReactNode;
  /** 무엇이 비었나 — 한 문장(`열린 이슈가 없습니다`). */
  title: string;
  /** 왜 / 다음 행동 안내 — 한 문장(`필터를 전체로 바꿔 보세요`). */
  description?: React.ReactNode;
  /** 다음 행동 하나(버튼/링크). */
  action?: React.ReactNode;
  /** 컨테이너가 없는 영역(빈 inspector rail 등)에서만 hairline 프레임을 켠다 — Card 안에서는 끈다(card-in-card 금지). */
  framed?: boolean;
  /** 밀도 — 테이블 안(sm)에서는 세로 여백을 줄인다. */
  size?: "default" | "sm";
  className?: string;
};

/**
 * 빈 상태 표준(design.md §Copy): 좌측 정렬, 한 문장 + 행동 하나. dashed border·가운데 정렬·
 * 아이콘-위-제목 타일을 쓰지 않는다(M17). DataTable은 `emptyState` prop으로 같은 컴포넌트를
 * table frame 안에 렌더한다.
 */
function EmptyState({
  icon,
  title,
  description,
  action,
  framed = false,
  size = "default",
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-start gap-1 text-left",
        size === "default" ? "py-6" : "py-4",
        framed && "rounded-panel border border-border px-4",
        className,
      )}
      data-slot="empty-state"
    >
      <div className="flex items-center gap-2 text-sm font-medium text-text-primary">
        {icon ? (
          <span aria-hidden="true" className="shrink-0 text-text-tertiary [&_svg]:size-4">
            {icon}
          </span>
        ) : null}
        <span>{title}</span>
      </div>
      {description ? (
        <p className="max-w-prose text-xs text-text-secondary">{description}</p>
      ) : null}
      {action ? <div className="mt-2 flex flex-wrap items-center gap-2">{action}</div> : null}
    </div>
  );
}

export { EmptyState };
export type { EmptyStateProps };
