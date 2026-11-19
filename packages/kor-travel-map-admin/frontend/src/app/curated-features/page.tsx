import type { Metadata } from "next";

import { adminDocumentTitle } from "@/lib/admin-nav";

import { CuratedFeatureMapClient } from "./curated-feature-map-client";

export const metadata: Metadata = {
  title: adminDocumentTitle("/curated-features", "큐레이션 지도"),
  description: "curated feature 지도/테이블 검토와 상세 확인을 위한 운영 화면",
};

export default function CuratedFeatureMapPage() {
  return <CuratedFeatureMapClient />;
}
