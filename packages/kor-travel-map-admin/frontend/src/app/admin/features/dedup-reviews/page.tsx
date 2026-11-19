import type { Metadata } from "next";

import { adminDocumentTitle } from "@/lib/admin-nav";

import { DedupReviewClient } from "../../dedup-reviews/dedup-review-client";

export const metadata: Metadata = {
  title: adminDocumentTitle("/admin/features/dedup-reviews", "중복 검토"),
};

export default function FeatureDedupReviewPage() {
  return <DedupReviewClient />;
}
