import type { Metadata } from "next";

import { DedupReviewClient } from "../../dedup-reviews/dedup-review-client";

export const metadata: Metadata = {
  title: "중복 검토 | kor-travel-map admin",
};

export default function FeatureDedupReviewPage() {
  return <DedupReviewClient />;
}
