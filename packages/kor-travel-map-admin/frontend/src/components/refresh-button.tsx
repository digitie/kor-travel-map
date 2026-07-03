"use client";

import { useQueryClient, type QueryKey } from "@tanstack/react-query";
import { RotateCwIcon } from "lucide-react";

import { Button } from "@/components/ui/button";

type RefreshButtonProps = {
  /** invalidate할 react-query 키 목록. */
  queries: QueryKey[];
  /** 하나라도 fetching 중일 때 눌림 방지용(호출부가 아는 상태 전달). */
  isFetching?: boolean;
  className?: string;
};

/** 목록/패널 새로고침 표준 버튼 (§3). 라벨 `새로고침`은 live 스펙이 단언하므로 고정. */
function RefreshButton({ queries, isFetching = false, className }: RefreshButtonProps) {
  const queryClient = useQueryClient();
  return (
    <Button
      className={className}
      disabled={isFetching}
      size="sm"
      type="button"
      variant="outline"
      onClick={() => {
        for (const key of queries) {
          void queryClient.invalidateQueries({ queryKey: key });
        }
      }}
    >
      <RotateCwIcon aria-hidden className="size-3.5" />
      새로고침
    </Button>
  );
}

export { RefreshButton };
export type { RefreshButtonProps };
