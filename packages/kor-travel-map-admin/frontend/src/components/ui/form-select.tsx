"use client";

import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
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
  FieldShellProps & { id?: string };

function FormSelect({
  label,
  hint,
  error,
  required,
  className,
  labelClassName,
  id,
  ref,
  "aria-describedby": ariaDescribedBy,
  children,
  ...selectProps
}: FormSelectProps) {
  const { fieldId, hintId, errorId } = useFieldIds(id);
  return (
    <Field
      className={className}
      data-disabled={selectProps.disabled ? true : undefined}
      data-invalid={error ? true : undefined}
    >
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
        aria-label={requiredFieldAriaLabel(label, required)}
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
}

export { FormSelect };
export type { FormSelectProps };
