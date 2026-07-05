import * as React from "react";

import { cn } from "@/lib/utils";

type EmptyStateProps = {
  icon?: React.ReactNode;
  title: string;
  /** 다음 행동을 알려주는 한 문장(불필요하면 생략). */
  description?: React.ReactNode;
  /** 다음 행동 링크/버튼. */
  action?: React.ReactNode;
  className?: string;
};

/** 테이블 밖 빈 상태 표준 (§3). DataTable 내부는 emptyMessage를 유지한다. */
function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-6 py-10 text-center",
        className,
      )}
    >
      {icon ? <div className="text-muted-foreground [&_svg]:size-8">{icon}</div> : null}
      <div className="text-sm font-medium">{title}</div>
      {description ? (
        <div className="max-w-md text-sm text-muted-foreground">{description}</div>
      ) : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export { EmptyState };
export type { EmptyStateProps };
