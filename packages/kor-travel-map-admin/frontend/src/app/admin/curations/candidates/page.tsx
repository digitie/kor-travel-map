import type { Metadata } from "next";

import { CurationCandidatesClient } from "./curation-candidates-client";

export const metadata: Metadata = {
  title: "큐레이션 후보 검토 | kor-travel-map admin",
};

export default function CurationCandidatesPage() {
  return <CurationCandidatesClient />;
}
