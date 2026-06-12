import type { Metadata } from "next";

import { FeatureChangeRequestsClient } from "./feature-change-requests-client";

export const metadata: Metadata = {
  title: "Feature change requests | kor-travel-map",
  description: "운영자용 feature 추가·수정·삭제 요청 큐",
};

export default function FeatureChangeRequestsPage() {
  return <FeatureChangeRequestsClient />;
}
