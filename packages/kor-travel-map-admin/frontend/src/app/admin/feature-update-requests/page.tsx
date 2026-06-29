import type { Metadata } from "next";

import { FeatureUpdateRequestsClient } from "./feature-update-requests-client";

export const metadata: Metadata = {
  title: "갱신 요청 | kor-travel-map admin",
};

export default function FeatureUpdateRequestsPage() {
  return <FeatureUpdateRequestsClient />;
}
