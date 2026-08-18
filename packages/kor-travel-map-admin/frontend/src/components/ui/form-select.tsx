"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

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
import {
  NativeSelect,
  type NativeSelectProps,
} from "@/components/ui/native-select";

type FormSelectProps = Omit<NativeSelectProps, "id" | "aria-invalid"> &
  FieldShellProps & {
    id?: string;
    /** hint/error 메시지 슬롯(1줄) 항상 예약(기본 true, M13). 인라인 툴바만 false. */
    reserveMessage?: boolean;
  };

/** 라벨 위 · NativeSelect · 메시지 슬롯 1개(error가 hint를 대체) — FormField와 같은 리듬. */
function FormSelect({
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
  children,
  ...selectProps
}: FormSelectProps) {
  const { fieldId, hintId, errorId } = useFieldIds(id);
  const showHint = !error && Boolean(hint);
  const showMessage = reserveMessage || Boolean(error) || showHint;
  return (
    <Field
      className={className}
      data-disabled={selectProps.disabled ? true : undefined}
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
      <NativeSelect
        aria-describedby={describedBy(
          ariaDescribedBy,
          showHint ? hintId : undefined,
          error ? errorId : undefined,
        )}
        aria-invalid={error ? true : undefined}
        aria-label={requiredFieldAriaLabel(label, required, help)}
        aria-required={required || undefined}
        className="w-full"
        id={fieldId}
        ref={ref}
        {...selectProps}
      >
        {children}
      </NativeSelect>
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

export { FormSelect };
export type { FormSelectProps };
