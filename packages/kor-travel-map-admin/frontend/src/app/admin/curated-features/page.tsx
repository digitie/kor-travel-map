import type { Metadata } from "next";

import { CuratedFeaturesClient } from "./curated-features-client";

export const metadata: Metadata = {
  title: "Curated features | kor-travel-map",
  description: "curated 후보, source rule, PinVi copy preview 운영 화면",
};

export default function CuratedFeaturesPage() {
  return <CuratedFeaturesClient />;
}
