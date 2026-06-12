import * as React from "react";

type FieldShellProps = {
  label: React.ReactNode;
  /** 보조 설명(에러와 별개, 항상 표시). */
  hint?: React.ReactNode;
  /** 검증 에러 메시지. 있으면 aria-invalid + role=alert 연결. */
  error?: string | null;
  required?: boolean;
  className?: string;
  labelClassName?: string;
};

function useFieldIds(explicitId: string | undefined) {
  const reactId = React.useId();
  const fieldId = explicitId ?? reactId;
  return {
    fieldId,
    hintId: `${fieldId}-hint`,
    errorId: `${fieldId}-error`,
  };
}

function describedBy(
  base: string | undefined,
  hintId: string | undefined,
  errorId: string | undefined,
): string | undefined {
  return [base, hintId, errorId].filter(Boolean).join(" ") || undefined;
}

export { describedBy, useFieldIds };
export type { FieldShellProps };
