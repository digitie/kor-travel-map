/* Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app */
import { cva, type VariantProps } from "class-variance-authority";

/**
 * Badge recipe — 상태 칩 전용(design.md §Status colour semantics). count/version/key 같은 정적
 * metadata는 badge가 아니라 muted inline text로 표기한다(M22). tone 변형(success/warning/info/
 * destructive/neutral)은 불투명 `*-tint` 토큰 위에 tone 잉크(각각 AA ≥ 4.5:1) — alpha 팔레트
 * 금지(M4/C2). 한글 라벨이므로 uppercase/tracking 없음(m3), 숫자는 tabular-nums(M24).
 *
 * 컴포넌트 파일(`badge.tsx`)은 컴포넌트만 export한다(react-refresh only-export-components) —
 * recipe는 button-variants.ts와 같은 방식으로 여기 둔다.
 *
 * 전환 속성은 열거한다(`transition-[color,background-color,border-color]`). tailwind v4의
 * `transition-colors`는 `outline-color`를 포함해서 링크 배지(`<a>`)의 포커스 링이 100ms 동안
 * 페이드인 되는데, design.md §Focus는 "링은 전환 대상이 아니라 즉시"로 못박고 있다.
 */
export const badgeVariants = cva(
  "group/badge inline-flex h-6 w-fit shrink-0 items-center justify-center gap-1 rounded-control border border-transparent px-2 text-2xs leading-none font-medium whitespace-nowrap tabular-nums transition-[color,background-color,border-color] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 aria-invalid:border-destructive [&>svg]:pointer-events-none [&>svg]:size-3!",
  {
    variants: {
      variant: {
        default: "bg-brand text-brand-foreground [a]:hover:bg-brand-hover",
        secondary: "bg-brand-tint text-brand [a]:hover:border-brand",
        destructive:
          "bg-destructive-tint text-destructive [a]:hover:border-destructive",
        outline:
          "border-border bg-card text-text-secondary [a]:hover:bg-surface-subtle [a]:hover:text-text-primary",
        ghost:
          "text-text-secondary [a]:hover:bg-surface-subtle [a]:hover:text-text-primary",
        link: "text-brand underline-offset-4 hover:underline",
        success: "bg-success-tint text-success [a]:hover:border-success",
        warning: "bg-warning-tint text-warning [a]:hover:border-warning",
        info: "bg-info-tint text-info [a]:hover:border-info",
        neutral:
          "bg-surface-subtle text-text-secondary [a]:hover:bg-surface-muted [a]:hover:text-text-primary",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export type BadgeVariant = NonNullable<VariantProps<typeof badgeVariants>["variant"]>;
