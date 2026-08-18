// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
import {
  featureStateLabel,
  type FeatureLifecycleState,
  type FeaturePublicationState,
  type FeatureQualityState,
} from "@/api/features";
import { StatusBadge } from "@/components/status-badge";

/**
 * Feature 3축 상태(수명/공개/품질) 배지. 톤은 축별 임의 polarity가 아니라 단일 tone 테이블
 * (`toneFor` via StatusBadge)에서 읽는다 — active/published = success · draft/valid = info ·
 * quarantined = warning · retired/suppressed = neutral(M20). 라벨은 기존 `featureStateLabel`
 * 사전을 그대로 쓴다(`수명: 운영` 형식 유지).
 */
export function FeatureStateBadges({
  lifecycleState,
  publicationState,
  qualityState,
  className,
}: {
  lifecycleState: FeatureLifecycleState;
  publicationState: FeaturePublicationState;
  qualityState: FeatureQualityState;
  className?: string;
}) {
  return (
    <>
      <StatusBadge
        className={className}
        data-axis="lifecycle"
        label={`수명: ${featureStateLabel("lifecycle", lifecycleState)}`}
        status={lifecycleState}
      />
      <StatusBadge
        className={className}
        data-axis="publication"
        label={`공개: ${featureStateLabel("publication", publicationState)}`}
        status={publicationState}
      />
      <StatusBadge
        className={className}
        data-axis="quality"
        label={`품질: ${featureStateLabel("quality", qualityState)}`}
        status={qualityState}
      />
    </>
  );
}
