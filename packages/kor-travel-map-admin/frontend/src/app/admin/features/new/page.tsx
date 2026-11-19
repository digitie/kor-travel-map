import type { Metadata } from "next";

import { adminDocumentTitle } from "@/lib/admin-nav";

import { FeatureCreateClient } from "./feature-create-client";

export const metadata: Metadata = {
  title: adminDocumentTitle("/admin/features/new", "새 Feature"),
  description: "운영자용 수동 feature 작성 화면",
};

export default function NewFeaturePage() {
  return <FeatureCreateClient />;
}
