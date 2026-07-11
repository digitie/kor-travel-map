import { toast } from "sonner";

/**
 * 큐레이션 관리 화면 공용 어휘 사전 (LIST/DETAIL/MAP 공유).
 *
 * 동사 규약: **채택**(select/공개) · **채택 해제**(unselect→거절됨) · **보관**(archive)
 * · **결과 적용**(place-search hit) · **규칙 적용**(rule apply). 상태 텍스트는 기존
 * `statusLabel`(후보/큐레이션됨/거절됨/보관됨)을 그대로 쓴다.
 *
 * select/option의 **value는 raw enum 그대로** 두고 표시 텍스트만 `enumOption()`으로
 * 한글+raw를 병기한다 — e2e `selectOption("curated")` 등 기존 locator를 깨지 않으면서
 * 운영자가 API 어휘를 계속 학습하게 한다.
 */

export const REUSE_POLICY_LABELS: Record<string, string> = {
  allowed: "재사용 허용",
  blocked: "재사용 차단",
  manual_review: "수동 검토",
};

export const CURATION_RELATION_LABELS: Record<string, string> = {
  primary_stop: "핵심 방문지",
  food_stop: "식사",
  cafe_stop: "카페",
  bookstore_stop: "서점",
  nearby_option: "주변 대안",
  accessibility_support: "무장애 지원",
  pet_support: "반려동물 동반",
  family_support: "가족 친화",
  theme_area_anchor: "테마 거리 앵커",
};

export const RULE_ACTION_LABELS: Record<string, string> = {
  candidate: "후보 등록",
  curated: "즉시 공개(검토 생략)",
  ignore: "무시",
};

/** 상태별 결과(consequence) 한 줄 — 라이프사이클 스트립·detail에서 공유. */
export const STATUS_CONSEQUENCES: Record<string, string> = {
  candidate: "검토 대기 — 채택하면 공개됩니다",
  curated: "공개 상태입니다",
  rejected: "규칙 재적용·자동 파이프라인이 되살리지 않습니다",
  archived: "소프트 삭제 — 원본 feature 삭제 시 자동 보관 포함",
};

export function reusePolicyLabel(value: string): string {
  return REUSE_POLICY_LABELS[value] ?? value;
}

export function curationRelationLabel(value: string): string {
  return CURATION_RELATION_LABELS[value] ?? value;
}

export function ruleActionLabel(value: string): string {
  return RULE_ACTION_LABELS[value] ?? value;
}

/** select option 표시 텍스트 — "재사용 허용 (allowed)" 형식. */
export function enumOption(label: string, raw: string): string {
  return `${label} (${raw})`;
}

/**
 * 상태 전환 mutation 성공 토스트 — 어느 화면에서 눌러도 같은 문구가 나오게 공유.
 * select는 "행이 어디 갔지?"를 바로 해소하는 필터 점프 액션을 받을 수 있다.
 */
export function notifyStatusTransition(
  kind: "select" | "unselect" | "archive",
  featureName: string,
  onJumpFilter?: () => void,
): void {
  if (kind === "select") {
    toast.success("채택 완료 — 후보 → 큐레이션됨", {
      description: `"${featureName}" — 큐레이션됨 상태로 이동했습니다.`,
      action: onJumpFilter
        ? { label: "큐레이션됨 보기", onClick: onJumpFilter }
        : undefined,
    });
    return;
  }
  if (kind === "unselect") {
    toast.success("채택 해제 완료 — 큐레이션됨 → 거절됨", {
      description: "규칙 재적용·자동 파이프라인이 이 항목을 되살리지 않습니다.",
    });
    return;
  }
  toast.success("보관 완료", {
    description:
      "공개·후보 목록에서 제외됩니다(소프트 삭제). '보관됨 포함'으로 조회할 수 있습니다.",
  });
}
