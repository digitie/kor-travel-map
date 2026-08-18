/**
 * 큐레이션 관리 화면 공용 어휘 — 상태별 결과 문구.
 *
 * T-VN-40A: legacy 편집 UI(reuse_policy/relation select, 채택/해제/보관 토스트)와 함께
 * 그 어휘(`REUSE_POLICY_LABELS`·`CURATION_RELATION_LABELS`·`enumOption` 등)는 삭제했다.
 * 남은 것은 lifecycle strip이 쓰는 상태 결과 문구뿐이다.
 */

/** 상태별 결과(consequence) 한 줄 — 라이프사이클 스트립·detail에서 공유. */
export const STATUS_CONSEQUENCES: Record<string, string> = {
  candidate: "검토 대기 — 채택하면 공개됩니다",
  curated: "공개 상태입니다",
  rejected: "규칙 재적용·자동 파이프라인이 되살리지 않습니다",
  archived: "소프트 삭제 — 원본 feature 삭제 시 자동 보관 포함",
};
