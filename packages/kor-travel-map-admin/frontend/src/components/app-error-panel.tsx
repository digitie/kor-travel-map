"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench(error page) · design-system: design.md · designed-as-app

import { ArrowLeftIcon, RefreshCwIcon } from "lucide-react";
import { useEffect, useMemo } from "react";

import { Button } from "@/components/ui/button";
import {
  errorRecoveryMessage,
  errorReloadStorageKey,
  isLikelyRecoverableNextRuntimeError,
} from "@/lib/error-recovery";
import { cn } from "@/lib/utils";

type AppErrorPanelProps = {
  error: Error & { digest?: string };
  reset?: () => void;
  standalone?: boolean;
};

function goBack() {
  if (typeof window === "undefined") {
    return;
  }
  if (window.history.length > 1) {
    window.history.back();
    return;
  }
  window.location.assign("/");
}

/**
 * 런타임 오류 패널 — 3부(무엇이 · 왜 · 무엇을 할까 — M18) 구조는 그대로, chrome 만 재설계:
 * 그림자 카드 대신 단일 가운데 열 + hairline (design.md §Depth, M8). 상세 정보는 hairline
 * 아래 접힘 영역의 mono 블록 하나(containment 1층).
 */
export function AppErrorPanel({ error, reset, standalone = false }: AppErrorPanelProps) {
  const recoverable = useMemo(() => isLikelyRecoverableNextRuntimeError(error), [error]);
  const details = useMemo(() => errorRecoveryMessage(error), [error]);

  useEffect(() => {
    if (!recoverable || typeof window === "undefined") {
      return;
    }

    // chunk/RSC/network 계열은 같은 pathname에서 1회만 hard reload(무한 reload 방지).
    const key = errorReloadStorageKey(window.location.pathname);
    if (window.sessionStorage.getItem(key) === "1") {
      return;
    }

    window.sessionStorage.setItem(key, "1");
    window.location.reload();
  }, [recoverable]);

  const retry = () => {
    if (typeof window !== "undefined") {
      window.sessionStorage.removeItem(errorReloadStorageKey(window.location.pathname));
    }
    if (reset) {
      reset();
      return;
    }
    if (typeof window !== "undefined") {
      window.location.reload();
    }
  };

  return (
    <section
      className={cn(
        "flex items-center justify-center bg-surface-page px-6 py-10 text-text-primary",
        standalone ? "min-h-dvh" : "min-h-[min(640px,calc(100dvh-80px))]",
      )}
      role="alert"
    >
      <div className="flex w-full max-w-2xl flex-col gap-4">
        {/* 분류 라벨 12px/500 — uppercase/tracking 없음(m3). */}
        <p className="text-2xs font-medium text-text-secondary">UI 런타임 오류</p>
        <h1 className="text-xl leading-tight font-bold tracking-tight text-text-primary">
          페이지를 다시 불러오지 못했습니다
        </h1>
        <p className="max-w-prose text-sm text-text-secondary">
          {recoverable
            ? "현재 탭의 화면 런타임 상태가 서버와 맞지 않아 새로고침이 필요합니다."
            : "현재 탭의 UI 상태가 서버와 맞지 않거나, 화면 렌더링 중 오류가 발생했습니다."}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button onClick={retry} type="button">
            <RefreshCwIcon aria-hidden="true" data-icon="inline-start" />
            다시 시도
          </Button>
          <Button onClick={goBack} type="button" variant="outline">
            <ArrowLeftIcon aria-hidden="true" data-icon="inline-start" />
            이전 화면
          </Button>
        </div>
        <details className="group/details mt-2 border-t border-border pt-3">
          <summary className="inline-flex h-control-sm cursor-pointer list-none items-center rounded-control px-1 text-xs font-medium text-text-secondary transition-[color,background-color] duration-fast ease-out outline-none hover:bg-surface-subtle hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus active:bg-surface-muted [&::-webkit-details-marker]:hidden">
            <span className="group-open/details:hidden">오류 정보 보기</span>
            <span className="hidden group-open/details:inline">오류 정보 닫기</span>
          </summary>
          <pre className="mt-2 max-h-48 overflow-auto rounded-control border border-border bg-surface-subtle p-3 font-mono text-2xs leading-normal break-words whitespace-pre-wrap text-text-primary">
            {details || "—"}
          </pre>
        </details>
      </div>
    </section>
  );
}
