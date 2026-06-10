"use client";

import * as React from "react";

import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
} from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import {
  NativeSelect,
  type NativeSelectProps,
} from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";

/**
 * 폼 a11y wrapper (T-218a).
 *
 * 기존 admin/ops 폼은 라벨 없이 `aria-label`/placeholder만 단 bare control이라
 * label↔control 연결, 에러 메시지의 `aria-describedby`, 제출 검증 시 `aria-invalid`
 * 토글, 첫 에러 필드 포커스가 화면마다 수동/누락이었다. 본 wrapper는 기존
 * `Field`/`Input`/`NativeSelect` 위에 얇게 얹어 이 4가지를 일원화한다.
 *
 * - controlled `useState` 화면에 드롭인(기존 `value`/`onChange`를 그대로 전달).
 * - `label`은 visible `<label htmlFor>`이자 접근 이름 → Playwright `getByLabel` 호환.
 * - `error` 지정 시 control에 `aria-invalid` + `aria-describedby=<id>-error` 연결.
 * - `ref`는 control로 전달 → `validateForm`의 `firstErrorField`로 포커스 이동.
 */

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

export type FormFieldProps = Omit<
  React.ComponentProps<typeof Input>,
  "id" | "aria-invalid" | "ref"
> &
  FieldShellProps & { id?: string };

const FormField = React.forwardRef<HTMLInputElement, FormFieldProps>(
  function FormField(
    {
      label,
      hint,
      error,
      required,
      className,
      labelClassName,
      id,
      "aria-describedby": ariaDescribedBy,
      ...inputProps
    },
    ref,
  ) {
    const { fieldId, hintId, errorId } = useFieldIds(id);
    return (
      <Field className={className} data-invalid={error ? true : undefined}>
        <FieldLabel className={labelClassName} htmlFor={fieldId}>
          {label}
          {required ? <span aria-hidden="true"> *</span> : null}
        </FieldLabel>
        <Input
          aria-describedby={describedBy(
            ariaDescribedBy,
            hint ? hintId : undefined,
            error ? errorId : undefined,
          )}
          aria-invalid={error ? true : undefined}
          aria-required={required || undefined}
          id={fieldId}
          ref={ref}
          {...inputProps}
        />
        {hint ? <FieldDescription id={hintId}>{hint}</FieldDescription> : null}
        {error ? <FieldError id={errorId}>{error}</FieldError> : null}
      </Field>
    );
  },
);

export type FormSelectProps = Omit<
  NativeSelectProps,
  "id" | "aria-invalid" | "ref"
> &
  FieldShellProps & { id?: string };

const FormSelect = React.forwardRef<HTMLSelectElement, FormSelectProps>(
  function FormSelect(
    {
      label,
      hint,
      error,
      required,
      className,
      labelClassName,
      id,
      "aria-describedby": ariaDescribedBy,
      children,
      ...selectProps
    },
    ref,
  ) {
    const { fieldId, hintId, errorId } = useFieldIds(id);
    return (
      <Field className={className} data-invalid={error ? true : undefined}>
        <FieldLabel className={labelClassName} htmlFor={fieldId}>
          {label}
          {required ? <span aria-hidden="true"> *</span> : null}
        </FieldLabel>
        <NativeSelect
          aria-describedby={describedBy(
            ariaDescribedBy,
            hint ? hintId : undefined,
            error ? errorId : undefined,
          )}
          aria-invalid={error ? true : undefined}
          aria-required={required || undefined}
          className="w-full"
          id={fieldId}
          ref={ref}
          {...selectProps}
        >
          {children}
        </NativeSelect>
        {hint ? <FieldDescription id={hintId}>{hint}</FieldDescription> : null}
        {error ? <FieldError id={errorId}>{error}</FieldError> : null}
      </Field>
    );
  },
);

export type FormTextAreaProps = Omit<
  React.ComponentProps<typeof Textarea>,
  "id" | "aria-invalid" | "ref"
> &
  FieldShellProps & { id?: string };

const FormTextArea = React.forwardRef<HTMLTextAreaElement, FormTextAreaProps>(
  function FormTextArea(
    {
      label,
      hint,
      error,
      required,
      className,
      labelClassName,
      id,
      "aria-describedby": ariaDescribedBy,
      ...textareaProps
    },
    ref,
  ) {
    const { fieldId, hintId, errorId } = useFieldIds(id);
    return (
      <Field className={className} data-invalid={error ? true : undefined}>
        <FieldLabel className={labelClassName} htmlFor={fieldId}>
          {label}
          {required ? <span aria-hidden="true"> *</span> : null}
        </FieldLabel>
        <Textarea
          aria-describedby={describedBy(
            ariaDescribedBy,
            hint ? hintId : undefined,
            error ? errorId : undefined,
          )}
          aria-invalid={error ? true : undefined}
          aria-required={required || undefined}
          id={fieldId}
          ref={ref}
          {...textareaProps}
        />
        {hint ? <FieldDescription id={hintId}>{hint}</FieldDescription> : null}
        {error ? <FieldError id={errorId}>{error}</FieldError> : null}
      </Field>
    );
  },
);

export { FormField, FormSelect, FormTextArea };
