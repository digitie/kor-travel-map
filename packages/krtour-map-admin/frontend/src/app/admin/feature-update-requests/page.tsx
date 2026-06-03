import type { Metadata } from "next";

import { FeatureUpdateRequestsClient } from "./feature-update-requests-client";

export const metadata: Metadata = {
  title: "Feature update requests | krtour-map admin",
};

export default function FeatureUpdateRequestsPage() {
  return <FeatureUpdateRequestsClient />;
}
