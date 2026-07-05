"use client";

import * as React from "react";

import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";

type ConfirmOptions = {
  title: string;
  description?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** true면 확인 버튼이 destructive 스타일. */
  destructive?: boolean;
};

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = React.createContext<ConfirmFn | null>(null);

type PendingConfirm = ConfirmOptions & {
  resolve: (confirmed: boolean) => void;
};

/**
 * `window.confirm` 대체 (§3). 루트에 한 번 마운트하고, 호출부는
 * `const confirm = useConfirm(); if (!(await confirm({...}))) return;`.
 */
function ConfirmDialogProvider({ children }: { children: React.ReactNode }) {
  const [pending, setPending] = React.useState<PendingConfirm | null>(null);

  const confirm = React.useCallback<ConfirmFn>((options) => {
    return new Promise<boolean>((resolve) => {
      setPending({ ...options, resolve });
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
    <ConfirmContext.Provider value={confirm}>
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
            <Button
              size="sm"
              type="button"
              variant={pending?.destructive ? "destructive" : "default"}
              onClick={() => settle(true)}
            >
              {pending?.confirmLabel ?? "확인"}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </ConfirmContext.Provider>
  );
}

function useConfirm(): ConfirmFn {
  const confirm = React.useContext(ConfirmContext);
  if (confirm === null) {
    throw new Error("useConfirm은 ConfirmDialogProvider 아래에서만 사용할 수 있습니다.");
  }
  return confirm;
}

export { ConfirmDialogProvider, useConfirm };
export type { ConfirmFn, ConfirmOptions };
