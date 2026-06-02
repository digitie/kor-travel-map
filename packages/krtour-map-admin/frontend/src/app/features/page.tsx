import type { Metadata } from "next";

import { FeaturesClient } from "./features-client";

export const metadata: Metadata = {
  title: "Feature 지도 | krtour-map admin",
  description: "feature 지도/테이블 검토와 상세 확인을 위한 운영 화면",
};

export default function FeaturesPage() {
  return <FeaturesClient />;
}
