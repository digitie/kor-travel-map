import type { Metadata } from "next";

import { AdminFeaturesClient } from "./admin-features-client";

export const metadata: Metadata = {
  title: "Feature 목록 | kor-travel-map",
  description: "운영자용 feature 목록과 상세 검토 화면",
};

export default function AdminFeaturesPage() {
  return <AdminFeaturesClient />;
}
