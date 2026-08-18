// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
import { Button as ButtonPrimitive } from "@base-ui/react/button"
import type { VariantProps } from "class-variance-authority"
import { Loader2Icon } from "lucide-react"

import { buttonVariants } from "@/components/ui/button-variants"
import { cn } from "@/lib/utils"

type ButtonProps = ButtonPrimitive.Props &
  VariantProps<typeof buttonVariants> & {
    /**
     * 비동기 진행 중(design.md §Microinteractions — row action은 page spinner 대신 trigger의
     * loading). disabled + `aria-busy` + inline spinner. 라벨은 자리를 지키고(폭 불변) 시각적으로만
     * 숨겨지므로 접근성 이름은 그대로다.
     */
    loading?: boolean
    /**
     * disabled 사유(사용자 노출 문장). disabled일 때 `title`로 붙는다 — hover로 도달 가능하고
     * (pointer-events 유지) 접근성 설명(accessible description)으로도 노출된다
     * (design.md: "Disabled controls state their reason (`title` + inline note), never colour-only").
     * 인라인 노트(helper/hint)는 호출부가 함께 렌더한다.
     */
    disabledReason?: string
  }

function Button({
  className,
  variant = "default",
  size = "default",
  loading = false,
  disabledReason,
  disabled,
  title,
  children,
  ...props
}: ButtonProps) {
  const isDisabled = Boolean(disabled) || loading
  const reason = disabled && !loading ? disabledReason : undefined
  return (
    <ButtonPrimitive
      data-slot="button"
      data-loading={loading ? "true" : undefined}
      aria-busy={loading || undefined}
      title={reason ?? title}
      disabled={isDisabled}
      className={cn(
        buttonVariants({ variant, size }),
        loading && "relative",
        className
      )}
      {...props}
    >
      {loading ? (
        <>
          <span
            aria-hidden="true"
            data-slot="button-spinner"
            className="absolute inset-0 flex items-center justify-center"
          >
            <Loader2Icon className="animate-spin" />
          </span>
          <span
            data-slot="button-label"
            className="inline-flex items-center justify-center gap-[inherit] opacity-0"
          >
            {children}
          </span>
        </>
      ) : (
        children
      )}
    </ButtonPrimitive>
  )
}

export { Button }
export type { ButtonProps }
