/* Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app */
import { cva } from "class-variance-authority";

/**
 * Button recipe (design.md §CTA voice / §Spacing·shape·size / §Motion).
 *
 * - 높이 2종만: `default`/`lg`/`icon`/`icon-lg` → `h-control`(36px), `sm`/`xs`/`icon-sm`/`icon-xs` →
 *   `h-control-sm`(30px). xs/lg 계열은 하위 호환 alias — 신규 코드는 default/sm/icon/icon-sm만.
 * - 8-state: rest · hover(colour) · focus-visible(불투명 outline, transition 밖 — `outline-none`을
 *   붙이지 않는다: tailwind v4에서 `--tw-outline-style: none`이 focus-visible까지 덮어 링이 사라진다) ·
 *   active(1px press) · disabled(`cursor-not-allowed`, pointer-events 유지 → `title` 사유 도달 가능) ·
 *   loading(`aria-busy` + `aria-disabled` — native disabled를 걸지 않아 포커스를 유지한다.
 *   Button `loading` prop이 spinner 오버레이) · aria-invalid · aria-expanded.
 *   그래서 disabled 계열 색은 `disabled:`/`aria-disabled:` 두 벌을 항상 같이 둔다.
 * - **흐림(opacity-55)은 이 레시피가 root에 걸지 않는다.** `opacity`는 요소 전체를 합성하므로
 *   outline(포커스 링)까지 55 %로 흐려진다 — `aria-disabled`는 포커스를 유지하는 상태라(loading·
 *   pager busy) light에서 링이 focus vs page 6.66:1 → 2.57:1로 무너졌다(WCAG 2.4.11 3:1 미달).
 *   그래서 `Button`이 `selectable-row.tsx`와 같은 방식으로 **라벨 자식**에만
 *   `group-disabled/button:opacity-55 group-aria-disabled/button:opacity-55`를 건다. 링과 경계는
 *   항상 100 %다. (bare `buttonVariants()` 소비자는 전부 `<Link>`/`<a>`라 두 상태를 갖지 않는다.)
 * - variant: `default`(brand fill, band당 1개) · `outline`(secondary CTA) · `ghost`(toolbar/table 안) ·
 *   `secondary`(선택/활성 tint chip) · `destructive`(in-page = outline + destructive text) ·
 *   `destructive-solid`(confirm dialog 안에서만 fill) · `link`.
 * - **경계는 컨트롤 hairline(`border-input` = `--control-line`)이다**(design.md §Hairlines/§CTA voice).
 *   장식용 `border-border`는 light에서 card 1.22:1 · page 1.17:1로 1.4.11(3:1) 미달이라 secondary
 *   CTA·pager가 배경에 녹았다. `border-input` = light card 3.69 · page 3.54 · subtle 3.43 ·
 *   muted 3.03 / dark 3.96 · 4.33 · 3.85 · 3.07. `secondary`는 tint 채움이 네 표면 모두
 *   1.04~1.42:1로 경계 구실을 못 해 `border-brand`로 테를 세운다(brand: light 5.29/5.08/4.93/4.35
 *   · dark 8.15/8.92/7.94/6.33, 자기 채움 대비 light 4.73 · dark 6.26) — `field.tsx`의 선택 상태
 *   (`has-data-checked:border-brand` + `bg-brand-tint`), `Checkbox`의 `data-checked:border-brand`와
 *   같은 레시피다. 모든 variant가 `border border-transparent`를 깔고 있어 테를 켜도 폭이 안 변한다.
 * - alpha 팔레트 금지 → hover는 불투명 토큰(`brand-hover`, `surface-subtle`, `*-tint`).
 * - `<Link className={buttonVariants()}>`도 같은 레시피(no-underline; 전역 a 규칙은 prose 스코프).
 */
const buttonVariants = cva(
  [
    "group/button inline-flex shrink-0 items-center justify-center rounded-control border border-transparent bg-clip-padding font-medium whitespace-nowrap no-underline select-none",
    "transition-[color,background-color,border-color,box-shadow,transform] duration-fast ease-out",
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
    "active:not-aria-[haspopup]:translate-y-px",
    // opacity는 root가 아니라 라벨 자식에만(위 주석) — root에 걸면 focus outline까지 흐려진다.
    "disabled:cursor-not-allowed aria-disabled:cursor-not-allowed aria-busy:cursor-progress",
    "aria-invalid:border-destructive",
    "[&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  ].join(" "),
  {
    variants: {
      variant: {
        default:
          "bg-brand text-brand-foreground hover:bg-brand-hover active:bg-brand-hover disabled:bg-surface-muted disabled:text-text-primary aria-disabled:bg-surface-muted aria-disabled:text-text-primary",
        outline:
          "border-input bg-card text-text-primary hover:bg-surface-subtle active:bg-surface-muted aria-expanded:bg-surface-subtle aria-expanded:text-text-primary disabled:border-input disabled:bg-card aria-disabled:border-input aria-disabled:bg-card",
        secondary:
          "border-brand bg-brand-tint text-brand hover:border-brand-hover hover:text-brand-hover active:border-brand-hover active:text-brand-hover aria-expanded:border-brand aria-expanded:bg-brand-tint aria-expanded:text-brand disabled:border-brand disabled:text-brand aria-disabled:border-brand aria-disabled:text-brand",
        ghost:
          "text-text-secondary hover:bg-surface-subtle hover:text-text-primary active:bg-surface-muted aria-expanded:bg-surface-subtle aria-expanded:text-text-primary disabled:bg-transparent disabled:text-text-secondary aria-disabled:bg-transparent aria-disabled:text-text-secondary",
        destructive:
          "border-input bg-card text-destructive hover:border-destructive hover:bg-destructive-tint active:bg-destructive-tint aria-expanded:bg-destructive-tint disabled:border-input disabled:bg-card aria-disabled:border-input aria-disabled:bg-card",
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
