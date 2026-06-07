import type { Metadata } from "next";

import { AdminIssuesClient } from "./admin-issues-client";

export const metadata: Metadata = {
  title: "Admin issues | krtour-map",
  description: "주소와 정합성 이슈 검토 및 조치 화면",
};

export default function AdminIssuesPage() {
  return <AdminIssuesClient />;
}
