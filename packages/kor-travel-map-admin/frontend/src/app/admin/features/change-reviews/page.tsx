import type { Metadata } from "next";

import { FeatureChangeRequestsClient } from "../change-requests/feature-change-requests-client";

export const metadata: Metadata = {
  title: "Feature 검수 | kor-travel-map",
  description: "운영자용 feature 변경 요청 검수",
};

export default function FeatureChangeReviewsPage() {
  return <FeatureChangeRequestsClient view="review" />;
}
