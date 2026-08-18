/* Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app */
import type { BadgeVariant } from "@/components/ui/badge-variants";
import type { StatusTone } from "@/lib/status-label";

/**
 * StatusTone → ui/badge variant 매핑(M20/M28) — 톤 테이블(`src/lib/status-label.ts`)의 다섯 tone이
 * badge tone variant와 1:1이다. 컴포넌트 파일(`status-badge.tsx`)은 컴포넌트만 export하므로
 * (react-refresh only-export-components) 매핑 헬퍼는 여기 둔다.
 */
const TONE_VARIANT: Record<StatusTone, BadgeVariant> = {
  success: "success",
  warning: "warning",
  destructive: "destructive",
  info: "info",
  neutral: "neutral",
};

/** tone → ui/badge variant. */
export function toneBadgeVariant(tone: StatusTone): BadgeVariant {
  return TONE_VARIANT[tone];
}
