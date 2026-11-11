"use client";
import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";
export {
  Field, FieldLabel, FieldDescription, FieldError, FieldGroup, FieldLegend,
  FieldSeparator, FieldSet, FieldContent, FieldTitle,
} from "@kor-travel/ui/field";

/** 오류와 안내가 교대하는 한 줄 공간은 Map 폼의 배치 계약이다. */
export function FieldMessage({ className, ...props }: ComponentProps<"div">) {
  return <div data-slot="field-message" className={cn("min-h-[1lh]", className)} {...props} />;
}
