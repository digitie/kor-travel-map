import type { Metadata } from "next";

import { FeatureUpdateRequestsClient } from "../../feature-update-requests/feature-update-requests-client";

export const metadata: Metadata = {
  title: "Feature 갱신 | kor-travel-map admin",
};

export default function FeatureUpdateRequestsPage() {
  return <FeatureUpdateRequestsClient />;
}
