import type { Metadata } from "next";

import { CuratedFeatureDetailClient } from "../../../curated-features/[curatedFeatureId]/curated-feature-detail-client";

type CuratedFeatureDetailPageProps = {
  params: Promise<{ curatedFeatureId: string }>;
};

export async function generateMetadata({
  params,
}: CuratedFeatureDetailPageProps): Promise<Metadata> {
  const { curatedFeatureId } = await params;
  return {
    title: `${curatedFeatureId} | Feature 큐레이션 상세`,
  };
}

export default async function FeatureCuratedDetailPage({
  params,
}: CuratedFeatureDetailPageProps) {
  const { curatedFeatureId } = await params;
  return <CuratedFeatureDetailClient curatedFeatureId={curatedFeatureId} />;
}
