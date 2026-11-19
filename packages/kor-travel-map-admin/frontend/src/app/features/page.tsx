import type { Metadata } from "next";

import { adminDocumentTitle } from "@/lib/admin-nav";

import { FeaturesClient } from "./features-client";

export const metadata: Metadata = {
  title: adminDocumentTitle("/features", "Feature 지도"),
  description: "feature 지도/테이블 검토와 상세 확인을 위한 운영 화면",
};

export default function FeaturesPage() {
  return <FeaturesClient />;
}
