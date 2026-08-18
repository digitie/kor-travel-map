"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import * as React from "react";

import { HelpTip } from "@/components/help-tip";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
  FieldMessage,
} from "@/components/ui/field";
import {
  describedBy,
  type FieldShellProps,
  requiredFieldAriaLabel,
  useFieldIds,
} from "@/components/ui/form-field-shared";
import { Input } from "@/components/ui/input";

type FormFieldProps = Omit<
  React.ComponentPropsWithRef<typeof Input>,
  "id" | "aria-invalid"
> &
  FieldShellProps & {
    id?: string;
    /**
     * hint/error 메시지 슬롯(1줄)을 항상 예약한다(기본 true — 오류가 나타나도 폼이 밀리지 않음,
     * M13). 인라인 툴바처럼 슬롯이 불필요한 곳만 false.
     */
    reserveMessage?: boolean;
  };

/**
 * 라벨 위 · 컨트롤 · 메시지 슬롯 1개(error가 hint를 대체) — 폼 컨트롤 표준(M43).
 * `aria-describedby`는 지금 표시 중인 메시지만 가리킨다.
 */
function FormField({
  label,
  hint,
  help,
  error,
  required,
  className,
  labelClassName,
  reserveMessage = true,
  id,
  ref,
  "aria-describedby": ariaDescribedBy,
  ...inputProps
}: FormFieldProps) {
  const { fieldId, hintId, errorId } = useFieldIds(id);
  const unavailable = inputProps.disabled || inputProps.readOnly;
  const showHint = !error && Boolean(hint);
  const showMessage = reserveMessage || Boolean(error) || showHint;
  return (
    <Field
      className={className}
      data-disabled={unavailable ? true : undefined}
      data-invalid={error ? true : undefined}
    >
      <FieldLabel className={labelClassName} htmlFor={fieldId}>
        {label}
        {required ? <span aria-hidden="true"> *</span> : null}
        {help !== undefined ? (
          <HelpTip label={typeof label === "string" ? label : "이 필드"}>
            {help}
          </HelpTip>
        ) : null}
      </FieldLabel>
      <Input
        aria-describedby={describedBy(
          ariaDescribedBy,
          showHint ? hintId : undefined,
          error ? errorId : undefined,
        )}
        aria-invalid={error ? true : undefined}
        aria-label={requiredFieldAriaLabel(label, required, help)}
        aria-required={required || undefined}
        id={fieldId}
        ref={ref}
        {...inputProps}
      />
      {showMessage ? (
        <FieldMessage>
          {error ? (
            <FieldError id={errorId}>{error}</FieldError>
          ) : showHint ? (
            <FieldDescription id={hintId}>{hint}</FieldDescription>
          ) : null}
        </FieldMessage>
      ) : null}
    </Field>
  );
}

export { FormField };
export type { FormFieldProps };
