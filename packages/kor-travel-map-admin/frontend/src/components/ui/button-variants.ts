import { buttonVariants as commonButtonVariants } from "@kor-travel/ui/button-variants";

import { cn } from "@/lib/utils";

/**
 * Map의 disabled 설명 도달성만 덧붙인다(흐림은 라벨 자식에만, `title` 사유는 hover로 도달).
 * 색상·크기·focus outline은 공통 정본(`@kor-travel/ui` 0.2.3: outline 2px·offset 2px·
 * `--kt-focus`)이 혼자 발행한다. 예전에는 공통 recipe의 `outline-none`·반투명 ring을 이기려고
 * `outline-solid`·`focus-visible:outline-*`·`ring-0`을 덧댔는데, 조건 없는 `outline-solid`가
 * 모든 버튼에 기본 폭(medium) outline을 상시로 그려 테두리가 굵어지고 포커스 때 겹쳐 보였다
 * (FS-7.8). 여기서는 상태 스타일을 더하지 않는다.
 */
const buttonInteractionClasses =
  "disabled:opacity-100 disabled:pointer-events-auto";

/**
 * 모바일(md 미만) 터치 표적 하한 44px(WCAG 2.5.5 · design.md §Microinteractions).
 * 공통 recipe의 아이콘 크기(`icon`=32px·`icon-sm`=28px·`icon-xs`=24px)는 데스크톱 밀도 그대로
 * 두고, 좁은 폭에서만 min-width/min-height로 넓힌다(아이콘 glyph 크기는 불변).
 */
const mobileTouchTargetClasses = "max-md:min-h-11 max-md:min-w-11";

function isIconSize(size: string | null | undefined): boolean {
  return typeof size === "string" && size.startsWith("icon");
}

/** Link/a 소비자도 같은 공통 recipe와 Map 상호작용 정책을 쓴다. */
function buttonVariants(options: Parameters<typeof commonButtonVariants>[0] = {}) {
  const { class: classValue, className, ...variants } = options ?? {};
  return cn(
    commonButtonVariants(variants),
    buttonInteractionClasses,
    isIconSize(variants.size) && mobileTouchTargetClasses,
    classValue,
    className,
  );
}

export {
  buttonVariants,
  buttonInteractionClasses,
  isIconSize,
  mobileTouchTargetClasses,
};
