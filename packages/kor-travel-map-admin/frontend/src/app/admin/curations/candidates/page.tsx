import type { Metadata } from "next";

import { adminDocumentTitle } from "@/lib/admin-nav";

import { CurationCandidatesClient } from "./curation-candidates-client";

export const metadata: Metadata = {
  title: adminDocumentTitle("/admin/curations/candidates", "큐레이션 후보 검토"),
};

export default function CurationCandidatesPage() {
  return <CurationCandidatesClient />;
}
