"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import { Button } from "@/components/ui/button";
import { NULL_GLYPH, formatCount } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * 페이지네이션 표준 바(design.md §Copy — 빈 값 `—`, 구분자 `·`). 손으로 만든 pager 대신
 * OffsetPager/CursorPager만 쓴다(M33). 기본은 flat(테이블 아래 한 행) — Card/SectionCard 안에서
 * 다시 테두리를 두르지 않는다(C3). `framed`는 컨테이너가 없는 곳에서만 켠다.
 *
 * aria-label 규약: `ariaPrefix`를 주면 기존 dedup 화면과 동일하게
 * `"dedup 첫 페이지"`처럼 접두어가 붙고, 생략하면 enrichment처럼 접두어 없이
 * `"첫 페이지"`가 된다 — 기존 e2e 로케이터를 그대로 보존하기 위한 설계.
 * 보이는 라벨은 항상 `첫 페이지/이전/다음/마지막 페이지`.
 */

function paginationAria(ariaPrefix: string | undefined, label: string): string {
  return ariaPrefix ? `${ariaPrefix} ${label}` : label;
}

type PagerButtonProps = {
  ariaLabel: string;
  children: React.ReactNode;
  /** 페이지 경계 등 구조적으로 없는 이동 — native `disabled`(탭 순서에서 빠지는 게 맞다). */
  unavailable: boolean;
  /** 전환이 진행 중 — `aria-disabled`만 건다. */
  busy: boolean;
  onActivate: () => void;
};

/**
 * P1-5: 전환 중(`isFetching`)에 native `disabled`를 걸면 방금 누른 버튼이 탭 순서에서 사라져
 * 포커스가 body로 떨어지고, 응답이 오면 돌아갈 자리가 없다. busy는 `aria-disabled` + 클릭
 * early-return 으로만 막는다(포커스 유지). 경계(첫/마지막 페이지)는 원래대로 native disabled.
 */
function PagerButton({
  ariaLabel,
  busy,
  children,
  unavailable,
  onActivate,
}: PagerButtonProps) {
  return (
    <Button
      aria-disabled={busy || undefined}
      aria-label={ariaLabel}
      disabled={unavailable}
      size="sm"
      type="button"
      variant="outline"
      onClick={() => {
        if (busy || unavailable) return;
        onActivate();
      }}
    >
      {children}
    </Button>
  );
}

type PagerShellProps = {
  ariaPrefix?: string;
  /** nav 자체의 aria-label 접두어가 버튼 접두어와 다른 화면용(예: enrichment는 nav만 접두어). */
  navAriaPrefix?: string;
  placement?: "top" | "bottom";
  summary?: React.ReactNode;
  /** hairline 프레임(컨테이너 없는 영역 전용). 기본 false = flat 행. */
  framed?: boolean;
  /** 페이지 전환 중 — nav에 aria-busy를 건다. */
  isFetching?: boolean;
  className?: string;
  children: React.ReactNode;
};

function PagerShell({
  ariaPrefix,
  navAriaPrefix,
  placement,
  summary,
  framed = false,
  isFetching = false,
  className,
  children,
}: PagerShellProps) {
  const navPrefix = navAriaPrefix ?? ariaPrefix;
  return (
    <nav
      aria-busy={isFetching || undefined}
      aria-label={`${navPrefix ? `${navPrefix} ` : ""}pagination${placement ? ` ${placement}` : ""}`}
      className={cn(
        "flex flex-col gap-2 py-1 sm:flex-row sm:items-center sm:justify-between",
        framed && "rounded-panel border border-border bg-card px-3 py-2",
        className,
      )}
      data-slot="pager"
    >
      {summary ? (
        <span className="text-xs text-text-secondary tabular-nums">{summary}</span>
      ) : null}
      <div className="flex flex-wrap items-center gap-1">{children}</div>
    </nav>
  );
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
  framed?: boolean;
  className?: string;
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
  framed,
  className,
}: OffsetPagerProps) {
  const hasPrev = hasPreviousPage ?? page > 1;
  const hasNext = hasNextPage ?? (totalPages !== null ? page < totalPages : false);
  return (
    <PagerShell
      ariaPrefix={ariaPrefix}
      className={className}
      framed={framed}
      isFetching={isFetching}
      navAriaPrefix={navAriaPrefix}
      placement={placement}
      summary={
        <>
          페이지 {page} / {totalPages ?? NULL_GLYPH}
          {totalCount !== undefined ? <> · 총 {formatCount(totalCount)}건</> : null}
          {currentCount !== undefined && currentCount !== null ? (
            <> · 현재 {formatCount(currentCount)}건</>
          ) : null}
        </>
      }
    >
      <PagerButton
        ariaLabel={paginationAria(ariaPrefix, "첫 페이지")}
        busy={isFetching}
        unavailable={!hasPrev}
        onActivate={() => onPageChange(1)}
      >
        첫 페이지
      </PagerButton>
      <PagerButton
        ariaLabel={paginationAria(ariaPrefix, "이전 페이지")}
        busy={isFetching}
        unavailable={!hasPrev}
        onActivate={() => onPageChange(page - 1)}
      >
        이전
      </PagerButton>
      <PagerButton
        ariaLabel={paginationAria(ariaPrefix, "다음 페이지")}
        busy={isFetching}
        unavailable={!hasNext}
        onActivate={() => onPageChange(page + 1)}
      >
        다음
      </PagerButton>
      <PagerButton
        ariaLabel={paginationAria(ariaPrefix, "마지막 페이지")}
        busy={isFetching}
        unavailable={totalPages === null || !hasNext}
        onActivate={() => {
          if (totalPages !== null) onPageChange(totalPages);
        }}
      >
        마지막 페이지
      </PagerButton>
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
  framed?: boolean;
  className?: string;
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
  framed,
  className,
}: CursorPagerProps) {
  return (
    <PagerShell
      ariaPrefix={ariaPrefix}
      className={className}
      framed={framed}
      isFetching={isFetching}
      placement={placement}
      summary={summary}
    >
      <PagerButton
        ariaLabel={paginationAria(ariaPrefix, "첫 페이지")}
        busy={isFetching}
        unavailable={isFirst}
        onActivate={onFirst}
      >
        첫 페이지
      </PagerButton>
      <PagerButton
        ariaLabel={paginationAria(ariaPrefix, "다음 페이지")}
        busy={isFetching}
        unavailable={!hasNext}
        onActivate={onNext}
      >
        다음
      </PagerButton>
    </PagerShell>
  );
}

export { CursorPager, OffsetPager };
export type { CursorPagerProps, OffsetPagerProps };
