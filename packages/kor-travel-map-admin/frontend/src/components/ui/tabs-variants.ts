/* Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app */
import { cva } from "class-variance-authority";

/**
 * TabsList recipe — 두 variant, 한 높이(`h-control` 36px):
 * - `default`(segmented): view 토글(지도/테이블)용. 트랙 `bg-surface-subtle`, 활성 = `bg-card` + hairline
 *   (그림자 없음).
 * - `line`(underline): 콘텐츠 탭용. hairline 베이스라인 + 활성은 ink 텍스트 + 2px brand 바.
 *
 * 컴포넌트 파일(`tabs.tsx`)은 컴포넌트만 export한다(react-refresh only-export-components).
 */
export const tabsListVariants = cva(
  "group/tabs-list inline-flex w-fit items-center justify-center text-text-secondary group-data-vertical/tabs:h-fit group-data-vertical/tabs:flex-col group-data-vertical/tabs:items-stretch",
  {
    variants: {
      variant: {
        default:
          "h-control gap-0.5 rounded-control bg-surface-subtle p-0.5 group-data-vertical/tabs:h-fit",
        line: "h-control gap-4 rounded-none border-b border-border bg-transparent p-0 group-data-vertical/tabs:border-r group-data-vertical/tabs:border-b-0",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);
