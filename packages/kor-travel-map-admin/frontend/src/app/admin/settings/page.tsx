import type { Metadata } from "next";

import { adminDocumentTitle } from "@/lib/admin-nav";

import { AdminSettingsClient } from "./settings-client";

export const metadata: Metadata = {
  title: adminDocumentTitle("/admin/settings", "설정"),
};

export default function AdminSettingsPage() {
  return <AdminSettingsClient />;
}
