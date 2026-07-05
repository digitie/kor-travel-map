"use client";

import { Button } from "@/components/ui/button";

/**
 * 페이지네이션 표준 바 (§3).
 *
 * aria-label 규약: `ariaPrefix`를 주면 기존 dedup 화면과 동일하게
 * `"dedup 첫 페이지"`처럼 접두어가 붙고, 생략하면 enrichment처럼 접두어 없이
 * `"첫 페이지"`가 된다 — 기존 e2e 로케이터를 그대로 보존하기 위한 설계.
 * 보이는 라벨은 항상 `첫 페이지/이전/다음/마지막 페이지`.
 */

function paginationAria(ariaPrefix: string | undefined, label: string): string {
  return ariaPrefix ? `${ariaPrefix} ${label}` : label;
}

type PagerShellProps = {
  ariaPrefix?: string;
  /** nav 자체의 aria-label 접두어가 버튼 접두어와 다른 화면용(예: enrichment는 nav만 접두어). */
  navAriaPrefix?: string;
  placement?: "top" | "bottom";
  summary: React.ReactNode;
  children: React.ReactNode;
};

function PagerShell({
  ariaPrefix,
  navAriaPrefix,
  placement,
  summary,
  children,
}: PagerShellProps) {
  const navPrefix = navAriaPrefix ?? ariaPrefix;
  return (
    <nav
      aria-label={`${navPrefix ? `${navPrefix} ` : ""}pagination${placement ? ` ${placement}` : ""}`}
      className="flex flex-col gap-2 rounded-lg border bg-background px-3 py-2 sm:flex-row sm:items-center sm:justify-between"
    >
      <span className="text-sm text-muted-foreground">{summary}</span>
      <div className="flex flex-wrap gap-1">{children}</div>
    </nav>
  );
}

function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return value.toLocaleString("ko-KR");
}

type OffsetPagerProps = {
  page: number;
  totalPages: number | null;
  totalCount?: number | null;
  /** 현재 페이지에 표시 중인 행 수(요약 문구용). */
  currentCount?: number | null;
  onPageChange: (page: number) => void;
  isFetching?: boolean;
  /** API meta가 별도 제공하는 이전/다음 가능 여부(기본은 page/totalPages에서 유도). */
  hasPreviousPage?: boolean;
  hasNextPage?: boolean;
  ariaPrefix?: string;
  navAriaPrefix?: string;
  placement?: "top" | "bottom";
};

function OffsetPager({
  page,
  totalPages,
  totalCount,
  currentCount,
  onPageChange,
  isFetching = false,
  hasPreviousPage,
  hasNextPage,
  ariaPrefix,
  navAriaPrefix,
  placement,
}: OffsetPagerProps) {
  const hasPrev = hasPreviousPage ?? page > 1;
  const hasNext = hasNextPage ?? (totalPages !== null ? page < totalPages : false);
  return (
    <PagerShell
      ariaPrefix={ariaPrefix}
      navAriaPrefix={navAriaPrefix}
      placement={placement}
      summary={
        <>
          페이지 {page} / {totalPages ?? "-"}
          {totalCount !== undefined ? <> · 총 {formatCount(totalCount)}건</> : null}
          {currentCount !== undefined && currentCount !== null ? (
            <> · 현재 {formatCount(currentCount)}건</>
          ) : null}
        </>
      }
    >
      <Button
        aria-label={paginationAria(ariaPrefix, "첫 페이지")}
        disabled={!hasPrev || isFetching}
        size="sm"
        type="button"
        variant="outline"
        onClick={() => onPageChange(1)}
      >
        첫 페이지
      </Button>
      <Button
        aria-label={paginationAria(ariaPrefix, "이전 페이지")}
        disabled={!hasPrev || isFetching}
        size="sm"
        type="button"
        variant="outline"
        onClick={() => onPageChange(page - 1)}
      >
        이전
      </Button>
      <Button
        aria-label={paginationAria(ariaPrefix, "다음 페이지")}
        disabled={!hasNext || isFetching}
        size="sm"
        type="button"
        variant="outline"
        onClick={() => onPageChange(page + 1)}
      >
        다음
      </Button>
      <Button
        aria-label={paginationAria(ariaPrefix, "마지막 페이지")}
        disabled={totalPages === null || !hasNext || isFetching}
        size="sm"
        type="button"
        variant="outline"
        onClick={() => (totalPages !== null ? onPageChange(totalPages) : undefined)}
      >
        마지막 페이지
      </Button>
    </PagerShell>
  );
}

type CursorPagerProps = {
  hasNext: boolean;
  onFirst: () => void;
  onNext: () => void;
  /** 현재 위치 요약(예: `page 3 · 이 페이지 20개`). */
  summary?: React.ReactNode;
  isFetching?: boolean;
  /** 첫 페이지(cursor=null)면 '첫 페이지' 버튼을 비활성. */
  isFirst?: boolean;
  ariaPrefix?: string;
  placement?: "top" | "bottom";
};

/** keyset cursor 페이지네이션(이전으로 못 돌아가는 목록)용 — 처음/다음만 제공. */
function CursorPager({
  hasNext,
  onFirst,
  onNext,
  summary,
  isFetching = false,
  isFirst = false,
  ariaPrefix,
  placement,
}: CursorPagerProps) {
  return (
    <PagerShell ariaPrefix={ariaPrefix} placement={placement} summary={summary}>
      <Button
        aria-label={paginationAria(ariaPrefix, "첫 페이지")}
        disabled={isFirst || isFetching}
        size="sm"
        type="button"
        variant="outline"
        onClick={onFirst}
      >
        첫 페이지
      </Button>
      <Button
        aria-label={paginationAria(ariaPrefix, "다음 페이지")}
        disabled={!hasNext || isFetching}
        size="sm"
        type="button"
        variant="outline"
        onClick={onNext}
      >
        다음
      </Button>
    </PagerShell>
  );
}

export { CursorPager, OffsetPager };
export type { CursorPagerProps, OffsetPagerProps };
