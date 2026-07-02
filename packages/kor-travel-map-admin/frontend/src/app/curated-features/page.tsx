import type { Metadata } from "next";

import { CuratedFeatureMapClient } from "./curated-feature-map-client";

export const metadata: Metadata = {
  title: "Curated Feature 지도 | kor-travel-map admin",
  description: "curated feature 지도/테이블 검토와 상세 확인을 위한 운영 화면",
};

export default function CuratedFeatureMapPage() {
  return <CuratedFeatureMapClient />;
}
