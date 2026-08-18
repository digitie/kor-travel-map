/* Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app */
import { cva } from "class-variance-authority";

/**
 * Button recipe (design.md §CTA voice / §Spacing·shape·size / §Motion).
 *
 * - 높이 2종만: `default`/`lg`/`icon`/`icon-lg` → `h-control`(36px), `sm`/`xs`/`icon-sm`/`icon-xs` →
 *   `h-control-sm`(30px). xs/lg 계열은 하위 호환 alias — 신규 코드는 default/sm/icon/icon-sm만.
 * - 8-state: rest · hover(colour) · focus-visible(불투명 outline, transition 밖) · active(1px press) ·
 *   disabled(`opacity-55 + cursor-not-allowed`, pointer-events 유지 → `title` 사유 도달 가능) ·
 *   loading(`aria-busy` — Button `loading` prop이 spinner 오버레이) · aria-invalid · aria-expanded.
 * - variant: `default`(brand fill, band당 1개) · `outline`(secondary CTA) · `ghost`(toolbar/table 안) ·
 *   `secondary`(선택/활성 tint chip) · `destructive`(in-page = outline + destructive text) ·
 *   `destructive-solid`(confirm dialog 안에서만 fill) · `link`.
 * - alpha 팔레트 금지 → hover는 불투명 토큰(`brand-hover`, `surface-subtle`, `*-tint`).
 * - `<Link className={buttonVariants()}>`도 같은 레시피(no-underline; 전역 a 규칙은 prose 스코프).
 */
const buttonVariants = cva(
  [
    "group/button inline-flex shrink-0 items-center justify-center rounded-control border border-transparent bg-clip-padding font-medium whitespace-nowrap no-underline select-none",
    "transition-[color,background-color,border-color,box-shadow,transform] duration-fast ease-out",
    "outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
    "active:not-aria-[haspopup]:translate-y-px",
    "disabled:cursor-not-allowed disabled:opacity-55 aria-disabled:cursor-not-allowed aria-disabled:opacity-55 aria-busy:cursor-progress",
    "aria-invalid:border-destructive",
    "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  ].join(" "),
  {
    variants: {
      variant: {
        default:
          "bg-brand text-brand-foreground hover:bg-brand-hover active:bg-brand-hover disabled:bg-surface-muted disabled:text-text-primary aria-disabled:bg-surface-muted aria-disabled:text-text-primary",
        outline:
          "border-border bg-card text-text-primary hover:bg-surface-subtle active:bg-surface-muted aria-expanded:bg-surface-subtle aria-expanded:text-text-primary disabled:bg-card aria-disabled:bg-card",
        secondary:
          "bg-brand-tint text-brand hover:text-brand-hover active:text-brand-hover aria-expanded:bg-brand-tint aria-expanded:text-brand disabled:text-brand aria-disabled:text-brand",
        ghost:
          "text-text-secondary hover:bg-surface-subtle hover:text-text-primary active:bg-surface-muted aria-expanded:bg-surface-subtle aria-expanded:text-text-primary disabled:bg-transparent disabled:text-text-secondary aria-disabled:bg-transparent aria-disabled:text-text-secondary",
        destructive:
          "border-border bg-card text-destructive hover:border-destructive hover:bg-destructive-tint active:bg-destructive-tint aria-expanded:bg-destructive-tint disabled:border-border disabled:bg-card aria-disabled:border-border aria-disabled:bg-card",
        "destructive-solid":
          "bg-destructive text-brand-foreground hover:bg-text-primary hover:text-surface-page active:bg-text-primary active:text-surface-page disabled:bg-surface-muted disabled:text-text-primary aria-disabled:bg-surface-muted aria-disabled:text-text-primary",
        link: "text-brand underline-offset-4 hover:text-brand-hover hover:underline",
      },
      size: {
        default:
          "h-control gap-2 px-3.5 text-sm has-data-[icon=inline-end]:pr-3 has-data-[icon=inline-start]:pl-3",
        sm: "h-control-sm gap-1.5 px-2.5 text-xs has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2 [&_svg:not([class*='size-'])]:size-3.5",
        /** @deprecated alias of `sm` (two control heights only). */
        xs: "h-control-sm gap-1.5 px-2 text-xs has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3.5",
        /** @deprecated alias of `default` (two control heights only). */
        lg: "h-control gap-2 px-3.5 text-sm has-data-[icon=inline-end]:pr-3 has-data-[icon=inline-start]:pl-3",
        icon: "size-control text-sm",
        "icon-sm": "size-control-sm text-xs [&_svg:not([class*='size-'])]:size-3.5",
        /** @deprecated alias of `icon-sm`. */
        "icon-xs": "size-control-sm text-xs [&_svg:not([class*='size-'])]:size-3.5",
        /** @deprecated alias of `icon`. */
        "icon-lg": "size-control text-sm",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export { buttonVariants };
