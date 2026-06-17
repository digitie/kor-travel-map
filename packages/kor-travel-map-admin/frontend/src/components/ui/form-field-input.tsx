"use client";

import * as React from "react";

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
import { Input } from "@/components/ui/input";

type FormFieldProps = Omit<
  React.ComponentPropsWithRef<typeof Input>,
  "id" | "aria-invalid"
> &
  FieldShellProps & { id?: string };

function FormField({
  label,
  hint,
  error,
  required,
  className,
  labelClassName,
  id,
  ref,
  "aria-describedby": ariaDescribedBy,
  ...inputProps
}: FormFieldProps) {
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
        aria-label={requiredFieldAriaLabel(label, required)}
        aria-required={required || undefined}
        id={fieldId}
        ref={ref}
        {...inputProps}
      />
      {hint ? <FieldDescription id={hintId}>{hint}</FieldDescription> : null}
      {error ? <FieldError id={errorId}>{error}</FieldError> : null}
    </Field>
  );
}

export { FormField };
export type { FormFieldProps };
