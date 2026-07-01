import type { Metadata } from "next";

import { CuratedFeaturesClient } from "../../curated-features/curated-features-client";

export const metadata: Metadata = {
  title: "Feature 큐레이션 | kor-travel-map admin",
  description: "curated 후보, source rule, detail snapshot preview 운영 화면",
};

export default function FeatureCuratedPage() {
  return <CuratedFeaturesClient />;
}
