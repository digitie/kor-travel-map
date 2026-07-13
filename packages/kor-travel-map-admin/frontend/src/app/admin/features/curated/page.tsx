import type { Metadata } from "next";

import { CurationCollectionsClient } from "./curation-collections-client";

export const metadata: Metadata = {
  title: "큐레이션 관리 | kor-travel-map admin",
};

export default function FeatureCuratedPage() {
  return <CurationCollectionsClient />;
}
