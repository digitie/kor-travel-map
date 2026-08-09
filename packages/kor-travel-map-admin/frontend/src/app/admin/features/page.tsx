import type { Metadata } from "next";

import { AdminFeaturesClient } from "./admin-features-client";

export const metadata: Metadata = {
  title: "Feature 목록 | kor-travel-map",
  description: "운영자용 feature 목록과 상세 검토 화면",
};

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function AdminFeaturesPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = (await searchParams) ?? {};
  return (
    <AdminFeaturesClient
      initialHasIssue={firstParam(params.has_issue)}
      initialKind={firstParam(params.kind)}
      initialLifecycleState={firstParam(params.lifecycle_state)}
      initialProviderDatasetId={firstParam(params.provider_dataset_id)}
      initialPublicationState={firstParam(params.publication_state)}
      initialQ={firstParam(params.q)}
      initialQualityState={firstParam(params.quality_state)}
    />
  );
}
