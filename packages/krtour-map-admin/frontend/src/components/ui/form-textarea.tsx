"use client";

import * as React from "react";

import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
} from "@/components/ui/field";
import { describedBy, type FieldShellProps, useFieldIds } from "@/components/ui/form-field-shared";
import { Textarea } from "@/components/ui/textarea";

type FormTextAreaProps = Omit<
  React.ComponentPropsWithRef<typeof Textarea>,
  "id" | "aria-invalid"
> &
  FieldShellProps & { id?: string };

function FormTextArea({
  label,
  hint,
  error,
  required,
  className,
  labelClassName,
  id,
  ref,
  "aria-describedby": ariaDescribedBy,
  ...textareaProps
}: FormTextAreaProps) {
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
}

export { FormTextArea };
export type { FormTextAreaProps };
