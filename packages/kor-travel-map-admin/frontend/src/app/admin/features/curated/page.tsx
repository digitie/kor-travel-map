import type { Metadata } from "next";

import { CuratedFeaturesClient } from "../../curated-features/curated-features-client";

export const metadata: Metadata = {
  title: "큐레이션 관리 | kor-travel-map admin",
};

export default function FeatureCuratedPage() {
  return <CuratedFeaturesClient />;
}
