import type { Metadata } from "next";

import { adminDocumentTitle } from "@/lib/admin-nav";

import { BackupsClient } from "./backups-client";

export const metadata: Metadata = {
  title: adminDocumentTitle("/admin/backups", "백업"),
};

export default function BackupsPage() {
  return <BackupsClient />;
}
