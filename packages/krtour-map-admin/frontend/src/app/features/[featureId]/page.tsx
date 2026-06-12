import type { Metadata } from "next";

import { FeatureDetailPageClient } from "./feature-detail-page-client";

type FeatureDetailPageProps = {
  params: Promise<{ featureId: string }>;
};

export async function generateMetadata({
  params,
}: FeatureDetailPageProps): Promise<Metadata> {
  const { featureId } = await params;
  return {
    title: `${featureId} | Feature detail`,
  };
}

export default async function FeatureDetailPage({
  params,
}: FeatureDetailPageProps) {
  const { featureId } = await params;
  return <FeatureDetailPageClient featureId={featureId} />;
}
