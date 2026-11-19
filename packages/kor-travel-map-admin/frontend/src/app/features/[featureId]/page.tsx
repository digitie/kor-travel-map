import type { Metadata } from "next";

import { adminDocumentTitle } from "@/lib/admin-nav";

import { FeatureDetailPageClient } from "./feature-detail-page-client";

type FeatureDetailPageProps = {
  params: Promise<{ featureId: string }>;
};

export async function generateMetadata({
  params,
}: FeatureDetailPageProps): Promise<Metadata> {
  const { featureId } = await params;
  return {
    title: adminDocumentTitle(`/features/${featureId}`, `Feature 상세 ${featureId}`),
  };
}

export default async function FeatureDetailPage({
  params,
}: FeatureDetailPageProps) {
  const { featureId } = await params;
  return <FeatureDetailPageClient featureId={featureId} />;
}
