import { buttonVariants as commonButtonVariants } from "@kor-travel/ui/button-variants";

import { cn } from "@/lib/utils";

/** Map의 진행 중 포커스·disabled 설명 도달성만 덧붙인다. 색상과 크기는 공통 정본이다. */
const buttonInteractionClasses =
  "outline-solid focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus focus-visible:ring-0 disabled:opacity-100 disabled:pointer-events-auto";

/** Link/a 소비자도 같은 공통 recipe와 Map 상호작용 정책을 쓴다. */
function buttonVariants(options: Parameters<typeof commonButtonVariants>[0] = {}) {
  const { class: classValue, className, ...variants } = options ?? {};
  return cn(
    commonButtonVariants(variants),
    buttonInteractionClasses,
    classValue,
    className,
  );
}

export { buttonVariants, buttonInteractionClasses };
