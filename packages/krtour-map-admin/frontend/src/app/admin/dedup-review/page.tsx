import type { Metadata } from "next";

import { DedupReviewClient } from "./dedup-review-client";

export const metadata: Metadata = {
  title: "Dedup review | krtour-map admin",
};

export default function DedupReviewPage() {
  return <DedupReviewClient />;
}
