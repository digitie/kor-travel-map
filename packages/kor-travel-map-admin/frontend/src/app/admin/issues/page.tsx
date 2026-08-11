import type { Metadata } from "next";

import { AdminIssuesClient } from "./admin-issues-client";

export const metadata: Metadata = {
  title: "이슈 | kor-travel-map",
  description: "주소와 정합성 이슈 검토 및 조치 화면",
};

function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

export default async function AdminIssuesPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = (await searchParams) ?? {};
  return (
    <AdminIssuesClient
      initialFeatureId={firstParam(params.feature_id)}
      initialProviderDatasetId={firstParam(params.provider_dataset_id)}
      initialStatus={firstParam(params.status)}
    />
  );
}
