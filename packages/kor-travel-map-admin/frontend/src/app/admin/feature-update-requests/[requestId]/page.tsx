import type { Metadata } from "next";

import { FeatureUpdateRequestDetailClient } from "./feature-update-request-detail-client";

type FeatureUpdateRequestDetailPageProps = {
  params: Promise<{ requestId: string }>;
};

export async function generateMetadata({
  params,
}: FeatureUpdateRequestDetailPageProps): Promise<Metadata> {
  const { requestId } = await params;
  return {
    title: `${requestId} | Feature update request`,
  };
}

export default async function FeatureUpdateRequestDetailPage({
  params,
}: FeatureUpdateRequestDetailPageProps) {
  const { requestId } = await params;
  return <FeatureUpdateRequestDetailClient requestId={requestId} />;
}
