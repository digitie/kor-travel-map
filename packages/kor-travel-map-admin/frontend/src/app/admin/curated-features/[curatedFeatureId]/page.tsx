import type { Metadata } from "next";

import { CuratedFeatureDetailClient } from "./curated-feature-detail-client";

type CuratedFeatureDetailPageProps = {
  params: Promise<{ curatedFeatureId: string }>;
};

export async function generateMetadata({
  params,
}: CuratedFeatureDetailPageProps): Promise<Metadata> {
  const { curatedFeatureId } = await params;
  return {
    title: `${curatedFeatureId} | Curated feature detail`,
  };
}

export default async function CuratedFeatureDetailPage({
  params,
}: CuratedFeatureDetailPageProps) {
  const { curatedFeatureId } = await params;
  return <CuratedFeatureDetailClient curatedFeatureId={curatedFeatureId} />;
}
