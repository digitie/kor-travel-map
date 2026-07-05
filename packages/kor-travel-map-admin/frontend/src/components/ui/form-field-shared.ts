import * as React from "react";

type FieldShellProps = {
  label: React.ReactNode;
  /** 보조 설명(에러와 별개, 항상 표시). */
  hint?: React.ReactNode;
  /**
   * 라벨 옆 도움말 팝오버 내용 (§5-6 텍스트 절약 — 상세 설명은 inline hint 대신
   * 도움말 아이콘 버튼으로). 지정하면 라벨 끝에 HelpTip이 붙는다.
   */
  help?: React.ReactNode;
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

/**
 * required 필드 라벨은 장식용 별표(`<span aria-hidden> *</span>`)를 덧붙인다.
 * 그런데 Chromium의 accessible-name 계산은 `<label>` 텍스트를 모을 때 aria-hidden
 * 별표까지 **포함**시켜 컨트롤의 접근성 이름이 `"name *"`가 된다(스크린리더가 'star'를
 * 낭독, Playwright `getByLabel(name, { exact:true })`도 미스). 라벨이 문자열이면 컨트롤에
 * 명시 `aria-label`을 부여해 접근성 이름을 별표 없는 깔끔한 라벨로 고정한다. 라벨이
 * ReactNode면 override가 불가하므로 undefined(기존 동작 유지). 호출부에서 spread보다
 * 먼저 적용해 caller의 명시 aria-label이 우선하도록 둔다.
 */
function requiredFieldAriaLabel(
  label: React.ReactNode,
  required: boolean | undefined,
  help?: React.ReactNode,
): string | undefined {
  // help 버튼(aria-label="도움말: …")도 라벨의 accessible name에 섞이므로(별표와
  // 동일한 Chromium 계산 문제) help가 있을 때도 명시 aria-label로 고정한다.
  return (required || help !== undefined) && typeof label === "string"
    ? label
    : undefined;
}

export { describedBy, requiredFieldAriaLabel, useFieldIds };
export type { FieldShellProps };
