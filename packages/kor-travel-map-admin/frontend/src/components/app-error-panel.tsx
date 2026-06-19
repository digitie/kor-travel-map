"use client";

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
        "flex items-center justify-center bg-surface-page p-6",
        standalone ? "min-h-[100dvh]" : "min-h-[min(640px,calc(100dvh-80px))]",
      )}
      role="alert"
    >
      <div className="flex w-full max-w-[680px] flex-col gap-4 rounded-2xl bg-card p-6 shadow-[var(--shadow-card)] ring-1 ring-border/70">
        <p className="text-[12px] font-bold tracking-[0.04em] text-text-secondary uppercase">
          UI runtime error
        </p>
        <h1 className="text-[24px] leading-snug font-bold text-text-primary">
          페이지를 다시 불러오지 못했습니다
        </h1>
        <p className="text-[14px] leading-relaxed text-text-secondary">
          {recoverable
            ? "현재 탭의 화면 런타임 상태가 서버와 맞지 않아 새로고침이 필요합니다."
            : "현재 탭의 UI 상태가 서버와 맞지 않거나, 화면 렌더링 중 오류가 발생했습니다."}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button onClick={retry} type="button">
            <RefreshCwIcon data-icon="inline-start" />
            다시 시도
          </Button>
          <Button onClick={goBack} type="button" variant="outline">
            <ArrowLeftIcon data-icon="inline-start" />
            이전 화면
          </Button>
        </div>
        <details className="border-t border-border pt-3">
          <summary className="cursor-pointer text-[13px] text-text-secondary">
            오류 정보
          </summary>
          <pre className="mt-2.5 max-h-[180px] overflow-auto rounded-md border border-border bg-surface-subtle p-2.5 text-[12px] leading-normal whitespace-pre-wrap text-text-primary">
            {details || "no details"}
          </pre>
        </details>
      </div>
    </section>
  );
}
