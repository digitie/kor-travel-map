import type { Metadata } from "next";

import { FeatureCreateClient } from "./feature-create-client";

export const metadata: Metadata = {
  title: "New feature | krtour-map",
  description: "운영자용 수동 feature 작성 화면",
};

export default function NewFeaturePage() {
  return <FeatureCreateClient />;
}
