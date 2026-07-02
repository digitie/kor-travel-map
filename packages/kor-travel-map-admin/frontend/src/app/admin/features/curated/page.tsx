import type { Metadata } from "next";

import { CuratedFeaturesClient } from "../../curated-features/curated-features-client";

export const metadata: Metadata = {
  title: "큐레이션 관리 | kor-travel-map admin",
  description:
    "소스 규칙이 만든 후보를 검토해 공개(큐레이션)하고 배포 스냅샷을 확인하는 운영 화면",
};

export default function FeatureCuratedPage() {
  return <CuratedFeaturesClient />;
}
