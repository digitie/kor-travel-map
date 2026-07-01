import type { Metadata } from "next";

import { FeatureUpdateRequestDetailClient } from "../../../feature-update-requests/[requestId]/feature-update-request-detail-client";

type FeatureUpdateRequestDetailPageProps = {
  params: Promise<{ requestId: string }>;
};

export async function generateMetadata({
  params,
}: FeatureUpdateRequestDetailPageProps): Promise<Metadata> {
  const { requestId } = await params;
  return {
    title: `${requestId} | Feature 갱신 요청`,
  };
}

export default async function FeatureUpdateRequestDetailPage({
  params,
}: FeatureUpdateRequestDetailPageProps) {
  const { requestId } = await params;
  return <FeatureUpdateRequestDetailClient requestId={requestId} />;
}
