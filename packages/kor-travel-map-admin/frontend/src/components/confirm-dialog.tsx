"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import * as React from "react";

import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";

/**
 * Generic "OK" labels are rejected: a confirm names the action (`삭제`, `보관`, `취소 요청`,
 * `즉시 실행`) so the operator reads what the primary button will do (design.md §Copy: "No `확인`
 * on a confirm — name the action"). Literal labels are checked at the type level; runtime values
 * (`string`) are checked in {@link resolveConfirmLabel} (throws in development).
 */
type GenericConfirmLabel =
  | "확인"
  | "예"
  | "네"
  | "OK"
  | "Ok"
  | "ok"
  | "Okay"
  | "okay"
  | "Yes"
  | "yes"
  | "Confirm"
  | "confirm";

/** `L` unless it is a generic OK label — then `never`, so the call site fails to type-check. */
type ConfirmVerbLabel<L extends string> = L extends GenericConfirmLabel ? never : L;

interface ConfirmOptions<L extends string = string> {
  /** 질문형 제목 — 무엇을 하려는지 (`'{key}' 대상을 삭제할까요?`). alertdialog의 접근성 이름이 된다. */
  title: string;
  /** 결과 한 줄 — 무엇이 어떻게 되는지·되돌릴 수 있는지 (design.md §Microinteractions). */
  description: React.ReactNode;
  /** 행동을 이름 짓는 동사 라벨 (`삭제` · `보관` · `취소 요청`). `확인`/`OK` 계열은 타입·런타임에서 거부. */
  confirmLabel: ConfirmVerbLabel<L>;
  /** 기본 `취소`. */
  cancelLabel?: string;
  /** true면 확인 버튼이 destructive 스타일 (비가역 행동). */
  destructive?: boolean;
}

type ConfirmFn = <L extends string>(options: ConfirmOptions<L>) => Promise<boolean>;

const ConfirmContext = React.createContext<ConfirmFn | null>(null);

/** 다이얼로그가 그리는 내용. 닫힘 애니메이션 동안에도 마지막 값이 남아 있어야 한다(P2-3). */
type ConfirmView = {
  title: string;
  description: React.ReactNode;
  confirmLabel: string;
  cancelLabel: string;
  destructive: boolean;
};

const GENERIC_CONFIRM_LABELS: ReadonlySet<string> = new Set([
  "확인",
  "예",
  "네",
  "ok",
  "okay",
  "yes",
  "confirm",
]);

/**
 * Runtime twin of {@link ConfirmVerbLabel} for labels that reach us as plain `string`
 * (lookup tables, props). Development: throw so the call site is fixed. Production: fall back
 * to a neutral verb rather than rendering `확인`.
 */
function resolveConfirmLabel(label: string | undefined): string {
  const trimmed = label?.trim() ?? "";
  const isGeneric =
    trimmed.length === 0 || GENERIC_CONFIRM_LABELS.has(trimmed.toLowerCase());
  if (!isGeneric) return trimmed;
  if (process.env.NODE_ENV !== "production") {
    throw new Error(
      `useConfirm: confirmLabel은 행동을 이름 짓는 동사여야 합니다 (예: 삭제 · 보관 · 취소 요청). ` +
        `받은 값: ${JSON.stringify(label)}`,
    );
  }
  return "진행";
}

/**
 * `window.confirm` 대체 (§3). 루트에 한 번 마운트하고, 호출부는
 * `const confirm = useConfirm(); if (!(await confirm({...}))) return;`.
 *
 * 비가역·파괴적 행동에만 쓴다(가역 행동은 optimistic + Undo, design.md §Microinteractions).
 * 첫 포커스는 `취소`(안전한 기본값); Escape / backdrop은 `false`로 settle된다. 실행 중 loading은
 * dialog가 아니라 호출한 트리거(`Button loading`)가 보인다 — 여기서는 즉시 닫힌다.
 */
function ConfirmDialogProvider({ children }: { children: React.ReactNode }) {
  // 열림 여부와 내용을 분리한다: settle 은 `open` 만 내리고 `view` 는 그대로 두므로
  // 닫힘 트랜지션(180ms) 동안 제목/설명/버튼 라벨이 빈칸으로 깜빡이지 않는다(P2-3).
  const [view, setView] = React.useState<ConfirmView | null>(null);
  const [open, setOpen] = React.useState(false);
  const resolveRef = React.useRef<((confirmed: boolean) => void) | null>(null);

  const confirm = React.useCallback<ConfirmFn>((options) => {
    const confirmLabel = resolveConfirmLabel(options.confirmLabel);
    return new Promise<boolean>((resolve) => {
      // 앞선 confirm 이 아직 살아 있으면(연속 호출) 안전한 기본값으로 먼저 정리한다.
      resolveRef.current?.(false);
      resolveRef.current = resolve;
      setView({
        title: options.title,
        description: options.description,
        confirmLabel,
        cancelLabel: options.cancelLabel?.trim() || "취소",
        destructive: options.destructive === true,
      });
      setOpen(true);
    });
  }, []);

  const settle = React.useCallback((confirmed: boolean) => {
    const resolve = resolveRef.current;
    resolveRef.current = null;
    setOpen(false);
    resolve?.(confirmed);
  }, []);

  return (
    <ConfirmContext value={confirm}>
      {children}
      <AlertDialog
        open={open}
        onOpenChange={(next) => {
          if (!next) settle(false);
        }}
      >
        <AlertDialogContent>
          <AlertDialogTitle>{view?.title}</AlertDialogTitle>
          {view?.description ? (
            <AlertDialogDescription>{view.description}</AlertDialogDescription>
          ) : null}
          <AlertDialogFooter>
            <Button
              size="sm"
              type="button"
              variant="outline"
              onClick={() => settle(false)}
            >
              {view?.cancelLabel ?? "취소"}
            </Button>
            {/* design.md §CTA voice: the destructive FILL exists only inside confirm dialogs. */}
            <Button
              size="sm"
              type="button"
              variant={view?.destructive ? "destructive-solid" : "default"}
              onClick={() => settle(true)}
            >
              {view?.confirmLabel}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </ConfirmContext>
  );
}

function useConfirm(): ConfirmFn {
  const confirm = React.use(ConfirmContext);
  if (confirm === null) {
    throw new Error("useConfirm은 ConfirmDialogProvider 아래에서만 사용할 수 있습니다.");
  }
  return confirm;
}

export { ConfirmDialogProvider, useConfirm };
export type { ConfirmFn, ConfirmOptions, ConfirmVerbLabel };
