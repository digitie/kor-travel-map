// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
import { cn } from "@/lib/utils"

/**
 * Skeleton — 대체할 콘텐츠의 형태를 그대로 따라 그린다(텍스트 줄 = h-4, 숫자 = h-8 w-24 …).
 * 장식 요소라 기본 aria-hidden; 로딩 여부는 감싸는 영역의 `aria-busy`가 알린다.
 * pulse는 전역 reduced-motion 규칙(globals.css)이 끈다.
 */
function Skeleton({
  className,
  "aria-hidden": ariaHidden = true,
  ...props
}: React.ComponentProps<"div">) {
  return (
    <div
      aria-hidden={ariaHidden}
      data-slot="skeleton"
      className={cn(
        "animate-pulse rounded-control bg-surface-muted motion-reduce:animate-none",
        className
      )}
      {...props}
    />
  )
}

export { Skeleton }
