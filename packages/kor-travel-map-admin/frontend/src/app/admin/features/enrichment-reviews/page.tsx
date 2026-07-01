import type { Metadata } from "next";

import { EnrichmentReviewClient } from "../../enrichment-reviews/enrichment-review-client";

export const metadata: Metadata = {
  title: "보강 검토 | kor-travel-map admin",
};

export default function FeatureEnrichmentReviewPage() {
  return <EnrichmentReviewClient />;
}
