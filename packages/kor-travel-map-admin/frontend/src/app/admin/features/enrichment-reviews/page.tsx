import type { Metadata } from "next";

import { adminDocumentTitle } from "@/lib/admin-nav";

import { EnrichmentReviewClient } from "../../enrichment-reviews/enrichment-review-client";

export const metadata: Metadata = {
  title: adminDocumentTitle("/admin/features/enrichment-reviews", "보강 검토"),
};

export default function FeatureEnrichmentReviewPage() {
  return <EnrichmentReviewClient />;
}
