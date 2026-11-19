import type { Metadata } from "next";

import { adminDocumentTitle } from "@/lib/admin-nav";

import { CurationCollectionsClient } from "./curation-collections-client";

export const metadata: Metadata = {
  title: adminDocumentTitle("/admin/features/curated", "큐레이션 관리"),
};

export default function FeatureCuratedPage() {
  return <CurationCollectionsClient />;
}
