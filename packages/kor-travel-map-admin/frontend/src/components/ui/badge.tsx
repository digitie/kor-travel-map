// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
import { mergeProps } from "@base-ui/react/merge-props"
import { useRender } from "@base-ui/react/use-render"
import { type VariantProps } from "class-variance-authority"

import { badgeVariants, type BadgeVariant } from "@/components/ui/badge-variants"
import { cn } from "@/lib/utils"

/**
 * Badge — 상태 칩 전용(design.md §Status colour semantics). count/version/key 같은 정적 metadata는
 * badge가 아니라 muted inline text로 표기한다(M22). tone 변형(success/warning/info/destructive/neutral)은
 * 불투명 `*-tint` 토큰 위에 tone 잉크(각각 AA ≥ 4.5:1) — alpha 팔레트 금지(M4/C2).
 * 한글 라벨이므로 uppercase/tracking 없음(m3), 숫자는 tabular-nums(M24).
 * recipe(`badgeVariants`)와 `BadgeVariant` 타입은 `badge-variants.ts`가 정본이다.
 */
function Badge({
  className,
  variant = "default",
  render,
  ...props
}: useRender.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return useRender({
    defaultTagName: "span",
    props: mergeProps<"span">(
      {
        className: cn(badgeVariants({ variant }), className),
      },
      props
    ),
    render,
    state: {
      slot: "badge",
      variant,
    },
  })
}

export { Badge }
export type { BadgeVariant }
