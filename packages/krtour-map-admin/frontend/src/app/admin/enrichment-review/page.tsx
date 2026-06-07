import type { Metadata } from "next";

import { EnrichmentReviewClient } from "./enrichment-review-client";

export const metadata: Metadata = {
  title: "Enrichment review | krtour-map admin",
};

export default function EnrichmentReviewPage() {
  return <EnrichmentReviewClient />;
}
