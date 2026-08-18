"use client"
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"
import { fieldLabelClassName } from "@/components/ui/field-variants"
import { Separator } from "@/components/ui/separator"

/**
 * Field primitives — 폼 라벨/보조문/오류의 단일 recipe(M43). 모든 라벨 처리(FormField/FormSelect/
 * FormTextArea/FilterField/직접 조합)는 여기서만 스타일을 얻는다.
 *
 * - `FieldLabel`/`FieldTitle`: 13.5px 500 ink-2, 컨트롤 위 6px(`gap-1.5`) — placeholder-as-label 금지.
 * - `FieldDescription`(hint) · `FieldError`: 라벨과 같은 크기, hint는 ink-2 · error는 destructive.
 * - `FieldMessage`: hint/error가 번갈아 들어가는 **한 슬롯**(`min-h-[1lh]`) — 오류가 나타나도 폼이
 *   밀리지 않는다(M13). error가 있으면 hint를 대체한다.
 * - `Field[data-invalid]`는 라벨을 destructive로, `[data-disabled]`는 라벨을 opacity 55로.
 */
function FieldSet({ className, ...props }: React.ComponentProps<"fieldset">) {
  return (
    <fieldset
      data-slot="field-set"
      className={cn(
        "flex flex-col gap-4 has-[>[data-slot=checkbox-group]]:gap-3 has-[>[data-slot=radio-group]]:gap-3",
        className
      )}
      {...props}
    />
  )
}

function FieldLegend({
  className,
  variant = "legend",
  ...props
}: React.ComponentProps<"legend"> & { variant?: "legend" | "label" }) {
  return (
    <legend
      data-slot="field-legend"
      data-variant={variant}
      className={cn(
        "mb-1.5 font-medium text-text-primary data-[variant=label]:text-xs data-[variant=label]:text-text-secondary data-[variant=legend]:text-sm data-[variant=legend]:font-semibold",
        className
      )}
      {...props}
    />
  )
}

function FieldGroup({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="field-group"
      className={cn(
        "group/field-group @container/field-group flex w-full flex-col gap-5 data-[slot=checkbox-group]:gap-3 *:data-[slot=field-group]:gap-4",
        className
      )}
      {...props}
    />
  )
}

const fieldVariants = cva("group/field flex w-full gap-1.5", {
  variants: {
    orientation: {
      vertical: "flex-col *:w-full [&>.sr-only]:w-auto",
      horizontal:
        "flex-row items-center gap-2 has-[>[data-slot=field-content]]:items-start *:data-[slot=field-label]:flex-auto has-[>[data-slot=field-content]]:[&>[role=checkbox],[role=radio]]:mt-px",
      responsive:
        "flex-col *:w-full @md/field-group:flex-row @md/field-group:items-center @md/field-group:gap-2 @md/field-group:*:w-auto @md/field-group:has-[>[data-slot=field-content]]:items-start @md/field-group:*:data-[slot=field-label]:flex-auto [&>.sr-only]:w-auto @md/field-group:has-[>[data-slot=field-content]]:[&>[role=checkbox],[role=radio]]:mt-px",
    },
  },
  defaultVariants: {
    orientation: "vertical",
  },
})

function Field({
  className,
  orientation = "vertical",
  ...props
}: React.ComponentProps<"div"> & VariantProps<typeof fieldVariants>) {
  return (
    <div
      role="group"
      data-slot="field"
      data-orientation={orientation}
      className={cn(fieldVariants({ orientation }), className)}
      {...props}
    />
  )
}

function FieldContent({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="field-content"
      className={cn(
        "group/field-content flex flex-1 flex-col gap-1 leading-snug",
        className
      )}
      {...props}
    />
  )
}

function FieldLabel({
  className,
  htmlFor,
  ...props
}: React.ComponentProps<"label"> & { htmlFor: string }) {
  return (
    <label
      data-slot="field-label"
      htmlFor={htmlFor}
      className={cn(
        "group/field-label peer/field-label flex w-fit items-center gap-1.5",
        fieldLabelClassName,
        // 라벨이 Field(체크박스 카드 등)를 감싸는 경우: hairline 1층 + 선택 시 brand-tint(불투명)
        "has-[>[data-slot=field]]:w-full has-[>[data-slot=field]]:flex-col has-[>[data-slot=field]]:rounded-control has-[>[data-slot=field]]:border has-[>[data-slot=field]]:border-border has-[>[data-slot=field]]:text-text-primary *:data-[slot=field]:p-2.5 has-[>[data-slot=field]]:has-data-checked:border-brand has-[>[data-slot=field]]:has-data-checked:bg-brand-tint",
        className
      )}
      {...props}
    />
  )
}

function FieldTitle({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="field-label"
      className={cn(
        "flex w-fit items-center gap-1.5",
        fieldLabelClassName,
        className
      )}
      {...props}
    />
  )
}

function FieldDescription({ className, ...props }: React.ComponentProps<"p">) {
  return (
    <p
      data-slot="field-description"
      className={cn(
        "text-left text-xs leading-normal font-normal text-text-secondary group-has-data-horizontal/field:text-balance [[data-variant=legend]+&]:-mt-1.5",
        "[&>a]:text-brand [&>a]:underline-offset-4 [&>a:hover]:underline",
        className
      )}
      {...props}
    />
  )
}

/**
 * hint/error 공용 메시지 슬롯. 항상 1줄 높이를 예약해(`min-h-[1lh]`) 오류 등장/소멸이 레이아웃을
 * 밀지 않게 한다. 자식이 없으면 빈 슬롯으로 남는다.
 */
function FieldMessage({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="field-message"
      className={cn("min-h-[1lh] text-xs leading-normal", className)}
      {...props}
    />
  )
}

function FieldSeparator({
  children,
  className,
  ...props
}: React.ComponentProps<"div"> & {
  children?: React.ReactNode
}) {
  return (
    <div
      data-slot="field-separator"
      data-content={!!children}
      className={cn(
        "relative -my-2 h-5 text-xs group-data-[variant=outline]/field-group:-mb-2",
        className
      )}
      {...props}
    >
      <Separator className="absolute inset-0 top-1/2" />
      {children && (
        <span
          className="relative mx-auto block w-fit bg-surface-page px-2 text-text-secondary"
          data-slot="field-separator-content"
        >
          {children}
        </span>
      )}
    </div>
  )
}

function FieldError({
  className,
  children,
  errors,
  ...props
}: React.ComponentProps<"div"> & {
  errors?: Array<{ message?: string } | undefined>
}) {
  let content: React.ReactNode = children

  if (!content) {
    if (!errors?.length) {
      return null
    }

    const uniqueErrors = [
      ...new Map(errors.map((error) => [error?.message, error])).values(),
    ]

    if (uniqueErrors?.length == 1) {
      content = uniqueErrors[0]?.message
    } else {
      content = (
        <ul className="ml-4 flex list-disc flex-col gap-1">
          {uniqueErrors.map(
            (error) =>
              error?.message && <li key={error.message}>{error.message}</li>
          )}
        </ul>
      )
    }
  }

  if (!content) {
    return null
  }

  return (
    <div
      role="alert"
      data-slot="field-error"
      className={cn(
        "text-xs leading-normal font-normal text-destructive",
        className
      )}
      {...props}
    >
      {content}
    </div>
  )
}

export {
  Field,
  FieldLabel,
  FieldDescription,
  FieldError,
  FieldGroup,
  FieldLegend,
  FieldMessage,
  FieldSeparator,
  FieldSet,
  FieldContent,
  FieldTitle,
}
