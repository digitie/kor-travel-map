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

type PendingConfirm = {
  title: string;
  description: React.ReactNode;
  confirmLabel: string;
  cancelLabel: string;
  destructive: boolean;
  resolve: (confirmed: boolean) => void;
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
  const [pending, setPending] = React.useState<PendingConfirm | null>(null);

  const confirm = React.useCallback<ConfirmFn>((options) => {
    const confirmLabel = resolveConfirmLabel(options.confirmLabel);
    return new Promise<boolean>((resolve) => {
      setPending({
        title: options.title,
        description: options.description,
        confirmLabel,
        cancelLabel: options.cancelLabel?.trim() || "취소",
        destructive: options.destructive === true,
        resolve,
      });
    });
  }, []);

  const settle = React.useCallback(
    (confirmed: boolean) => {
      setPending((current) => {
        current?.resolve(confirmed);
        return null;
      });
    },
    [],
  );

  return (
    <ConfirmContext value={confirm}>
      {children}
      <AlertDialog
        open={pending !== null}
        onOpenChange={(open) => {
          if (!open) settle(false);
        }}
      >
        <AlertDialogContent>
          <AlertDialogTitle>{pending?.title}</AlertDialogTitle>
          {pending?.description ? (
            <AlertDialogDescription>{pending.description}</AlertDialogDescription>
          ) : null}
          <AlertDialogFooter>
            <Button
              size="sm"
              type="button"
              variant="outline"
              onClick={() => settle(false)}
            >
              {pending?.cancelLabel ?? "취소"}
            </Button>
            {/* design.md §CTA voice: the destructive FILL exists only inside confirm dialogs. */}
            <Button
              size="sm"
              type="button"
              variant={pending?.destructive ? "destructive-solid" : "default"}
              onClick={() => settle(true)}
            >
              {pending?.confirmLabel}
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
