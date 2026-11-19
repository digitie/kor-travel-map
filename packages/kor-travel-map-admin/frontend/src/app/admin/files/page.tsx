import type { Metadata } from "next";

import { adminDocumentTitle } from "@/lib/admin-nav";

import { FilesClient } from "./files-client";

export const metadata: Metadata = {
  title: adminDocumentTitle("/admin/files", "파일 관리"),
};

export default function FilesPage() {
  return <FilesClient />;
}
