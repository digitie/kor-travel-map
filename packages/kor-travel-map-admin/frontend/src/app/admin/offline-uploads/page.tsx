import type { Metadata } from "next";

import { adminDocumentTitle } from "@/lib/admin-nav";

import { OfflineUploadsClient } from "./offline-uploads-client";

export const metadata: Metadata = {
  title: adminDocumentTitle("/admin/offline-uploads", "오프라인 업로드"),
};

export default function OfflineUploadsPage() {
  return <OfflineUploadsClient />;
}
